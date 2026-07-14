"""Persistent background-task helpers for long-running CLI operations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


FINAL_TASK_STATUSES = {"completed", "failed", "timeout", "cancelled"}
BUILD_TASK_COMMANDS = {"build.compile", "build.cook", "build.package"}


def _task_root() -> Path:
    override = os.environ.get("UE_CLI_TASK_DIR")
    if override:
        root = Path(override)
    else:
        root = Path(tempfile.gettempdir()) / "ue_cli_tasks"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _task_path(task_id: str) -> Path:
    return _task_root() / f"{task_id}.json"



def _cancel_path(task_id: str) -> Path:
    return _task_root() / f"{task_id}.cancel"


def _lock_path(task_id: str) -> Path:
    return _task_root() / f"{task_id}.lock"


@contextmanager
def _task_lock(task_id: str):
    """Serialize task read-modify-write updates across CLI/worker processes."""
    lock_path = _lock_path(task_id)
    with lock_path.open("a+b") as lock_file:
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            lock_file.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _normalize_project_path(path: str) -> str:
    return str(Path(path).resolve()).replace("/", "\\").casefold()


def _request_task_cancel(task_id: str) -> None:
    _cancel_path(task_id).touch(exist_ok=True)


def _task_cancel_requested(task_id: str) -> bool:
    return _cancel_path(task_id).exists()


def _query_process_info(pid: int) -> dict:
    """Read current PID identity before acting on persisted task metadata."""
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return {"query_ok": True, "found": False, "pid": pid}
        except Exception as exc:
            return {"query_ok": False, "found": False, "pid": pid, "error": str(exc)}
        return {"query_ok": True, "found": True, "pid": pid}

    ps_cmd = (
        f'$p = Get-CimInstance Win32_Process -Filter "ProcessId = {pid}"; '
        'if ($null -ne $p) { '
        '$p | Select-Object ProcessId, ParentProcessId, Name, CommandLine, CreationDate '
        '| ConvertTo-Json -Compress }'
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return {"query_ok": False, "found": False, "pid": pid, "error": str(exc)}
    if result.returncode != 0:
        return {
            "query_ok": False,
            "found": False,
            "pid": pid,
            "error": (result.stderr or result.stdout or "process query failed").strip(),
        }
    if not result.stdout.strip():
        return {"query_ok": True, "found": False, "pid": pid}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"query_ok": False, "found": False, "pid": pid, "error": str(exc)}
    return {
        "query_ok": True,
        "found": True,
        "pid": int(data.get("ProcessId") or pid),
        "parent_pid": int(data.get("ParentProcessId") or 0),
        "name": str(data.get("Name") or ""),
        "cmdline": str(data.get("CommandLine") or ""),
        "creation_date": str(data.get("CreationDate") or ""),
    }


def _same_process_identity(before: dict, after: dict) -> bool:
    if before.get("pid") != after.get("pid"):
        return False
    before_created = before.get("creation_date")
    after_created = after.get("creation_date")
    if before_created and after_created:
        return before_created == after_created
    return all(
        before.get(key) == after.get(key)
        for key in ("parent_pid", "name", "cmdline")
    )

def new_task_id() -> str:
    return f"t-{uuid.uuid4().hex[:12]}"


def create_task(command: str, payload: dict) -> dict:
    payload = dict(payload)
    project_path = payload.get("project_path")
    if project_path:
        payload["project_path"] = str(Path(project_path).resolve())

    now = time.time()
    task = {
        "task_id": new_task_id(),
        "command": command,
        "payload": payload,
        "status": "submitted",
        "created_at": now,
        "updated_at": now,
        "suggested_poll_interval_seconds": 5,
    }
    return save_task(task)


def load_task(task_id: str) -> dict | None:
    path = _task_path(task_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_task_unlocked(task: dict) -> dict:
    task["updated_at"] = time.time()
    path = _task_path(task["task_id"])
    temp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temp_path.write_text(
            json.dumps(task, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return task


def save_task(task: dict) -> dict:
    with _task_lock(task["task_id"]):
        return _write_task_unlocked(task)


def update_task_fields(
    task_id: str,
    updates: dict | None = None,
    *,
    remove: tuple[str, ...] = (),
    **fields,
) -> dict | None:
    """Atomically merge task fields without dropping another process's metadata."""
    with _task_lock(task_id):
        task = load_task(task_id)
        if task is None:
            return None
        if updates:
            task.update(updates)
        task.update(fields)
        for key in remove:
            task.pop(key, None)
        return _write_task_unlocked(task)


