"""Editor control commands."""

from __future__ import annotations

import ast
import codecs
import json
import re
import socket
import subprocess as sp
import sys
import time
from pathlib import Path

import click

from cli_anything.unreal.commands import AppError, AppState, handle_error, output, require_editor, require_project
from cli_anything.unreal.core.tasks import FINAL_TASK_STATUSES, cancel_task, iter_tasks, load_task, submit_task, task_data_path, task_progress, wait_for_task


DEFAULT_EDITOR_LAUNCH_FOREGROUND_WAIT_SECONDS = 110
DEFAULT_EDITOR_LAUNCH_WORKER_TIMEOUT_SECONDS = 300
REMOTE_UNREACHABLE_GRACE_SECONDS = 60
REMOTE_UNREACHABLE_CACHE_TTL_SECONDS = 7200


def _read_stdin_python_code(stream=None) -> str:
    """Read piped Python without letting the Windows console code page eat a BOM."""
    stream = sys.stdin if stream is None else stream
    raw_stream = getattr(stream, "buffer", None)
    if raw_stream is None:
        return stream.read().removeprefix("\ufeff")

    raw = raw_stream.read()
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig")
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        encoding = getattr(stream, "encoding", None)
        if not encoding:
            raise
        return raw.decode(encoding)


def _load_command_project(state: AppState, project_path: str | None) -> None:
    if not project_path:
        return
    try:
        state.session.load_project(project_path)
    except FileNotFoundError:
        raise AppError(
            "PROJECT_NOT_FOUND",
            f"Project not found: {project_path}",
            exit_code=3,
            suggestion="Pass --project <path-to.uproject> before or after editor launch.",
        )


def _project_option(func):
    return click.option("--project", "project_path", type=click.Path(), help="Path to .uproject file")(func)


_VIEWPORT_CAMERA_SCRIPT = """\
import unreal
_fn = getattr(unreal.EditorLevelLibrary, "get_level_viewport_camera_info", None)
if _fn is None:
    _subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    _fn = getattr(_subsystem, "get_level_viewport_camera_info", None)
if _fn is None:
    result = {
        "error": "Active Level Viewport camera is not exposed by this UE Python API.",
        "tried": [
            "unreal.EditorLevelLibrary.get_level_viewport_camera_info",
            "unreal.LevelEditorSubsystem.get_level_viewport_camera_info",
        ],
    }
else:
    loc, rot = _fn()
    result = {
        "loc": [loc.x, loc.y, loc.z],
        "rot": [rot.roll, rot.pitch, rot.yaw],
    }
"""


def _get_viewport_camera(api, timeout: int) -> dict:
    from cli_anything.unreal.core.script_runner import run_python_code

    result = run_python_code(api, _VIEWPORT_CAMERA_SCRIPT, timeout=timeout, save=False)
    if "error" in result:
        raise AppError(
            "VIEWPORT_CAMERA_FAILED",
            f"Could not read Level Viewport camera: {result['error']}",
            details=result,
        )
    if "loc" not in result or "rot" not in result:
        raise AppError(
            "VIEWPORT_CAMERA_FAILED",
            "Could not read Level Viewport camera: script returned no loc/rot.",
            details=result,
        )
    return {"loc": result["loc"], "rot": result["rot"]}


def _set_viewport_game_view(api, mode: str | None) -> dict:
    from cli_anything.unreal.core.script_runner import run_python_code

    requested_mode = (mode or "get").lower()
    script = f"""
import unreal
_mode = {json.dumps(requested_mode)}
_subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
_get = getattr(_subsystem, "editor_get_game_view", None)
_set = getattr(_subsystem, "editor_set_game_view", None)
_active_viewport = False
_viewport_error = None
try:
    _bounds = unreal.CliAnythingBridgeLibrary.get_active_viewport_screen_bounds()
    _active_viewport = int(_bounds.z) > 0 and int(_bounds.w) > 0
except Exception as _exc:
    _viewport_error = str(_exc)
if not _active_viewport:
    result = {{
        "error": "No active Level Viewport could be verified.",
        "mode": _mode,
        "viewport_error": _viewport_error,
        "suggestion": "Focus a Level Viewport and ensure the bundled bridge plugin is current.",
    }}
elif _get is None or (_mode != "get" and _set is None):
    result = {{
        "error": "Level Viewport game-view state is not exposed by this UE Python API.",
        "mode": _mode,
        "tried": [
            "LevelEditorSubsystem.editor_get_game_view",
            "LevelEditorSubsystem.editor_set_game_view",
        ],
    }}
else:
    _before = bool(_get())
    _desired = _before
    if _mode == "toggle":
        _desired = not _before
    elif _mode == "on":
        _desired = True
    elif _mode == "off":
        _desired = False
    if _mode != "get" and _desired != _before:
        _set(_desired)
    _after = bool(_get())
    result = {{
        "status": "ok",
        "mode": _mode,
        "before": _before,
        "after": _after,
        "changed": _after != _before,
    }}
    if _after != _desired:
        result["error"] = "Level Viewport game-view state did not reach the requested value."
"""
    result = run_python_code(api, script, save=False)
    if result.get("error"):
        raise AppError(
            "VIEWPORT_GAME_VIEW_FAILED",
            f"Could not update Level Viewport game view: {result['error']}",
            exit_code=3,
            details=result,
        )
    required = {"before", "after", "changed"}
    if not required.issubset(result):
        raise AppError(
            "VIEWPORT_GAME_VIEW_FAILED",
            "Could not read Level Viewport game-view state.",
            exit_code=3,
            details=result,
        )
    return {
        "status": result.get("status", "ok"),
        "mode": result.get("mode", requested_mode),
        "before": result["before"],
        "after": result["after"],
        "changed": result["changed"],
    }


def _camera_changed(before: dict, after: dict, tolerance: float = 1e-3) -> bool:
    for key in ("loc", "rot"):
        for a, b in zip(before.get(key, []), after.get(key, [])):
            if abs(float(a) - float(b)) > tolerance:
                return True
    return False


