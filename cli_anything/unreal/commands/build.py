"""commands/build.py — Build system commands."""

import sys
from pathlib import Path

import click

from cli_anything.unreal.commands import AppState, handle_error, output, require_project


def _announce_log(label: str, log_file: str) -> None:
    """Print the build log path to stderr before blocking.

    Lets AI callers start ``tail``-ing the log in a second shell (or just
    know where to look if they ever need to) without waiting 5-15 min
    for the final JSON payload.
    """
    try:
        sys.stderr.write(f"[{label}] log {log_file}\n")
        sys.stderr.flush()
    except Exception:
        pass


def _preallocate_log(project_dir: str, label: str) -> str:
    """Allocate a timestamped ``cli_<label>_<ts>.log`` path under Saved/Logs.

    Uses the same helper the build core would use, so the announced path
    is exactly the file UAT will eventually write to.
    """
    from cli_anything.unreal.utils.ue_backend import _allocate_log_path
    return _allocate_log_path(project_dir, label)


@click.group("build")
def build_group():
    """Build system — compile, cook, package via UAT/UBT."""
    pass


@build_group.command("compile")
@click.option("--config", "build_config", default="Development",
              type=click.Choice(["Development", "Shipping", "DebugGame", "Test"]))
@click.option("--platform", default="Win64")
@handle_error
@click.pass_obj
def build_compile(state: AppState, build_config, platform):
    """Compile the project's C++ code.

    Synchronous: blocks until UAT finishes (5-15 min for a full rebuild).
    Before blocking, the log path is printed to stderr so you can tail it
    in a second shell. A heartbeat line is also written to stderr every
    60 seconds while UAT runs. If your shell has a short timeout, wrap
    this command in your harness's background-task mechanism (e.g. Bash
    ``run_in_background=true``) rather than racing the timeout.
    """
    from cli_anything.unreal.core.build import compile_project

    require_project(state)
    log_file = _preallocate_log(state.session.project_dir, "compile")
    _announce_log("compile", log_file)
    state.skin.info(
        f"Compiling {state.session.project_name} "
        f"({build_config} / {platform}, 5-15 min)..."
    )
    result = compile_project(
        state.session.project_path, build_config, platform,
        state.session.engine_root, log_file=log_file,
    )
    output(result, state)


@build_group.command("cook")
@click.option("--platform", default="Win64")
@handle_error
@click.pass_obj
def build_cook(state: AppState, platform):
    """Cook content assets for the target platform.

    Synchronous. See ``build compile --help`` for progress/log handling.
    """
    from cli_anything.unreal.core.build import cook_content

    require_project(state)
    log_file = _preallocate_log(state.session.project_dir, "cook")
    _announce_log("cook", log_file)
    state.skin.info(f"Cooking content for {platform}...")
    result = cook_content(
        state.session.project_path, platform, state.session.engine_root,
        log_file=log_file,
    )
    output(result, state)


@build_group.command("package")
@click.option("--platform", default="Win64")
@click.option("--config", "build_config", default="Development",
              type=click.Choice(["Development", "Shipping", "DebugGame", "Test"]))
@click.option("--output", "output_dir", type=click.Path(), help="Archive output directory")
@handle_error
@click.pass_obj
def build_package(state: AppState, platform, build_config, output_dir):
    """Full package pipeline: build + cook + stage + package.

    Synchronous (15-30 min). See ``build compile --help`` for progress
    handling.
    """
    from cli_anything.unreal.core.build import package_project

    require_project(state)
    log_file = _preallocate_log(state.session.project_dir, "package")
    _announce_log("package", log_file)
    state.skin.info(
        f"Packaging {state.session.project_name} "
        f"({build_config} / {platform}, 15-30 min)..."
    )
    result = package_project(
        state.session.project_path, platform, build_config,
        output_dir, state.session.engine_root, log_file=log_file,
    )
    output(result, state)


@build_group.command("stop")
@handle_error
@click.pass_obj
def build_stop(state: AppState):
    """Stop a running build (kills MSBuild/UBT process tree)."""
    from cli_anything.unreal.core.build import stop_build

    require_project(state)
    state.skin.info(f"Stopping build for {state.session.project_name}...")
    result = stop_build(state.session.project_path)
    output(result, state)


@build_group.command("is-building")
@handle_error
@click.pass_obj
def build_is_building(state: AppState):
    """Check if the project is currently being compiled."""
    from cli_anything.unreal.core.build import is_building

    require_project(state)
    result = is_building(state.session.project_path)
    output(result, state)


@build_group.command("status")
@handle_error
@click.pass_obj
def build_status_cmd(state: AppState):
    """Check build status (binaries, logs)."""
    from cli_anything.unreal.core.build import build_status

    require_project(state)
    result = build_status(state.session.project_path)
    output(result, state)