def _finalize_build_task(
    task_id: str,
    result: dict | None = None,
    *,
    exception: bool = False,
) -> dict | None:
    """Commit a build result against the latest cancellation state."""
    with _task_lock(task_id):
        task = load_task(task_id)
        if task is None:
            return None

        cancel_wins = (
            task.get("status") == "cancelled"
            or (
                (_task_cancel_requested(task_id) or task.get("cancel_requested"))
                and task.get("cancelled") is not False
                and task.get("status") not in FINAL_TASK_STATUSES
            )
        )
        if cancel_wins:
            task.update(status="cancelled", cancelled=True)
            task.pop("error", None)
            return _write_task_unlocked(task)
        if exception:
            return None

        result = result or {}
        status = "completed" if result.get("status") == "ok" else "failed"
        task.update({
            "log_file": result.get("log_file", task.get("log_file")),
            "result": result,
            "status": status,
        })
        if status == "failed":
            task["error"] = {
                "code": "TASK_EXECUTION_FAILED",
                "message": result.get("error", "Task execution failed"),
            }
        else:
            task.pop("error", None)
        return _write_task_unlocked(task)


def reconcile_task_cancellation(task_id: str, killed_pids: list[int]) -> dict | None:
    """Reconcile a task after a later process scan kills prior survivors."""
    killed_set = set(killed_pids)
    with _task_lock(task_id):
        task = load_task(task_id)
        if task is None:
            return None
        cancel_result = dict(task.get("cancel_result", {}))
        killed = list(dict.fromkeys(cancel_result.get("killed", []) + killed_pids))
        remaining = [
            pid for pid in cancel_result.get("remaining", [])
            if pid not in killed_set
        ]
        cancel_result.update(killed=killed, remaining=remaining)
        task["cancel_result"] = cancel_result
        if not remaining and task.get("status") not in FINAL_TASK_STATUSES:
            task.update(status="cancelled", cancelled=True)
            task.pop("error", None)
        return _write_task_unlocked(task)


def task_data_path(name: str) -> Path:
    """Return a small metadata path beside task JSON files."""
    return _task_root() / name


def iter_tasks() -> list[dict]:
    """Return readable task records, newest first."""
    tasks: list[dict] = []
    for path in _task_root().glob("*.json"):
        try:
            tasks.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    tasks.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    return tasks


def active_build_tasks(project_path: str) -> list[dict]:
    """Return non-final build tasks owned by one project."""
    target = _normalize_project_path(project_path)
    return [
        task
        for task in iter_tasks()
        if task.get("command") in BUILD_TASK_COMMANDS
        and task.get("status") not in FINAL_TASK_STATUSES
        and _normalize_project_path(
            str(task.get("payload", {}).get("project_path", ""))
        )
        == target
    ]


def task_progress(task: dict) -> dict:
    status = task.get("status", "submitted")
    result = {
        "task_id": task["task_id"],
        "command": task.get("command"),
        "status": status,
        "suggested_poll_interval_seconds": task.get("suggested_poll_interval_seconds", 5),
    }
    if "pid" in task:
        result["pid"] = task["pid"]
    if "worker_pid" in task:
        result["worker_pid"] = task["worker_pid"]
    if "log_file" in task:
        result["log_file"] = task["log_file"]

    if "result" in task:
        result["result"] = task["result"]
    if "error" in task:
        result["error"] = task["error"]
    if "cancel_result" in task:
        result["cancel_result"] = task["cancel_result"]
    return result


def _spawn_creationflags() -> int:
    if sys.platform != "win32":
        return 0
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_BREAKAWAY_FROM_JOB"):
        flags |= getattr(subprocess, name, 0)
    return flags


def spawn_worker(task_id: str) -> int:
    cmd = [
        sys.executable,
        "-m",
        "cli_anything.unreal",
        "--output",
        "json",
        "_task-worker",
        "run",
        task_id,
    ]
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = _spawn_creationflags()
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    update_task_fields(task_id, worker_pid=proc.pid)
    return proc.pid


def submit_task(command: str, payload: dict) -> dict:
    task = create_task(command, payload)
    spawn_worker(task["task_id"])
    return load_task(task["task_id"]) or task


