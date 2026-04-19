"""commands/skills.py — Install AI agent skills."""

import shutil
from pathlib import Path

import click

from cli_anything.unreal.commands import AppState, handle_error, output


# Skill installation targets (extracted from inline list for maintainability)
SKILL_TARGETS = {
    "claude_global": lambda: Path.home() / ".claude" / "skills" / "cli-anything-unreal",
    "codebuddy_global": lambda: Path.home() / ".codebuddy" / "agents" / "cli-anything-unreal",
    "gemini_global": lambda: Path.home() / ".gemini" / "skills" / "cli-anything-unreal",
}


def register(cli_group: click.Group):
    """Register the install-skills command onto the root CLI group."""
    cli_group.add_command(install_skills)


@click.command("install-skills")
@handle_error
@click.pass_obj
def install_skills(state: AppState):
    """Install AI agent skills for Cursor and Claude Code."""
    source_dir = Path(__file__).parent.parent / "skills"
    if not source_dir.exists() or not source_dir.is_dir():
        state.skin.error("Could not find skills directory in the package.")
        return

    installed = 0
    for name, target_fn in SKILL_TARGETS.items():
        target_dir = target_fn()
        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            installed += 1
            if not state.json_output:
                state.skin.success(f"Installed skill to: {target_dir}")
        except Exception as e:
            if not state.json_output:
                state.skin.warning(f"Failed to install skill to {target_dir}: {e}")

    if state.json_output:
        output({"status": "ok", "installed_count": installed}, state)
