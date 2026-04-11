"""unreal_cli.py — Click CLI main entry point for cli-anything-unreal.

Thin entry point that wires up the root Click group and delegates
all command definitions to the ``commands/`` package.
"""

import json
import sys

# ── Fix Windows GBK terminal encoding for Unicode output (✓✗⚠●◆) ────
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import click

from cli_anything.unreal.commands import AppState, register_commands


def _fix_argv_msys2():
    """Fix MSYS2 (Git Bash) path mangling in sys.argv BEFORE Click parses.

    MSYS2 auto-converts any argument starting with / to a Windows path
    when calling non-MSYS .exe programs:
        /Game/M_Test  ->  D:/Git/Game/M_Test
        /Engine/...   ->  D:/Git/Engine/...

    Detection: if an argv looks like a Windows absolute path (X:/...)
    but that path does NOT exist on disk, it was almost certainly mangled.
    Restore it to /remainder (strip the drive + MSYS prefix).

    This runs once at startup and is invisible to the user.
    """
    import os
    fixed = []
    for arg in sys.argv:
        if (
            len(arg) >= 3
            and arg[0].isalpha()
            and arg[1] == ":"
            and arg[2] in ("/", "\\")
            and not os.path.exists(arg)          # real disk path? leave it alone
            and not os.path.exists(arg.split("*")[0])  # glob pattern guard
        ):
            # Strip drive + leading prefix, restore as /...
            rest = arg[2:].replace("\\", "/")    # ":/Git/Game/M_Test" -> "/Git/Game/M_Test"
            # MSYS2 prepends its install dir, e.g. D:/Git -> /Git is the root
            # The original arg was just /Game/M_Test, which became D:/Git/Game/M_Test
            # We need to strip everything up to (but not including) the first path
            # component that the user actually typed.
            # Heuristic: the MSYS root is the part that exists on disk.
            # Walk from the left, find the longest prefix that is a real directory.
            parts = rest.strip("/").split("/")
            msys_prefix_len = 0
            for i in range(len(parts)):
                candidate = arg[0:3] + "/".join(parts[:i + 1])
                if os.path.isdir(candidate):
                    msys_prefix_len = i + 1
                else:
                    break
            # Restore: skip the MSYS prefix directories
            restored = "/" + "/".join(parts[msys_prefix_len:])
            fixed.append(restored)
        else:
            fixed.append(arg)
    sys.argv = fixed


# ── Root CLI group ──────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.option("--json", "use_json", is_flag=True, help="Output in JSON format")
@click.option(
    "--project", "project_path", type=click.Path(),
    help="Path to .uproject file",
)
@click.option(
    "--port", type=int, default=30010,
    help="Editor Remote Control API port (default: 30010, for multi-instance support)",
)
@click.pass_context
def cli(ctx, use_json, project_path, port):
    """cli-anything-unreal — AI Agent CLI for Unreal Engine.

    Control UE editor via command-line: materials, screenshots, builds.

    Multi-instance: use --port to target a specific editor instance.
    """
    state = AppState()
    state.json_output = use_json
    state.session.port = port
    ctx.obj = state

    if project_path:
        try:
            state.session.load_project(project_path)
        except FileNotFoundError:
            if use_json:
                click.echo(json.dumps({"error": f"Project not found: {project_path}"}))
            else:
                state.skin.error(f"Project not found: {project_path}")

    if ctx.invoked_subcommand is None:
        from cli_anything.unreal.commands.repl import repl_cmd
        ctx.invoke(repl_cmd)


# ── Register all command groups ─────────────────────────────────────────
register_commands(cli)


# ── Entry point ─────────────────────────────────────────────────────────

def main():
    _fix_argv_msys2()
    cli()


if __name__ == "__main__":
    main()
