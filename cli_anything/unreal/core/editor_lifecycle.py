"""Editor launch lifecycle helpers shared by commands and task workers."""

from __future__ import annotations

import re
import socket
import sys
import time
from pathlib import Path

from cli_anything.unreal.core.tasks import FINAL_TASK_STATUSES, iter_tasks


_FATAL_LOG_PATTERNS = [
    "modules are missing or built with a different engine version",
    "Still incompatible or missing module:",
    "Engine modules cannot be compiled at runtime",
    "Missing or incompatible modules",
    "Plugin .* failed to load",
    "Fatal Error:",
    "Assertion failed:",
]

_WINDOWS_STATUS_ENTRYPOINT_NOT_FOUND = 0xC0000139
_MISSING_VIRTUAL_SHADER_SOURCE_PATTERN = re.compile(
    r"Couldn't find source file of virtual shader path\s+['\"](?P<shader_path>[^'\"]+)['\"]",
    re.IGNORECASE,
)


def _active_launch_task_for_project(
    project_path: str | None,
    pid: int | None = None,
    *,
    timeout: float | None = None,
) -> dict | None:
    if not project_path:
        return None
    now = time.time()
    for task in iter_tasks(timeout=timeout):
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

def _summarize_startup_precheck(check: dict) -> dict:
    errors = check.get("engine", {}).get("errors", []) + check.get("project", {}).get("errors", [])
    warnings = check.get("engine", {}).get("warnings", []) + check.get("project", {}).get("warnings", [])
    for issue in check.get("bridge_plugin", {}).get("issues", []):
        warnings.append(issue)
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
                "suggestion": (
                    "The existing editor is preserved. Restore its Remote Control endpoint, "
                    "or use editor close --force only when data loss is authorized."
                ),
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

def _deploy_bridge(session, state) -> dict:
    from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed

    return ensure_plugin_deployed(session.project_dir, preserve_existing=True)

def _launch_extra_arg_parts(arg) -> tuple[str, str | None]:
    raw = str(arg).strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1].strip()
    token = raw.lstrip("-/")
    name, separator, value = token.partition("=")
    if not separator:
        return name.casefold(), None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return name.casefold(), value

def _remote_control_launch_error(extra_args) -> dict | None:
    for arg in extra_args or ():
        name, _ = _launch_extra_arg_parts(arg)
        if name != "nullrhi":
            continue
        return {
            "code": "EDITOR_LAUNCH_NULLRHI_UNSUPPORTED",
            "message": "editor launch cannot use Remote Control with -NullRHI.",
            "suggestion": "Remove -NullRHI; controlled editor launch requires a render-capable UnrealEditor process.",
            "details": {
                "incompatible_argument": str(arg),
                "required_service": "WebRemoteControl",
                "editor_started": False,
            },
        }
    return None

def _resolve_launch_log_file(project_dir, project_name, extra_args=None) -> Path:
    for arg in extra_args or ():
        name, value = _launch_extra_arg_parts(arg)
        if name == "abslog" and value:
            return Path(value)
    return Path(project_dir) / "Saved" / "Logs" / f"{project_name}.log"

def _build_launch_cmd(
    editor_exe,
    project_path,
    map_path,
    extra_args=None,
    *,
    unattended: bool = False,
) -> list:
    cmd = [editor_exe, project_path]
    if map_path:
        # Unreal parses maps as URL parameters only before command-line flags.
        cmd.append(map_path)
    cmd.append("-nosplash")
    if unattended:
        cmd.append("-unattended")
    if extra_args:
        cmd.extend(str(arg) for arg in extra_args if arg is not None and str(arg) != "")
    return cmd

def _extract_log_error(text: str) -> tuple[str | None, str | None]:
    for pattern in _FATAL_LOG_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start = max(0, match.start() - 100)
            end = min(len(text), match.end() + 300)
            return text[start:end].strip(), pattern
    return None, None


def _full_editor_rebuild_diagnostics(
    *,
    project_path: str | None,
    log_error: str | None = None,
    returncode: int | None = None,
) -> dict:
    """Recognize launch signatures that need a full, non-module Editor rebuild."""
    diagnostic_basis = None
    failure_kind = None
    shader_path = None
    if log_error:
        shader_match = _MISSING_VIRTUAL_SHADER_SOURCE_PATTERN.search(log_error)
        if shader_match:
            diagnostic_basis = "registered_virtual_shader_source_missing"
            failure_kind = "engine_binary_source_mismatch"
            shader_path = shader_match.group("shader_path")

    normalized_returncode = None
    if returncode is not None:
        try:
            normalized_returncode = int(returncode) & 0xFFFFFFFF
        except (TypeError, ValueError):
            normalized_returncode = None
        if normalized_returncode == _WINDOWS_STATUS_ENTRYPOINT_NOT_FOUND:
            diagnostic_basis = "windows_status_entrypoint_not_found"
            failure_kind = "engine_binary_entrypoint_mismatch"

    if failure_kind is None:
        return {}

    result = {
        "failure_kind": failure_kind,
        "likely_cause": "stale_or_mixed_engine_binaries",
        "diagnostic_basis": diagnostic_basis,
        "requires_full_editor_rebuild": True,
        "suggestion": (
            "The checked-out Engine source and loaded DLL set may be inconsistent. "
            "Run a full Editor target compile without --module, then retry editor launch."
        ),
    }
    if project_path:
        result["recovery_command"] = (
            f'ue-cli --project "{project_path}" build compile '
            "--platform Win64 --config Development"
        )
    if shader_path:
        result["missing_virtual_shader_path"] = shader_path
    if normalized_returncode == _WINDOWS_STATUS_ENTRYPOINT_NOT_FOUND:
        result["windows_status"] = "STATUS_ENTRYPOINT_NOT_FOUND"
        result["returncode_hex"] = "0xC0000139"
    return result

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

