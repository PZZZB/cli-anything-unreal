"""Build command definitions."""

from __future__ import annotations

import click

from cli_anything.unreal.commands import AppError, AppState, handle_error, output, require_project
from cli_anything.unreal.core.tasks import load_task, submit_task, task_progress, wait_for_task
from cli_anything.unreal.utils.ue_backend import _allocate_log_path


def _build_payload(state: AppState, label: str, **kwargs) -> dict:
    payload = {
        "project_path": state.session.project_path,
        "engine_root": state.session.engine_root,
        "log_file": _allocate_log_path(state.session.project_dir, label),
    }
    payload.update(kwargs)
    return payload


def _run_task(command: str, payload: dict, *, timeout: int | None, no_wait: bool, timeout_code: str):
    task = submit_task(command, payload)
    if no_wait:
        return {
            "task_id": task["task_id"],
            "status": "submitted",
            "suggested_poll_interval_seconds": 5,
        }

    final_task = wait_for_task(task["task_id"], timeout)
    if final_task is None:
        current = load_task(task["task_id"]) or task
        return {
            "task_id": task["task_id"],
            "status": "timeout",
            "progress": task_progress(current).get("progress", 0),
            "suggested_poll_interval_seconds": 5,
            "message": f"Task did not finish within {timeout}s.",
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
@click.option("--config", "build_config", default="Development", type=click.Choice(["Development", "Shipping", "DebugGame", "Test"]))
@click.option("--platform", default="Win64")
@click.option("--no-wait", is_flag=True, default=False)
@click.option("--timeout", type=int, default=1800)
@handle_error
@click.pass_obj
def build_compile(state: AppState, build_config, platform, no_wait, timeout):
    require_project(state)
    payload = _build_payload(state, "compile", build_config=build_config, platform=platform)
    result = _run_task("build.compile", payload, timeout=timeout, no_wait=no_wait, timeout_code="BUILD_WAIT_TIMEOUT")
    output(result, state)


@build_group.command("cook")
@click.option("--platform", default="Win64")
@click.option("--no-wait", is_flag=True, default=False)
@click.option("--timeout", type=int, default=1800)
@handle_error
@click.pass_obj
def build_cook(state: AppState, platform, no_wait, timeout):
    require_project(state)
    payload = _build_payload(state, "cook", platform=platform)
    result = _run_task("build.cook", payload, timeout=timeout, no_wait=no_wait, timeout_code="BUILD_WAIT_TIMEOUT")
    output(result, state)


@build_group.command("package")
@click.option("--platform", default="Win64")
@click.option("--config", "build_config", default="Development", type=click.Choice(["Development", "Shipping", "DebugGame", "Test"]))
@click.option("--output-dir", type=click.Path(), help="Archive output directory")
@click.option("--no-wait", is_flag=True, default=False)
@click.option("--timeout", type=int, default=3600)
@handle_error
@click.pass_obj
def build_package(state: AppState, platform, build_config, output_dir, no_wait, timeout):
    require_project(state)
    payload = _build_payload(state, "package", platform=platform, build_config=build_config, output_dir=output_dir)
    result = _run_task("build.package", payload, timeout=timeout, no_wait=no_wait, timeout_code="BUILD_WAIT_TIMEOUT")
    output(result, state)


@build_group.command("status")
@click.argument("task_id", required=False)
@handle_error
@click.pass_obj
def build_status_cmd(state: AppState, task_id):
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
@handle_error
@click.pass_obj
def build_stop(state: AppState):
    from cli_anything.unreal.core.build import stop_build

    require_project(state)
    output(stop_build(state.session.project_path), state)


@build_group.command("is-building")
@handle_error
@click.pass_obj
def build_is_building(state: AppState):
    from cli_anything.unreal.core.build import is_building

    require_project(state)
    output(is_building(state.session.project_path), state)
