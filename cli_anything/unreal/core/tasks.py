"""Persistent background-task helpers for long-running CLI operations."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


FINAL_TASK_STATUSES = {"completed", "failed", "timeout", "cancelled"}
BUILD_TASK_COMMANDS = {"build.compile", "build.cook", "build.package"}
EDITOR_EXEC_TASK_COMMAND = "editor.exec"
EDITOR_RUN_SCRIPT_TASK_COMMAND = "editor.run-script"
EDITOR_OBSERVATION_TASK_COMMANDS = {
    EDITOR_EXEC_TASK_COMMAND,
    EDITOR_RUN_SCRIPT_TASK_COMMAND,
}
EDITOR_LAUNCH_SPAWN_GRACE_SECONDS = 30
_WINDOWS_TASK_IO_RETRY_DELAYS_SECONDS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.4, 0.8)
_WINDOWS_PROCESS_IDENTITY_QUERY_TIMEOUT_SECONDS = 3
_COOK_STALL_THRESHOLD_SECONDS = 600
_COOK_STALL_THRESHOLD_ENV = "UE_CLI_COOK_STALL_THRESHOLD_SECONDS"
_COOK_DIAGNOSTIC_LOG_BYTES = 1024 * 1024
_COOK_BLOCKED_PATTERN = re.compile(
    r"Cooker has been blocked from saving (?:the )?current packages for\s+"
    r"([0-9]+(?:\.[0-9]+)?)\s+seconds?\b",
    re.IGNORECASE,
)
_COOK_PACKAGE_PATTERN = re.compile(r"/Game/[A-Za-z0-9_./-]+")
_UNCHANGED = object()
_TASK_STATUS_TRANSITIONS = {
    "submitted": {"running", "failed", "cancelled"},
    "running": {"running", "compiling", "completed", "failed", "timeout", "cancelled"},
    "compiling": {"compiling", "running", "completed", "failed", "timeout", "cancelled"},
}


class TaskLockTimeout(TimeoutError):
    """Raised when a bounded task-state read cannot acquire its file lock."""

    def __init__(self, task_id: str, timeout: float):
        self.task_id = task_id
        self.timeout = timeout
        super().__init__(
            f"Timed out after {timeout:g}s waiting for task lock: {task_id}"
        )


class TaskWorkerSpawnError(RuntimeError):
    """Raised when no background task worker process can be created."""

    code = "TASK_WORKER_SPAWN_FAILED"

    def __init__(self, task_id: str, attempts: list[dict]):
        self.task_id = task_id
        self.attempts = attempts
        self.details = {
            "task_id": task_id,
            "fallback_attempted": len(attempts) > 1,
            "attempts": attempts,
        }
        if len(attempts) > 1:
            message = (
                "Failed to start background task worker, including retry without "
                "CREATE_BREAKAWAY_FROM_JOB."
            )
        else:
            message = "Failed to start background task worker."
        super().__init__(message)

    def as_task_error(self) -> dict:
        return {
            "code": self.code,
            "message": str(self),
            "details": self.details,
        }


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
def _task_lock(task_id: str, timeout: float | None = None):
    """Serialize task read-modify-write updates across CLI/worker processes."""
    lock_path = _lock_path(task_id)
    with lock_path.open("a+b") as lock_file:
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        deadline = time.monotonic() + timeout if timeout is not None else None
        if sys.platform == "win32":
            import msvcrt

            if deadline is None:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            else:
                while True:
                    try:
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TaskLockTimeout(task_id, timeout)
                        time.sleep(min(0.01, remaining))
        else:
            import fcntl

            if deadline is None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            else:
                while True:
                    try:
                        fcntl.flock(
                            lock_file.fileno(),
                            fcntl.LOCK_EX | fcntl.LOCK_NB,
                        )
                        break
                    except BlockingIOError:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TaskLockTimeout(task_id, timeout)
                        time.sleep(min(0.01, remaining))
        try:
            yield
        finally:
            lock_file.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _retry_windows_task_io(operation):
    """Retry task-file operations blocked by transient Windows sharing locks."""
    for delay in _WINDOWS_TASK_IO_RETRY_DELAYS_SECONDS:
        try:
            return operation()
        except PermissionError:
            if sys.platform != "win32":
                raise
            time.sleep(delay)
    return operation()


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
            timeout=_WINDOWS_PROCESS_IDENTITY_QUERY_TIMEOUT_SECONDS,
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


def _capture_windows_process_identity(pid: int) -> dict | None:
    """Capture a compact identity that can be checked without CIM later."""
    if sys.platform != "win32":
        return None

    from cli_anything.unreal.utils.ue_backend import _windows_process_identity

    identity = _windows_process_identity(pid)
    if (
        not identity.get("query_ok")
        or not identity.get("found")
        or identity.get("creation_time") is None
    ):
        return None
    return {
        key: identity[key]
        for key in ("pid", "creation_time", "image_path", "identity_source")
        if key in identity
    }


def _recorded_process_identity_matches(recorded: dict, current: dict) -> bool:
    if int(recorded.get("pid") or 0) != int(current.get("pid") or 0):
        return False
    if recorded.get("creation_time") != current.get("creation_time"):
        return False

    recorded_image = str(recorded.get("image_path") or "")
    current_image = str(current.get("image_path") or "")
    if recorded_image and current_image:
        recorded_image = recorded_image.replace("/", "\\").casefold()
        current_image = current_image.replace("/", "\\").casefold()
        return recorded_image == current_image
    return True


def _terminate_just_spawned_process(proc, recorded_identity: dict | None) -> dict:
    """Stop a process spawned across a cancellation race using exact identity."""

    pid = int(proc.pid)
    if sys.platform == "win32" and recorded_identity:
        from cli_anything.unreal.utils.ue_backend import (
            _kill_process_tree_result,
            _windows_process_identity,
        )

        current_identity = _windows_process_identity(pid)
        if not current_identity.get("query_ok"):
            return {
                "ok": False,
                "pid": pid,
                "identity_query_failed": True,
                "process": current_identity,
            }
        if not current_identity.get("found"):
            return {
                "ok": True,
                "pid": pid,
                "already_exited": True,
                "process": current_identity,
            }
        if not _recorded_process_identity_matches(recorded_identity, current_identity):
            return {
                "ok": False,
                "pid": pid,
                "ownership_mismatch": True,
                "process": current_identity,
            }
        result = _kill_process_tree_result(pid)
        result.setdefault("process", current_identity)
        return result

    # ``Popen`` still owns the exact process handle here, so this fallback does
    # not depend on a reusable numeric PID.
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "pid": pid,
                "method": "popen_terminate",
                "error": str(exc),
                "still_running": True,
            }
        except AttributeError as exc:
            return {
                "ok": False,
                "pid": pid,
                "method": "popen_terminate",
                "error": str(exc),
                "exit_unverified": True,
            }
        return {"ok": True, "pid": pid, "method": "popen_terminate"}
    except Exception as exc:
        return {"ok": False, "pid": pid, "error": str(exc)}


def _cancel_spawned_editor_if_requested(
    task_id: str,
    task: dict,
    proc,
    process_identity: dict | None,
) -> dict | None:
    """Resolve the cancel-after-check race immediately after editor spawn."""

    if task.get("status") == "running" and not _task_cancel_requested(task_id):
        return None
    cleanup = _terminate_just_spawned_process(proc, process_identity)
    update_task_fields(task_id, spawn_cancel_cleanup=cleanup)
    if not cleanup.get("ok"):
        current = load_task(task_id) or task
        current_status = str(current.get("status") or "running")
        if current_status in FINAL_TASK_STATUSES:
            return transition_task(
                task_id,
                expected_statuses={"cancelled"},
                status="failed",
                phase="exited",
                cancelled=False,
                error={
                    "code": "TASK_CANCEL_FAILED",
                    "message": (
                        "A newly spawned editor exit could not be verified after "
                        "cancellation."
                    ),
                    "details": cleanup,
                },
                spawn_cancel_cleanup_failed=True,
            ) or current
        return transition_task(
            task_id,
            status=current_status,
            cancelled=False,
            error={
                "code": "TASK_CANCEL_FAILED",
                "message": "A newly spawned editor could not be safely terminated.",
            },
        ) or current
    return transition_task(
        task_id,
        status="cancelled",
        phase="exited",
        error=None,
        cancelled=True,
        remove=("error",),
    ) or task


def _query_owned_task_process(
    role: str,
    pid: int,
    *,
    task_id: str,
    worker_pid: int | None,
    worker_owned: bool,
    recorded_identity: dict | None,
) -> tuple[dict, bool]:
    """Query one task process, preferring its recorded kernel identity."""
    native_info = None
    if recorded_identity:
        from cli_anything.unreal.utils.ue_backend import _windows_process_identity

        native_info = _windows_process_identity(pid)
        native_info["recorded_identity_available"] = True
        if native_info.get("query_ok"):
            matches = bool(
                native_info.get("found")
                and _recorded_process_identity_matches(recorded_identity, native_info)
            )
            native_info["identity_matches"] = matches
            return native_info, matches

    process_info = _query_process_info(pid)
    if native_info is not None:
        process_info["native_identity_query"] = native_info
    if role == "worker":
        owned = bool(
            process_info.get("query_ok")
            and process_info.get("found")
            and "_task-worker" in process_info.get("cmdline", "")
            and task_id in process_info.get("cmdline", "")
        )
    else:
        owned = bool(
            worker_owned
            and process_info.get("query_ok")
            and process_info.get("found")
            and process_info.get("parent_pid") == worker_pid
        )
    return process_info, owned


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
        "task_state_version": 2,
        "created_at": now,
        "updated_at": now,
        "suggested_poll_interval_seconds": 5,
    }
    return save_task(task)


def _load_task_unlocked(task_id: str) -> dict | None:
    path = _task_path(task_id)
    try:
        text = _retry_windows_task_io(
            lambda: path.read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return None
    return json.loads(text)


def load_task(task_id: str, timeout: float | None = None) -> dict | None:
    lock = (
        _task_lock(task_id)
        if timeout is None
        else _task_lock(task_id, timeout=timeout)
    )
    with lock:
        return _load_task_unlocked(task_id)


def load_task_snapshot(task_id: str) -> dict | None:
    """Read the last fully published task record without waiting for its lock.

    Task writers publish through an atomic replace, so a direct reader sees the
    previous or next complete JSON document. This is intentionally a stale,
    best-effort read for status reporting only; callers must not mutate task
    state from this snapshot.
    """
    try:
        text = _task_path(task_id).read_text(encoding="utf-8")
        return json.loads(text)
    except (OSError, json.JSONDecodeError):
        return None


def iter_task_snapshots() -> list[dict]:
    """Return last-published task snapshots without waiting for task locks."""
    tasks = []
    for path in _task_root().glob("*.json"):
        task = load_task_snapshot(path.stem)
        if task is not None:
            tasks.append(task)
    tasks.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    return tasks


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
        _retry_windows_task_io(lambda: os.replace(temp_path, path))
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
    if (updates and "status" in updates) or "status" in fields:
        raise ValueError("Task status changes must use transition_task().")
    with _task_lock(task_id):
        task = _load_task_unlocked(task_id)
        if task is None:
            return None
        if updates:
            task.update(updates)
        task.update(fields)
        for key in remove:
            task.pop(key, None)
        return _write_task_unlocked(task)


def transition_task(
    task_id: str,
    *,
    expected_statuses: set[str] | tuple[str, ...] | list[str] | None = None,
    status: str,
    phase: str | None | object = _UNCHANGED,
    result_patch: dict | None = None,
    result_remove: tuple[str, ...] = (),
    error: dict | None | object = _UNCHANGED,
    remove: tuple[str, ...] = (),
    **fields,
) -> dict | None:
    """Atomically apply one guarded task-state transition.

    Terminal states cannot be overwritten. A verified timeout recovery or
    cancellation-cleanup failure must name its current terminal state through
    ``expected_statuses``. A pending cancellation wins over late worker output.
    """

    with _task_lock(task_id):
        task = _load_task_unlocked(task_id)
        if task is None:
            return None

        current_status = str(task.get("status") or "submitted")
        if expected_statuses is not None and current_status not in set(expected_statuses):
            return task

        requested_status = str(status)
        if current_status in FINAL_TASK_STATUSES and requested_status == current_status:
            return task
        cancellation_pending = bool(
            (_task_cancel_requested(task_id) or task.get("cancel_requested"))
            and fields.get("cancelled", task.get("cancelled")) is not False
            and current_status not in FINAL_TASK_STATUSES
        )
        if cancellation_pending and requested_status != "cancelled":
            requested_status = "cancelled"
            fields = {"cancelled": True}
            result_patch = None
            result_remove = ()
            phase = "exited"
            error = None

        transition_allowed = requested_status == current_status
        expected = set(expected_statuses or ())
        if not transition_allowed and current_status == "timeout":
            transition_allowed = requested_status == "cancelled" or (
                requested_status == "completed" and expected == {"timeout"}
            )
        elif not transition_allowed and current_status == "cancelled":
            transition_allowed = requested_status == "failed" and expected == {"cancelled"}
        elif not transition_allowed and current_status not in FINAL_TASK_STATUSES:
            transition_allowed = requested_status in _TASK_STATUS_TRANSITIONS.get(
                current_status,
                set(),
            )
        if not transition_allowed:
            return task

        task["status"] = requested_status
        if phase is not _UNCHANGED:
            if phase is None:
                task.pop("phase", None)
            else:
                task["phase"] = str(phase)
        if result_patch or result_remove:
            merged_result = dict(task.get("result", {}))
            for key in result_remove:
                merged_result.pop(key, None)
            merged_result.update(result_patch or {})
            task["result"] = merged_result
        if error is not _UNCHANGED:
            if error is None:
                task.pop("error", None)
            else:
                task["error"] = error
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
        task = _load_task_unlocked(task_id)
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
        if task.get("status") in FINAL_TASK_STATUSES:
            return task
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
                "code": result.get("code", "TASK_EXECUTION_FAILED"),
                "message": result.get("error", "Task execution failed"),
            }
        else:
            task.pop("error", None)
        return _write_task_unlocked(task)


def reconcile_task_cancellation(task_id: str, killed_pids: list[int]) -> dict | None:
    """Reconcile a task after a later process scan kills prior survivors."""
    killed_set = set(killed_pids)
    with _task_lock(task_id):
        task = _load_task_unlocked(task_id)
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


def _probe_task_process(task: dict, role: str) -> dict:
    """Return conservative liveness evidence for one persisted task PID."""
    pid_key = "worker_pid" if role == "worker" else "pid"
    identity_key = (
        "worker_process_identity"
        if role == "worker"
        else "build_process_identity"
    )
    pid_value = task.get(pid_key)
    if not pid_value:
        return {"role": role, "state": "not_started"}

    pid = int(pid_value)
    recorded_identity = task.get(identity_key)
    native_info = None
    if sys.platform == "win32" and recorded_identity:
        from cli_anything.unreal.utils.ue_backend import _windows_process_identity

        native_info = _windows_process_identity(pid)
        evidence = {
            "role": role,
            "pid": pid,
            "state": "unknown",
            "query": native_info,
        }
        if native_info.get("query_ok"):
            if not native_info.get("found"):
                evidence["state"] = "exited"
                return evidence
            if recorded_identity:
                matches = _recorded_process_identity_matches(
                    recorded_identity,
                    native_info,
                )
                evidence["identity_matches"] = matches
                evidence["state"] = "running" if matches else "pid_reused"
                return evidence

    # Legacy tasks may not have a native creation token. A command-line match
    # can still distinguish their worker from a reused PID. If that richer
    # query is unhealthy, retain unknown rather than declaring a false exit.
    process_info = _query_process_info(pid)
    evidence = {
        "role": role,
        "pid": pid,
        "state": "unknown",
        "query": process_info,
    }
    if native_info is not None:
        evidence["native_query"] = native_info
    if not process_info.get("query_ok"):
        return evidence
    if not process_info.get("found"):
        evidence["state"] = "exited"
        return evidence
    if sys.platform == "win32" and role == "worker":
        worker_owned = bool(
            "_task-worker" in process_info.get("cmdline", "")
            and task["task_id"] in process_info.get("cmdline", "")
        )
        evidence["state"] = "running" if worker_owned else "pid_reused"
        evidence["identity_matches"] = worker_owned
        return evidence
    evidence["state"] = "running"
    if sys.platform == "win32" and role == "build":
        evidence["identity_verified"] = False
    return evidence


def reconcile_task_state(task_id: str) -> dict | None:
    """Reconcile supported persisted tasks from process or log evidence."""
    task = load_task(task_id)
    if task is not None and task.get("command") in EDITOR_OBSERVATION_TASK_COMMANDS:
        from cli_anything.unreal.core.editor_exec import (
            reconcile_editor_observation,
        )

        return reconcile_editor_observation(task_id, task)
    if (
        task is None
        or task.get("command") not in BUILD_TASK_COMMANDS
        or task.get("status") in FINAL_TASK_STATUSES
        or not task.get("worker_pid")
    ):
        return task

    worker_probe = _probe_task_process(task, "worker")
    build_probe = _probe_task_process(task, "build")
    worker_exited = worker_probe.get("state") in {"exited", "pid_reused"}
    build_exited = build_probe.get("state") in {
        "exited",
        "pid_reused",
        "not_started",
    }
    if not (worker_exited and build_exited):
        return task

    with _task_lock(task_id):
        current = _load_task_unlocked(task_id)
        if current is None:
            return None
        if (
            current.get("command") not in BUILD_TASK_COMMANDS
            or current.get("status") in FINAL_TASK_STATUSES
            or current.get("worker_pid") != task.get("worker_pid")
            or current.get("pid") != task.get("pid")
        ):
            return current

        reconciliation = {
            "reason": "tracked_processes_exited",
            "processes": [worker_probe, build_probe],
        }
        if _task_cancel_requested(task_id) or current.get("cancel_requested"):
            current.update(status="cancelled", cancelled=True)
            cancel_result = dict(current.get("cancel_result", {}))
            if cancel_result:
                cancel_result["remaining"] = []
                current["cancel_result"] = cancel_result
            current.pop("error", None)
            reconciliation["outcome"] = "cancelled"
        else:
            current.update(
                status="failed",
                error={
                    "code": "TASK_WORKER_EXITED",
                    "message": (
                        "Background build worker exited before publishing "
                        "a final task result."
                    ),
                },
            )
            reconciliation["outcome"] = "failed"
        current["reconciliation"] = reconciliation
        return _write_task_unlocked(current)


def task_data_path(name: str) -> Path:
    """Return a small metadata path beside task JSON files."""
    return _task_root() / name


def iter_tasks(timeout: float | None = None) -> list[dict]:
    """Return readable task records, newest first."""
    deadline = time.monotonic() + timeout if timeout is not None else None
    tasks: list[dict] = []
    for path in _task_root().glob("*.json"):
        try:
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - time.monotonic())
                if remaining <= 0:
                    raise TaskLockTimeout(path.stem, timeout)
            task = load_task(path.stem, timeout=remaining)
        except TaskLockTimeout:
            raise
        except (OSError, json.JSONDecodeError):
            continue
        if task is not None:
            tasks.append(task)
    tasks.sort(key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    return tasks


def active_build_tasks(project_path: str) -> list[dict]:
    """Return non-final build tasks owned by one project."""
    target = _normalize_project_path(project_path)
    active = []
    for task in iter_tasks():
        if (
            task.get("command") not in BUILD_TASK_COMMANDS
            or task.get("status") in FINAL_TASK_STATUSES
            or _normalize_project_path(
                str(task.get("payload", {}).get("project_path", ""))
            )
            != target
        ):
            continue
        task = reconcile_task_state(task["task_id"]) or task
        if task.get("status") not in FINAL_TASK_STATUSES:
            active.append(task)
    return active


def _cook_stall_threshold_seconds() -> int:
    raw_value = os.environ.get(_COOK_STALL_THRESHOLD_ENV)
    if raw_value is None:
        return _COOK_STALL_THRESHOLD_SECONDS
    try:
        return max(0, int(raw_value))
    except ValueError:
        return _COOK_STALL_THRESHOLD_SECONDS


def _read_log_suffix(log_file: Path, max_bytes: int) -> str:
    try:
        with log_file.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes), os.SEEK_SET)
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _strip_cook_log_prefix(line: str) -> str:
    text = line.strip()
    for marker in ("LogCook: Warning:", "LogCook: Display:", "LogCook:"):
        marker_index = text.find(marker)
        if marker_index >= 0:
            return text[marker_index + len(marker):].strip()
    return text


def _cook_stall_diagnostic(task: dict) -> dict | None:
    if (
        task.get("command") not in {"build.cook", "build.package"}
        or task.get("status") in FINAL_TASK_STATUSES
    ):
        return None

    payload = task.get("payload", {})
    log_file_value = task.get("log_file") or payload.get("log_file")
    if not log_file_value:
        return None
    log_text = _read_log_suffix(
        Path(str(log_file_value)),
        _COOK_DIAGNOSTIC_LOG_BYTES,
    )
    matches = list(_COOK_BLOCKED_PATTERN.finditer(log_text))
    if not matches:
        return None

    latest_match = matches[-1]
    blocked_seconds_value = float(latest_match.group(1))
    blocked_seconds: int | float = blocked_seconds_value
    if blocked_seconds_value.is_integer():
        blocked_seconds = int(blocked_seconds_value)

    packages: list[str] = []
    objects: list[str] = []
    section = None
    for line in log_text[latest_match.end():].splitlines()[:64]:
        text = _strip_cook_log_prefix(line)
        lowered = text.casefold()
        if "packages in the savequeue:" in lowered:
            section = "packages"
            continue
        if (
            "objects that have not yet returned true from "
            "iscachedcookedplatformdataloaded:" in lowered
        ):
            section = "objects"
            continue
        if not text:
            continue
        if "cooker has been blocked from saving" in lowered:
            break
        if (
            "cooked packages " in lowered
            or "cookworkerheartbeat:" in lowered
        ):
            section = None
            continue
        if section == "packages":
            packages.extend(_COOK_PACKAGE_PATTERN.findall(text))
        elif section == "objects":
            objects.append(text[:500])
        if len(packages) >= 5 and len(objects) >= 5:
            break

    packages = list(dict.fromkeys(packages))[:5]
    objects = list(dict.fromkeys(objects))[:5]
    threshold_seconds = _cook_stall_threshold_seconds()
    stalled = blocked_seconds_value >= threshold_seconds
    diagnostic = {
        "code": "COOK_SAVE_STALLED" if stalled else "COOK_SAVE_BLOCKED",
        "message": (
            "Cook worker reports a package-save stall."
            if stalled
            else "Cook worker reports a package-save blockage below the stall threshold."
        ),
        "stalled": stalled,
        "blocked_seconds": blocked_seconds,
        "threshold_seconds": threshold_seconds,
        "packages": packages,
        "objects": objects,
        "log_file": str(log_file_value),
        "cancellation_under_user_control": True,
        "cancellation_command": f"ue-cli task cancel {task['task_id']}",
        "retry_guidance": (
            "Inspect the named package/object and cooked-platform-data cache. "
            "Cancel only if progress is no longer expected; retry after resolving "
            "the asset or cache issue."
        ),
    }
    return diagnostic


def task_progress(task: dict) -> dict:
    status = task.get("status", "submitted")
    result = {
        "task_id": task["task_id"],
        "command": task.get("command"),
        "status": status,
        "suggested_poll_interval_seconds": task.get("suggested_poll_interval_seconds", 5),
    }
    if "phase" in task:
        result["phase"] = task["phase"]
    if "pid" in task:
        result["pid"] = task["pid"]
    if "worker_pid" in task:
        result["worker_pid"] = task["worker_pid"]
    log_file = task.get("log_file") or task.get("payload", {}).get("log_file")
    if log_file:
        result["log_file"] = log_file

    diagnostic = _cook_stall_diagnostic(task)
    if diagnostic:
        result["stalled"] = diagnostic["stalled"]
        result["diagnostic"] = diagnostic

    if "result" in task:
        result["result"] = task["result"]
    if "error" in task:
        result["error"] = task["error"]
    if "cancel_result" in task:
        result["cancel_result"] = task["cancel_result"]
    if "output_integrity" in task:
        result["output_integrity"] = task["output_integrity"]
    if "reconciliation" in task:
        result["reconciliation"] = task["reconciliation"]
    if "worker_spawn" in task:
        result["worker_spawn"] = task["worker_spawn"]
    return result


def _spawn_creationflags() -> int:
    if sys.platform != "win32":
        return 0
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_BREAKAWAY_FROM_JOB"):
        flags |= getattr(subprocess, name, 0)
    return flags


def _worker_spawn_attempt(error: OSError, creationflags: int, *, mode: str) -> dict:
    return {
        "mode": mode,
        "creationflags": creationflags,
        "breakaway_requested": bool(
            creationflags & getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        ),
        "error": {
            "type": type(error).__name__,
            "errno": getattr(error, "errno", None),
            "winerror": getattr(error, "winerror", None),
            "message": str(error),
        },
    }


def _raise_worker_spawn_error(task_id: str, attempts: list[dict]) -> None:
    error = TaskWorkerSpawnError(task_id, attempts)
    try:
        transition_task(task_id, status="failed", error=error.as_task_error())
    except OSError:
        # Preserve the process-creation failure if task-state persistence is
        # independently blocked.
        pass
    raise error


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
    initial_creationflags = 0
    if sys.platform == "win32":
        initial_creationflags = _spawn_creationflags()
        kwargs["creationflags"] = initial_creationflags
    else:
        kwargs["start_new_session"] = True
    worker_spawn = None
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except OSError as initial_error:
        breakaway_flag = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        should_retry_without_breakaway = (
            sys.platform == "win32"
            and getattr(initial_error, "winerror", None) == 5
            and bool(breakaway_flag)
            and bool(initial_creationflags & breakaway_flag)
        )
        initial_mode = (
            "with_breakaway"
            if breakaway_flag and initial_creationflags & breakaway_flag
            else "default"
        )
        attempts = [
            _worker_spawn_attempt(
                initial_error,
                initial_creationflags,
                mode=initial_mode,
            )
        ]
        if not should_retry_without_breakaway:
            _raise_worker_spawn_error(task_id, attempts)

        fallback_creationflags = initial_creationflags & ~breakaway_flag
        kwargs["creationflags"] = fallback_creationflags
        try:
            proc = subprocess.Popen(cmd, **kwargs)
        except OSError as fallback_error:
            attempts.append(
                _worker_spawn_attempt(
                    fallback_error,
                    fallback_creationflags,
                    mode="without_breakaway",
                )
            )
            _raise_worker_spawn_error(task_id, attempts)
        worker_spawn = {
            "fallback_used": True,
            "reason": "breakaway_access_denied",
            "initial_attempt": attempts[0],
            "fallback_creationflags": fallback_creationflags,
        }
    updates = {"worker_pid": proc.pid}
    if worker_spawn:
        updates["worker_spawn"] = worker_spawn
    worker_identity = _capture_windows_process_identity(proc.pid)
    if worker_identity:
        updates["worker_process_identity"] = worker_identity
    try:
        latest = transition_task(
            task_id,
            expected_statuses={"submitted"},
            status="submitted",
            **updates,
        )
        if (
            latest is not None
            and latest.get("status") == "running"
            and int(latest.get("worker_pid") or 0) == int(proc.pid)
        ):
            # The child claimed the task before the parent published its PID.
            # Its atomic claim already contains the same identity.
            pass
    except PermissionError:
        # The worker is already alive and will persist its own PID/status. Do
        # not tell the caller launch failed while that task still exists.
        if not _task_path(task_id).exists():
            raise
    return proc.pid


def submit_task(command: str, payload: dict) -> dict:
    task = create_task(command, payload)
    worker_pid = spawn_worker(task["task_id"])
    try:
        latest = load_task(task["task_id"])
    except PermissionError:
        if not _task_path(task["task_id"]).exists():
            raise
        latest = None
    submitted = latest or task
    submitted.setdefault("worker_pid", worker_pid)
    return submitted


def wait_for_task(task_id: str, timeout: int | None) -> dict | None:
    deadline = None if timeout is None else time.time() + timeout
    while True:
        try:
            task = load_task(task_id)
            if (
                task is not None
                and (
                    (
                        task.get("command") in BUILD_TASK_COMMANDS
                        and task.get("worker_pid")
                    )
                    or task.get("command") in EDITOR_OBSERVATION_TASK_COMMANDS
                )
                and task.get("status") not in FINAL_TASK_STATUSES
            ):
                task = reconcile_task_state(task_id) or task
        except PermissionError:
            if not _task_path(task_id).exists():
                raise
            if deadline is not None and time.time() >= deadline:
                return None
            time.sleep(0.5)
            continue
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
    if task.get("status") in {"completed", "failed", "cancelled"}:
        return task

    command = task.get("command")
    payload = task.get("payload", {})
    if command in EDITOR_OBSERVATION_TASK_COMMANDS:
        task = dict(task)
        task["error"] = {
            "code": "TASK_CANCEL_UNSUPPORTED",
            "message": (
                "This task only observes an already-dispatched editor command; "
                "cancelling it cannot safely stop that Unreal command."
            ),
        }
        task["cancelled"] = False
        return task
    _request_task_cancel(task_id)
    task = update_task_fields(task_id, cancel_requested=True) or task

    if (
        command == "editor.launch"
        and not task.get("pid")
        and task.get("status") not in FINAL_TASK_STATUSES
    ):
        # Do not kill/finalize the worker while it may be between the last
        # cancel check and Popen. The worker publishes any new editor identity,
        # rechecks this marker, terminates that exact process, then commits the
        # terminal cancellation itself.
        return transition_task(
            task_id,
            status=str(task.get("status") or "submitted"),
            phase="cancelling",
            error=None,
            cancel_requested=True,
        ) or task

    if command in BUILD_TASK_COMMANDS:
        from cli_anything.unreal.utils.ue_backend import (
            _kill_process_tree_result,
            kill_build_processes,
        )

        kill_results = []
        worker_pid = int(task["worker_pid"]) if task.get("worker_pid") else None
        build_pid = int(task["pid"]) if task.get("pid") else None

        if sys.platform == "win32":
            worker_identity = task.get("worker_process_identity")
            build_identity = task.get("build_process_identity")
            worker_info, worker_owned = (
                _query_owned_task_process(
                    "worker",
                    worker_pid,
                    task_id=task_id,
                    worker_pid=worker_pid,
                    worker_owned=True,
                    recorded_identity=worker_identity,
                )
                if worker_pid
                else (None, False)
            )
            build_info, build_owned = (
                _query_owned_task_process(
                    "build",
                    build_pid,
                    task_id=task_id,
                    worker_pid=worker_pid,
                    worker_owned=worker_owned,
                    recorded_identity=build_identity,
                )
                if build_pid
                else (None, False)
            )
            process_specs = (
                ("worker", worker_pid, worker_info, worker_owned, worker_identity),
                ("build", build_pid, build_info, build_owned, build_identity),
            )
        else:
            process_specs = (
                ("worker", worker_pid, None, True, None),
                ("build", build_pid, None, True, None),
            )

        seen_pids = set()
        process_context = {}
        worker_still_owned = worker_owned if sys.platform == "win32" else True
        for role, pid, process_info, owned, recorded_identity in process_specs:
            if not pid or pid in seen_pids:
                continue
            seen_pids.add(pid)
            process_context[pid] = (role, recorded_identity)
            if (
                sys.platform == "win32"
                and process_info is not None
                and owned
            ):
                current_info, current_owned = _query_owned_task_process(
                    role,
                    pid,
                    task_id=task_id,
                    worker_pid=worker_pid,
                    worker_owned=worker_still_owned,
                    recorded_identity=recorded_identity,
                )
                if recorded_identity:
                    owned = current_owned
                else:
                    owned = bool(
                        current_owned
                        and _same_process_identity(process_info, current_info)
                    )
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
        recorded_identity_coverage = bool(seen_pids) and all(
            recorded_identity
            for _, pid, _, _, recorded_identity in process_specs
            if pid
        )
        direct_kill_failed = any(
            not result.get("ok")
            and not result.get("identity_query_failed")
            for result in kill_results
        )
        if project_path and (
            not seen_pids
            or (direct_kill_failed and not recorded_identity_coverage)
        ):
            stop_result = kill_build_processes(project_path)
        elif seen_pids:
            stop_result = {
                "status": "skipped",
                "reason": (
                    "tracked_process_identities"
                    if recorded_identity_coverage
                    else "tracked_processes_handled_directly"
                ),
                "killed": [],
                "remaining": [],
            }
        else:
            stop_result = {"status": "none", "killed": [], "remaining": []}
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
            if result.get("identity_query_failed"):
                # Repeating the same stalled CIM call only delays the error
                # payload.  Without a trustworthy identity snapshot, retain
                # the PID conservatively and return its first query failure.
                remaining.append(result["pid"])
                continue
            if sys.platform == "win32":
                role, recorded_identity = process_context[result["pid"]]
                final_info, final_owned = _query_owned_task_process(
                    role,
                    result["pid"],
                    task_id=task_id,
                    worker_pid=worker_pid,
                    worker_owned=True,
                    recorded_identity=recorded_identity,
                )
                result["final_process"] = final_info
                if final_info.get("query_ok"):
                    if not final_info.get("found"):
                        continue
                    if not final_owned:
                        continue
                    original_info = result.get("process")
                    if (
                        not recorded_identity
                        and original_info is not None
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
            return transition_task(
                task_id,
                status="running",
                error={
                    "code": "TASK_CANCEL_FAILED",
                    "message": "Build task cancellation left processes running.",
                },
                cancelled=False,
                **updates,
            ) or task

        if (
            command == "build.compile"
            and str(payload.get("platform", "Win64")).casefold() == "win64"
        ):
            try:
                from cli_anything.unreal.core.build import (
                    inspect_win64_editor_runtime_dependencies,
                )

                updates["output_integrity"] = (
                    inspect_win64_editor_runtime_dependencies(
                        payload.get("project_path", ""),
                        payload.get("engine_root"),
                        payload.get("build_config", "Development"),
                    )
                )
            except Exception as exc:
                updates["output_integrity"] = {
                    "status": "unavailable",
                    "reason": "runtime_dependency_inspection_failed",
                    "message": (
                        "Build cancellation succeeded, but output integrity "
                        f"inspection failed: {exc}"
                    ),
                }
        return transition_task(
            task_id,
            status="cancelled",
            error=None,
            cancelled=True,
            remove=("error",),
            **updates,
        ) or task

    process_specs = []
    if task.get("pid"):
        process_specs.append((
            "editor",
            int(task["pid"]),
            task.get("editor_process_identity"),
        ))
    if task.get("worker_pid") and int(task["worker_pid"]) not in {
        item[1] for item in process_specs
    }:
        process_specs.append((
            "worker",
            int(task["worker_pid"]),
            task.get("worker_process_identity"),
        ))

    kill_results = []
    if process_specs:
        from cli_anything.unreal.utils.ue_backend import _kill_process_tree_result

        for role, pid, recorded_identity in process_specs:
            if sys.platform == "win32":
                if not recorded_identity:
                    kill_result = {
                        "ok": False,
                        "pid": pid,
                        "role": role,
                        "identity_missing": True,
                        "error": "Recorded process identity is unavailable; refusing to kill an unverified PID.",
                    }
                    kill_results.append(kill_result)
                    continue
                from cli_anything.unreal.utils.ue_backend import _windows_process_identity

                current_identity = _windows_process_identity(pid)
                if not current_identity.get("query_ok"):
                    kill_result = {
                        "ok": False,
                        "pid": pid,
                        "role": role,
                        "identity_query_failed": True,
                        "process": current_identity,
                    }
                    kill_results.append(kill_result)
                    continue
                if not current_identity.get("found"):
                    kill_results.append({
                        "ok": True,
                        "pid": pid,
                        "role": role,
                        "already_exited": True,
                        "process": current_identity,
                    })
                    continue
                if not _recorded_process_identity_matches(
                    recorded_identity,
                    current_identity,
                ):
                    kill_results.append({
                        "ok": False,
                        "pid": pid,
                        "role": role,
                        "ownership_mismatch": True,
                        "process": current_identity,
                    })
                    continue
            try:
                kill_result = _kill_process_tree_result(pid)
            except Exception as exc:
                kill_result = {"ok": False, "pid": pid, "error": str(exc)}
            kill_result["role"] = role
            kill_results.append(kill_result)

    failures = [item for item in kill_results if not item.get("ok")]
    if failures:
        current_status = str(task.get("status") or "running")
        return transition_task(
            task_id,
            status=current_status,
            error={
                "code": "TASK_CANCEL_FAILED",
                "message": "Task cancellation could not safely terminate every verified process.",
            },
            cancelled=False,
            cancel_result={"processes": kill_results},
        ) or task

    return transition_task(
        task_id,
        status="cancelled",
        error=None,
        cancelled=True,
        cancel_result={"processes": kill_results},
        remove=("error",),
    ) or task


def run_task_worker(task_id: str) -> dict:
    task = load_task(task_id)
    if task is None:
        raise FileNotFoundError(f"Task not found: {task_id}")
    if task.get("status") in FINAL_TASK_STATUSES:
        return task

    if _task_cancel_requested(task_id):
        return transition_task(
            task_id,
            status="cancelled",
            error=None,
            cancelled=True,
            remove=("error",),
        ) or task

    worker_updates = {
        "started_at": time.time(),
        "worker_pid": os.getpid(),
    }
    worker_identity = _capture_windows_process_identity(os.getpid())
    if worker_identity:
        worker_updates["worker_process_identity"] = worker_identity
    task = transition_task(
        task_id,
        expected_statuses={"submitted"},
        status="running",
        **worker_updates,
    ) or task
    if (
        task.get("status") != "running"
        or int(task.get("worker_pid") or 0) != os.getpid()
    ):
        return task

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
        updates = {
            "pid": proc.pid,
            "estimated_total_seconds": estimated_total_seconds,
        }
        build_identity = _capture_windows_process_identity(proc.pid)
        if build_identity:
            updates["build_process_identity"] = build_identity
        transition_task(task["task_id"], status="running", **updates)

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


def _claim_editor_launch_task(task_id: str, project_path: str) -> dict | None:
    """Claim one project's launch slot; return the older active blocker."""

    target = _normalize_project_path(project_path)
    claim_lock_id = f"editor-launch-{uuid.uuid5(uuid.NAMESPACE_URL, target).hex}"
    with _task_lock(claim_lock_id):
        current = load_task(task_id)
        if current is None:
            return None
        candidates = []
        now = time.time()
        for candidate in iter_tasks():
            if candidate.get("command") != "editor.launch":
                continue
            if candidate.get("status") in FINAL_TASK_STATUSES:
                continue
            if now - float(candidate.get("updated_at") or candidate.get("created_at") or 0) > 7200:
                continue
            candidate_project = str(candidate.get("payload", {}).get("project_path", ""))
            if not candidate_project or _normalize_project_path(candidate_project) != target:
                continue
            if candidate.get("task_id") != task_id:
                if not candidate.get("worker_pid"):
                    created_at = float(candidate.get("created_at") or 0)
                    if (
                        candidate.get("status") != "submitted"
                        or now - created_at > EDITOR_LAUNCH_SPAWN_GRACE_SECONDS
                    ):
                        continue
                elif _probe_task_process(candidate, "worker").get("state") != "running":
                    continue
            candidates.append(candidate)

        candidates.sort(
            key=lambda item: (
                float(item.get("created_at") or 0),
                str(item.get("task_id") or ""),
            )
        )
        winner = candidates[0] if candidates else current
        if winner.get("task_id") != task_id:
            return winner
        update_task_fields(task_id, launch_claimed_at=time.time())
        return None


