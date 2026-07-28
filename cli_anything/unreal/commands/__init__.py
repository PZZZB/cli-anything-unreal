"""Shared CLI protocol helpers and command registration."""

from __future__ import annotations

import functools
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import click

from cli_anything.unreal._version import __version__
from cli_anything.unreal.core.session import Session
from cli_anything.unreal.utils.repl_skin import ReplSkin


@dataclass
class AppError(Exception):
    code: str
    message: str
    exit_code: int = 1
    suggestion: str | None = None
    details: dict | list | None = None


class AppState:
    """Holds mutable session state shared across Click commands."""

    def __init__(self):
        self.json_output: bool = True
        self.session: Session = Session()
        self.port_is_explicit: bool = False
        self.skin: ReplSkin = ReplSkin("unreal", version=__version__)
        self.in_repl: bool = False
        self.output_mode: str = "json"


def emit_json(payload: dict | list) -> None:
    click.echo(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def success_payload(result) -> dict:
    return {"status": "success", "result": result}


def error_payload(
    code: str,
    message: str,
    *,
    suggestion: str | None = None,
    details=None,
) -> dict:
    payload = {
        "status": "error",
        "code": code,
        "message": message,
    }
    if suggestion:
        payload["suggestion"] = suggestion
    if details is not None:
        payload["details"] = details
    return payload


def output(data, state: AppState):
    """Emit either structured JSON or a compact text rendering."""
    if state.json_output:
        emit_json(success_payload(data))
        return

    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                click.echo(f"{k}: {json.dumps(v, indent=2, ensure_ascii=False, default=str)}")
            else:
                click.echo(f"{k}: {v}")
        return

    if isinstance(data, list):
        for item in data:
            click.echo(json.dumps(item, ensure_ascii=False, default=str) if isinstance(item, dict) else str(item))
        return

    click.echo(str(data))


def fail(
    state: AppState,
    code: str,
    message: str,
    *,
    exit_code: int = 1,
    suggestion: str | None = None,
    details=None,
):
    if state.json_output:
        emit_json(error_payload(code, message, suggestion=suggestion, details=details))
    else:
        state.skin.error(message)
        if suggestion:
            state.skin.hint(suggestion)
    if not state.in_repl:
        raise SystemExit(exit_code)


def handle_error(f):
    """Decorator for consistent protocol-level error handling."""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        state = _get_state()
        try:
            return f(*args, **kwargs)
        except SystemExit:
            raise
        except AppError as e:
            fail(
                state,
                e.code,
                e.message,
                exit_code=e.exit_code,
                suggestion=e.suggestion,
                details=e.details,
            )
        except click.UsageError as e:
            fail(
                state,
                "INVALID_ARGUMENT",
                str(e),
                exit_code=2,
                suggestion="Check --help for the expected arguments.",
            )
        except FileNotFoundError as e:
            fail(
                state,
                "FILE_NOT_FOUND",
                str(e),
                exit_code=3,
            )
        except ConnectionError as e:
            fail(
                state,
                "EDITOR_UNREACHABLE",
                str(e),
                exit_code=4,
                suggestion=f"Editor not reachable on port {state.session.port}. Launch with: editor launch --project <path-to-.uproject>",
            )
        except Exception as e:
            fail(
                state,
                "INTERNAL_ERROR",
                f"{type(e).__name__}: {e}",
                exit_code=1,
            )

    return wrapper


def _get_state() -> AppState:
    try:
        ctx = click.get_current_context()
        return ctx.obj
    except RuntimeError:
        return AppState()


def require_project(state: AppState):
    if not state.session.is_loaded:
        raise AppError(
            "PROJECT_REQUIRED",
            "No project loaded.",
            exit_code=2,
            suggestion="Pass --project <path-to.uproject>.",
        )


@click.command("preflight")
@handle_error
@click.pass_obj
def preflight_cmd(state: AppState):
    """Run read-only editor startup preflight checks."""
    from cli_anything.unreal.utils.ue_backend import preflight_check

    require_project(state)
    output(preflight_check(state.session.project_path, state.session.engine_root), state)


def _same_project_path(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    try:
        return Path(left).resolve().as_posix().lower() == Path(right).resolve().as_posix().lower()
    except Exception:
        return Path(left).as_posix().lower() == Path(right).as_posix().lower()


def _project_mismatch_details(state: AppState, running: list[dict]) -> dict:
    return {
        "port": state.session.port,
        "project": state.session.project_path,
        "running_editors": [
            {"pid": editor.get("pid"), "project": editor.get("project", "")}
            for editor in running
        ],
    }


def _guard_editor_project(state: AppState, api_cls) -> None:
    if not state.session.project_path or sys.platform != "win32":
        return

    try:
        from cli_anything.unreal.utils.ue_backend import find_running_editors

        running = find_running_editors()
    except Exception:
        return

    if not running:
        return

    try:
        listening_pid = api_cls._get_pid_listening_on_port(state.session.port)
    except Exception:
        listening_pid = None

    if listening_pid:
        owner = next(
            (editor for editor in running if int(editor.get("pid", 0)) == int(listening_pid)),
            None,
        )
        if owner and not _same_project_path(owner.get("project", ""), state.session.project_path):
            raise AppError(
                "EDITOR_PROJECT_NOT_RUNNING",
                f"Editor HTTP API on port {state.session.port} belongs to another project.",
                exit_code=3,
                details=_project_mismatch_details(state, running),
            )
        return

    if not any(_same_project_path(editor.get("project", ""), state.session.project_path) for editor in running):
        raise AppError(
            "EDITOR_PROJECT_NOT_RUNNING",
            f"Editor HTTP API is alive on port {state.session.port}, but no running UnrealEditor process matches this project.",
            exit_code=3,
            details=_project_mismatch_details(state, running),
        )


def _discover_online_editor_port(
    state: AppState,
    *,
    fail_if_ambiguous: bool = False,
) -> int | None:
    """Return one unambiguous live editor port when the selected port is stale."""
    if state.port_is_explicit:
        return None

    try:
        from cli_anything.unreal.commands.editor import _scan_editor_status_instances

        instances = _scan_editor_status_instances(
            state,
            "30010-30020",
            include_bridge_status=False,
        )
    except Exception:
        return None

    online_by_port: dict[int, dict] = {}
    for instance in instances:
        if instance.get("status") != "online" or instance.get("port") is None:
            continue
        if state.session.project_path and not _same_project_path(
            instance.get("project_path"),
            state.session.project_path,
        ):
            continue
        try:
            port = int(instance["port"])
        except (TypeError, ValueError):
            continue
        online_by_port.setdefault(port, instance)
    if len(online_by_port) == 1:
        return next(iter(online_by_port))
    if fail_if_ambiguous and len(online_by_port) > 1:
        live_editors = []
        for port, instance in sorted(online_by_port.items()):
            live_editors.append({
                "pid": instance.get("pid"),
                "port": port,
                "project_path": instance.get("project_path"),
            })
        if state.session.project_path:
            suggestion = "Pass --port <port> to select one matching editor."
        else:
            suggestion = "Pass --project <path-to.uproject> or --port <port> to select one editor."
        raise AppError(
            "EDITOR_TARGET_AMBIGUOUS",
            f"Multiple live editors match while selected port {state.session.port} is offline.",
            exit_code=3,
            suggestion=suggestion,
            details={
                "selected_port": state.session.port,
                "project": state.session.project_path,
                "live_editors": live_editors,
            },
        )
    return None


def require_editor(
    state: AppState,
    *,
    timeout: int | float | None = None,
):
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    deadline = time.monotonic() + timeout if timeout is not None else None

    def remaining_timeout() -> float | None:
        if deadline is None:
            return None
        return max(0.0, deadline - time.monotonic())

    def is_alive(api) -> bool:
        remaining = remaining_timeout()
        if remaining is None:
            return api.is_alive()
        return api.is_alive(timeout=remaining)

    api = UEEditorAPI(port=state.session.port)
    api.project_path = state.session.project_path
    api_alive = is_alive(api)
    if not api_alive:
        live_port = _discover_online_editor_port(state, fail_if_ambiguous=True)
        if live_port is not None:
            live_api = UEEditorAPI(port=live_port)
            live_api.project_path = state.session.project_path
            if is_alive(live_api):
                state.session.port = live_port
                api = live_api
                api_alive = True
    if not api_alive:
        raise AppError(
            "EDITOR_UNREACHABLE",
            f"Editor HTTP API not responding on port {state.session.port}.",
            exit_code=4,
            suggestion="Launch the editor with: editor launch --project <path-to-.uproject>",
        )
    _guard_editor_project(state, UEEditorAPI)
    return api


def register_commands(cli_group: click.Group):
    from cli_anything.unreal.commands.project import project_group
    from cli_anything.unreal.commands.asset import asset_group
    from cli_anything.unreal.commands.build import build_group
    from cli_anything.unreal.commands.scene import scene_group
    from cli_anything.unreal.commands.material import material_group
    from cli_anything.unreal.commands.blueprint import blueprint_group
    from cli_anything.unreal.commands.umg import umg_group
    from cli_anything.unreal.commands.screenshot import screenshot_group
    from cli_anything.unreal.commands.editor import editor_group
    from cli_anything.unreal.commands.session import session_group
    from cli_anything.unreal.commands.skills import register as register_skills
    from cli_anything.unreal.commands.repl import register as register_repl

    cli_group.add_command(project_group)
    cli_group.add_command(asset_group)
    cli_group.add_command(build_group)
    cli_group.add_command(scene_group)
    cli_group.add_command(material_group)
    cli_group.add_command(blueprint_group)
    cli_group.add_command(umg_group)
    cli_group.add_command(screenshot_group)
    cli_group.add_command(editor_group)
    cli_group.add_command(preflight_cmd)
    cli_group.add_command(session_group)
    register_skills(cli_group)
    register_repl(cli_group)
