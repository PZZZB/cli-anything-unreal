"""Click CLI main entry point for ue-cli."""

from __future__ import annotations

import json
import sys

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import click

from cli_anything.unreal._version import __version__
from cli_anything.unreal.commands import AppError, AppState, emit_json, error_payload, register_commands
from cli_anything.unreal.core.plugin_bridge import get_bundled_version
from cli_anything.unreal.core.tasks import cancel_task, load_task, run_task_worker, submit_task, task_progress, wait_for_task


_BRIDGE_VERSION = get_bundled_version() or "unknown"


COMMAND_SPECS = [
    {
        "name": "build compile",
        "description": "Compile the project's C++ code.",
        "async_supported": True,
        "estimated_duration": "300-900s",
        "parameters": [
            {"name": "--project", "required": True},
            {"name": "--config", "required": False},
            {"name": "--platform", "required": False},
            {"name": "--no-wait", "required": False},
            {"name": "--timeout", "required": False},
        ],
    },
    {
        "name": "build cook",
        "description": "Cook content assets for the target platform.",
        "async_supported": True,
        "estimated_duration": "120-600s",
        "parameters": [
            {"name": "--project", "required": True},
            {"name": "--platform", "required": False},
            {"name": "--no-wait", "required": False},
            {"name": "--timeout", "required": False},
        ],
    },
    {
        "name": "build package",
        "description": "Run build, cook, stage and package.",
        "async_supported": True,
        "estimated_duration": "600-1800s",
        "parameters": [
            {"name": "--project", "required": True},
            {"name": "--platform", "required": False},
            {"name": "--config", "required": False},
            {"name": "--output-dir", "required": False},
            {"name": "--no-wait", "required": False},
            {"name": "--timeout", "required": False},
        ],
    },
    {
        "name": "editor launch",
        "description": "Launch the Unreal Editor and wait for Remote Control API readiness.",
        "async_supported": True,
        "estimated_duration": "30-180s",
        "parameters": [
            {"name": "--project", "required": True},
            {"name": "--map", "required": False},
            {"name": "--no-wait", "required": False},
            {"name": "--timeout", "required": False},
        ],
    },
    {
        "name": "editor viewport bookmark jump",
        "description": "Jump the Level Viewport camera to a saved bookmark using the numeric shortcut.",
        "async_supported": False,
        "estimated_duration": "<5s",
        "parameters": [
            {"name": "--project", "required": True},
            {"name": "--index", "required": True},
            {"name": "--timeout", "required": False},
        ],
    },
]


def _fix_argv_msys2():
    import os

    if sys.platform != "win32" or not any(os.environ.get(name) for name in ("MSYSTEM", "MSYSTEM_PREFIX", "MSYS")):
        return

    virtual_roots = {"Game", "Engine", "Script"}
    fixed = []
    for arg in sys.argv:
        if (
            len(arg) >= 3
            and arg[0].isalpha()
            and arg[1] == ":"
            and arg[2] in ("/", "\\")
            and not os.path.exists(arg)
            and not os.path.exists(arg.split("*")[0])
        ):
            rest = arg[2:].replace("\\", "/")
            parts = rest.strip("/").split("/")
            msys_prefix_len = 0
            for i in range(len(parts)):
                candidate = arg[0:3] + "/".join(parts[: i + 1])
                if os.path.isdir(candidate):
                    msys_prefix_len = i + 1
                else:
                    break
            remaining = parts[msys_prefix_len:]
            if remaining and remaining[0] in virtual_roots:
                fixed.append("/" + "/".join(remaining))
            else:
                fixed.append(arg)
        else:
            fixed.append(arg)
    sys.argv = fixed


def _default_output_mode() -> str:
    return "text" if sys.stdout.isatty() else "json"


@click.group(invoke_without_command=True)
@click.version_option(
    __version__,
    prog_name="ue-cli",
    message=f"%(prog)s, version %(version)s\nCliAnythingBridge bundled version {_BRIDGE_VERSION}",
)
@click.option("--output", "output_mode", type=click.Choice(["json", "text"]), default=None)
@click.option("--project", "project_path", type=click.Path(), help="Path to .uproject file")
@click.option("--port", type=int, default=None, help="Editor Remote Control API port (auto-detected from project config if omitted)")
@click.option("--list-commands", is_flag=True, help="List CLI commands in a machine-readable format")
@click.pass_context
def cli(ctx, output_mode, project_path, port, list_commands):
    state = AppState()
    state.output_mode = output_mode or _default_output_mode()
    state.json_output = state.output_mode == "json"
    ctx.obj = state

    if project_path:
        try:
            state.session.load_project(project_path)
        except FileNotFoundError:
            emit_json(error_payload("PROJECT_NOT_FOUND", f"Project not found: {project_path}"))
            raise SystemExit(3)

    if port is not None:
        state.session.port = port
    elif state.session.project_dir:
        from cli_anything.unreal.utils.ue_backend import read_rc_port
        ini_port = read_rc_port(state.session.project_dir)
        if ini_port is not None:
            state.session.port = ini_port

    if list_commands:
        emit_json(COMMAND_SPECS)
        return

    if ctx.invoked_subcommand is None:
        if state.json_output:
            emit_json({"name": "ue-cli", "commands": COMMAND_SPECS})
        else:
            from cli_anything.unreal.commands.repl import repl_cmd

            ctx.invoke(repl_cmd)


@cli.group("_task-worker", hidden=True)
def task_worker_group():
    pass


@task_worker_group.command("run")
@click.argument("task_id")
def task_worker_run(task_id):
    try:
        run_task_worker(task_id)
        emit_json({"task_id": task_id, "status": "accepted"})
    except FileNotFoundError:
        emit_json(error_payload("TASK_NOT_FOUND", f"Task not found: {task_id}"))
        raise SystemExit(3)
    except Exception as e:
        task = load_task(task_id)
        if task:
            task["status"] = "failed"
            task["error"] = {"code": "TASK_EXECUTION_FAILED", "message": str(e)}
            task["result"] = {"exception_type": type(e).__name__}
            from cli_anything.unreal.core.tasks import save_task

            save_task(task)
        emit_json(error_payload("TASK_EXECUTION_FAILED", str(e)))
        raise SystemExit(1)


@cli.group("task")
def task_group():
    """Background task management."""


@task_group.command("status")
@click.argument("task_id")
def task_status_cmd(task_id):
    task = load_task(task_id)
    if task is None:
        emit_json(error_payload("TASK_NOT_FOUND", f"Task not found: {task_id}"))
        raise SystemExit(3)
    emit_json(task_progress(task))


@task_group.command("cancel")
@click.argument("task_id")
def task_cancel_cmd(task_id):
    task = cancel_task(task_id)
    if task is None:
        emit_json(error_payload("TASK_NOT_FOUND", f"Task not found: {task_id}"))
        raise SystemExit(3)
    emit_json(task_progress(task))


register_commands(cli)


def main():
    _fix_argv_msys2()
    try:
        cli()
    except AppError as e:
        emit_json(error_payload(e.code, e.message, suggestion=e.suggestion, details=e.details))
        raise SystemExit(e.exit_code)


if __name__ == "__main__":
    main()