def _jump_viewport_bookmark_win32(project_title_hint: str, index: int) -> dict:
    if sys.platform != "win32":
        raise AppError(
            "UNSUPPORTED_PLATFORM",
            "Viewport bookmark keyboard simulation is only supported on Windows.",
            exit_code=2,
        )

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                title = buffer.value
                if "Unreal Editor" in title and (not project_title_hint or project_title_hint in title):
                    found.append((int(hwnd), title))
        return True

    user32.EnumWindows(enum_proc, 0)
    if not found:
        raise AppError(
            "EDITOR_WINDOW_NOT_FOUND",
            f"Could not find a visible Unreal Editor window matching project title: {project_title_hint}",
            exit_code=3,
            suggestion="Make sure the editor window is visible and not minimized to another desktop.",
        )

    hwnd, title = found[0]
    user32.ShowWindow(wintypes.HWND(hwnd), 9)  # SW_RESTORE
    user32.SetForegroundWindow(wintypes.HWND(hwnd))
    user32.BringWindowToTop(wintypes.HWND(hwnd))
    time.sleep(0.2)

    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise AppError("EDITOR_WINDOW_RECT_FAILED", "Could not read Unreal Editor window bounds.", exit_code=3)

    x = int(rect.left + (rect.right - rect.left) // 2)
    y = int(rect.top + (rect.bottom - rect.top) // 2)
    user32.SetCursorPos(x, y)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
    time.sleep(0.1)

    vk = 0x30 + int(index)
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 0x0002, 0)
    time.sleep(0.5)

    return {"hwnd": hwnd, "title": title, "focus_point": [x, y]}


@click.group("editor")
def editor_group():
    """Editor control commands."""


def _parse_scan_range(scan_range: str) -> tuple[int, int]:
    parts = str(scan_range).split("-", 1)
    start = int(parts[0])
    end = int(parts[1]) if len(parts) > 1 else start
    if end < start:
        start, end = end, start
    return start, end


def _project_config_port(project_path: str | None) -> int | None:
    if not project_path:
        return None
    try:
        from cli_anything.unreal.utils.ue_backend import read_rc_port

        return read_rc_port(str(Path(project_path).parent))
    except Exception:
        return None


def _editor_log_error(project_path: str | None) -> str | None:
    if not project_path:
        return None
    try:
        project = Path(project_path)
        return _check_log_errors(project.parent / "Saved" / "Logs" / f"{project.stem}.log")
    except Exception:
        return None


def _compact_editor_entry(status: str, pid: int | None, port: int | None, project_path: str | None) -> dict:
    return {
        "status": status,
        "pid": pid,
        "port": port,
        "project_path": project_path or None,
    }


def _remote_unreachable_cache_path() -> Path:
    return task_data_path("editor_remote_unreachable.json")


def _remote_unreachable_key(project_path: str | None, pid: int | None, port: int | None) -> str:
    project = str(project_path or "").lower()
    return f"{project}|{pid or ''}|{port or ''}"


def _load_remote_unreachable_cache() -> dict:
    path = _remote_unreachable_cache_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_remote_unreachable_cache(cache: dict) -> None:
    path = _remote_unreachable_cache_path()
    now = time.time()
    compact = {
        key: value
        for key, value in cache.items()
        if now - float(value.get("last_seen_at") or value.get("first_seen_at") or 0) <= REMOTE_UNREACHABLE_CACHE_TTL_SECONDS
    }
    try:
        path.write_text(json.dumps(compact, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _clear_remote_unreachable_observation(project_path: str | None, pid: int | None, port: int | None) -> None:
    cache = _load_remote_unreachable_cache()
    key = _remote_unreachable_key(project_path, pid, port)
    if key in cache:
        cache.pop(key, None)
        _save_remote_unreachable_cache(cache)


def _record_remote_unreachable_observation(entry: dict) -> dict:
    now = time.time()
    key = _remote_unreachable_key(entry.get("project_path"), entry.get("pid"), entry.get("port"))
    cache = _load_remote_unreachable_cache()
    obs = cache.get(key) or {"first_seen_at": now, "count": 0}
    obs["last_seen_at"] = now
    obs["count"] = int(obs.get("count") or 0) + 1
    cache[key] = obs
    _save_remote_unreachable_cache(cache)
    obs = dict(obs)
    obs["unreachable_seconds"] = int(max(0, now - float(obs.get("first_seen_at") or now)))
    return obs


def _add_transient_unreachable_hint(entry: dict, observation: dict) -> None:
    entry["status"] = "unreachable"
    entry["message"] = "Remote Control API is temporarily unreachable; UnrealEditor is still running and may be busy with PIE, loading, shader work, or startup."
    entry["suggestion"] = "Retry editor status before relaunching. Do not terminate the editor unless it remains unreachable past the stale grace period or the process exits."
    entry["unreachable_seconds"] = observation.get("unreachable_seconds", 0)
    entry["stale_after_seconds"] = REMOTE_UNREACHABLE_GRACE_SECONDS
    project_path = entry.get("project_path")
    if project_path:
        entry["next_command"] = f'ue-cli --project "{project_path}" editor status'


def _active_launch_task_for_project(project_path: str | None, pid: int | None = None) -> dict | None:
    if not project_path:
        return None
    now = time.time()
    for task in iter_tasks():
        if task.get("command") != "editor.launch":
            continue
        if task.get("status") in FINAL_TASK_STATUSES:
            continue
        if now - float(task.get("updated_at") or task.get("created_at") or 0) > 7200:
            continue
        payload = task.get("payload") or {}
        if not _same_project_path(payload.get("project_path"), project_path):
            continue
        task_pid = task.get("pid") or (task.get("result") or {}).get("pid")
        if pid is not None and task_pid is not None:
            try:
                if int(task_pid) != int(pid):
                    continue
            except (TypeError, ValueError):
                continue
        if pid is not None and task_pid is None:
            continue
        return task
    return None


def _add_launching_recovery_hint(entry: dict, task: dict) -> None:
    entry["status"] = "launching"
    entry["task_id"] = task.get("task_id")
    entry["launch_task_status"] = task.get("status")
    if task.get("worker_pid"):
        entry["worker_pid"] = task.get("worker_pid")
    log_file = task.get("log_file") or (task.get("result") or {}).get("log_file")
    if log_file:
        entry["log_file"] = log_file
    entry["message"] = "UnrealEditor process is running for an active launch task, but the Remote Control API is not reachable yet."
    entry["suggestion"] = "Wait for startup to finish or inspect the launch task; do not start another launch unless the task times out or fails."
    project_path = entry.get("project_path")
    if project_path and task.get("task_id"):
        entry["next_command"] = f'ue-cli --project "{project_path}" editor status {task["task_id"]}'


def _add_offline_recovery_hint(entry: dict, observation: dict | None = None) -> None:
    entry["message"] = "UnrealEditor process is running, but the Remote Control API is not reachable."
    if observation:
        entry["unreachable_seconds"] = observation.get("unreachable_seconds", 0)
        entry["stale_after_seconds"] = REMOTE_UNREACHABLE_GRACE_SECONDS
    project_path = entry.get("project_path")
    if project_path:
        entry["suggestion"] = (
            "Remote Control has stayed unreachable past the stale grace period. Run editor launch to "
            "terminate the stale matching process and start a fresh editor if needed."
        )
        entry["next_command"] = f'ue-cli --project "{project_path}" editor launch'
    else:
        entry["suggestion"] = "Run editor launch with --project <path-to.uproject> to start a reachable editor."


def _add_online_bridge_status(entry: dict) -> None:
    if entry.get("status") != "online" or not entry.get("port"):
        return

    from cli_anything.unreal.core.plugin_bridge import get_bundled_version, get_loaded_plugin_version
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    bundled = get_bundled_version()
    loaded = None
    probe_failed = False
    try:
        loaded = get_loaded_plugin_version(UEEditorAPI(port=int(entry["port"])), timeout=5.0, raise_on_error=True)
    except Exception:
        probe_failed = True
        loaded = None

    entry["bridge_version"] = loaded
    entry["bundled_version"] = bundled
    if probe_failed:
        entry["plugin_match"] = None
        return

    project_path = entry.get("project_path")
    if loaded is None:
        entry["plugin_match"] = False
        entry["bridge_status"] = "missing_or_unversioned"
        entry["degraded_mode"] = "remote_control_only"
        entry["read_only_commands_available"] = True
        entry["bridge_commands_available"] = False
        entry["message"] = (
            "Editor is online via Remote Control, but CliAnythingBridge is missing or does not expose a version. "
            "Bridge-only commands may fail until the plugin is upgraded and the editor is restarted."
        )
        entry["suggestion"] = (
            "Non-bridge read-only commands can still run in remote-control-only mode. "
            "Schedule editor plugin-upgrade when bridge commands are needed and a restart is acceptable."
        )
        if project_path:
            entry["upgrade_command"] = f'ue-cli --project "{project_path}" editor plugin-upgrade'
        return

    entry["plugin_match"] = bundled is not None and loaded == bundled
    if not entry["plugin_match"] and project_path:
        entry["restart_required"] = True
        entry["bridge_status"] = "version_mismatch"
        entry["bridge_commands_available"] = False
        entry["message"] = (
            f"running editor loaded CliAnythingBridge {loaded}, "
            f"but ue-cli bundles {bundled or 'unknown'}. UE cannot hot-reload this C++ bridge safely; "
            "run editor plugin-upgrade to deploy, compile, restart, then retry bridge commands."
        )
        entry["suggestion"] = "CliAnythingBridge plugin is version-mismatched. Run editor plugin-upgrade; it will restart the editor when needed."
        entry["next_command"] = f'ue-cli --project "{project_path}" editor plugin-upgrade'


def _add_online_bridge_statuses(entries: list[dict]) -> None:
    targets = [
        entry for entry in entries
        if entry.get("status") == "online" and entry.get("port")
    ]
    if not targets:
        return
    if len(targets) == 1:
        _add_online_bridge_status(targets[0])
        return

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as executor:
        futures = [executor.submit(_add_online_bridge_status, entry) for entry in targets]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass


def _scan_editor_status_instances(state: AppState, scan_range: str) -> list[dict]:
    from cli_anything.unreal.utils.ue_backend import find_running_editors
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI, scan_editor_ports

    start, end = _parse_scan_range(scan_range)
    extra_ports: set[int] = set()
    if state.session.port:
        extra_ports.add(int(state.session.port))
    configured_port = _project_config_port(state.session.project_path)
    if configured_port and int(configured_port) == int(state.session.port):
        extra_ports.add(int(configured_port))

    running = find_running_editors() if sys.platform == "win32" else []
    proc_config_port_by_pid: dict[int, int] = {}
    for proc in running:
        proc_port = _project_config_port(proc.get("project") or None)
        if proc_port:
            extra_ports.add(int(proc_port))
            try:
                proc_config_port_by_pid[int(proc.get("pid", 0))] = int(proc_port)
            except (TypeError, ValueError):
                pass

    online_by_port: dict[int, dict] = {}
    for item in scan_editor_ports(port_range=(start, end)):
        online_by_port[int(item["port"])] = item
    for port in sorted(extra_ports):
        if start <= port <= end:
            continue
        for item in scan_editor_ports(port_range=(port, port)):
            online_by_port[int(item["port"])] = item

    process_by_pid: dict[int, dict] = {}
    for proc in running:
        try:
            process_by_pid[int(proc.get("pid", 0))] = proc
        except (TypeError, ValueError):
            pass

    pid_by_port: dict[int, int | None] = {}
    port_by_pid: dict[int, int] = {}
    ports_to_resolve = sorted(online_by_port)
    if len(ports_to_resolve) <= 1:
        resolved = [
            (port, UEEditorAPI._get_pid_listening_on_port(port))
            for port in ports_to_resolve
        ]
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        resolved = []
        with ThreadPoolExecutor(max_workers=min(8, len(ports_to_resolve))) as executor:
            futures = {
                executor.submit(UEEditorAPI._get_pid_listening_on_port, port): port
                for port in ports_to_resolve
            }
            for future in as_completed(futures):
                port = futures[future]
                try:
                    resolved.append((port, future.result()))
                except Exception:
                    resolved.append((port, None))
    for port, owner_pid in resolved:
        pid_by_port[port] = owner_pid
        if owner_pid:
            port_by_pid[int(owner_pid)] = port

    instances: list[dict] = []
    used_ports: set[int] = set()
    for proc in running:
        try:
            pid = int(proc.get("pid", 0))
        except (TypeError, ValueError):
            pid = None
        project_path = proc.get("project") or None
        port = port_by_pid.get(pid) if pid is not None else None
        if port is None and pid is not None:
            configured_proc_port = proc_config_port_by_pid.get(pid)
            if configured_proc_port in online_by_port:
                port = configured_proc_port
        if port is None and pid is not None and _same_project_path(project_path, state.session.project_path):
            probe_port = int(
                state.session.port
                or proc_config_port_by_pid.get(pid)
                or _project_config_port(project_path)
                or 30010
            )
            if probe_port not in online_by_port:
                try:
                    for item in scan_editor_ports(port_range=(probe_port, probe_port), timeout=3.0):
                        online_by_port[int(item["port"])] = item
                except Exception:
                    pass
            if probe_port in online_by_port:
                try:
                    owner_pid = UEEditorAPI._get_pid_listening_on_port(probe_port)
                except Exception:
                    owner_pid = None
                pid_by_port[probe_port] = owner_pid
                if owner_pid:
                    port_by_pid[int(owner_pid)] = probe_port
                if owner_pid is None or int(owner_pid) == pid:
                    port = probe_port
                    port_by_pid[pid] = probe_port
        if port is not None:
            used_ports.add(port)
            entry = _compact_editor_entry("online", pid, port, project_path)
            _clear_remote_unreachable_observation(project_path, pid, port)
        else:
            entry = _compact_editor_entry("offline", pid, _project_config_port(project_path), project_path)
            active_launch = _active_launch_task_for_project(project_path, pid)
            log_error = _editor_log_error(project_path)
            if active_launch:
                _add_launching_recovery_hint(entry, active_launch)
            elif log_error:
                _add_offline_recovery_hint(entry)
            else:
                observation = _record_remote_unreachable_observation(entry)
                if int(observation.get("unreachable_seconds") or 0) < REMOTE_UNREACHABLE_GRACE_SECONDS:
                    _add_transient_unreachable_hint(entry, observation)
                else:
                    _add_offline_recovery_hint(entry, observation)
            if log_error:
                entry["log_error"] = log_error
        instances.append(entry)

    for port in sorted(online_by_port):
        if port in used_ports:
            continue
        owner_pid = pid_by_port.get(port)
        owner = process_by_pid.get(int(owner_pid)) if owner_pid else None
        project_path = owner.get("project") if owner else None
        if project_path is None and state.session.project_path and port == state.session.port:
            project_path = state.session.project_path
        entry = _compact_editor_entry(
            "online",
            int(owner_pid) if owner_pid else None,
            port,
            project_path,
        )
        instances.append(entry)

    _add_online_bridge_statuses(instances)
    return instances


def _filter_editor_status_instances(instances: list[dict], project_path: str | None) -> list[dict]:
    if not project_path:
        return instances
    return [
        item for item in instances
        if _same_project_path(item.get("project_path"), project_path)
    ]


def _launch_wait_timeouts(timeout: int | None) -> tuple[int, int]:
    if timeout is not None:
        return timeout, timeout
    return DEFAULT_EDITOR_LAUNCH_FOREGROUND_WAIT_SECONDS, DEFAULT_EDITOR_LAUNCH_WORKER_TIMEOUT_SECONDS


def _recover_online_launch_result(state: AppState, task_id: str, current_task: dict) -> dict | None:
    if (current_task.get("payload") or {}).get("map_path"):
        return None

    try:
        instances = _scan_editor_status_instances(state, "30010-30020")
        instances = _filter_editor_status_instances(instances, state.session.project_path)
    except Exception:
        return None

    online = next((item for item in instances if item.get("status") == "online"), None)
    if online is None:
        return None

    result = dict(online)
    result["task_id"] = task_id
    result["command"] = "editor.launch"
    result["launch_task_status"] = current_task.get("status", "unknown")
    result["recovered_from"] = "launch_task_wait"
    if not result.get("pid") and current_task.get("pid"):
        result["pid"] = current_task.get("pid")
    if current_task.get("log_file") and not result.get("log_file"):
        result["log_file"] = current_task.get("log_file")
    return result


@editor_group.command("status")
@click.option("--scan-range", default="30010-30020", help="Port range to scan")
@click.option("--all", "show_all", is_flag=True, default=False, help="Show all editor instances instead of filtering to --project.")
@_project_option
@click.argument("task_id", required=False)
@handle_error
@click.pass_obj
def editor_status(state: AppState, scan_range, show_all, project_path, task_id):
    if task_id:
        task = load_task(task_id)
        if task is None:
            raise AppError("TASK_NOT_FOUND", f"Task not found: {task_id}", exit_code=3)
        output(task_progress(task), state)
        return

    _load_command_project(state, project_path)
    instances = _scan_editor_status_instances(state, scan_range)
    if not show_all:
        instances = _filter_editor_status_instances(instances, state.session.project_path)
    output(instances, state)


@editor_group.command("preflight")
@handle_error
@click.pass_obj
def editor_preflight(state: AppState):
    from cli_anything.unreal.utils.ue_backend import preflight_check

    require_project(state)
    output(preflight_check(state.session.project_path, state.session.engine_root), state)


@editor_group.group("viewport")
def viewport_group():
    """Viewport commands."""


@viewport_group.command("camera")
@click.option("--timeout", default=30, type=int, help="Seconds to wait when reading the viewport camera.")
@handle_error
@click.pass_obj
def viewport_camera(state: AppState, timeout):
    """Read the active Level Viewport camera."""
    api = require_editor(state)
    output(_get_viewport_camera(api, timeout), state)


@viewport_group.command("game-view")
@click.argument(
    "mode",
    required=False,
    type=click.Choice(["on", "off", "toggle"], case_sensitive=False),
)
@handle_error
@click.pass_obj
def viewport_game_view(state: AppState, mode):
    """Read or change the active Level Viewport game-view state."""
    api = require_editor(state)
    output(_set_viewport_game_view(api, mode), state)


@viewport_group.group("bookmark")
def viewport_bookmark_group():
    """Level Viewport bookmark commands."""


@viewport_bookmark_group.command("jump")
@click.option("--index", required=True, type=click.IntRange(0, 9), help="Bookmark index to jump to (0-9).")
@click.option("--timeout", default=30, type=int, help="Seconds to wait when reading the viewport camera.")
@handle_error
@click.pass_obj
def viewport_bookmark_jump(state: AppState, index, timeout):
    """Jump to a Level Viewport bookmark using the editor's numeric shortcut."""
    require_project(state)
    if sys.platform != "win32":
        raise AppError(
            "UNSUPPORTED_PLATFORM",
            "Viewport bookmark keyboard simulation is only supported on Windows.",
            exit_code=2,
        )
    api = require_editor(state)
    before = _get_viewport_camera(api, timeout)
    window = _jump_viewport_bookmark_win32(state.session.project_name or "", index)
    after = _get_viewport_camera(api, timeout)

    if not _camera_changed(before, after):
        raise AppError(
            "BOOKMARK_JUMP_UNCHANGED",
            "Viewport camera did not change after sending the bookmark shortcut.",
            exit_code=3,
            suggestion="Ensure the Level Viewport is focused, the bookmark exists, the numeric shortcut is unchanged, and the correct editor window was activated.",
            details={"index": index, "window": window, "before": before, "after": after},
        )

    output({"status": "jumped", "index": index, "window": window, "before": before, "after": after}, state)


def _summarize_startup_precheck(check: dict) -> dict:
    errors = check.get("engine", {}).get("errors", []) + check.get("project", {}).get("errors", [])
    warnings = check.get("engine", {}).get("warnings", []) + check.get("project", {}).get("warnings", [])
    for issue in check.get("bridge_plugin", {}).get("issues", []):
        warnings.append(f"Fixed: {issue}")
    return {
        "ready": check.get("ready", False),
        "errors": errors,
        "warnings": warnings,
    }


def _same_project_path(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    try:
        return Path(left).resolve().as_posix().lower() == Path(right).resolve().as_posix().lower()
    except Exception:
        return Path(left).as_posix().lower() == Path(right).as_posix().lower()


def _find_matching_project_editors(project_path: str | None) -> tuple[list[dict], list[dict]]:
    from cli_anything.unreal.utils.ue_backend import find_running_editors

    running = find_running_editors()
    matches = [
        proc for proc in running
        if _same_project_path(proc.get("project", ""), project_path)
    ]
    return running, matches


def _project_process_exit_evidence(
    project_path: str,
    target_pids: list[int],
) -> tuple[bool, dict]:
    from cli_anything.unreal.utils.ue_backend import _windows_process_exists

    pid_evidence = [
        {
            "pid": pid,
            "project_match": False,
            "exists": _windows_process_exists(pid),
        }
        for pid in target_pids
    ]
    if target_pids and all(item["exists"] is False for item in pid_evidence):
        return True, {"matching_pids": [], "pids": pid_evidence}

    _, matches = _find_matching_project_editors(project_path)
    matching_pids = set()
    for proc in matches:
        try:
            matching_pids.add(int(proc.get("pid", 0)))
        except (TypeError, ValueError):
            continue

    for item in pid_evidence:
        if item["pid"] in matching_pids:
            item["project_match"] = True
            item["exists"] = True

    return False, {
        "matching_pids": sorted(matching_pids),
        "pids": pid_evidence,
    }


def _kill_matching_project_editors(
    project_path: str | None,
    port: int,
    *,
    success_message: str,
    failure_message: str,
) -> dict | None:
    if not project_path:
        return None

    from cli_anything.unreal.utils.ue_backend import (
        _kill_process_tree_result,
        _windows_process_exists,
    )

    _, matches = _find_matching_project_editors(project_path)
    if not matches:
        return None

    closed = []
    failed = []
    for proc in matches:
        try:
            pid = int(proc.get("pid", 0))
        except (TypeError, ValueError):
            pid = 0
        entry = {"pid": pid, "project": proc.get("project", "")}
        if pid:
            _, current_matches = _find_matching_project_editors(project_path)
            current_pids = set()
            for current in current_matches:
                try:
                    current_pids.add(int(current.get("pid", 0)))
                except (TypeError, ValueError):
                    continue
            if pid not in current_pids:
                process_exists = _windows_process_exists(pid)
                if process_exists is False:
                    entry.update({"already_exited": True, "skipped": True})
                    closed.append(entry)
                    continue

                if process_exists is True:
                    error = "Process is still running, but its project identity no longer matches."
                else:
                    error = "Unable to verify whether the process still exists or matches the project."
                entry["kill_result"] = {
                    "ok": False,
                    "error": error,
                    "process_exists_after_rescan": process_exists,
                    "retry_suggested": True,
                    "suggestion": (
                        "Retry editor close after refreshing editor status; do not kill this PID "
                        "until it is confirmed to belong to the target project."
                    ),
                }
                failed.append(entry)
                continue
        kill_result = _kill_process_tree_result(pid) if pid else {
            "ok": False,
            "error": "Missing process id.",
            "retry_suggested": False,
        }
        if kill_result.get("ok"):
            closed.append(entry)
        else:
            entry["kill_result"] = kill_result
            failed.append(entry)

    if closed:
        result = {
            "status": "closed",
            "port": port,
            "method": "process_tree_kill",
            "message": success_message,
            "closed_processes": closed,
        }
        if failed:
            result["failed_processes"] = failed
        return result

    result = {
        "status": "failed",
        "port": port,
        "message": failure_message,
        "failed_processes": failed,
    }
    suggestions = [
        item.get("kill_result", {}).get("suggestion")
        for item in failed
        if item.get("kill_result", {}).get("suggestion")
    ]
    if suggestions:
        result["suggestion"] = suggestions[0]
    retry_flags = [
        item.get("kill_result", {}).get("retry_suggested")
        for item in failed
        if "kill_result" in item
    ]
    if retry_flags:
        result["retry_suggested"] = any(bool(flag) for flag in retry_flags)
    return result


def _check_already_running(session, state) -> dict | None:
    from cli_anything.unreal.utils.ue_backend import detect_ue_dialogs, find_running_editors
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    running = find_running_editors()
    api = UEEditorAPI(port=state.session.port)
    api_alive = api.is_alive()
    api_owner_pid = None
    if api_alive:
        try:
            api_owner_pid = UEEditorAPI._get_pid_listening_on_port(state.session.port)
        except Exception:
            api_owner_pid = None
    dialogs = detect_ue_dialogs() if sys.platform == "win32" else []
    for editor_proc in running:
        proc_project = editor_proc.get("project", "")
        if _same_project_path(proc_project, session.project_path):
            editor_pid = int(editor_proc["pid"])
            api_belongs_to_editor = api_alive and (api_owner_pid is None or int(api_owner_pid) == editor_pid)
            if api_belongs_to_editor:
                return {
                    "status": "already_running",
                    "pid": editor_pid,
                    "project": proc_project,
                    "message": f"Editor is already running for this project (PID {editor_pid}).",
                }
            active_launch = _active_launch_task_for_project(proc_project, editor_pid)
            if active_launch:
                starting = {
                    "status": "starting",
                    "pid": editor_pid,
                    "project": proc_project,
                    "port": state.session.port,
                    "task_id": active_launch.get("task_id"),
                    "launch_task_status": active_launch.get("status"),
                    "message": f"Editor launch is already in progress for this project (PID {editor_pid}), but the API is not reachable yet.",
                    "suggestion": "Wait for the active launch task or inspect it with editor status <task_id> before retrying launch.",
                }
                if active_launch.get("task_id"):
                    starting["next_command"] = f'ue-cli --project "{proc_project}" editor status {active_launch["task_id"]}'
                return starting
            zombie = {
                "status": "zombie",
                "pid": editor_pid,
                "project": proc_project,
                "message": f"Found UnrealEditor.exe for this project but the API is not reachable on port {state.session.port}.",
                "suggestion": "Stale process will be automatically terminated on next launch. Run editor launch to proceed.",
            }
            if api_alive and api_owner_pid is not None:
                zombie["api_owner_pid"] = int(api_owner_pid)
                zombie["message"] = (
                    f"Found UnrealEditor.exe for this project (PID {editor_pid}) but Remote Control "
                    f"port {state.session.port} belongs to PID {api_owner_pid}."
                )
            if dialogs:
                zombie["dialogs"] = [{"title": dialog["title"]} for dialog in dialogs]
                zombie["status"] = "starting"
                zombie["message"] = f"Editor process exists for this project but startup is still blocked or incomplete on port {state.session.port}."
                zombie["suggestion"] = "Wait briefly or dismiss any blocking dialogs before retrying."
            return zombie
    return None


def _check_port_in_use(poll_port, state) -> dict | None:
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    api_check = UEEditorAPI(port=poll_port)
    if api_check.is_alive():
        return {
            "status": "already_running",
            "port": poll_port,
            "message": f"An editor is already responding on port {poll_port}.",
        }
    from cli_anything.unreal.utils.ue_backend import is_tcp_port_in_use

    if is_tcp_port_in_use(poll_port):
        return {
            "status": "port_in_use",
            "port": poll_port,
            "message": f"TCP port {poll_port} is already in use.",
        }
    return None


def _remove_tree_with_retries(path: Path, *, attempts: int = 30, delay: float = 1.0) -> None:
    """Remove a tree, waiting for Unreal to release locked plugin DLLs."""
    import shutil

    if not path.exists():
        return
    last_error = None
    for attempt in range(attempts):
        try:
            shutil.rmtree(str(path))
            return
        except PermissionError as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(delay)
    raise last_error


def _wait_for_project_editor_exit(project_path: str | None, port: int, *, timeout: float = 60.0) -> dict | None:
    """Wait for same-project UnrealEditor processes to exit, then kill stale lock holders."""
    if not project_path or sys.platform != "win32":
        return None

    deadline = time.time() + timeout
    while time.time() < deadline:
        _, matches = _find_matching_project_editors(project_path)
        if not matches:
            return {"status": "closed", "method": "process_exit"}
        time.sleep(1)

    kill_result = _kill_matching_project_editors(
        project_path,
        port,
        success_message="Editor API closed but UnrealEditor process still held project DLLs; terminated matching process before compile.",
        failure_message="Editor API closed but UnrealEditor process still held project DLLs and could not be terminated.",
    )
    if kill_result:
        return kill_result

    # The process can exit between the timeout loop and the kill scan.
    _, final_matches = _find_matching_project_editors(project_path)
    if not final_matches:
        return {
            "status": "closed",
            "method": "process_exit_after_timeout_race",
        }

    return {
        "status": "timeout",
        "port": port,
        "message": "Timed out waiting for matching UnrealEditor process to exit before compile.",
        "running_processes": [
            {"pid": proc.get("pid"), "project": proc.get("project", "")}
            for proc in final_matches
        ],
    }


def _extract_compile_lock_error(log_file: str | None) -> dict:
    if not log_file:
        return {}
    try:
        text = Path(log_file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    match = re.search(r"LNK1104:\s*cannot open file\s+['\"]?([^'\"\r\n]+)['\"]?", text, re.IGNORECASE)
    if not match:
        return {}

    locked_file = match.group(1).strip()
    details = {
        "lock_error": "LNK1104",
        "locked_file": locked_file,
    }
    if locked_file.lower().endswith(".dll"):
        details["lock_hint"] = (
            "A running UnrealEditor or stale child process is holding this DLL. "
            "Close/kill editors for this project, then retry editor plugin-upgrade."
        )
    return details


def _deploy_bridge(session, state) -> dict:
    from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed

    return ensure_plugin_deployed(session.project_dir)


def _build_launch_cmd(editor_exe, project_path, map_path, extra_args=None) -> list:
    cmd = [editor_exe, project_path, "-nosplash", "-unattended"]
    if map_path:
        cmd.append(map_path)
    if extra_args:
        cmd.extend(str(arg) for arg in extra_args if arg is not None and str(arg) != "")
    return cmd


_FATAL_LOG_PATTERNS = [
    "modules are missing or built with a different engine version",
    "Still incompatible or missing module:",
    "Engine modules cannot be compiled at runtime",
    "Missing or incompatible modules",
    "Plugin .* failed to load",
    "Fatal Error:",
    "Assertion failed:",
]


def _extract_log_error(text: str) -> tuple[str | None, str | None]:
    for pattern in _FATAL_LOG_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start = max(0, match.start() - 100)
            end = min(len(text), match.end() + 300)
            return text[start:end].strip(), pattern
    return None, None


def _check_log_errors(log_file: Path) -> str | None:
    if not log_file.exists():
        return None
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
        excerpt, _pattern = _extract_log_error(text)
        return excerpt
    except Exception:
        return None


def _check_log_errors_incremental(log_file: Path, offset: int) -> tuple[str | None, int]:
    if not log_file.exists():
        return None, offset
    try:
        size = log_file.stat().st_size
        if offset < 0 or offset > size:
            offset = 0
        with log_file.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            text = handle.read()
            new_offset = handle.tell()
        if not text:
            return None, new_offset
        excerpt, _pattern = _extract_log_error(text)
        return excerpt, new_offset
    except Exception:
        return None, offset


def _tcp_port_accepts_connection(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _read_log_tail(log_file: Path, max_bytes: int = 128 * 1024) -> str:
    if not log_file.exists():
        return ""
    try:
        size = log_file.stat().st_size
        with log_file.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            data = handle.read()
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _bounded_log_tail_lines(
    log_file: Path,
    *,
    since_offset: int | None = None,
    limit: int = 8,
    max_line_chars: int = 500,
) -> list[str]:
    """Return a small startup-log tail suitable for structured error output."""
    if not log_file.exists():
        return []
    try:
        size = log_file.stat().st_size
        offset = int(since_offset or 0)
        if offset < 0 or offset > size:
            offset = 0
        with log_file.open("rb") as handle:
            handle.seek(max(offset, size - 128 * 1024, 0))
            text = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return [
        line if len(line) <= max_line_chars else line[:max_line_chars] + "..."
        for line in lines[-limit:]
    ]




def _remote_control_health_from_lines(lines: list[str], *, limit: int = 8) -> dict:
    falcon_lines = [line for line in lines if re.search(r"FalconTunnel|connect failed", line, re.IGNORECASE)]
    http_restart_lines = [
        line for line in lines
        if re.search(r"LogHttpServerModule:.*(Stopping all listeners|All listeners stopped|Starting all listeners|All listeners started)", line, re.IGNORECASE)
        or re.search(r"Start(Http|Gateway|Websocket)Server on port", line, re.IGNORECASE)
        or re.search(r"HttpListener.*(unable to bind|Created new HttpListener)", line, re.IGNORECASE)
    ]
    remote_lines = [
        line for line in lines
        if re.search(r"RemoteControl|WebRemoteControl|WebSocket", line, re.IGNORECASE)
    ]

    hints: list[str] = []
    for group in (falcon_lines, http_restart_lines, remote_lines):
        for line in group[-limit:]:
            if line not in hints:
                hints.append(line)
            if len(hints) >= limit:
                break
        if len(hints) >= limit:
            break

    if not hints:
        return {}

    result = {"log_hints": hints}
    if falcon_lines and http_restart_lines:
        result["likely_cause"] = "http_server_restarted_by_project_plugin"
        result["cause_hint"] = (
            "A project plugin appears to restart Unreal's HttpServer after Remote Control starts, "
            "leaving the TCP port reachable while Remote Control routes are unhealthy."
        )
    elif http_restart_lines:
        result["likely_cause"] = "http_server_restarted"
        result["cause_hint"] = "Unreal's HttpServer listeners were restarted while waiting for Remote Control."
    elif remote_lines:
        result["likely_cause"] = "remote_control_started_but_not_reachable"
        result["cause_hint"] = "Remote Control logged startup lines, but its HTTP route did not answer."
    return result


def _extract_remote_control_health_hints(text: str, *, limit: int = 8) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return {}
    return _remote_control_health_from_lines(lines, limit=limit)


def _extract_remote_control_health_hints_from_log(log_file: Path, *, since_offset: int | None = None, limit: int = 8) -> dict:
    if not log_file.exists():
        return {}
    matched: list[str] = []
    try:
        size = log_file.stat().st_size
        offset = int(since_offset or 0)
        if offset < 0 or offset > size:
            offset = 0
        with log_file.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                if re.search(
                    r"FalconTunnel|connect failed|RemoteControl|WebRemoteControl|WebSocket|"
                    r"LogHttpServerModule:.*(Stopping all listeners|All listeners stopped|Starting all listeners|All listeners started)|"
                    r"Start(Http|Gateway|Websocket)Server on port|"
                    r"HttpListener.*(unable to bind|Created new HttpListener)",
                    line,
                    re.IGNORECASE,
                ):
                    matched.append(line)
    except OSError:
        return {}

    if not matched:
        return {}
    return _remote_control_health_from_lines(matched, limit=limit)


def _diagnose_api_unreachable(log_file: Path, port: int, *, since_offset: int | None = None) -> dict:
    port_listening = _tcp_port_accepts_connection(port)
    result = {
        "port_listening": port_listening,
        "api_route_healthy": False,
        "failure_kind": "api_route_unhealthy" if port_listening else "api_not_listening",
    }
    if port_listening:
        result["suggestion"] = (
            f"Remote Control port is listening on {port}, but the HTTP route did not answer. "
            "Check project plugins that restart Unreal's HttpServer or bind competing HTTP listeners, then retry editor status/launch."
        )
    else:
        result["suggestion"] = (
            f"Port {port} is not accepting TCP connections yet. The editor may still be starting, blocked by a dialog, "
            "or Remote Control may not have bound the configured port."
        )

    hints = _extract_remote_control_health_hints_from_log(log_file, since_offset=since_offset)
    if not hints:
        hints = _extract_remote_control_health_hints(_read_log_tail(log_file))
    result.update(hints)
    return result


def _wait_for_api(proc, poll_port, timeout, log_file, state, on_progress=None) -> dict:
    from cli_anything.unreal.utils.ue_backend import _emit_heartbeat
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    if not state.json_output:
        try:
            if timeout is not None:
                sys.stderr.write(f"[editor] waiting for Remote Control API on port {poll_port} (timeout {timeout}s), log {log_file}\n")
            else:
                sys.stderr.write(f"[editor] waiting for Remote Control API on port {poll_port} (no timeout), log {log_file}\n")
            sys.stderr.flush()
        except Exception:
            pass

    api = UEEditorAPI(port=poll_port)
    start_time = time.time()
    progress_start = time.monotonic()
    deadline = start_time + timeout if timeout is not None else float("inf")
    poll_interval = 5.0
    heartbeat_interval = 60.0
    next_beat = start_time + heartbeat_interval
    result = {}
    startup_log_offset = log_file.stat().st_size if log_file.exists() else 0
    log_offset = startup_log_offset

    while time.time() < deadline:
        returncode = proc.poll()
        elapsed_seconds = int(time.monotonic() - progress_start)
        progress = {
            "startup_phase": "waiting_for_remote_control",
            "elapsed_seconds": elapsed_seconds,
            "port": poll_port,
            "process_alive": returncode is None,
            "log_file": str(log_file),
        }
        if on_progress is not None:
            try:
                on_progress(progress)
            except Exception:
                pass

        if returncode is not None:
            crash_result = {
                "status": "crashed",
                "failure_kind": "editor_process_exited",
                "startup_phase": "waiting_for_remote_control",
                "returncode": returncode,
                "port": poll_port,
                "process_alive": False,
                "elapsed_seconds": elapsed_seconds,
                "log_file": str(log_file),
                "error": f"Editor process exited with code {returncode} before API came online.",
                "suggestion": "Inspect log_tail and log_file for the startup failure, then retry editor launch after resolving it.",
            }
            log_tail = _bounded_log_tail_lines(
                log_file,
                since_offset=startup_log_offset,
            )
            if log_tail:
                crash_result["log_tail"] = log_tail
            project_path = getattr(state.session, "project_path", None)
            if project_path:
                crash_result["next_command"] = (
                    f'ue-cli --project "{project_path}" editor launch'
                )
            return crash_result

        if api.is_alive():
            return {
                "status": "online",
                "startup_phase": "ready",
                "port": poll_port,
                "process_alive": True,
                "startup_time_seconds": int(time.time() - start_time),
            }

        elapsed = time.time() - start_time
        if elapsed > 2:
            log_error, log_offset = _check_log_errors_incremental(log_file, log_offset)
            if log_error:
                return {
                    "status": "error_dialog",
                    "log_file": str(log_file),
                    "error": f"Editor appears stuck on an error dialog: {log_error}",
                }

        now = time.time()
        if now >= next_beat:
            if not state.json_output:
                _emit_heartbeat("editor", now - start_time, Path(log_file))
            next_beat += heartbeat_interval
        time.sleep(poll_interval)

    result["startup_phase"] = "waiting_for_remote_control"
    result["port"] = poll_port
    result["process_alive"] = proc.poll() is None
    result["status"] = "timeout"
    result["log_file"] = str(log_file)
    if timeout is not None:
        result["error"] = f"Editor API did not respond within {timeout}s on port {poll_port}."
    else:
        result["error"] = f"Editor API did not respond on port {poll_port}."
    log_error, _ = _check_log_errors_incremental(log_file, log_offset)
    if not log_error:
        log_error = _check_log_errors(log_file)
    if log_error:
        result["error"] += f" Log hint: {log_error}"
    diagnostics = _diagnose_api_unreachable(log_file, poll_port, since_offset=startup_log_offset)
    result.update(diagnostics)
    return result


@editor_group.command("launch")
@_project_option
@click.option("--map", "map_path", default=None, help="Level/map to open (.umap path)")
@click.option("--no-wait", is_flag=True, default=False)
@click.option("--timeout", default=None, type=int, help="Max seconds to wait for editor startup")
@click.option(
    "--extra-arg",
    "extra_args",
    multiple=True,
    metavar="ARG",
    help="Extra UE command-line argument forwarded verbatim to UnrealEditor.exe "
         "(repeat for multiple, e.g. --extra-arg -vulkan --extra-arg -ResX=1280).",
)
@handle_error
@click.pass_obj
def editor_launch(state: AppState, project_path, map_path, no_wait, timeout, extra_args):
    _load_command_project(state, project_path)
    require_project(state)
    foreground_timeout, worker_timeout = _launch_wait_timeouts(timeout)
    duplicate = _check_already_running(state.session, state)
    if duplicate is not None:
        if duplicate.get("status") == "already_running":
            raise AppError("ALREADY_RUNNING", duplicate["message"], exit_code=3, details=duplicate)
        if duplicate.get("status") == "starting":
            raise AppError("EDITOR_STARTING", duplicate["message"], exit_code=3, details=duplicate)
        # zombie: auto-kill the stale process and proceed
        from cli_anything.unreal.utils.ue_backend import _kill_process_tree
        _kill_process_tree(int(duplicate["pid"]))
        time.sleep(2)

    payload = {
        "project_path": state.session.project_path,
        "port": state.session.port,
        "map_path": map_path,
        "timeout": worker_timeout,
        "extra_args": list(extra_args) if extra_args else [],
    }
    task = submit_task("editor.launch", payload)
    if no_wait:
        output({"task_id": task["task_id"], "status": "submitted", "suggested_poll_interval_seconds": 5}, state)
        return

    final_task = wait_for_task(task["task_id"], foreground_timeout)
    if final_task is None:
        current = load_task(task["task_id"]) or task
        online_result = _recover_online_launch_result(state, task["task_id"], current)
        if online_result is not None:
            output(online_result, state)
            return
        progress = task_progress(current)
        if current.get("status") not in {"completed", "failed", "timeout", "cancelled"}:
            progress["status"] = "launching"
            progress["foreground_wait_timeout_seconds"] = foreground_timeout
            progress["message"] = "Editor launch is still in progress; poll this task or editor status."
            progress["next_command"] = f'ue-cli --project "{state.session.project_path}" editor status {task["task_id"]}'
        output(
            progress,
            state,
        )
        return

    progress = task_progress(final_task)
    if final_task.get("status") == "timeout":
        online_result = _recover_online_launch_result(state, task["task_id"], final_task)
        if online_result is not None:
            output(online_result, state)
            return
    if final_task.get("status") == "failed":
        error = final_task.get("error", {})
        raise AppError(error.get("code", "TASK_EXECUTION_FAILED"), error.get("message", "Editor launch failed"), exit_code=3, details=progress)
    output(progress, state)


@editor_group.command("cancel")
@click.argument("task_id")
@handle_error
@click.pass_obj
def editor_cancel(state: AppState, task_id):
    task = cancel_task(task_id)
    if task is None:
        raise AppError("TASK_NOT_FOUND", f"Task not found: {task_id}", exit_code=3)
    output(task_progress(task), state)


@editor_group.command("close")
@handle_error
@click.pass_obj
def editor_close(state: AppState):
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    api = UEEditorAPI(port=state.session.port)
    output(_close_editor_for_project(api, state), state)


def _close_editor_for_project(api, state: AppState) -> dict:
    """Close the targeted editor using the same robust path for all callers."""
    if not api.is_alive():
        kill_result = _kill_matching_project_editors(
            state.session.project_path,
            state.session.port,
            success_message="Remote Control API was offline; terminated matching UnrealEditor process.",
            failure_message="Remote Control API was offline and matching UnrealEditor process could not be terminated.",
        )
        if kill_result:
            if kill_result.get("status") == "closed":
                return kill_result
            raise AppError("EDITOR_CLOSE_FAILED", kill_result["message"], exit_code=3, details=kill_result)

        return {"status": "offline", "port": state.session.port, "message": "No editor running on this port."}

    target_pids = []
    if state.session.project_path and sys.platform == "win32":
        running, matches = _find_matching_project_editors(state.session.project_path)
        if not matches:
            raise AppError(
                "EDITOR_PROJECT_NOT_RUNNING",
                f"Remote Control API is alive on port {state.session.port}, but no running UnrealEditor process matches this project.",
                exit_code=3,
                details={
                    "port": state.session.port,
                    "project": state.session.project_path,
                    "running_editors": [
                        {"pid": editor.get("pid"), "project": editor.get("project", "")}
                        for editor in running
                    ],
                },
            )
        for editor in matches:
            try:
                target_pids.append(int(editor.get("pid", 0)))
            except (TypeError, ValueError):
                continue
        target_pids = sorted(pid for pid in set(target_pids) if pid)

    try:
        api.call_function(
            "/Script/UnrealEd.Default__EditorLoadingAndSavingUtils",
            "SaveDirtyPackages",
            {"bSaveMapPackages": True, "bSaveContentPackages": True},
        )
        time.sleep(1)
    except Exception:
        pass

    api.exec_console("QUIT_EDITOR")
    deadline = time.time() + 30
    last_process_evidence = None
    while time.time() < deadline:
        if not api.is_alive():
            drain_result = _wait_for_project_editor_exit(state.session.project_path, state.session.port, timeout=60)
            if drain_result is None:
                return {"status": "closed", "port": state.session.port}
            if drain_result.get("status") == "closed":
                result = {"status": "closed", "port": state.session.port}
                result.update(drain_result)
                result["port"] = state.session.port
                return result
            raise AppError(
                "EDITOR_CLOSE_FAILED",
                drain_result.get("message", "Editor API closed but UnrealEditor process did not exit."),
                exit_code=3,
                details=drain_result,
            )
        if target_pids:
            confirmed_exit, process_evidence = _project_process_exit_evidence(
                state.session.project_path,
                target_pids,
            )
            last_process_evidence = process_evidence
            if confirmed_exit:
                return {
                    "status": "closed",
                    "port": state.session.port,
                    "method": "project_process_exit",
                    "target_pids": target_pids,
                    "pid_evidence": process_evidence["pids"],
                }
        time.sleep(2)

    kill_result = _kill_matching_project_editors(
        state.session.project_path,
        state.session.port,
        success_message="Editor did not close gracefully within 30s; terminated matching UnrealEditor process.",
        failure_message="Editor did not close within 30s and matching UnrealEditor process could not be terminated.",
    )
    if kill_result and kill_result.get("status") == "closed":
        return kill_result

    details = kill_result or {"status": "timeout", "port": state.session.port}
    details.setdefault("stage", "wait_for_project_process_exit")
    if target_pids:
        details["target_pids"] = target_pids
        details["last_process_evidence"] = last_process_evidence
    raise AppError("EDITOR_CLOSE_TIMEOUT", "Editor did not close within 30s.", exit_code=3, details=details)


def _exec_console_with_log_capture(api, command: str, timeout: int = 15) -> dict:
    """Run a console command through Python so ExecutePythonCommandEx returns logs."""
    marker = f"{time.time_ns()}"
    begin = f"__ue_cli_exec_begin__:{marker}"
    end = f"__ue_cli_exec_end__:{marker}"
    script = f"""
import unreal
_cmd = {json.dumps(command)}
_begin = {json.dumps(begin)}
_end = {json.dumps(end)}
_world = None
try:
    _world = unreal.EditorLevelLibrary.get_editor_world()
except Exception:
    try:
        _world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    except Exception:
        _world = None
unreal.log(_begin)
try:
    unreal.SystemLibrary.execute_console_command(_world, _cmd)
finally:
    unreal.log(_end)
"""
    result = api.exec_python_ex(script, timeout=timeout)
    if result.get("error") or result.get("ReturnValue") is False:
        return {"error": result.get("error") or "Python console execution failed", "raw": result}

    captured: list[dict] = []
    inside = False
    saw_begin = False
    saw_end = False
    for item in result.get("LogOutput", []) or []:
        line = str(item.get("Output", ""))
        if "__ue_cli_exec_begin__:" in line:
            inside = True
            saw_begin = True
            continue
        if "__ue_cli_exec_end__:" in line:
            inside = False
            saw_end = True
            continue
        if inside:
            captured.append(item)

    if not saw_begin and not saw_end:
        captured = list(result.get("LogOutput", []) or [])

    log_text = "\n".join(str(item.get("Output", "")) for item in captured)
    return {
        "status": "executed",
        "command": command,
        "capture_mode": "python_log_output",
        "log_output": captured,
        "log_text": log_text,
        "_log_begin_marker": begin,
        "_log_end_marker": end,
    }


def _resolve_editor_log_file(state: AppState) -> Path | None:
    """Find the active editor log file for the current project/port."""
    project_dir = state.session.project_dir
    if not project_dir:
        try:
            from cli_anything.unreal.utils.ue_backend import find_running_editors
            from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

            pid = UEEditorAPI._get_pid_listening_on_port(state.session.port)
            for editor in find_running_editors():
                if pid and int(editor.get("pid", 0)) == int(pid):
                    project = editor.get("project")
                    if project:
                        project_dir = str(Path(project).parent)
                        break
        except Exception:
            project_dir = None

    if not project_dir:
        return None

    log_dir = Path(project_dir) / "Saved" / "Logs"
    if not log_dir.is_dir():
        return None

    project_log = log_dir / f"{Path(project_dir).name}.log"
    if project_log.exists():
        return project_log

    logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _read_log_delta(
    log_file: Path | None,
    start_pos: int,
    wait_seconds: float = 1.0,
    begin_marker: str | None = None,
    end_marker: str | None = None,
    completion_markers: tuple[str, ...] = (),
) -> str:
    if not log_file:
        return ""

    from cli_anything.unreal.utils.ue_http_api import _decode_windows_command_output

    deadline = time.time() + max(wait_seconds, 0.0)
    data = b""
    last_size: int | None = None
    stable_since: float | None = None
    completion_bytes = tuple(
        marker.encode("utf-8").lower()
        for marker in completion_markers
    )
    while True:
        try:
            size = log_file.stat().st_size
            offset = start_pos if size >= start_pos else 0
            with log_file.open("rb") as fh:
                fh.seek(offset)
                data = fh.read(2 * 1024 * 1024)
        except Exception:
            data = b""
            size = 0

        now = time.time()
        if data:
            if completion_bytes:
                lowered_data = data.lower()
                if any(marker in lowered_data for marker in completion_bytes):
                    break
            else:
                if size == last_size:
                    if stable_since is None:
                        stable_since = now
                    if (now - stable_since) >= 0.2 or now >= deadline:
                        break
                else:
                    last_size = size
                    stable_since = now

        if now >= deadline:
            break
        time.sleep(0.1)

    text = _decode_windows_command_output(data)
    lines = text.splitlines()
    if begin_marker and end_marker:
        captured: list[str] = []
        inside = False
        saw_begin = False
        for line in lines:
            if begin_marker in line:
                inside = True
                saw_begin = True
                continue
            if end_marker in line:
                break
            if inside:
                captured.append(line)
        if saw_begin:
            lines = captured
        else:
            return ""
    else:
        lines = [
            line
            for line in lines
            if "__ue_cli_exec_begin__:" not in line and "__ue_cli_exec_end__:" not in line
        ]
    return "\n".join(lines).strip()


@editor_group.command("exec")
@click.option("--timeout", default=15, type=int, help="Max seconds to wait for captured log output.")
@click.option(
    "--log-wait",
    default=1.0,
    type=float,
    help="Max seconds to collect Output Log lines; Automation waits for Queue Empty.",
)
@click.argument("command")
@handle_error
@click.pass_obj
def editor_exec(state: AppState, timeout, log_wait, command):
    """Execute a console command in the editor.

    Sends a UE console command directly (e.g. stat unit, renderdoc.captureframe).
    For Python execution, use ``editor run-script -c "code"`` for one-liners
    or ``editor run-script -`` for stdin.
    """
    api = require_editor(state)
    log_file = _resolve_editor_log_file(state)
    log_start = log_file.stat().st_size if log_file and log_file.exists() else 0

    result = _exec_console_with_log_capture(api, command, timeout=timeout)
    log_begin_marker = result.pop("_log_begin_marker", None)
    log_end_marker = result.pop("_log_end_marker", None)
    if result.get("error"):
        log_begin_marker = None
        log_end_marker = None
        result = api.exec_console(command)
        if not isinstance(result, dict):
            result = {"raw": result}
        if result:
            result.setdefault("capture_mode", "remote_console")

    if "error" in result and "400" in str(result["error"]):
        result["hint"] = (
            "Console command execution may be disabled in Remote Control settings. "
            "Run: ue-cli editor enable-remote"
        )
    elif not result or result == {}:
        result = {
            "status": "executed",
            "command": command,
            "capture_mode": "remote_console",
            "note": "Command executed. Console output is not captured by Remote Control API. "
                    "Check editor Output Log for results.",
        }

    automation_run = bool(
        re.match(r"^\s*Automation\s+RunTests(?:\s|$)", command, re.IGNORECASE)
    )
    file_log_text = ""
    if automation_run:
        file_log_text = _read_log_delta(
            log_file,
            log_start,
            wait_seconds=log_wait,
            completion_markers=("Automation Test Queue Empty",),
        )
    elif log_begin_marker and log_end_marker:
        file_log_text = _read_log_delta(
            log_file,
            log_start,
            wait_seconds=log_wait,
            begin_marker=log_begin_marker,
            end_marker=log_end_marker,
        )
    if file_log_text:
        result["log_file"] = str(log_file)
        result["log_file_text"] = file_log_text
        existing_output = list(result.get("log_output") or [])
        seen_output = {
            str(item.get("Output", ""))
            for item in existing_output
            if isinstance(item, dict)
        }
        result["log_output"] = existing_output + [
            {
                "Type": "Info",
                "Output": line,
                "Source": "editor_log_file",
            }
            for line in file_log_text.splitlines()
            if line and line not in seen_output
        ]
        if not result.get("log_text"):
            result["log_text"] = file_log_text
            result["capture_mode"] = "editor_log_file"

    if automation_run:
        automation_completed = (
            "automation test queue empty" in file_log_text.lower()
        )
        result["automation_completed"] = automation_completed
        result["log_capture_status"] = (
            "completed" if automation_completed else "timeout"
        )
        result["log_wait_seconds"] = log_wait
        if not automation_completed:
            result["suggestion"] = (
                "Automation did not emit 'Automation Test Queue Empty' within "
                "--log-wait. Inspect the project log or retry with a longer wait."
            )
            if log_file:
                escaped_log = str(log_file).replace("'", "''")
                result["log_file"] = str(log_file)
                result["next_command"] = (
                    "powershell -NoProfile -Command "
                    f"\"Get-Content -LiteralPath '{escaped_log}' -Tail 200\""
                )

    output(result, state)


def _is_transport_disconnect_result(result: dict) -> bool:
    """Return True when a command failed because the editor connection dropped."""
    if not isinstance(result, dict) or result.get("error_type"):
        return False
    text = " ".join(str(result.get(key, "")) for key in ("error", "traceback"))
    markers = (
        "ConnectionResetError",
        "Connection aborted",
        "RemoteDisconnected",
        "Connection refused",
        "forcibly closed",
        "WinError 10054",
        "10054",
    )
    return any(marker in text for marker in markers)


def _is_transport_timeout_result(result: dict) -> bool:
    """Return True when a command timed out waiting for an editor HTTP response."""
    if not isinstance(result, dict) or result.get("error_type"):
        return False
    text = " ".join(str(result.get(key, "")) for key in ("error", "traceback")).lower()
    markers = (
        "read timed out",
        "read timeout",
        "readtimeout",
        "timed out",
        "timeouterror",
    )
    return any(marker in text for marker in markers)


def _raise_editor_connection_lost(result: dict, operation: str) -> None:
    details = dict(result)
    details["failure_kind"] = "transport_disconnect"
    details["operation"] = operation
    raise AppError(
        "EDITOR_CONNECTION_LOST",
        f"Editor connection was lost while running {operation}.",
        exit_code=3,
        details=details,
        suggestion=(
            "Run editor status to check whether Unreal Editor crashed, exited, or is restarting; "
            "relaunch if offline, then retry after the editor is online."
        ),
    )


def _raise_editor_script_timeout(result: dict, operation: str, timeout: int) -> None:
    details = dict(result)
    details["failure_kind"] = "transport_timeout"
    details["operation"] = operation
    details["timeout_seconds"] = timeout
    details["completion_state"] = "unknown"
    raise AppError(
        "EDITOR_SCRIPT_TIMEOUT",
        f"Editor script timed out after {timeout} seconds without returning a result.",
        exit_code=3,
        details=details,
        suggestion=(
            f"Run editor status to verify the editor is still online. If the script is expected to run longer, "
            f"rerun with editor run-script --timeout <seconds> greater than {timeout}. "
            "Check the project Output Log because the script may still have completed in-editor after the HTTP timeout."
        ),
    )


def _raise_level_command_failed(result: dict, operation: str, code: str) -> None:
    raise AppError(
        code,
        str(result.get("error") or f"{operation} failed."),
        exit_code=3,
        details=result,
        suggestion="Run editor status, verify the active editor world, then retry the level command after the editor is online.",
    )


def _unsafe_run_script_operation(code: str) -> dict | None:
    """Detect UE Python operations known to crash unattended editor sessions."""
    if not code:
        return None

    operation = _unsafe_top_level_call(code)
    if operation:
        return {
            "operation": operation,
            "reason": "known_world_teardown_crash",
            "safe_workflow": [
                "ue-cli --project <Project.uproject> editor new-level /Game/Path/Level",
                "ue-cli --project <Project.uproject> editor open-level /Game/Path/Level",
                "ue-cli --project <Project.uproject> editor run-script <actor_setup.py>",
                "ue-cli --project <Project.uproject> editor save-level",
            ],
        }
    for match in re.finditer(r"open\s*\(\s*r?[\"']([^\"']+\.py)[\"']", code):
        source_path = Path(match.group(1))
        if not source_path.is_file():
            continue
        try:
            nested_code = source_path.read_text(encoding="utf-8")
        except OSError:
            continue
        unsafe = _unsafe_run_script_operation(nested_code)
        if unsafe:
            unsafe = dict(unsafe)
            unsafe["source_path"] = str(source_path)
            return unsafe
    return None


def _unsafe_top_level_call(code: str) -> str | None:
    """Find top-level map transition calls while allowing reusable helper defs."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        patterns = (
            r"\bEditorLoadingAndSavingUtils\s*\.\s*new_blank_map\s*\(",
            r"\bEditorLoadingAndSavingUtils\s*\.\s*load_map\s*\(",
            r"\bnew_blank_map\s*\(",
            r"\bload_map\s*\(",
        )
        if any(re.search(pattern, code) for pattern in patterns):
            return (
                "EditorLoadingAndSavingUtils.load_map"
                if re.search(r"\b(?:EditorLoadingAndSavingUtils\s*\.\s*)?load_map\s*\(", code)
                else "EditorLoadingAndSavingUtils.new_blank_map"
            )
        return None

    class Visitor(ast.NodeVisitor):
        found: str | None = None

        def visit_FunctionDef(self, node):  # noqa: N802
            return

        def visit_AsyncFunctionDef(self, node):  # noqa: N802
            return

        def visit_ClassDef(self, node):  # noqa: N802
            return

        def visit_Lambda(self, node):  # noqa: N802
            return

        def visit_Call(self, node):  # noqa: N802
            name = _call_name(node.func)
            if name in {"load_map", "EditorLoadingAndSavingUtils.load_map", "unreal.EditorLoadingAndSavingUtils.load_map"}:
                self.found = "EditorLoadingAndSavingUtils.load_map"
                return
            if name in {"new_blank_map", "EditorLoadingAndSavingUtils.new_blank_map", "unreal.EditorLoadingAndSavingUtils.new_blank_map"}:
                self.found = "EditorLoadingAndSavingUtils.new_blank_map"
                return
            self.generic_visit(node)

    visitor = Visitor()
    for statement in tree.body:
        if visitor.found:
            break
        visitor.visit(statement)
    return visitor.found


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _raise_unsafe_run_script_operation(unsafe: dict) -> None:
    raise AppError(
        "UNSAFE_RUN_SCRIPT_OPERATION",
        f"{unsafe['operation']} is blocked in editor run-script because it can crash unattended editor sessions.",
        exit_code=2,
        details=unsafe,
        suggestion=(
            "Use editor new-level or editor open-level for map transitions, then run a separate script "
            "for actor/content setup and save with editor save-level."
        ),
    )


@editor_group.command("run-script")
@click.argument("script_path", type=click.Path(exists=False), required=False, default=None)
@click.option("-c", "--code", default=None, help="Short inline Python code; use '-' or a script file for multiline code.")
@click.option("--timeout", default=30, type=int, help="Max seconds to wait for results.")
@click.option("--no-save", "no_save", is_flag=True, default=False, help="Skip auto-saving dirty packages after script execution.")
@handle_error
@click.pass_obj
def editor_run_script(state: AppState, script_path, code, timeout, no_save):
    """Execute Python in the editor with structured result capture.

    Provide a script file path, "-" to read code from stdin, or short inline
    code via -c:

    \b
        editor run-script myscript.py
        editor run-script -
        editor run-script -c "result = {'hello': 'world'}"

    For multiline Python in PowerShell, pipe a here-string into
    ``editor run-script -`` so shell argument splitting cannot corrupt code
    or indentation.

    The script should set a ``result`` dict variable.  It will be
    automatically captured and returned as structured JSON output.

    By default, dirty packages are saved after execution.
    Use --no-save to skip this.
    """
    if not script_path and not code:
        raise AppError("MISSING_INPUT", "Provide a script file path, '-' for stdin, or use -c for short inline code.",
                       suggestion="editor run-script myscript.py  OR  editor run-script -  OR  editor run-script -c \"code\"")
    if script_path and code:
        raise AppError("AMBIGUOUS_INPUT", "Provide either a script file path or -c, not both.")

    from cli_anything.unreal.core.script_runner import run_python_code, run_python_script

    stdin_code = None
    if script_path == "-":
        stdin_code = _read_stdin_python_code()
        if stdin_code == "":
            raise AppError(
                "MISSING_STDIN_CODE",
                "No Python code was received on stdin.",
                exit_code=2,
                suggestion="Pipe a PowerShell here-string: @' ... '@ | ue-cli editor run-script -",
            )
    elif script_path:
        path = Path(script_path)
        if not path.is_file():
            raise AppError(
                "FILE_NOT_FOUND",
                f"Script file not found: {script_path}",
                exit_code=3,
                suggestion="Pass an existing .py file, '-' for stdin, or -c for a short one-liner.",
            )

    if code is not None or stdin_code is not None:
        unsafe = _unsafe_run_script_operation(code if code is not None else stdin_code)
        if unsafe:
            _raise_unsafe_run_script_operation(unsafe)
    else:
        script_code = Path(script_path).read_text(encoding="utf-8")
        unsafe = _unsafe_run_script_operation(script_code)
        if unsafe:
            _raise_unsafe_run_script_operation(unsafe)

    api = require_editor(state)

    if code is not None or stdin_code is not None:
        result = run_python_code(
            api, code if code is not None else stdin_code,
            project_dir=state.session.project_dir,
            timeout=timeout,
            save=not no_save,
        )
    else:
        result = run_python_script(
            api, script_path,
            project_dir=state.session.project_dir,
            timeout=timeout,
            save=not no_save,
        )
    if isinstance(result, dict) and result.get("error"):
        if _is_transport_disconnect_result(result):
            _raise_editor_connection_lost(result, "editor run-script")
        if _is_transport_timeout_result(result):
            _raise_editor_script_timeout(result, "editor run-script", timeout)
        raise AppError(
            "SCRIPT_EXECUTION_FAILED",
            str(result.get("error")),
            exit_code=3,
            details=result,
            suggestion="Fix the UE Python script exception and rerun editor run-script.",
        )
    output(result, state)


@editor_group.command("api-discover")
@click.argument("target")
@click.option("--query", "-q", default=None, help="Case-insensitive regex filter for property/function names.")
@click.option("--detail", "-d", default=None, metavar="NAMES", help="Comma-separated names to get full detail for.")
@click.option("--timeout", default=30, type=int, help="Max seconds to wait for results.")
@handle_error
@click.pass_obj
def editor_api_discover(state: AppState, target, query, detail, timeout):
    """Discover the API surface of a UE class via C++ reflection.

    TARGET is auto-detected: class name, asset/subobject path, or actor path.
    Use -d to drill into specific properties/functions.
    """
    from cli_anything.unreal.core.script_runner import api_discover
    api = require_editor(state)
    result = api_discover(api, target, query=query, detail=detail, timeout=timeout)
    output(result, state)


@editor_group.command("enable-remote")
@handle_error
@click.pass_obj
def editor_enable_remote(state: AppState):
    """Enable Remote Control features for CLI use.

    Creates/updates DefaultRemoteControl.ini to allow remote console
    command execution and remote Python execution. Requires editor
    restart to take effect.
    """
    from cli_anything.unreal.utils.ue_backend import ensure_remote_control_config, get_editor_binary_prefix

    require_project(state)
    result = ensure_remote_control_config(
        state.session.project_dir,
        engine_root=state.session.engine_root,
        editor_binary_prefix=get_editor_binary_prefix(state.session.engine_root),
    )
    output(result, state)


@editor_group.command("plugin-version")
@handle_error
@click.pass_obj
def editor_plugin_version(state: AppState):
    """Check CliAnythingBridge plugin version (bundled vs loaded).

    Reports the version bundled with the CLI package and the version
    currently loaded in the running editor (if any).
    """
    from cli_anything.unreal.core.plugin_bridge import get_bundled_version, get_loaded_plugin_version

    bundled = get_bundled_version()
    loaded = None

    if state.session.project_dir:
        api = require_editor(state)
        loaded = get_loaded_plugin_version(api)

    output({
        "bundled_version": bundled,
        "loaded_version": loaded,
        "match": loaded is not None and loaded == bundled,
    }, state)


@editor_group.command("plugin-upgrade")
@handle_error
@click.pass_obj
def editor_plugin_upgrade(state: AppState):
    """Upgrade the CliAnythingBridge plugin if a newer version is available.

    Workflow: deploy updated plugin source, compile the project,
    restart the editor if it was running, verify the new version.
    """
    from cli_anything.unreal.core.plugin_bridge import (
        ensure_plugin_deployed,
        get_bundled_version,
        get_loaded_plugin_version,
    )

    require_project(state)
    project_dir = state.session.project_dir

    import shutil
    plugin_dir = Path(project_dir) / "Plugins" / "CliAnythingBridge"
    bundled = get_bundled_version()

    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI
    api = UEEditorAPI(port=state.session.port)
    editor_was_running = api.is_alive()
    loaded = None

    if editor_was_running:
        loaded = get_loaded_plugin_version(api)
        if loaded == bundled:
            output({"status": "up_to_date", "version": bundled}, state)
            return

        _close_editor_for_project(api, state)
        for _ in range(30):
            if not api.is_alive():
                break
            time.sleep(1)
        drain_result = _wait_for_project_editor_exit(state.session.project_path, state.session.port, timeout=60)
        if drain_result and drain_result.get("status") not in {"closed", "offline"}:
            raise AppError(
                "EDITOR_CLOSE_FAILED",
                "Editor process did not fully exit before plugin compile; project DLLs may still be locked.",
                exit_code=3,
                suggestion="Close or kill UnrealEditor processes for this project, then retry editor plugin-upgrade.",
                details=drain_result,
            )

    if plugin_dir.exists():
        _remove_tree_with_retries(plugin_dir)

    deploy = ensure_plugin_deployed(project_dir)
    if not deploy["deployed"]:
        raise AppError("DEPLOY_FAILED", deploy.get("error", "Deployment failed"))

    plugin_intermediate = plugin_dir / "Intermediate"
    plugin_binaries = plugin_dir / "Binaries"
    if plugin_intermediate.exists():
        _remove_tree_with_retries(plugin_intermediate)
    if plugin_binaries.exists():
        _remove_tree_with_retries(plugin_binaries)

    from cli_anything.unreal.core.build import compile_project
    build_result = compile_project(state.session.project_path, engine_root=state.session.engine_root)
    if build_result.get("status") == "error":
        details = {
            "log_file": build_result.get("log_file", ""),
            "returncode": build_result.get("returncode"),
        }
        details.update(_extract_compile_lock_error(build_result.get("log_file", "")))
        suggestion = None
        if details.get("locked_file"):
            suggestion = (
                "A DLL is locked during compile. Close all UnrealEditor processes for this project "
                "or stop the process holding the DLL, then retry editor plugin-upgrade."
            )
        raise AppError(
            "COMPILE_FAILED",
            build_result.get("error", "Build failed"),
            suggestion=suggestion,
            details=details,
        )

    if editor_was_running:
        from cli_anything.unreal.utils.ue_backend import find_editor_exe
        engine_root = state.session.engine_root
        editor_exe = find_editor_exe(engine_root) if engine_root else None
        if editor_exe:
            cmd = _build_launch_cmd(editor_exe, state.session.project_path, None)
            sp.Popen(cmd, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
            for _ in range(60):
                time.sleep(2)
                if api.is_alive():
                    break

            new_loaded = get_loaded_plugin_version(api)
            if new_loaded == bundled:
                output({
                    "status": "upgraded",
                    "version": bundled,
                    "previous_version": loaded,
                }, state)
            else:
                output({
                    "status": "version_mismatch",
                    "expected": bundled,
                    "loaded": new_loaded,
                }, state)
            return

    output({
        "status": "deployed",
        "action": deploy.get("action"),
        "version": deploy.get("version", bundled),
        "plugin_dir": deploy.get("plugin_dir"),
        "needs_restart": editor_was_running,
    }, state)


@editor_group.group("cvar")
def cvar_group():
    """Get and set console variables."""


@cvar_group.command("get")
@click.argument("name")
@handle_error
@click.pass_obj
def cvar_get(state: AppState, name):
    """Get a console variable value."""
    api = require_editor(state)
    info = api.get_cvar_info(name)
    value = str(info.get("value", ""))
    exists = info.get("exists")
    if exists is False:
        raise AppError(
            "CVAR_NOT_FOUND",
            f"CVar not found: {name}",
            exit_code=2,
            suggestion="Check the CVar name, or search with UE console command help.",
            details=info,
        )
    if value == "" and exists is None:
        raise AppError(
            "CVAR_GET_AMBIGUOUS_EMPTY",
            f"CVar returned an empty value, but existence could not be verified: {name}",
            exit_code=2,
            suggestion="Run: ue-cli editor plugin-upgrade, restart editor, then retry.",
            details=info,
        )
    result = {"name": info.get("name", name), "value": value}
    if exists is not None:
        result["exists"] = exists
    if info.get("verification"):
        result["verification"] = info["verification"]
    output(result, state)


@cvar_group.command(
    "set",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("name")
@click.argument("value", nargs=-1, type=click.UNPROCESSED)
@handle_error
@click.pass_obj
def cvar_set(state: AppState, name, value):
    """Set a console variable value."""
    if not value:
        raise AppError(
            "MISSING_CVAR_VALUE",
            "CVar set requires a value.",
            exit_code=2,
            suggestion="Use: ue-cli editor cvar set NAME VALUE",
        )
    value = " ".join(value)
    api = require_editor(state)
    result = api.set_cvar(name, value)
    if "error" in result and "400" in str(result["error"]):
        raise AppError(
            "CVAR_SET_FAILED",
            "CVar set failed. Remote console command execution is disabled.",
            suggestion="Run: ue-cli editor enable-remote, then restart editor.",
            details={"name": name, "value": value},
        )
    output({"name": name, "value": value, "status": "ok", **result}, state)


@editor_group.command("new-level")
@click.argument("level_path")
@click.option("--template", default=None, help="Optional path to a template level to clone")
@handle_error
@click.pass_obj
def editor_new_level(state: AppState, level_path, template):
    """Create and open a new level."""
    from cli_anything.unreal.core.scene import new_level
    api = require_editor(state)
    result = new_level(api, level_path, template)
    if _is_transport_disconnect_result(result):
        _raise_editor_connection_lost(result, "editor new-level")
    if isinstance(result, dict) and (result.get("error") or result.get("status") == "failed"):
        _raise_level_command_failed(result, "editor new-level", "EDITOR_NEW_LEVEL_FAILED")
    output(result, state)


@editor_group.command("open-level")
@click.argument("level_path")
@handle_error
@click.pass_obj
def editor_open_level(state: AppState, level_path):
    """Open an existing level."""
    from cli_anything.unreal.core.scene import open_level
    api = require_editor(state)
    result = open_level(api, level_path)
    if _is_transport_disconnect_result(result):
        _raise_editor_connection_lost(result, "editor open-level")
    if isinstance(result, dict) and (result.get("error") or result.get("status") == "failed"):
        _raise_level_command_failed(result, "editor open-level", "EDITOR_OPEN_LEVEL_FAILED")
    output(result, state)


@editor_group.command("save-level")
@handle_error
@click.pass_obj
def editor_save_level(state: AppState):
    """Save the current level."""
    from cli_anything.unreal.core.scene import save_level
    api = require_editor(state)
    result = save_level(api)
    if _is_transport_disconnect_result(result):
        _raise_editor_connection_lost(result, "editor save-level")
    output(result, state)
