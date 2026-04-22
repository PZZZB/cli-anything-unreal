"""Session management commands."""

import click

from cli_anything.unreal.commands import AppState, handle_error, output


@click.group("session")
def session_group():
    """Session management commands."""


@session_group.command("status")
@handle_error
@click.pass_obj
def session_status(state: AppState):
    output(state.session.status(), state)


@session_group.command("undo")
@handle_error
@click.pass_obj
def session_undo(state: AppState):
    result = state.session.undo()
    output({"restored": result["description"]} if result else {"status": "nothing_to_undo"}, state)


@session_group.command("redo")
@handle_error
@click.pass_obj
def session_redo(state: AppState):
    result = state.session.redo()
    output({"restored": result["description"]} if result else {"status": "nothing_to_redo"}, state)


@session_group.command("history")
@handle_error
@click.pass_obj
def session_history(state: AppState):
    output(state.session.list_history(), state)
