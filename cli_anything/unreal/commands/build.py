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
@handle_error
@click.pass_obj
def build_compile(state: AppState, build_config, platform):
    """Compile the project's C++ code."""
    from cli_anything.unreal.core.build import compile_project

    require_project(state)
    state.skin.info(f"Compiling {state.session.project_name} ({build_config} / {platform})...")
    result = compile_project(
        state.session.project_path, build_config, platform,
        state.session.engine_root,
    )
    output(result, state)


@build_group.command("cook")
@click.option("--platform", default="Win64")
@handle_error
@click.pass_obj
def build_cook(state: AppState, platform):
    """Cook content assets for the target platform."""
    from cli_anything.unreal.core.build import cook_content

    require_project(state)
    state.skin.info(f"Cooking content for {platform}...")
    result = cook_content(state.session.project_path, platform, state.session.engine_root)
    output(result, state)


@build_group.command("package")
@click.option("--platform", default="Win64")
@click.option("--config", "build_config", default="Development",
              type=click.Choice(["Development", "Shipping", "DebugGame", "Test"]))
@click.option("--output", "output_dir", type=click.Path(), help="Archive output directory")
@handle_error
@click.pass_obj
def build_package(state: AppState, platform, build_config, output_dir):
    """Full package pipeline: build + cook + stage + package."""
    from cli_anything.unreal.core.build import package_project

    require_project(state)
    state.skin.info(f"Packaging {state.session.project_name} ({build_config} / {platform})...")
    result = package_project(
        state.session.project_path, platform, build_config,
        output_dir, state.session.engine_root,
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
