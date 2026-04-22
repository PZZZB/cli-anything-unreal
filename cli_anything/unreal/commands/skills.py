"""Install AI agent skills."""

import shutil
from pathlib import Path

import click

from cli_anything.unreal.commands import AppState, handle_error, output


SKILL_TARGETS = {
    "claude_global": lambda: Path.home() / ".claude" / "skills" / "cli-anything-unreal",
    "codebuddy_global": lambda: Path.home() / ".codebuddy" / "agents" / "cli-anything-unreal",
    "gemini_global": lambda: Path.home() / ".gemini" / "skills" / "cli-anything-unreal",
}


def register(cli_group: click.Group):
    cli_group.add_command(install_skills)


@click.command("install-skills")
@click.option(
    "--target",
    "targets",
    multiple=True,
    type=click.Path(path_type=Path),
    help="Install into the given directory instead of the default IDE locations.",
)
@handle_error
@click.pass_obj
def install_skills(state: AppState, targets):
    source_dir = Path(__file__).parent.parent / "skills"
    if not source_dir.exists() or not source_dir.is_dir():
        output({"installed_count": 0, "targets": {}, "warning": "Could not find skills directory in the package."}, state)
        return

    resolved = {f"custom_{i}": Path(p) for i, p in enumerate(targets)} if targets else {name: fn() for name, fn in SKILL_TARGETS.items()}
    installed = 0
    results: dict[str, dict] = {}
    for name, target_dir in resolved.items():
        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            installed += 1
            results[name] = {"path": str(target_dir), "installed": True}
        except Exception as e:
            results[name] = {"path": str(target_dir), "installed": False, "error": str(e)}

    output({"installed_count": installed, "targets": results}, state)
