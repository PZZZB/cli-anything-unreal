"""Install AI agent skills."""

import shutil
from pathlib import Path

import click

from cli_anything.unreal.commands import AppError, AppState, handle_error, output


SKILL_TARGETS = {
    "agents_global": lambda: Path.home() / ".agents" / "skills" / "ue-cli",
    "claude_global": lambda: Path.home() / ".claude" / "skills" / "ue-cli",
    "codebuddy_global": lambda: Path.home() / ".codebuddy" / "agents" / "ue-cli",
    "gemini_global": lambda: Path.home() / ".gemini" / "skills" / "ue-cli",
}

SKILL_TARGET_AGENTS = {
    "agents_global": (
        "codex",
        "cursor",
        "github_copilot",
        "windsurf",
        "opencode",
    ),
    "claude_global": ("claude_code",),
    "codebuddy_global": ("codebuddy",),
    "gemini_global": ("gemini",),
}


def register(cli_group: click.Group):
    cli_group.add_command(install_skills)


@click.command("install-skills")
@click.option(
    "--target",
    "targets",
    multiple=True,
    type=click.Path(path_type=Path),
    help="Install into this exact .../ue-cli skill directory; repeatable.",
)
@click.option(
    "--all-targets",
    is_flag=True,
    help="Install every built-in target even when its client is not detected.",
)
@handle_error
@click.pass_obj
def install_skills(state: AppState, targets, all_targets):
    source_dir = Path(__file__).parent.parent / "skills"
    if not source_dir.exists() or not source_dir.is_dir():
        output({"installed_count": 0, "targets": {}, "warning": "Could not find skills directory in the package."}, state)
        return

    if targets and all_targets:
        raise AppError(
            "INVALID_SKILL_TARGET",
            "--target and --all-targets cannot be used together.",
            exit_code=2,
        )

    source_dir = source_dir.resolve()
    detected_clients = _detect_clients(Path.home())
    results: dict[str, dict] = {}
    if targets:
        resolved = {}
        for target in targets:
            target_dir = _validate_custom_target(source_dir, Path(target))
            if target_dir not in resolved.values():
                resolved[f"custom_{len(resolved)}"] = target_dir
    else:
        resolved = {}
        for name, target_fn in SKILL_TARGETS.items():
            target_dir = target_fn()
            clients = SKILL_TARGET_AGENTS[name]
            detected = sorted(set(clients) & detected_clients)
            if all_targets or detected or target_dir.parent.exists():
                resolved[name] = target_dir
                continue
            results[name] = {
                "path": str(target_dir),
                "installed": False,
                "skipped": True,
                "clients": list(clients),
                "reason": "No matching client or initialized skill directory detected.",
            }

    installed = 0
    for name, target_dir in resolved.items():
        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            installed += 1
            results[name] = {"path": str(target_dir), "installed": True}
            if not targets:
                results[name]["clients"] = list(SKILL_TARGET_AGENTS[name])
        except Exception as e:
            results[name] = {"path": str(target_dir), "installed": False, "error": str(e)}
            if not targets:
                results[name]["clients"] = list(SKILL_TARGET_AGENTS[name])

    response = {
        "installed_count": installed,
        "skipped_count": sum(bool(item.get("skipped")) for item in results.values()),
        "targets": results,
    }
    if not targets:
        response["detected_clients"] = sorted(detected_clients)
        response["forced_all_targets"] = all_targets
        if installed == 0:
            if resolved:
                response["warning"] = (
                    "No skill target was installed. Inspect each target error."
                )
            else:
                response["warning"] = (
                    "No supported client was detected. Run the client once, use "
                    "--all-targets, or pass --target <path/to/ue-cli>."
                )
    output(response, state)


def _detect_clients(home: Path) -> set[str]:
    markers = {
        "claude_code": (home / ".claude",),
        "codebuddy": (home / ".codebuddy",),
        "codex": (home / ".codex",),
        "cursor": (home / ".cursor",),
        "gemini": (home / ".gemini",),
        "opencode": (home / ".config" / "opencode", home / ".opencode"),
        "windsurf": (home / ".codeium" / "windsurf", home / ".windsurf"),
        "github_copilot": (home / ".copilot",),
    }
    detected = {
        client
        for client, client_markers in markers.items()
        if any(marker.exists() for marker in client_markers)
    }

    extension_roots = (
        home / ".vscode" / "extensions",
        home / ".vscode-insiders" / "extensions",
        home / ".cursor" / "extensions",
    )
    for extension_root in extension_roots:
        try:
            if any(
                entry.name.lower().startswith("github.copilot")
                for entry in extension_root.iterdir()
            ):
                detected.add("github_copilot")
                break
        except OSError:
            continue
    return detected


def _validate_custom_target(source_dir: Path, target_dir: Path) -> Path:
    target_dir = target_dir.expanduser().resolve()
    if (
        target_dir == source_dir
        or target_dir in source_dir.parents
        or source_dir in target_dir.parents
    ):
        raise AppError(
            "INVALID_SKILL_TARGET",
            f"Custom skill target overlaps the bundled skill source: {target_dir}",
            exit_code=2,
            suggestion="Choose a client skill directory outside the ue-cli repository.",
        )
    if target_dir.name != "ue-cli":
        raise AppError(
            "INVALID_SKILL_TARGET",
            f"Custom skill target must end with 'ue-cli': {target_dir}",
            exit_code=2,
            suggestion="Pass the full skill directory, for example: --target C:/agent/skills/ue-cli",
        )
    return target_dir
