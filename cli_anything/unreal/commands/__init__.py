"""Shared CLI protocol helpers and command registration."""

from __future__ import annotations

import functools
import json
import sys
from dataclasses import dataclass

import click

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
        self.skin: ReplSkin = ReplSkin("unreal", version="0.2.0")
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
                suggestion=f"Run 'editor status --port {state.session.port}' to verify editor connectivity.",
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


def require_editor(state: AppState):
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    api = UEEditorAPI(port=state.session.port)
    if not api.is_alive():
        raise AppError(
            "EDITOR_UNREACHABLE",
            f"Editor HTTP API not responding on port {state.session.port}.",
            exit_code=4,
            suggestion="Start the editor first or confirm the Remote Control port.",
        )
    return api


def register_commands(cli_group: click.Group):
    from cli_anything.unreal.commands.project import project_group
    from cli_anything.unreal.commands.asset import asset_group
    from cli_anything.unreal.commands.build import build_group
    from cli_anything.unreal.commands.scene import scene_group
    from cli_anything.unreal.commands.material import material_group
    from cli_anything.unreal.commands.blueprint import blueprint_group
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
    cli_group.add_command(screenshot_group)
    cli_group.add_command(editor_group)
    cli_group.add_command(session_group)
    register_skills(cli_group)
    register_repl(cli_group)