def wait_for_task(task_id: str, timeout: int | None) -> dict | None:
    deadline = None if timeout is None else time.time() + timeout
    while True:
        task = load_task(task_id)
        if task is None:
            return None
        if task.get("status") in FINAL_TASK_STATUSES:
            return task
        if deadline is not None and time.time() >= deadline:
            return None
        time.sleep(0.5)


def cancel_task(task_id: str) -> dict | None:
    task = load_task(task_id)
    if task is None:
        return None
    if task.get("status") in FINAL_TASK_STATUSES:
        task["cancelled"] = False
        return save_task(task)

    command = task.get("command")
    payload = task.get("payload", {})
    _request_task_cancel(task_id)
    task = update_task_fields(task_id, cancel_requested=True) or task

    if command in BUILD_TASK_COMMANDS:
        from cli_anything.unreal.utils.ue_backend import (
            _kill_process_tree_result,
            kill_build_processes,
        )

        kill_results = []
        worker_pid = int(task["worker_pid"]) if task.get("worker_pid") else None
        build_pid = int(task["pid"]) if task.get("pid") else None

        if sys.platform == "win32":
            worker_info = _query_process_info(worker_pid) if worker_pid else None
            build_info = _query_process_info(build_pid) if build_pid else None
            worker_owned = bool(
                worker_info
                and worker_info.get("query_ok")
                and worker_info.get("found")
                and "_task-worker" in worker_info.get("cmdline", "")
                and task_id in worker_info.get("cmdline", "")
            )
            build_owned = bool(
                worker_owned
                and build_info
                and build_info.get("query_ok")
                and build_info.get("found")
                and build_info.get("parent_pid") == worker_pid
            )
            process_specs = (
                ("worker", worker_pid, worker_info, worker_owned),
                ("build", build_pid, build_info, build_owned),
            )
        else:
            process_specs = (
                ("worker", worker_pid, None, True),
                ("build", build_pid, None, True),
            )

        seen_pids = set()
        worker_still_owned = worker_owned if sys.platform == "win32" else True
        for role, pid, process_info, owned in process_specs:
            if not pid or pid in seen_pids:
                continue
            seen_pids.add(pid)
            if (
                sys.platform == "win32"
                and process_info is not None
                and owned
            ):
                if role == "build":
                    owned = worker_still_owned
                current_info = _query_process_info(pid)
                if (
                    current_info.get("query_ok")
                    and current_info.get("found")
                    and (
                        not _same_process_identity(process_info, current_info)
                        or (
                            role == "build"
                            and current_info.get("parent_pid") != worker_pid
                        )
                    )
                ):
                    owned = False
                process_info = current_info
            if role == "worker" and sys.platform == "win32":
                worker_still_owned = bool(
                    owned
                    and process_info
                    and process_info.get("query_ok")
                    and process_info.get("found")
                )
            if process_info is not None and not process_info.get("query_ok"):
                kill_result = {
                    "ok": False,
                    "pid": pid,
                    "error": process_info.get("error", "process identity query failed"),
                    "identity_query_failed": True,
                }
            elif process_info is not None and not process_info.get("found"):
                kill_result = {
                    "ok": True,
                    "pid": pid,
                    "already_exited": True,
                    "skipped": True,
                }
            elif not owned:
                kill_result = {
                    "ok": True,
                    "pid": pid,
                    "ownership_mismatch": True,
                    "skipped": True,
                    "process": process_info,
                }
            else:
                try:
                    kill_result = _kill_process_tree_result(pid)
                except Exception as exc:
                    kill_result = {"ok": False, "pid": pid, "error": str(exc)}
            if process_info is not None:
                kill_result.setdefault("process", process_info)
            kill_result["role"] = role
            kill_results.append(kill_result)

        project_path = payload.get("project_path")
        stop_result = (
            kill_build_processes(project_path)
            if project_path
            else {"status": "none", "killed": [], "remaining": []}
        )
        scan_killed = set(stop_result.get("killed", []))
        killed = [
            result["pid"]
            for result in kill_results
            if result.get("ok")
            and not result.get("already_exited")
            and not result.get("skipped")
        ]
        killed.extend(stop_result.get("killed", []))
        remaining = []
        for result in kill_results:
            if result.get("ok") or result["pid"] in scan_killed:
                continue
            if sys.platform == "win32":
                final_info = _query_process_info(result["pid"])
                result["final_process"] = final_info
                if final_info.get("query_ok"):
                    if not final_info.get("found"):
                        continue
                    original_info = result.get("process")
                    if (
                        original_info is not None
                        and original_info.get("query_ok")
                        and original_info.get("found")
                        and not _same_process_identity(original_info, final_info)
                    ):
                        continue
            remaining.append(result["pid"])
        remaining.extend(stop_result.get("remaining", []))
        killed = list(dict.fromkeys(killed))
        remaining = list(dict.fromkeys(remaining))

        updates = {
            "stop_result": stop_result,
            "cancel_result": {
                "killed": killed,
                "remaining": remaining,
                "processes": kill_results,
            },
        }
        if remaining:
            updates.update({
                "status": "running",
                "cancelled": False,
                "error": {
                    "code": "TASK_CANCEL_FAILED",
                    "message": "Build task cancellation left processes running.",
                },
            })
            return update_task_fields(task_id, updates) or task

        updates.update({"status": "cancelled", "cancelled": True})
        return update_task_fields(
            task_id,
            updates,
            remove=("error",),
        ) or task

    pid = task.get("pid") or task.get("worker_pid")
    if pid:
        try:
            from cli_anything.unreal.utils.ue_backend import _kill_process_tree

            _kill_process_tree(int(pid))
        except Exception:
            pass

    return update_task_fields(
        task_id,
        status="cancelled",
        cancelled=True,
        remove=("error",),
    ) or task


