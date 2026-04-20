"""commands/skills.py — Install AI agent skills."""

import shutil
from pathlib import Path

import click

from cli_anything.unreal.commands import AppState, handle_error, output


# Skill installation targets (extracted from inline list for maintainability).
# Each value is a zero-arg lambda so Path.home() is evaluated at call time,
# not at import time.
SKILL_TARGETS = {
    "claude_global": lambda: Path.home() / ".claude" / "skills" / "cli-anything-unreal",
    "codebuddy_global": lambda: Path.home() / ".codebuddy" / "agents" / "cli-anything-unreal",
    "gemini_global": lambda: Path.home() / ".gemini" / "skills" / "cli-anything-unreal",
}


def register(cli_group: click.Group):
    """Register the install-skills command onto the root CLI group."""
    cli_group.add_command(install_skills)


@click.command("install-skills")
@click.option(
    "--target",
    "targets",
    multiple=True,
    type=click.Path(path_type=Path),
    help=(
        "Install into the given directory instead of the default IDE locations. "
        "Repeat the flag for multiple targets. Primarily for tests."
    ),
)
@handle_error
@click.pass_obj
def install_skills(state: AppState, targets):
    """Install AI agent skills for Cursor and Claude Code.

    By default writes to each supported IDE's global skill directory under
    $HOME. Pass --target <dir> (repeatable) to install into custom paths
    instead — useful for unit tests that verify the deploy against a
    temporary directory.
    """
    source_dir = Path(__file__).parent.parent / "skills"
    if not source_dir.exists() or not source_dir.is_dir():
        state.skin.error("Could not find skills directory in the package.")
        return

    # Resolve target list: either explicit --target paths or the default IDEs.
    if targets:
        resolved: dict[str, Path] = {
            f"custom_{i}": Path(p) for i, p in enumerate(targets)
        }
    else:
        resolved = {name: fn() for name, fn in SKILL_TARGETS.items()}

    installed = 0
    results: dict[str, dict] = {}
    for name, target_dir in resolved.items():
        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            installed += 1
            results[name] = {"path": str(target_dir), "installed": True}
            if not state.json_output:
                state.skin.success(f"Installed skill to: {target_dir}")
        except Exception as e:
            results[name] = {"path": str(target_dir), "installed": False, "error": str(e)}
            if not state.json_output:
                state.skin.warning(f"Failed to install skill to {target_dir}: {e}")

    if state.json_output:
        output(
            {"status": "ok", "installed_count": installed, "targets": results},
            state,
        )
