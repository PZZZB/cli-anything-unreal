"""Interactive REPL mode."""

import shlex

import click

from cli_anything.unreal.commands import AppState


def register(cli_group: click.Group):
    cli_group.add_command(repl_cmd)


@click.command("repl")
@click.pass_obj
def repl_cmd(state: AppState):
    state.in_repl = True
    state.skin.print_banner()

    if state.session.is_loaded:
        state.skin.info(f"Project: {state.session.project_name}")
        if state.session.engine_root:
            state.skin.info(f"Engine: {state.session.engine_root}")
    else:
        state.skin.hint("No project loaded. Use: project info --project <path>")

    state.skin.info(f"Editor port: {state.session.port}")
    print()
    pt_session = state.skin.create_prompt_session()
    from cli_anything.unreal.unreal_cli import cli

    while True:
        try:
            project_name = state.session.project_name or ""
            line = state.skin.get_input(
                pt_session,
                project_name=project_name,
                modified=state.session.modified,
                context=f":{state.session.port}" if not project_name else f"{project_name}:{state.session.port}",
            )
            if not line:
                continue
            if line.lower() in ("quit", "exit", "q"):
                break
            if line.lower() in ("help", "h", "?"):
                _print_repl_help(state)
                continue

            args = shlex.split(line)
            try:
                cli.main(args=args, standalone_mode=False)
            except SystemExit:
                pass
            except click.exceptions.UsageError as e:
                state.skin.error(str(e))
            except Exception as e:
                state.skin.error(f"{type(e).__name__}: {e}")
        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            break

    state.skin.print_goodbye()
    state.in_repl = False


def _print_repl_help(state: AppState):
    state.skin.help({
        "project info": "Display project information",
        "build compile --no-wait": "Submit a background compile task",
        "build status <task_id>": "Query a build task",
        "editor launch --no-wait": "Launch the editor asynchronously",
        "task status <task_id>": "Query any async task",
        "task cancel <task_id>": "Cancel any async task",
        "help": "Show this help",
        "quit": "Exit REPL",
    })