def run_task_worker(task_id: str) -> dict:
    task = load_task(task_id)
    if task is None:
        raise FileNotFoundError(f"Task not found: {task_id}")
    if task.get("status") in FINAL_TASK_STATUSES:
        return task

    if _task_cancel_requested(task_id):
        return update_task_fields(
            task_id,
            status="cancelled",
            cancelled=True,
            remove=("error",),
        ) or task

    task = update_task_fields(
        task_id,
        status="running",
        started_at=time.time(),
    ) or task

    command = task.get("command")
    if command == "build.compile":
        return _run_build_task(task, "compile_project", estimated_total_seconds=600)
    if command == "build.cook":
        return _run_build_task(task, "cook_content", estimated_total_seconds=300)
    if command == "build.package":
        return _run_build_task(task, "package_project", estimated_total_seconds=1200)
    if command == "editor.launch":
        return _run_editor_launch_task(task, estimated_total_seconds=120)
    raise RuntimeError(f"Unsupported task command: {command}")


def _run_build_task(task: dict, func_name: str, *, estimated_total_seconds: int) -> dict:
    from cli_anything.unreal.core import build as build_core

    payload = task["payload"]

    def _on_start(proc):
        update_task_fields(
            task["task_id"],
            status="running",
            pid=proc.pid,
            estimated_total_seconds=estimated_total_seconds,
        )

    kwargs = {
        "uproject_path": payload["project_path"],
        "engine_root": payload.get("engine_root"),
        "log_file": payload.get("log_file"),
        "on_start": _on_start,
    }
    if func_name == "compile_project":
        kwargs["config"] = payload.get("build_config", "Development")
        kwargs["platform"] = payload.get("platform", "Win64")
        kwargs["modules"] = payload.get("modules")
    elif func_name == "cook_content":
        kwargs["platform"] = payload.get("platform", "Win64")
        kwargs["packages"] = payload.get("packages")
        kwargs["output_dir"] = payload.get("output_dir")
        kwargs["ini_overrides"] = payload.get("ini_overrides")
    elif func_name == "package_project":
        kwargs["platform"] = payload.get("platform", "Win64")
        kwargs["config"] = payload.get("build_config", "Development")
        kwargs["output_dir"] = payload.get("output_dir")
        kwargs["maps"] = payload.get("maps")
        kwargs["cook_flavor"] = payload.get("cook_flavor")
        kwargs["uat_args"] = payload.get("uat_args")

    try:
        result = getattr(build_core, func_name)(**kwargs)
    except Exception:
        finalized = _finalize_build_task(task["task_id"], exception=True)
        if finalized is None:
            raise
        return finalized

    return _finalize_build_task(task["task_id"], result) or task


