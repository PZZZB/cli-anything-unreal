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
        # ── project ────────────────────────────────────────────────────
        "project info": "Display project information",
        "project config list": "List all configuration files",
        "project config get <name>": "Read a configuration file",
        "project config set <name> <sec> <k> <v>": "Set a configuration value",
        "project generate": "Generate Visual Studio project files",
        "": "",
        # ── asset ──────────────────────────────────────────────────────
        "asset list": "List content assets in the project",
        "asset exists <path>": "Check if an asset exists",
        "asset delete <path>": "Safely delete an asset (with ref check)",
        "asset refs <path>": "List all assets that reference this asset",
        "asset duplicate <src> <dst>": "Duplicate an asset to a new path",
        "asset rename <src> <dst>": "Rename/move an asset",
        "asset property <path> Prop": "Get or set a property (Prop or Prop=Val)",
        " ": "",
        # ── build ──────────────────────────────────────────────────────
        "build compile": "Compile the project's C++ code",
        "build cook": "Cook content assets for target platform",
        "build package": "Full package pipeline: build + cook + stage + package",
        "build status": "Check build status (binaries, logs)",
        "  ": "",
        # ── scene ──────────────────────────────────────────────────────
        "scene list": "List actors (use -q to filter by name)",
        "scene property <path> Prop": "Get or set a property (Prop or Prop=Val)",
        "scene list-components <path>": "List components on an actor",
        "scene get-material <path>": "Get the material on an actor's mesh",
        "scene get-transform <path>": "Get an actor's transform",
        "   ": "",
        # ── material ───────────────────────────────────────────────────
        "material list": "List all materials in the project",
        "material info <path>": "Show detailed material information",
        "material get-stats <path>": "Show material compilation statistics",
        "material get-errors <path>": "Check material for compilation errors",
        "material list-textures <path>": "List all referenced textures",
        "material get-graph <path>": "Show node topology as Mermaid graph",
        "material analyze <path>": "Analyze material for common issues",
        "material dump-hlsl <path>": "Get compiled HLSL/USF shader code",
        "material add-node <path>": "Add a new material expression node",
        "material set-node-property <path>": "Set properties on a node",
        "material delete-node <path>": "Delete a material expression node",
        "material connect <path>": "Connect two material expression nodes",
        "material disconnect <path>": "Disconnect material expression nodes",
        "material get-param <path>": "Get a parameter on a MaterialInstanceConstant",
        "material set-param <path>": "Set a parameter on a MaterialInstanceConstant",
        "material recompile <path>": "Recompile a material (force shader recompilation)",
        "    ": "",
        # ── blueprint ──────────────────────────────────────────────────
        "blueprint list": "List all blueprints in the project",
        "blueprint info <path>": "Show detailed blueprint information",
        "blueprint add-function <path>": "Add a function graph to a blueprint",
        "blueprint delete-function <path>": "Remove a function graph from a blueprint",
        "blueprint add-variable <path>": "Add a member variable to a blueprint",
        "blueprint delete-variable <path>": "Delete a member variable from a blueprint",
        "blueprint delete-unused-variables <path>": "Remove all unused variables",
        "blueprint compile <path>": "Compile a blueprint",
        "blueprint rename-graph <path>": "Rename a graph in a blueprint",
        "     ": "",
        # ── screenshot ─────────────────────────────────────────────────
        "screenshot capture": "Take a single static screenshot",
        "screenshot capture-sequence": "Viewport frames over time merged into atlas",
        "      ": "",
        # ── editor ─────────────────────────────────────────────────────
        "editor status": "Check if the UE editor is running and reachable",
        "editor list": "Discover all running UE editor instances",
        "editor preflight": "Check if engine and project are compiled and ready",
        "editor launch": "Launch UE editor with preflight build check",
        "editor close": "Close the running UE editor",
        "editor exec <cmd>": "Execute a console command in the editor",
        "editor run-script <path>": "Execute a Python script file in the editor",
        "editor api-discover <target>": "Discover the API surface of a UE Python class",
        "editor new-level <path>": "Create and open a new level",
        "editor save-level": "Save the current level",
        "editor enable-remote": "Enable Remote Control features for CLI use",
        "editor cvar get <name>": "Get a console variable value",
        "editor cvar set <name> <val>": "Set a console variable value",
        "       ": "",
        # ── session ────────────────────────────────────────────────────
        "session status": "Show current session status",
        "session undo": "Undo the last change",
        "session redo": "Redo the last undone change",
        "session history": "Show undo history",
        "        ": "",
        # ── REPL built-ins ─────────────────────────────────────────────
        "help": "Show this help",
        "quit": "Exit REPL",
    })
