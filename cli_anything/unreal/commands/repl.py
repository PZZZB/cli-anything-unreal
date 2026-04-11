"""commands/repl.py — Interactive REPL mode."""

import shlex
import sys

import click

from cli_anything.unreal.commands import AppState


def register(cli_group: click.Group):
    """Register the repl command onto the root CLI group."""
    cli_group.add_command(repl_cmd)


@click.command("repl")
@click.pass_obj
def repl_cmd(state: AppState):
    """Start interactive REPL mode."""
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

    # Try to create prompt_toolkit session
    pt_session = state.skin.create_prompt_session()

    # Import here to avoid circular — cli is defined in unreal_cli.py
    from cli_anything.unreal.unreal_cli import cli

    while True:
        try:
            # Build prompt
            project_name = state.session.project_name or ""
            line = state.skin.get_input(
                pt_session,
                project_name=project_name,
                modified=state.session.modified,
                context=f":{state.session.port}" if not project_name else f"{project_name}:{state.session.port}",
            )

            if not line:
                continue

            # Built-in REPL commands
            if line.lower() in ("quit", "exit", "q"):
                break
            if line.lower() in ("help", "h", "?"):
                _print_repl_help(state)
                continue

            # Parse and execute via Click
            try:
                args = shlex.split(line)
            except ValueError as e:
                state.skin.error(f"Parse error: {e}")
                continue

            try:
                cli.main(args, standalone_mode=False)
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
    """Print REPL help."""
    state.skin.help({
        "project info": "Show project information",
        "project config list": "List configuration files",
        "project config get <name>": "Read a config file",
        "project config set <name> <sec> <k> <v>": "Set a config value",
        "asset list": "List content assets",
        "asset info <path>": "Describe a UAsset",
        "asset exists <path>": "Check if asset exists",
        "asset delete <path>": "Delete asset (with ref check)",
        "asset refs <path>": "List asset referencers",
        "asset duplicate <s_path> <d_path>": "Duplicate asset",
        "asset rename <s_path> <d_path>": "Rename/move asset",
        "asset get-property <path> <prop>": "Get asset property",
        "asset set-property <path> <prop> <val>": "Set asset property",
        "project generate": "Generate VS project files",
        "": "",
        "build compile": "Compile C++ code",
        "build cook": "Cook content assets",
        "build package": "Full package pipeline",
        "build status": "Check build status",
        " ": "",
        "scene list": "List all actors in level",
        "scene find <name>": "Find actor by name",
        "scene info <path>": "Describe actor properties",
        "scene get-property <path> <prop>": "Get property value",
        "scene set-property <path> <prop> <val>": "Set property value",
        "scene list-components <path>": "List actor components",
        "scene get-material <path>": "Get actor's material",
        "scene get-transform <path>": "Get actor transform",
        "material list": "List all materials",
        "material info <path>": "Material details + connections",
        "material get-connections <path>": "Connection graph + orphans",
        "material get-stats <path>": "Compilation statistics",
        "material get-errors <path>": "Check for errors",
        "material list-textures <path>": "List referenced textures",
        "material analyze <path>": "Auto-analyze issues",
        "  ": "",
        "screenshot capture": "Capture viewport (static)",
        "screenshot capture-sequence": "Time-ordered frame atlas (dynamic)",
        "   ": "",
        "editor status": "Check editor connection",
        "editor list": "Discover running editors",
        "editor exec <cmd>": "Run console command",
        "editor cvar get <name>": "Get CVar value",
        "editor cvar set <name> <val>": "Set CVar value",
        "    ": "",
        "session status": "Session info",
        "session undo": "Undo last change",
        "session redo": "Redo",
        "session history": "Undo history",
        "     ": "",
        "help": "Show this help",
        "quit": "Exit REPL",
    })