def _run_editor_launch_task(task: dict, *, estimated_total_seconds: int) -> dict:
    import subprocess as sp
    from types import SimpleNamespace

    from cli_anything.unreal.core.editor_lifecycle import (
        _build_launch_cmd,
        _check_already_running,
        _check_port_in_use,
        _deploy_bridge,
        _plugin_load_failure_diagnostics,
        _remote_control_launch_error,
        _resolve_launch_log_file,
        _summarize_startup_precheck,
        _wait_for_api,
    )
    from cli_anything.unreal.core.session import Session
    from cli_anything.unreal.utils.ue_backend import (
        _write_rc_port,
        ensure_remote_control_config,
        find_editor_exe,
        get_editor_binary_prefix,
        preflight_check,
    )

    payload = task["payload"]
    task_id = task["task_id"]
    session = Session()
    session.load_project(payload["project_path"])
    state = SimpleNamespace(json_output=True, session=session)
    if payload.get("port") is not None:
        state.session.port = int(payload["port"])

    task = transition_task(
        task_id,
        expected_statuses={"submitted", "running"},
        status="running",
        phase="preflight",
        requested_port=state.session.port,
        resolved_port=state.session.port,
    ) or task
    if task.get("status") != "running":
        return task

    blocker = _claim_editor_launch_task(task_id, state.session.project_path)
    if blocker is not None:
        return transition_task(
            task_id,
            status="failed",
            phase="blocked",
            error={
                "code": "EDITOR_LAUNCH_ALREADY_ACTIVE",
                "message": "Another editor launch task is already active for this project.",
                "details": {
                    "active_task_id": blocker.get("task_id"),
                    "active_status": blocker.get("status"),
                    "project_path": state.session.project_path,
                },
            },
            result_patch={
                "active_task_id": blocker.get("task_id"),
                "active_status": blocker.get("status"),
            },
        ) or task

    launch_error = _remote_control_launch_error(payload.get("extra_args"))
    if launch_error:
        return transition_task(
            task_id,
            status="failed",
            phase="blocked",
            error=launch_error,
        ) or task

    launch_binary_prefix = (
        get_editor_binary_prefix(state.session.engine_root)
        if state.session.engine_root
        else None
    )

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
        task = transition_task(
            task_id,
            status="running",
            phase="preparing_remote_control",
        ) or task
        if task.get("status") != "running":
            return task
        remote_control_prepare = ensure_remote_control_config(
            state.session.project_dir,
            engine_root=state.session.engine_root,
            editor_binary_prefix=launch_binary_prefix,
            uproject_path=state.session.project_path,
        )
        preflight = preflight_check(state.session.project_path, state.session.engine_root)

    startup_precheck = _summarize_startup_precheck(preflight)
    if not preflight.get("ready"):
        return transition_task(
            task_id,
            status="failed",
            phase="blocked",
            error={
                "code": "PREFLIGHT_FAILED",
                "message": "Editor preflight failed",
                "details": startup_precheck,
            },
            result_patch={
                "startup_precheck": startup_precheck,
                "preflight": preflight,
                "remote_control_prepare": remote_control_prepare,
            },
        ) or task

    editor_exe = find_editor_exe(state.session.engine_root)
    if not editor_exe:
        return transition_task(
            task_id,
            status="failed",
            phase="blocked",
            error={
                "code": "EDITOR_NOT_FOUND",
                "message": f"UnrealEditor.exe not found in {state.session.engine_root}",
            },
        ) or task

    dup_result = _check_already_running(state.session, state)
    if dup_result is not None:
        duplicate_status = dup_result.get("status")
        duplicate_code = {
            "already_running": "ALREADY_RUNNING",
            "starting": "EDITOR_STARTING",
            "zombie": "EDITOR_ALREADY_RUNNING_OFFLINE",
        }.get(duplicate_status, "EDITOR_ALREADY_RUNNING")
        return transition_task(
            task_id,
            status="failed",
            phase="blocked",
            error={
                "code": duplicate_code,
                "message": dup_result.get("message", "Editor already running"),
                "details": {
                    **dup_result,
                    "decision": "preserve_existing_editor",
                    "requires_user_input": False,
                },
            },
            result_patch=dup_result,
        ) or task

    port_result = _check_port_in_use(state.session.port, state)
    if port_result is not None:
        # Port occupied — auto-resolve to next available port
        from cli_anything.unreal.utils.ue_backend import resolve_available_port
        new_port = resolve_available_port(
            state.session.project_dir,
            state.session.port,
            editor_binary_prefix=launch_binary_prefix,
        )
        state.session.port = new_port

    try:
        remote_control_port_config = _write_rc_port(
            state.session.project_dir,
            state.session.port,
            editor_binary_prefix=launch_binary_prefix,
        )
    except OSError as exc:
        return transition_task(
            task_id,
            status="failed",
            phase="blocked",
            error={
                "code": "EDITOR_LAUNCH_PORT_CONFIG_FAILED",
                "message": "Could not persist the selected Remote Control port before launch.",
                "details": {
                    "port": state.session.port,
                    "editor_binary_prefix": launch_binary_prefix,
                    "error": str(exc),
                },
            },
        ) or task

    task = transition_task(
        task_id,
        status="running",
        phase="deploying_bridge",
        resolved_port=state.session.port,
        result_patch={
            "port": state.session.port,
            "remote_control_port_config": remote_control_port_config,
        },
    ) or task
    if task.get("status") != "running":
        return task

    bridge_enabled_changed = False
    compile_reason = None
    deploy_result = _deploy_bridge(state.session, state)
    if (
        not deploy_result.get("deployed", False)
        or deploy_result.get("action") == "update_pending_locked"
    ):
        deploy_locked = deploy_result.get("action") == "update_pending_locked"
        return transition_task(
            task_id,
            status="failed",
            phase="blocked",
            error={
                "code": "BRIDGE_DEPLOY_LOCKED" if deploy_locked else "BRIDGE_DEPLOY_FAILED",
                "message": deploy_result.get(
                    "warning" if deploy_locked else "error",
                    "CliAnythingBridge deployment failed",
                ),
                "details": deploy_result,
            },
            result_patch={"bridge_deploy": deploy_result},
        ) or task

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
        task = transition_task(
            task_id,
            status="compiling",
            phase="compiling_bridge",
            estimated_total_seconds=estimated_total_seconds,
            result_patch={
                "project": state.session.project_name,
                "editor_exe": editor_exe,
                "startup_precheck": startup_precheck,
                "remote_control_prepare": remote_control_prepare,
                "bridge_deploy": deploy_result,
                "bridge_enabled_changed": bridge_enabled_changed,
                "bridge_binary_status": bridge_binary_status,
                "compile_reason": compile_reason,
            },
        ) or task
        if task.get("status") != "compiling":
            return task

        from cli_anything.unreal.core.plugin_bridge import (
            compile_bridge_plugin,
            finalize_plugin_deployment,
            rollback_plugin_deployment,
        )
        compile_result = compile_bridge_plugin(
            state.session.project_path,
            engine_root=state.session.engine_root,
        )
        if compile_result.get("status") != "ok":
            rollback = rollback_plugin_deployment(deploy_result)
            error_details = dict(compile_result)
            error_details["bridge_rollback"] = rollback
            return transition_task(
                task_id,
                status="failed",
                phase="blocked",
                error={
                    "code": compile_result.get("code", "BRIDGE_MODULE_COMPILE_FAILED"),
                    "message": compile_result.get(
                        "error",
                        "Bridge plugin targeted compilation failed.",
                    ),
                    "details": error_details,
                },
                result_patch={
                    "compile_result": compile_result,
                    "bridge_rollback": rollback,
                },
            ) or task

        bridge_binary_status = get_plugin_binary_status(
            state.session.project_dir,
            engine_root=state.session.engine_root,
        )
        if not bridge_binary_status.get("ready", False):
            rollback = rollback_plugin_deployment(deploy_result)
            error_details = dict(bridge_binary_status)
            error_details["bridge_rollback"] = rollback
            return transition_task(
                task_id,
                status="failed",
                phase="blocked",
                error={
                    "code": "BRIDGE_BINARY_NOT_READY",
                    "message": bridge_binary_status.get(
                        "message",
                        "Bridge plugin binary is still not ready after compilation.",
                    ),
                    "details": error_details,
                },
                result_patch={
                    "compile_result": compile_result,
                    "bridge_binary_status": bridge_binary_status,
                    "bridge_rollback": rollback,
                },
            ) or task
        task = transition_task(
            task_id,
            status="compiling",
            phase="compiling_bridge",
            result_patch={
                "compile_result": compile_result,
                "bridge_binary_status": bridge_binary_status,
                "bridge_deployment_commit": finalize_plugin_deployment(deploy_result),
                "precompiled_bridge": True,
            },
        ) or task
        if task.get("status") != "compiling":
            return task

    task = transition_task(
        task_id,
        status="running",
        phase="spawning",
        estimated_total_seconds=estimated_total_seconds,
    ) or task
    if task.get("status") != "running":
        return task

    cmd = _build_launch_cmd(
        editor_exe,
        state.session.project_path,
        payload.get("map_path"),
        payload.get("extra_args"),
        unattended=bool(payload.get("unattended", False)),
    )
    log_file = _resolve_launch_log_file(
        state.session.project_dir,
        state.session.project_name,
        payload.get("extra_args"),
    )
    if _task_cancel_requested(task_id):
        return transition_task(
            task_id,
            status="cancelled",
            phase="exited",
            error=None,
            cancelled=True,
        ) or task
    proc = sp.Popen(cmd, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    process_identity = _capture_windows_process_identity(proc.pid)

    task_result = {
        "pid": proc.pid,
        "project": state.session.project_name,
        "editor_exe": editor_exe,
        "log_file": str(log_file),
        "startup_precheck": startup_precheck,
        "remote_control_prepare": remote_control_prepare,
        "bridge_deploy": deploy_result,
        "bridge_binary_status": bridge_binary_status,
        "port": state.session.port,
        "remote_control_port_config": remote_control_port_config,
        "delivery_state": "accepted",
    }
    if compile_reason:
        task_result["compile_reason"] = compile_reason
        task_result["precompiled_bridge"] = True
    identity_fields = {}
    if process_identity:
        identity_fields["editor_process_identity"] = process_identity
    task = transition_task(
        task_id,
        status="running",
        phase="waiting_remote_control",
        result_patch=task_result,
        pid=proc.pid,
        log_file=str(log_file),
        estimated_total_seconds=estimated_total_seconds,
        resolved_port=state.session.port,
        **identity_fields,
    ) or task
    cancelled_task = _cancel_spawned_editor_if_requested(
        task_id,
        task,
        proc,
        process_identity,
    )
    if cancelled_task is not None:
        return cancelled_task

    def _record_launch_progress(progress: dict) -> None:
        progress = dict(progress)
        waiting_for_user = progress.get("status") == "waiting_for_user_action"
        if waiting_for_user:
            progress.setdefault(
                "next_command",
                f'ue-cli --project "{state.session.project_path}" editor status {task_id}',
            )
        transition_task(
            task_id,
            status="running",
            phase="waiting_user_action" if waiting_for_user else "waiting_remote_control",
            log_file=str(log_file),
            result_patch=progress,
            result_remove=() if waiting_for_user else (
                "blocking_reason",
                "blocking_dialog",
                "message",
                "suggestion",
                "next_command",
            ),
        )

    wait_result = _wait_for_api(
        proc,
        state.session.port,
        payload.get("timeout"),
        log_file,
        state,
        on_progress=_record_launch_progress,
    )

    plugin_load_failure = _plugin_load_failure_diagnostics(wait_result.get("error"))
    if plugin_load_failure:
        wait_result.update(plugin_load_failure)

    # Rebuild only when startup named CliAnythingBridge as the failing plugin.
    is_bridge_load_failure = bool(
        wait_result.get("status") == "error_dialog"
        and plugin_load_failure
        and str(plugin_load_failure.get("plugin") or "").casefold()
        == "clianythingbridge"
    )
    if plugin_load_failure and not is_bridge_load_failure:
        wait_result["bridge_rebuild_attempted"] = False
    if is_bridge_load_failure:
        startup_failure = dict(wait_result)
        editor_cleanup = _terminate_just_spawned_process(proc, process_identity)
        if not editor_cleanup.get("ok"):
            return transition_task(
                task_id,
                status="failed",
                phase="blocked",
                error={
                    "code": "BRIDGE_REBUILD_EDITOR_TERMINATION_FAILED",
                    "message": (
                        "CliAnythingBridge failed to load, but the spawned editor "
                        "could not be safely terminated before rebuilding it."
                    ),
                    "details": {
                        "startup_failure": startup_failure,
                        "editor_cleanup": editor_cleanup,
                    },
                },
                result_patch={
                    "startup_failure": startup_failure,
                    "bridge_rebuild_editor_cleanup": editor_cleanup,
                },
            ) or task

        wait_result["bridge_rebuild_attempted"] = True
        task = transition_task(
            task_id,
            status="compiling",
            phase="compiling_bridge",
            result_patch={
                "compile_reason": "CliAnythingBridge plugin failed to load",
                "startup_failure": startup_failure,
                "bridge_rebuild_editor_cleanup": editor_cleanup,
            },
        ) or task
        if task.get("status") != "compiling":
            return task

        from cli_anything.unreal.core.plugin_bridge import (
            compile_bridge_plugin,
            finalize_plugin_deployment,
            rollback_plugin_deployment,
        )
        compile_result = compile_bridge_plugin(
            state.session.project_path,
            engine_root=state.session.engine_root,
        )
        if compile_result.get("status") != "ok":
            rollback = rollback_plugin_deployment(deploy_result)
            error_details = dict(compile_result)
            error_details["bridge_rollback"] = rollback
            error_details["startup_failure"] = startup_failure
            error_details["bridge_rebuild_editor_cleanup"] = editor_cleanup
            return transition_task(
                task_id,
                status="failed",
                phase="blocked",
                error={
                    "code": compile_result.get("code", "BRIDGE_MODULE_COMPILE_FAILED"),
                    "message": compile_result.get(
                        "error",
                        "Bridge plugin targeted compilation failed.",
                    ),
                    "details": error_details,
                },
                result_patch={
                    "compile_result": compile_result,
                    "bridge_rollback": rollback,
                    "startup_failure": startup_failure,
                    "bridge_rebuild_editor_cleanup": editor_cleanup,
                },
            ) or task

        task = transition_task(
            task_id,
            status="running",
            phase="spawning",
            result_patch={
                "compile_result": compile_result,
                "bridge_deployment_commit": finalize_plugin_deployment(deploy_result),
            },
        ) or task
        if task.get("status") != "running":
            return task

        # Relaunch after successful compilation
        cmd = _build_launch_cmd(
            editor_exe,
            state.session.project_path,
            payload.get("map_path"),
            payload.get("extra_args"),
            unattended=bool(payload.get("unattended", False)),
        )
        if _task_cancel_requested(task_id):
            return transition_task(
                task_id,
                status="cancelled",
                phase="exited",
                error=None,
                cancelled=True,
            ) or task
        proc = sp.Popen(cmd, stdout=sp.DEVNULL, stderr=sp.DEVNULL)

        process_identity = _capture_windows_process_identity(proc.pid)
        identity_fields = {}
        if process_identity:
            identity_fields["editor_process_identity"] = process_identity
        task = transition_task(
            task_id,
            status="running",
            phase="waiting_remote_control",
            result_patch={
                "pid": proc.pid,
                "recompiled": True,
                "delivery_state": "accepted",
            },
            pid=proc.pid,
            **identity_fields,
        ) or task
        cancelled_task = _cancel_spawned_editor_if_requested(
            task_id,
            task,
            proc,
            process_identity,
        )
        if cancelled_task is not None:
            return cancelled_task

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
        task = transition_task(
            task_id,
            status="running",
            phase="verifying_map",
            result_patch=wait_result,
        ) or task
        if task.get("status") != "running":
            return task
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

    if wait_result.get("status") == "timeout":
        wait_result.setdefault(
            "next_command",
            f'ue-cli --project "{state.session.project_path}" editor status {task["task_id"]}',
        )

    wait_status = wait_result.get("status")
    if wait_status == "online":
        final_status = "completed"
        final_phase = "online"
        final_error = None
    elif wait_status == "timeout":
        final_status = "timeout"
        final_phase = "blocked"
        final_error = {
            "code": "TASK_TIMEOUT",
            "message": wait_result.get("error", "Editor startup timed out"),
            "details": wait_result,
        }
    elif wait_status == "map_mismatch":
        final_status = "failed"
        final_phase = "blocked"
        final_error = {
            "code": "EDITOR_LAUNCH_MAP_MISMATCH",
            "message": wait_result.get("error", "Editor launch map verification failed"),
            "details": wait_result,
        }
    elif wait_status == "map_recovery_crashed":
        final_status = "failed"
        final_phase = "exited"
        final_error = {
            "code": "EDITOR_CRASHED_DURING_MAP_RECOVERY",
            "message": wait_result.get("error", "Editor crashed during launch map recovery."),
            "details": wait_result,
        }
    elif wait_result.get("failure_kind") == "external_editor_ddc_crash":
        final_status = "failed"
        final_phase = "exited"
        final_error = {
            "code": "EDITOR_EXTERNAL_DDC_CRASH",
            "message": wait_result.get(
                "error",
                "Unreal Editor crashed in its file-system DDC maintainer during startup.",
            ),
            "details": wait_result,
        }
    elif wait_result.get("failure_kind") == "engine_binary_source_mismatch":
        final_status = "failed"
        final_phase = "blocked"
        final_error = {
            "code": "EDITOR_ENGINE_BINARY_SOURCE_MISMATCH",
            "message": wait_result.get("error", "Engine binary/source mismatch detected during startup."),
            "details": wait_result,
        }
    elif wait_result.get("failure_kind") == "engine_binary_entrypoint_mismatch":
        final_status = "failed"
        final_phase = "exited"
        final_error = {
            "code": "EDITOR_ENGINE_BINARY_ENTRYPOINT_MISMATCH",
            "message": wait_result.get("error", "Engine DLL entry-point mismatch detected during startup."),
            "details": wait_result,
        }
    elif wait_result.get("failure_kind") == "plugin_load_failure":
        final_status = "failed"
        final_phase = "blocked" if wait_result.get("process_alive") is not False else "exited"
        final_error = {
            "code": "EDITOR_PLUGIN_LOAD_FAILED",
            "message": wait_result.get(
                "diagnostic",
                wait_result.get("error", "An Unreal Editor plugin failed to load during startup."),
            ),
            "details": wait_result,
        }
    else:
        final_status = "failed"
        final_phase = "exited"
        final_error = {
            "code": "TASK_EXECUTION_FAILED",
            "message": wait_result.get("error", "Editor startup failed"),
            "details": wait_result,
        }
    return transition_task(
        task_id,
        status=final_status,
        phase=final_phase,
        result_patch=wait_result,
        error=final_error,
        log_file=str(log_file),
        resolved_port=state.session.port,
    ) or task