def _remote_control_health_from_lines(
    lines: list[str],
    *,
    limit: int = 8,
    target_port: int | None = None,
) -> dict:
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

    latest_stop = max(
        (
            index for index, line in enumerate(lines)
            if re.search(r"LogHttpServerModule:.*Stopping all listeners", line, re.IGNORECASE)
        ),
        default=None,
    )
    cycle_lines = lines[latest_stop:] if latest_stop is not None else lines
    cycle_http_lines = [line for line in cycle_lines if line in http_restart_lines]
    cycle_falcon_lines = [line for line in cycle_lines if line in falcon_lines]

    def _mentions_target_port(line: str) -> bool:
        if target_port is None:
            return True
        return bool(re.search(rf"(?<!\d){re.escape(str(target_port))}(?!\d)", line))

    target_bind_lines = [
        line for line in cycle_lines
        if re.search(r"HttpListener.*unable to bind", line, re.IGNORECASE)
        and _mentions_target_port(line)
    ]
    restart_completed = bool(
        latest_stop is not None
        and any(
            re.search(r"LogHttpServerModule:.*All listeners started", line, re.IGNORECASE)
            for line in cycle_lines
        )
    )

    hints: list[str] = []
    for group in (
        target_bind_lines,
        cycle_http_lines,
        cycle_falcon_lines,
        remote_lines,
        http_restart_lines,
        falcon_lines,
    ):
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
    if latest_stop is not None:
        if target_bind_lines:
            result["http_server_restart_status"] = "bind_failed"
        elif restart_completed:
            result["http_server_restart_status"] = "completed"
        else:
            result["http_server_restart_status"] = "incomplete"

    if target_bind_lines:
        result["likely_cause"] = "remote_control_port_bind_failed"
        port_label = str(target_port) if target_port is not None else "the requested Remote Control port"
        result["cause_hint"] = (
            f"Unreal's HttpListener failed to bind {port_label}."
        )
    elif latest_stop is not None and not restart_completed:
        if cycle_falcon_lines:
            result["likely_cause"] = "http_server_restart_incomplete_by_project_plugin"
            result["cause_hint"] = (
                "A project plugin restarted Unreal's HttpServer, but the latest log cycle did not record listener startup completion."
            )
        else:
            result["likely_cause"] = "http_server_restart_incomplete"
            result["cause_hint"] = (
                "Unreal's latest HttpServer restart did not record listener startup completion."
            )
    elif restart_completed:
        result["cause_hint"] = (
            "The HttpServer listener restart completed without a logged bind failure. "
            "This log sequence alone does not show that Remote Control routes were lost."
        )
    elif remote_lines:
        result["likely_cause"] = "remote_control_started_but_not_reachable"
        result["cause_hint"] = "Remote Control logged startup lines, but its HTTP route did not answer."
    return result

def _extract_remote_control_health_hints(
    text: str,
    *,
    limit: int = 8,
    target_port: int | None = None,
) -> dict:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return {}
    return _remote_control_health_from_lines(lines, limit=limit, target_port=target_port)

def _extract_remote_control_health_hints_from_log(
    log_file: Path,
    *,
    since_offset: int | None = None,
    limit: int = 8,
    target_port: int | None = None,
) -> dict:
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
    return _remote_control_health_from_lines(matched, limit=limit, target_port=target_port)

