"""commands/session.py — Session management commands."""

import click

from cli_anything.unreal.commands import AppState, handle_error, output


@click.group("session")
def session_group():
    """Session management — undo, redo, status."""
    pass


@session_group.command("status")
@handle_error
@click.pass_obj
def session_status(state: AppState):
    """Show current session status."""
    output(state.session.status(), state)


@session_group.command("undo")
@handle_error
@click.pass_obj
def session_undo(state: AppState):
    """Undo the last change."""
    result = state.session.undo()
    if result:
        output({"status": "ok", "restored": result["description"]}, state)
    else:
        output({"status": "nothing_to_undo"}, state)


@session_group.command("redo")
@handle_error
@click.pass_obj
def session_redo(state: AppState):
    """Redo the last undone change."""
    result = state.session.redo()
    if result:
        output({"status": "ok", "restored": result["description"]}, state)
    else:
        output({"status": "nothing_to_redo"}, state)


@session_group.command("history")
@handle_error
@click.pass_obj
def session_history(state: AppState):
    """Show undo history."""
    history = state.session.list_history()
    output(history, state)
