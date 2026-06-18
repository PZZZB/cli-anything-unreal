"""Build command definitions."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click

from cli_anything.unreal.commands import AppError, AppState, handle_error, output, require_project
from cli_anything.unreal.core.tasks import FINAL_TASK_STATUSES, load_task, submit_task, task_progress
from cli_anything.unreal.utils.ue_backend import _allocate_log_path


def _build_payload(state: AppState, label: str, **kwargs) -> dict:
    payload = {
        "project_path": state.session.project_path,
        "engine_root": state.session.engine_root,
        "log_file": _allocate_log_path(state.session.project_dir, label),
    }
    payload.update(kwargs)
    return payload


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
            suggestion="Pass --project <path-to.uproject>.",
        )


def _project_option(func):
    return click.option("--project", "project_path", type=click.Path(), help="Path to .uproject file")(func)


def _stream_log_delta(log_file: str | None, offset: int = 0) -> int:
    if not log_file:
        return offset
    path = Path(log_file)
    try:
        size = path.stat().st_size
    except OSError:
        return offset
    if size < offset:
        offset = 0
    if size <= offset:
        return offset
    try:
        with path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read(size - offset)
    except OSError:
        return offset
    if data:
        sys.stderr.write(data.decode("utf-8", errors="replace"))
        sys.stderr.flush()
    return size


def _wait_for_task_with_log_stream(task_id: str, timeout: int | None, log_file: str | None) -> dict | None:
    deadline = None if timeout is None else time.time() + timeout
    offset = 0
    while True:
        offset = _stream_log_delta(log_file, offset)
        task = load_task(task_id)
        if task is None:
            return None
        if task.get("status") in FINAL_TASK_STATUSES:
            _stream_log_delta(log_file, offset)
            return task
        if deadline is not None and time.time() >= deadline:
            _stream_log_delta(log_file, offset)
            return None
        time.sleep(0.5)


def _run_task(command: str, payload: dict, *, timeout: int | None, no_wait: bool, timeout_code: str):
    task = submit_task(command, payload)
    if no_wait:
        return {
            "task_id": task["task_id"],
            "status": "submitted",
            "suggested_poll_interval_seconds": 5,
        }

    final_task = _wait_for_task_with_log_stream(task["task_id"], timeout, payload.get("log_file"))
    if final_task is None:
        current = load_task(task["task_id"]) or task
        if timeout is None:
            message = "Task did not finish (no timeout was set)."
        else:
            message = f"Task did not finish within {timeout}s."
        return {
            "task_id": task["task_id"],
            "status": "timeout",
            "progress": task_progress(current).get("progress", 0),
            "suggested_poll_interval_seconds": 5,
            "message": message,
            "code": timeout_code,
        }

    progress = task_progress(final_task)
    if final_task.get("status") == "failed":
        error = final_task.get("error", {})
        raise AppError(
            error.get("code", "TASK_EXECUTION_FAILED"),
            error.get("message", "Task execution failed"),
            exit_code=3,
            details=progress,
        )
    return progress


@click.group("build")
def build_group():
    """Build system commands."""


@build_group.command("compile")
@_project_option
@click.option("--config", "build_config", default="Development", type=click.Choice(["Development", "Shipping", "DebugGame", "Test"]))
@click.option("--platform", default="Win64")
@click.option("--no-wait", is_flag=True, default=False)
@click.option("--timeout", type=int, default=None)
@handle_error
@click.pass_obj
def build_compile(state: AppState, project_path, build_config, platform, no_wait, timeout):
    _load_command_project(state, project_path)
    require_project(state)
    payload = _build_payload(state, "compile", build_config=build_config, platform=platform)
    result = _run_task("build.compile", payload, timeout=timeout, no_wait=no_wait, timeout_code="BUILD_WAIT_TIMEOUT")
    output(result, state)


@build_group.command("cook")
@_project_option
@click.option("--platform", default="Win64")
@click.option("--no-wait", is_flag=True, default=False)
@click.option("--timeout", type=int, default=None)
@handle_error
@click.pass_obj
def build_cook(state: AppState, project_path, platform, no_wait, timeout):
    _load_command_project(state, project_path)
    require_project(state)
    payload = _build_payload(state, "cook", platform=platform)
    result = _run_task("build.cook", payload, timeout=timeout, no_wait=no_wait, timeout_code="BUILD_WAIT_TIMEOUT")
    output(result, state)


@build_group.command("package")
@_project_option
@click.option("--platform", default="Win64")
@click.option("--config", "build_config", default="Development", type=click.Choice(["Development", "Shipping", "DebugGame", "Test"]))
@click.option("--output-dir", type=click.Path(), help="Archive output directory")
@click.option("--no-wait", is_flag=True, default=False)
@click.option("--timeout", type=int, default=None)
@handle_error
@click.pass_obj
def build_package(state: AppState, project_path, platform, build_config, output_dir, no_wait, timeout):
    _load_command_project(state, project_path)
    require_project(state)
    payload = _build_payload(state, "package", platform=platform, build_config=build_config, output_dir=output_dir)
    result = _run_task("build.package", payload, timeout=timeout, no_wait=no_wait, timeout_code="BUILD_WAIT_TIMEOUT")
    output(result, state)


@build_group.command("status")
@_project_option
@click.argument("task_id", required=False)
@handle_error
@click.pass_obj
def build_status_cmd(state: AppState, project_path, task_id):
    _load_command_project(state, project_path)
    require_project(state)
    if task_id:
        task = load_task(task_id)
        if task is None:
            raise AppError("TASK_NOT_FOUND", f"Task not found: {task_id}", exit_code=3)
        output(task_progress(task), state)
        return

    from cli_anything.unreal.core.build import build_status

    output(build_status(state.session.project_path), state)


@build_group.command("cancel")
@click.argument("task_id")
@handle_error
@click.pass_obj
def build_cancel(state: AppState, task_id):
    from cli_anything.unreal.core.tasks import cancel_task

    task = cancel_task(task_id)
    if task is None:
        raise AppError("TASK_NOT_FOUND", f"Task not found: {task_id}", exit_code=3)
    output(task_progress(task), state)


@build_group.command("stop")
@_project_option
@handle_error
@click.pass_obj
def build_stop(state: AppState, project_path):
    from cli_anything.unreal.core.build import stop_build

    _load_command_project(state, project_path)
    require_project(state)
    output(stop_build(state.session.project_path), state)


@build_group.command("is-building")
@_project_option
@handle_error
@click.pass_obj
def build_is_building(state: AppState, project_path):
    from cli_anything.unreal.core.build import is_building

    _load_command_project(state, project_path)
    require_project(state)
    output(is_building(state.session.project_path), state)