def _clean_bridge_build_outputs(project_dir: str) -> None:
    import shutil

    plugin_dir = Path(project_dir) / "Plugins" / "CliAnythingBridge"
    for sub in ("Intermediate", "Binaries"):
        path = plugin_dir / sub
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def _looks_like_transport_disconnect(result: dict) -> bool:
    text = " ".join(str(result.get(key, "")) for key in ("error", "message", "traceback")).lower()
    markers = (
        "connectionreseterror",
        "connection aborted",
        "remote disconnected",
        "connection refused",
        "forcibly closed",
        "winerror 10054",
        "10054",
    )
    return any(marker in text for marker in markers)


def _map_recovery_timeout_seconds(timeout_value) -> float:
    try:
        launch_timeout = float(timeout_value)
    except (TypeError, ValueError):
        launch_timeout = 30.0
    return min(90.0, max(15.0, launch_timeout / 2.0))


def _map_recovery_crash_diagnostics(log_file: Path, project_dir: str | None) -> dict:
    diagnostics: dict = {}
    try:
        if log_file.exists():
            with log_file.open("rb") as fh:
                fh.seek(max(0, log_file.stat().st_size - 256 * 1024))
                tail = fh.read().decode("utf-8", errors="replace")
        else:
            tail = ""
    except Exception:
        tail = ""

    hints: list[str] = []
    if "World Memory Leaks" in tail:
        diagnostics["likely_cause"] = "python_world_reference_leak_during_level_transition"
        hints.append("World Memory Leaks")
    if "FPyReferenceCollector" in tail:
        diagnostics.setdefault("likely_cause", "python_world_reference_leak_during_level_transition")
        hints.append("FPyReferenceCollector retained Python object references")
    if "LevelEditorSubsystem.LoadLevel" in tail:
        hints.append("Crash occurred during LevelEditorSubsystem.LoadLevel")
    if hints:
        diagnostics["log_hints"] = hints

    if project_dir:
        crash_root = Path(project_dir) / "Saved" / "Crashes"
        try:
            recent = sorted(
                [path for path in crash_root.iterdir() if path.is_dir()],
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )[:3]
        except Exception:
            recent = []
        if recent:
            diagnostics["recent_crash_dirs"] = [str(path) for path in recent]

    return diagnostics


