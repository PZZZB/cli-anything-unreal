"""commands/ — Domain-separated Click command definitions for cli-anything-unreal.

This package provides:
  - AppState: shared state object stored on Click's ctx.obj
  - output(): unified output (JSON or pretty-printed)
  - handle_error: decorator for consistent error handling
  - require_project() / require_editor(): precondition helpers
  - register_commands(): wire all groups into the root CLI
"""

import functools
import json
import sys

import click

from cli_anything.unreal.core.session import Session
from cli_anything.unreal.utils.repl_skin import ReplSkin


# ── State ──────────────────────────────────────────────────────────────

class AppState:
    """Holds all mutable session state, stored on Click's ctx.obj."""

    def __init__(self):
        self.json_output: bool = False
        self.session: Session = Session()
        self.skin: ReplSkin = ReplSkin("unreal", version="0.1.1")
        self.in_repl: bool = False


# ── Output ─────────────────────────────────────────────────────────────

def output(data, state: AppState):
    """Output data as JSON or pretty-printed."""
    if state.json_output:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    elif isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                click.echo(f"  {k}: {json.dumps(v, indent=2, ensure_ascii=False, default=str)}")
            else:
                click.echo(f"  {k}: {v}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                click.echo(f"  {json.dumps(item, ensure_ascii=False, default=str)}")
            else:
                click.echo(f"  {item}")
    else:
        click.echo(str(data))


# ── Error handling ─────────────────────────────────────────────────────

def handle_error(f):
    """Decorator for consistent error handling across commands."""

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except FileNotFoundError as e:
            state = _get_state()
            if state.json_output:
                click.echo(json.dumps({"error": str(e)}))
            else:
                state.skin.error(str(e))
            if not state.in_repl:
                sys.exit(1)
        except ConnectionError as e:
            state = _get_state()
            msg = f"Editor not reachable (port {state.session.port}): {e}"
            if state.json_output:
                click.echo(json.dumps({"error": msg}))
            else:
                state.skin.error(msg)
                state.skin.hint("Is the UE editor running with Remote Control plugin enabled?")
                state.skin.hint(f"Try: cli-anything-unreal editor status --port {state.session.port}")
            if not state.in_repl:
                sys.exit(1)
        except Exception as e:
            state = _get_state()
            if state.json_output:
                click.echo(json.dumps({"error": str(e), "type": type(e).__name__}))
            else:
                state.skin.error(f"{type(e).__name__}: {e}")
            if not state.in_repl:
                sys.exit(1)

    return wrapper


def _get_state() -> AppState:
    """Retrieve AppState from the current Click context."""
    try:
        ctx = click.get_current_context()
        return ctx.obj
    except RuntimeError:
        # Fallback for edge cases (e.g. tests without a Click context)
        return AppState()


# ── Precondition helpers ───────────────────────────────────────────────

def require_project(state: AppState):
    """Ensure a project is loaded. Raises click.UsageError if not."""
    if not state.session.is_loaded:
        raise click.UsageError(
            "No project loaded. Use --project or run: project info --project <path>"
        )


def require_editor(state: AppState):
    """Ensure editor is reachable. Returns UEEditorAPI."""
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    api = UEEditorAPI(port=state.session.port)
    if not api.is_alive():
        raise ConnectionError(
            f"Editor HTTP API not responding on port {state.session.port}"
        )
    return api


# ── Command registration ──────────────────────────────────────────────

def register_commands(cli_group: click.Group):
    """Import and register all command sub-groups onto the root CLI."""
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
