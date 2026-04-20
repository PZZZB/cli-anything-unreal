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
    """Register the install-skills group onto the root CLI group."""
    cli_group.add_command(install_skills)


def _source_dir() -> Path:
    """Return the packaged skill source directory."""
    return Path(__file__).parent.parent / "skills"


def _do_install(source_dir: Path) -> dict[str, dict]:
    """Install the skill to every target. Returns a per-target status dict."""
    results: dict[str, dict] = {}
    for name, target_fn in SKILL_TARGETS.items():
        target_dir = target_fn()
        try:
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            results[name] = {"path": str(target_dir), "installed": True}
        except Exception as e:
            results[name] = {"path": str(target_dir), "installed": False, "error": str(e)}
    return results


@click.group(
    "install-skills",
    invoke_without_command=True,
    help="Install AI agent skills for Cursor and Claude Code.",
)
@click.pass_context
def install_skills(ctx: click.Context):
    """Install skill files under each IDE's global skill directory.

    Running without a subcommand performs the install (backwards compatible).
    Use `install-skills test` to exercise a full install + verify + cleanup
    cycle — handy for CI and release checks.
    """
    if ctx.invoked_subcommand is not None:
        return

    # Default action — install.
    state: AppState = ctx.obj
    source_dir = _source_dir()
    if not source_dir.exists() or not source_dir.is_dir():
        if not state.json_output:
            state.skin.error("Could not find skills directory in the package.")
        if state.json_output:
            output({"status": "error", "error": "source_missing"}, state)
        return

    results = _do_install(source_dir)
    installed = sum(1 for r in results.values() if r.get("installed"))

    if not state.json_output:
        for name, r in results.items():
            if r.get("installed"):
                state.skin.success(f"Installed skill to: {r['path']}")
            else:
                state.skin.warning(f"Failed to install skill to {r['path']}: {r.get('error')}")

    if state.json_output:
        output({"status": "ok", "installed_count": installed, "targets": results}, state)


@install_skills.command("test")
@handle_error
@click.pass_obj
def install_skills_test(state: AppState):
    """Self-test: install → verify files → clean up.

    Writes skill files to each target, verifies every file from the source
    survived the copy, then removes the target directories that did not
    exist before the test. Targets that were already present are left
    untouched (we refuse to run the test in that case to avoid clobbering
    a real install).

    Use this in CI or before releasing a new version of the skill bundle.
    """
    source_dir = _source_dir()
    if not source_dir.exists() or not source_dir.is_dir():
        output({"status": "error", "error": "source_missing"}, state)
        return

    # ── Pre-check: refuse if any target already exists, to protect real installs ──
    pre_existing: list[str] = []
    target_paths: dict[str, Path] = {name: fn() for name, fn in SKILL_TARGETS.items()}
    for name, path in target_paths.items():
        if path.exists():
            pre_existing.append(str(path))

    if pre_existing:
        output({
            "status": "skipped",
            "reason": "pre_existing_targets",
            "message": (
                "Refusing to run test — one or more target directories already exist. "
                "Remove them first so we don't clobber a real install."
            ),
            "pre_existing": pre_existing,
        }, state)
        return

    # Pre-compute the expected file list (relative paths under source_dir).
    expected = sorted(
        str(p.relative_to(source_dir))
        for p in source_dir.rglob("*")
        if p.is_file()
    )

    results: dict[str, dict] = {}
    try:
        # ── Install ──
        install_results = _do_install(source_dir)
        results = install_results

        # ── Verify ──
        for name, r in results.items():
            if not r.get("installed"):
                r["verified"] = False
                continue
            target_dir = Path(r["path"])
            missing = [
                rel for rel in expected
                if not (target_dir / rel).is_file()
            ]
            r["verified"] = len(missing) == 0
            if missing:
                r["missing_files"] = missing[:10]  # cap to keep JSON readable
                r["missing_count"] = len(missing)
    finally:
        # ── Cleanup: only remove what we created (pre-check guaranteed empty) ──
        for name, path in target_paths.items():
            if path.exists():
                try:
                    shutil.rmtree(path)
                    if name in results:
                        results[name]["cleaned"] = True
                except Exception as e:
                    if name in results:
                        results[name]["cleaned"] = False
                        results[name]["cleanup_error"] = str(e)

    all_ok = all(
        r.get("installed") and r.get("verified") and r.get("cleaned")
        for r in results.values()
    )
    output({
        "status": "ok" if all_ok else "failed",
        "targets": results,
        "expected_files": len(expected),
    }, state)