def _diagnose_api_unreachable(log_file: Path, port: int, *, since_offset: int | None = None) -> dict:
    port_listening = _tcp_port_accepts_connection(port)
    result = {
        "port_listening": port_listening,
        "api_route_healthy": False,
        "failure_kind": "api_route_unhealthy" if port_listening else "api_not_listening",
    }
    hints = _extract_remote_control_health_hints_from_log(
        log_file,
        since_offset=since_offset,
        target_port=port,
    )
    if not hints:
        hints = _extract_remote_control_health_hints(
            _read_log_tail(log_file),
            target_port=port,
        )
    result.update(hints)
    if port_listening and result.get("http_server_restart_status") == "completed" and not result.get("likely_cause"):
        result["suggestion"] = (
            f"Remote Control port is listening on {port}, but the HTTP route did not answer. "
            "The HttpServer listener restart completed without bind errors, so do not restart the editor from this signal alone; "
            "poll the active launch task or retry editor status."
        )
    elif port_listening and result.get("likely_cause") == "remote_control_port_bind_failed":
        result["suggestion"] = (
            f"Remote Control port is listening on {port}, but the HTTP route did not answer and the log shows a bind failure "
            "for that port. Inspect port ownership and the reported HttpListener log hints, then retry editor status."
        )
    elif port_listening and result.get("likely_cause") == "http_server_restart_incomplete_by_project_plugin":
        result["suggestion"] = (
            f"Remote Control port is listening on {port}, but the HTTP route did not answer and the log shows an incomplete "
            "listener restart or bind failure. Inspect the reported project-plugin log hints, then retry editor status."
        )
    elif port_listening:
        result["suggestion"] = (
            f"Remote Control port is listening on {port}, but the HTTP route did not answer. "
            "The editor may still be initializing or temporarily busy; retry editor status."
        )
    else:
        result["suggestion"] = (
            f"Port {port} is not accepting TCP connections yet. The editor may still be starting, blocked by a dialog, "
            "or Remote Control may not have bound the configured port."
        )
    return result

def _restore_packages_blocker(proc) -> dict | None:
    if sys.platform != "win32":
        return None
    try:
        process_id = int(proc.pid)
    except (AttributeError, TypeError, ValueError):
        return None
    if process_id <= 0:
        return None

    from cli_anything.unreal.utils.ue_backend import detect_ue_dialogs

    try:
        dialogs = detect_ue_dialogs(process_id=process_id)
    except Exception:
        return None

    for dialog in dialogs:
        title = str(dialog.get("title") or "")
        title_lower = title.casefold()
        if "restore" not in title_lower or "package" not in title_lower:
            continue
        return {
            "title": title,
            "hwnd": dialog.get("hwnd"),
            "process_id": process_id,
        }
    return None

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
            crash_result.update(
                _full_editor_rebuild_diagnostics(
                    project_path=project_path,
                    returncode=returncode,
                )
            )
            if project_path:
                crash_result["next_command"] = (
                    f'ue-cli --project "{project_path}" editor launch'
                )
            return crash_result

        if api.is_alive():
            owner_pid = None
            owner_verified = sys.platform != "win32"
            if sys.platform == "win32":
                try:
                    owner_pid = UEEditorAPI._get_pid_listening_on_port(poll_port)
                    owner_verified = (
                        owner_pid is not None
                        and int(owner_pid) == int(proc.pid)
                    )
                except (AttributeError, OSError, TypeError, ValueError):
                    owner_verified = False
            if owner_verified:
                return {
                    "status": "online",
                    "startup_phase": "ready",
                    "port": poll_port,
                    "process_alive": True,
                    "process_id": int(proc.pid),
                    "port_owner_pid": int(owner_pid) if owner_pid is not None else None,
                    "port_owner_verified": sys.platform == "win32",
                    "startup_time_seconds": int(time.time() - start_time),
                }
            progress.update({
                "startup_phase": "waiting_for_port_owner",
                "api_reachable": True,
                "expected_process_id": int(proc.pid),
                "port_owner_pid": int(owner_pid) if owner_pid is not None else None,
                "port_owner_verified": False,
            })
            if on_progress is not None:
                try:
                    on_progress(progress)
                except Exception:
                    pass

        restore_blocker = _restore_packages_blocker(proc)
        if restore_blocker is not None:
            blocked_result = {
                "status": "blocked_by_restore_packages",
                "failure_kind": "blocked_by_restore_packages",
                "startup_phase": "blocked_by_restore_packages",
                "port": poll_port,
                "process_alive": True,
                "elapsed_seconds": elapsed_seconds,
                "log_file": str(log_file),
                "blocking_dialog": restore_blocker,
                "error": "Editor startup is blocked by the Restore Packages dialog.",
                "suggestion": (
                    "Choose Restore Selected or Skip Restore in the Unreal Editor dialog, "
                    "then run editor status. Do not start a second editor for this project."
                ),
            }
            if on_progress is not None:
                try:
                    on_progress(blocked_result)
                except Exception:
                    pass
            return blocked_result

        elapsed = time.time() - start_time
        if elapsed > 2:
            log_error, log_offset = _check_log_errors_incremental(log_file, log_offset)
            if log_error:
                error_result = {
                    "status": "error_dialog",
                    "log_file": str(log_file),
                    "error": f"Editor appears stuck on an error dialog: {log_error}",
                }
                error_result.update(
                    _full_editor_rebuild_diagnostics(
                        project_path=getattr(state.session, "project_path", None),
                        log_error=log_error,
                    )
                )
                return error_result

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
