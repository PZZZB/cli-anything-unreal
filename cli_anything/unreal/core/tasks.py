"""Persistent background-task helpers for long-running CLI operations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


FINAL_TASK_STATUSES = {"completed", "failed", "timeout", "cancelled"}


def _task_root() -> Path:
    override = os.environ.get("CLI_ANYTHING_UNREAL_TASK_DIR")
    if override:
        root = Path(override)
    else:
        root = Path(tempfile.gettempdir()) / "cli_anything_unreal_tasks"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _task_path(task_id: str) -> Path:
    return _task_root() / f"{task_id}.json"


def new_task_id() -> str:
    return f"t-{uuid.uuid4().hex[:12]}"


def create_task(command: str, payload: dict) -> dict:
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


def save_task(task: dict) -> dict:
    task["updated_at"] = time.time()
    path = _task_path(task["task_id"])
    path.write_text(json.dumps(task, indent=2, ensure_ascii=False), encoding="utf-8")
    return task


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

    if status in FINAL_TASK_STATUSES:
        result["progress"] = 100
        if "result" in task:
            result["result"] = task["result"]
        if "error" in task:
            result["error"] = task["error"]
        return result

    if status == "submitted":
        result["progress"] = 0
        return result

    started_at = task.get("started_at", task.get("created_at", time.time()))
    estimate = task.get("estimated_total_seconds")
    if estimate:
        elapsed = max(0, int(time.time() - started_at))
        result["progress"] = min(95, int((elapsed / estimate) * 100))
        result["estimated_remaining_seconds"] = max(0, estimate - elapsed)
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
    task = load_task(task_id)
    if task is not None:
        task["worker_pid"] = proc.pid
        save_task(task)
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
    if command in {"build.compile", "build.cook", "build.package"}:
        from cli_anything.unreal.core.build import stop_build

        project_path = payload.get("project_path")
        if project_path:
            task["stop_result"] = stop_build(project_path)

    pid = task.get("pid") or task.get("worker_pid")
    if pid:
        try:
            from cli_anything.unreal.utils.ue_backend import _kill_process_tree

            _kill_process_tree(int(pid))
        except Exception:
            pass

    task["status"] = "cancelled"
    task["cancelled"] = True
    return save_task(task)


def run_task_worker(task_id: str) -> dict:
    task = load_task(task_id)
    if task is None:
        raise FileNotFoundError(f"Task not found: {task_id}")
    if task.get("status") in FINAL_TASK_STATUSES:
        return task

    task["status"] = "running"
    task["started_at"] = time.time()
    save_task(task)

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
        task_live = load_task(task["task_id"]) or task
        task_live["status"] = "running"
        task_live["pid"] = proc.pid
        task_live["estimated_total_seconds"] = estimated_total_seconds
        save_task(task_live)

    kwargs = {
        "uproject_path": payload["project_path"],
        "engine_root": payload.get("engine_root"),
        "log_file": payload.get("log_file"),
        "on_start": _on_start,
    }
    if func_name == "compile_project":
        kwargs["config"] = payload.get("build_config", "Development")
        kwargs["platform"] = payload.get("platform", "Win64")
    elif func_name == "cook_content":
        kwargs["platform"] = payload.get("platform", "Win64")
    elif func_name == "package_project":
        kwargs["platform"] = payload.get("platform", "Win64")
        kwargs["config"] = payload.get("build_config", "Development")
        kwargs["output_dir"] = payload.get("output_dir")

    result = getattr(build_core, func_name)(**kwargs)
    task = load_task(task["task_id"]) or task
    task["log_file"] = result.get("log_file", task.get("log_file"))
    task["result"] = result
    task["status"] = "completed" if result.get("status") == "ok" else "failed"
    if task["status"] == "failed":
        task["error"] = {
            "code": "TASK_EXECUTION_FAILED",
            "message": result.get("error", "Task execution failed"),
        }
    return save_task(task)


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
    from cli_anything.unreal.utils.ue_backend import find_editor_exe, preflight_check

    payload = task["payload"]
    state = AppState()
    state.json_output = True
    state.session.load_project(payload["project_path"])
    if payload.get("port") is not None:
        state.session.port = int(payload["port"])

    preflight = preflight_check(state.session.project_path, state.session.engine_root)
    startup_precheck = _summarize_startup_precheck(preflight)
    if not preflight.get("ready"):
        task["status"] = "failed"
        task["error"] = {
            "code": "PREFLIGHT_FAILED",
            "message": "Editor preflight failed",
            "details": startup_precheck,
        }
        task["result"] = {"startup_precheck": startup_precheck, "preflight": preflight}
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
        task["status"] = "failed"
        task["error"] = {
            "code": "PORT_IN_USE",
            "message": port_result.get("message", "Target port already in use"),
        }
        task["result"] = port_result
        return save_task(task)

    _deploy_bridge(state.session, state)

    cmd = _build_launch_cmd(editor_exe, state.session.project_path, payload.get("map_path"))
    proc = sp.Popen(cmd, stdout=sp.DEVNULL, stderr=sp.DEVNULL)

    task = load_task(task["task_id"]) or task
    task["pid"] = proc.pid
    task["estimated_total_seconds"] = estimated_total_seconds
    task["status"] = "running"
    task["result"] = {
        "pid": proc.pid,
        "project": state.session.project_name,
        "editor_exe": editor_exe,
        "startup_precheck": startup_precheck,
    }
    save_task(task)

    log_file = Path(state.session.project_dir) / "Saved" / "Logs" / f"{state.session.project_name}.log"
    wait_result = _wait_for_api(proc, state.session.port, int(payload.get("timeout", 600)), log_file, state)

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
        }
    else:
        task["status"] = "failed"
        task["error"] = {
            "code": "TASK_EXECUTION_FAILED",
            "message": wait_result.get("error", "Editor startup failed"),
        }
    return save_task(task)


