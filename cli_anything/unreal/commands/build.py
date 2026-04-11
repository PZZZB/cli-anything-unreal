"""commands/build.py — Build system commands."""

import click

from cli_anything.unreal.commands import AppState, handle_error, output, require_project


@click.group("build")
def build_group():
    """Build system — compile, cook, package via UAT/UBT."""
    pass


@build_group.command("compile")
@click.option("--config", "build_config", default="Development",
              type=click.Choice(["Development", "Shipping", "DebugGame", "Test"]))
@click.option("--platform", default="Win64")
@click.option("--timeout", default=3600, help="Timeout in seconds")
@handle_error
@click.pass_obj
def build_compile(state: AppState, build_config, platform, timeout):
    """Compile the project's C++ code."""
    from cli_anything.unreal.core.build import compile_project

    require_project(state)
    state.skin.info(f"Compiling {state.session.project_name} ({build_config} / {platform})...")
    result = compile_project(
        state.session.project_path, build_config, platform,
        state.session.engine_root, timeout,
    )
    output(result, state)


@build_group.command("cook")
@click.option("--platform", default="Win64")
@click.option("--timeout", default=3600, help="Timeout in seconds")
@handle_error
@click.pass_obj
def build_cook(state: AppState, platform, timeout):
    """Cook content assets for the target platform."""
    from cli_anything.unreal.core.build import cook_content

    require_project(state)
    state.skin.info(f"Cooking content for {platform}...")
    result = cook_content(state.session.project_path, platform, state.session.engine_root, timeout)
    output(result, state)


@build_group.command("package")
@click.option("--platform", default="Win64")
@click.option("--config", "build_config", default="Development",
              type=click.Choice(["Development", "Shipping", "DebugGame", "Test"]))
@click.option("--output", "output_dir", type=click.Path(), help="Archive output directory")
@click.option("--timeout", default=7200, help="Timeout in seconds")
@handle_error
@click.pass_obj
def build_package(state: AppState, platform, build_config, output_dir, timeout):
    """Full package pipeline: build + cook + stage + package."""
    from cli_anything.unreal.core.build import package_project

    require_project(state)
    state.skin.info(f"Packaging {state.session.project_name} ({build_config} / {platform})...")
    result = package_project(
        state.session.project_path, platform, build_config,
        output_dir, state.session.engine_root, timeout,
    )
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
