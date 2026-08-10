"""Commands for actively querying and answering brokered editor dialogs."""

from __future__ import annotations

import click

from cli_anything.unreal.commands import (
    AppError,
    AppState,
    handle_error,
    output,
    require_editor,
    require_project,
)


@click.group("confirmation")
def confirmation_group():
    """Query and answer UE confirmation dialogs without UI automation."""


@confirmation_group.command("enable")
@click.option("--pid", type=click.IntRange(min=1), help="Exact editor process id.")
@click.option(
    "--ttl",
    "ttl_seconds",
    type=click.IntRange(min=30, max=86400),
    default=900,
    show_default=True,
    help="Seconds before unanswered dialogs fall back to normal editor UI.",
)
@handle_error
@click.pass_obj
def confirmation_enable(state: AppState, pid: int | None, ttl_seconds: int):
    """Arm bounded Bridge interception for one running editor."""

    from cli_anything.unreal.core.confirmations import (
        confirmation_bridge_supported,
        enable_confirmation_broker,
    )
    from cli_anything.unreal.core.plugin_bridge import get_loaded_plugin_version

    require_project(state)
    api = require_editor(state)
    loaded_version = get_loaded_plugin_version(api, timeout=10.0, raise_on_error=True)
    if not confirmation_bridge_supported(loaded_version):
        raise AppError(
            "CONFIRMATION_BRIDGE_UPGRADE_REQUIRED",
            "The running CliAnythingBridge does not support confirmation brokerage.",
            exit_code=3,
            suggestion=(
                f'Run: ue-cli --project "{state.session.project_path}" '
                "editor plugin-upgrade"
            ),
            details={
                "loaded_version": loaded_version,
                "minimum_version": "1.32",
            },
        )
    output(
        enable_confirmation_broker(
            state.session.project_path,
            pid=pid,
            ttl_seconds=ttl_seconds,
        ),
        state,
    )


@confirmation_group.command("list")
@click.option("--pid", type=click.IntRange(min=1), help="Restrict results to one editor process.")
@handle_error
@click.pass_obj
def confirmation_list(state: AppState, pid: int | None):
    """List pending Bridge confirmations and detected UE dialog windows."""

    from cli_anything.unreal.core.confirmations import list_confirmations

    require_project(state)
    output(list_confirmations(state.session.project_path, pid=pid), state)


@confirmation_group.command("answer")
@click.argument("confirmation_id")
@click.option("--choice", required=True, help="One choice reported by confirmation list.")
@click.option(
    "--wait",
    "wait_seconds",
    type=click.FloatRange(min=0.0, max=30.0),
    default=2.0,
    show_default=True,
    help="Seconds to wait for the editor to consume the answer.",
)
@handle_error
@click.pass_obj
def confirmation_answer(
    state: AppState,
    confirmation_id: str,
    choice: str,
    wait_seconds: float,
):
    """Answer one brokered FMessageDialog by id."""

    from cli_anything.unreal.core.confirmations import answer_confirmation

    require_project(state)
    output(
        answer_confirmation(
            state.session.project_path,
            confirmation_id,
            choice,
            wait_seconds=wait_seconds,
        ),
        state,
    )


@confirmation_group.command("disable")
@click.option("--pid", type=click.IntRange(min=1), help="Exact editor process id.")
@handle_error
@click.pass_obj
def confirmation_disable(state: AppState, pid: int | None):
    """Disarm interception and return pending dialogs to normal editor UI."""

    from cli_anything.unreal.core.confirmations import disable_confirmation_broker

    require_project(state)
    output(disable_confirmation_broker(state.session.project_path, pid=pid), state)