def _run_editor_launch_task(task: dict, *, estimated_total_seconds: int) -> dict:
    import subprocess as sp

    from cli_anything.unreal.commands import AppState
    from cli_anything.unreal.commands.editor import (
        _build_launch_cmd,
        _check_already_running,
        _check_port_in_use,
        _deploy_bridge,
        _summarize_startup_precheck,
        _wait_for_api,
    )
    from cli_anything.unreal.utils.ue_backend import (
        ensure_remote_control_config,
        find_editor_exe,
        get_editor_binary_prefix,
        preflight_check,
    )

    payload = task["payload"]
    state = AppState()
    state.json_output = True
    state.session.load_project(payload["project_path"])
    if payload.get("port") is not None:
        state.session.port = int(payload["port"])

    launch_binary_prefix = (
        get_editor_binary_prefix(state.session.engine_root)
        if state.session.engine_root
        else None
    )
    bridge_launch_prepare = None
    if launch_binary_prefix == "UE4Editor":
        from cli_anything.unreal.core.plugin_bridge import ensure_project_bridge_disabled_by_default

        bridge_launch_prepare = ensure_project_bridge_disabled_by_default(state.session.project_dir)

    preflight = preflight_check(state.session.project_path, state.session.engine_root)
    remote_control = preflight.get("remote_control", {})
    if remote_control.get("configured", False):
        remote_control_prepare = {
            "status": "not_needed",
            "changes": [],
            "reason": "already_configured",
        }
    elif not (
        preflight.get("engine", {}).get("ready", False)
        and preflight.get("project", {}).get("ready", False)
    ):
        remote_control_prepare = {
            "status": "not_applied",
            "changes": [],
            "reason": "engine_or_project_not_ready",
        }
    elif not remote_control.get("plugin_loadable", {}).get("available", False):
        remote_control_prepare = {
            "status": "not_applied",
            "changes": [],
            "reason": "plugin_unavailable",
        }
    else:
        remote_control_prepare = ensure_remote_control_config(
            state.session.project_dir,
            engine_root=state.session.engine_root,
            editor_binary_prefix=launch_binary_prefix,
        )
        preflight = preflight_check(state.session.project_path, state.session.engine_root)

    startup_precheck = _summarize_startup_precheck(preflight)
    if not preflight.get("ready"):
        task["status"] = "failed"
        task["error"] = {
            "code": "PREFLIGHT_FAILED",
            "message": "Editor preflight failed",
            "details": startup_precheck,
        }
        task["result"] = {
            "startup_precheck": startup_precheck,
            "preflight": preflight,
            "remote_control_prepare": remote_control_prepare,
            "bridge_launch_prepare": bridge_launch_prepare,
        }
        return save_task(task)

    editor_exe = find_editor_exe(state.session.engine_root)
    if not editor_exe:
        task["status"] = "failed"
        task["error"] = {
            "code": "EDITOR_NOT_FOUND",
            "message": f"UnrealEditor.exe not found in {state.session.engine_root}",
        }
        return save_task(task)

    dup_result = _check_already_running(state.session, state)
    if dup_result is not None and dup_result.get("status") == "already_running":
        task["status"] = "failed"
        task["error"] = {
            "code": "ALREADY_RUNNING",
            "message": dup_result.get("message", "Editor already running"),
        }
        task["result"] = dup_result
        return save_task(task)

    port_result = _check_port_in_use(state.session.port, state)
    if port_result is not None:
        # Port occupied — auto-resolve to next available port
        from cli_anything.unreal.utils.ue_backend import resolve_available_port
        new_port = resolve_available_port(state.session.project_dir, state.session.port)
        state.session.port = new_port

    editor_binary_prefix = preflight.get("engine", {}).get("details", {}).get("editor_binary_prefix", "UnrealEditor")
    bridge_enabled_changed = False
    bridge_binary_status = {"ready": False, "reason": "skipped_ue4", "message": "Bridge plugin skipped for UE4 projects."}
    compile_reason = None
    if editor_binary_prefix == "UE4Editor":
        from cli_anything.unreal.core.plugin_bridge import ensure_project_bridge_disabled_by_default

        if bridge_launch_prepare is None:
            bridge_launch_prepare = ensure_project_bridge_disabled_by_default(state.session.project_dir)
        deploy_result = {
            "deployed": False,
            "action": "skipped_ue4",
            "skipped": True,
            "normalize_result": bridge_launch_prepare,
        }
    else:
        deploy_result = _deploy_bridge(state.session, state)
        if not deploy_result.get("deployed", False):
            task["status"] = "failed"
            task["error"] = {
                "code": "BRIDGE_DEPLOY_FAILED",
                "message": deploy_result.get("error", "CliAnythingBridge deployment failed"),
                "details": deploy_result,
            }
            return save_task(task)

        # Auto-enable CliAnythingBridge in .uproject
        from cli_anything.unreal.utils.ue_backend import _ensure_plugin_enabled
        bridge_enabled_changed = _ensure_plugin_enabled(state.session.project_dir, "CliAnythingBridge")

        from cli_anything.unreal.core.plugin_bridge import get_plugin_binary_status
        bridge_binary_status = get_plugin_binary_status(
            state.session.project_dir,
            engine_root=state.session.engine_root,
        )
        if not bridge_binary_status.get("ready", False):
            compile_reason = bridge_binary_status.get("message") or "Bridge plugin binary is not ready."
        elif deploy_result.get("action") != "already_up_to_date":
            compile_reason = f"Bridge plugin source {deploy_result.get('action')} requires compilation."

    if compile_reason:
        task = load_task(task["task_id"]) or task
        task["status"] = "compiling"
        task["estimated_total_seconds"] = estimated_total_seconds
        task["result"] = {
            "project": state.session.project_name,
            "editor_exe": editor_exe,
            "startup_precheck": startup_precheck,
            "remote_control_prepare": remote_control_prepare,
            "bridge_deploy": deploy_result,
            "bridge_enabled_changed": bridge_enabled_changed,
            "bridge_binary_status": bridge_binary_status,
            "compile_reason": compile_reason,
        }
        save_task(task)

        _clean_bridge_build_outputs(state.session.project_dir)

        from cli_anything.unreal.core.build import compile_project
        compile_result = compile_project(
            state.session.project_path,
            engine_root=state.session.engine_root,
        )
        task = load_task(task["task_id"]) or task
        task["result"] = dict(task.get("result", {}))
        task["result"]["compile_result"] = compile_result
        if compile_result.get("status") != "ok":
            task["status"] = "failed"
            task["error"] = {
                "code": "COMPILE_FAILED",
                "message": f"Bridge plugin compilation failed: {compile_result.get('error', 'Unknown error')}",
                "details": compile_result,
            }
            return save_task(task)

        bridge_binary_status = get_plugin_binary_status(
            state.session.project_dir,
            engine_root=state.session.engine_root,
        )
        task["result"]["bridge_binary_status"] = bridge_binary_status
        if not bridge_binary_status.get("ready", False):
            task["status"] = "failed"
            task["error"] = {
                "code": "BRIDGE_BINARY_NOT_READY",
                "message": bridge_binary_status.get("message", "Bridge plugin binary is still not ready after compilation."),
                "details": bridge_binary_status,
            }
            return save_task(task)
        task["result"]["precompiled_bridge"] = True
        save_task(task)

    cmd = _build_launch_cmd(editor_exe, state.session.project_path, payload.get("map_path"), payload.get("extra_args"))
    proc = sp.Popen(cmd, stdout=sp.DEVNULL, stderr=sp.DEVNULL)

    task = load_task(task["task_id"]) or task
    task["pid"] = proc.pid
    task["estimated_total_seconds"] = estimated_total_seconds
    task["status"] = "running"
    task_result = dict(task.get("result", {}))
    task_result.update({
        "pid": proc.pid,
        "project": state.session.project_name,
        "editor_exe": editor_exe,
        "startup_precheck": startup_precheck,
        "remote_control_prepare": remote_control_prepare,
        "bridge_deploy": deploy_result,
        "bridge_binary_status": bridge_binary_status,
    })
    task["result"] = task_result
    if compile_reason:
        task["result"]["compile_reason"] = compile_reason
        task["result"]["precompiled_bridge"] = True
    save_task(task)

    log_file = Path(state.session.project_dir) / "Saved" / "Logs" / f"{state.session.project_name}.log"

    def _record_launch_progress(progress: dict) -> None:
        latest = load_task(task["task_id"]) or task
        latest_result = dict(latest.get("result", {}))
        latest_result.update(progress)
        update_task_fields(
            task["task_id"],
            log_file=str(log_file),
            result=latest_result,
        )

    wait_result = _wait_for_api(
        proc,
        state.session.port,
        payload.get("timeout"),
        log_file,
        state,
        on_progress=_record_launch_progress,
    )

    # Auto-compile and retry if plugin failed to load
    if wait_result.get("status") == "error_dialog" and "failed to load" in wait_result.get("error", ""):
        _clean_bridge_build_outputs(state.session.project_dir)

        task = load_task(task["task_id"]) or task
        task["status"] = "compiling"
        task["result"] = dict(task.get("result", {}))
        task["result"]["compile_reason"] = "Bridge plugin failed to load"
        save_task(task)

        from cli_anything.unreal.core.build import compile_project
        compile_result = compile_project(
            state.session.project_path,
            engine_root=state.session.engine_root,
        )
        if compile_result.get("status") != "ok":
            task["status"] = "failed"
            task["error"] = {
                "code": "COMPILE_FAILED",
                "message": f"Bridge plugin compilation failed: {compile_result.get('error', 'Unknown error')}",
                "details": compile_result,
            }
            task["result"]["compile_result"] = compile_result
            return save_task(task)

        # Relaunch after successful compilation
        cmd = _build_launch_cmd(editor_exe, state.session.project_path, payload.get("map_path"), payload.get("extra_args"))
        proc = sp.Popen(cmd, stdout=sp.DEVNULL, stderr=sp.DEVNULL)

        task = load_task(task["task_id"]) or task
        task["pid"] = proc.pid
        task["status"] = "running"
        task["result"]["pid"] = proc.pid
        task["result"]["recompiled"] = True
        save_task(task)

        wait_result = _wait_for_api(
            proc,
            state.session.port,
            payload.get("timeout"),
            log_file,
            state,
            on_progress=_record_launch_progress,
        )

    requested_map = payload.get("map_path")
    if wait_result.get("status") == "online" and requested_map:
        from cli_anything.unreal.core.scene import _verify_current_level, open_level
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        api = UEEditorAPI(port=state.session.port)
        verify_timeout = min(30.0, max(5.0, float(payload.get("timeout") or 30.0)))
        try:
            map_verification = _verify_current_level(api, requested_map, verify_timeout=verify_timeout)
        except Exception as exc:
            map_verification = {"status": "failed", "error": str(exc)}
        wait_result["requested_map"] = requested_map
        wait_result["map_verification"] = map_verification
        if map_verification.get("status") != "ok":
            try:
                map_recovery = open_level(api, requested_map, verify_timeout=verify_timeout)
            except Exception as exc:
                map_recovery = {"status": "failed", "error": str(exc)}
            wait_result["map_recovery"] = map_recovery
            if map_recovery.get("status") == "ok":
                wait_result["map_recovered_by_open_level"] = True
                if map_recovery.get("active_world"):
                    wait_result["active_world"] = map_recovery["active_world"]
            else:
                if _looks_like_transport_disconnect(map_recovery):
                    recovery_timeout = _map_recovery_timeout_seconds(payload.get("timeout"))
                    try:
                        map_recovery_wait = _wait_for_api(
                            proc,
                            state.session.port,
                            recovery_timeout,
                            log_file,
                            state,
                            on_progress=_record_launch_progress,
                        )
                    except Exception as exc:
                        map_recovery_wait = {"status": "failed", "error": str(exc)}
                    wait_result["map_recovery_wait"] = map_recovery_wait
                    if map_recovery_wait.get("status") == "online":
                        api = UEEditorAPI(port=state.session.port)
                        try:
                            post_disconnect_verification = _verify_current_level(
                                api,
                                requested_map,
                                verify_timeout=verify_timeout,
                            )
                        except Exception as exc:
                            post_disconnect_verification = {"status": "failed", "error": str(exc)}
                        wait_result["map_recovery_post_disconnect_verification"] = post_disconnect_verification
                        if post_disconnect_verification.get("status") == "ok":
                            wait_result["map_recovered_after_connection_reset"] = True
                            if post_disconnect_verification.get("active_world"):
                                wait_result["active_world"] = post_disconnect_verification["active_world"]
                        else:
                            wait_result["status"] = "map_mismatch"
                    elif map_recovery_wait.get("status") == "crashed":
                        wait_result["status"] = "map_recovery_crashed"
                        wait_result["failure_kind"] = "editor_crash_during_map_recovery"
                        wait_result["error"] = (
                            "Editor crashed while opening the requested --map during automatic recovery."
                        )
                        wait_result.update(_map_recovery_crash_diagnostics(log_file, state.session.project_dir))
                    else:
                        wait_result["status"] = "map_mismatch"
                else:
                    wait_result["status"] = "map_mismatch"

                if wait_result.get("status") == "map_mismatch":
                    wait_result["error"] = (
                        "Editor launched, but active level does not match --map, "
                        "and automatic open-level recovery failed."
                    )
                    wait_result["next_command"] = (
                        f'ue-cli --project "{state.session.project_path}" editor open-level {requested_map}'
                    )

    task = load_task(task["task_id"]) or task
    task["log_file"] = str(log_file)
    merged_result = dict(task.get("result", {}))
    merged_result.update(wait_result)
    task["result"] = merged_result
    wait_status = wait_result.get("status")
    if wait_status == "online":
        task["status"] = "completed"
    elif wait_status == "timeout":
        task["status"] = "timeout"
        task["error"] = {
            "code": "TASK_TIMEOUT",
            "message": wait_result.get("error", "Editor startup timed out"),
            "details": wait_result,
        }
    elif wait_status == "map_mismatch":
        task["status"] = "failed"
        task["error"] = {
            "code": "EDITOR_LAUNCH_MAP_MISMATCH",
            "message": wait_result.get("error", "Editor launch map verification failed"),
            "details": wait_result,
        }
    elif wait_status == "map_recovery_crashed":
        task["status"] = "failed"
        task["error"] = {
            "code": "EDITOR_CRASHED_DURING_MAP_RECOVERY",
            "message": wait_result.get("error", "Editor crashed during launch map recovery."),
            "details": wait_result,
        }
    else:
        task["status"] = "failed"
        task["error"] = {
            "code": "TASK_EXECUTION_FAILED",
            "message": wait_result.get("error", "Editor startup failed"),
            "details": wait_result,
        }
    return save_task(task)
