"""Project management commands."""

import click

from cli_anything.unreal.commands import AppError, AppState, handle_error, output, require_project


@click.group("project")
def project_group():
    """Project management commands."""


@project_group.command("info")
@click.option("--project", "proj", type=click.Path(), help="Path to .uproject")
@handle_error
@click.pass_obj
def project_info(state: AppState, proj):
    from cli_anything.unreal.core.project import get_project_info

    path = proj or state.session.project_path
    if not path:
        raise AppError("PROJECT_REQUIRED", "No project specified.", exit_code=2, suggestion="Pass --project <path-to.uproject>.")
    if proj and not state.session.is_loaded:
        state.session.load_project(proj)
    output(get_project_info(path), state)


@project_group.group("config")
def config_group():
    """Read and modify project configuration files."""


@config_group.command("list")
@handle_error
@click.pass_obj
def config_list(state: AppState):
    from cli_anything.unreal.core.project import list_configs

    require_project(state)
    output(list_configs(state.session.project_dir), state)


@config_group.command("get")
@click.argument("config_name")
@click.option("--section", help="Filter by section name")
@handle_error
@click.pass_obj
def config_get(state: AppState, config_name, section):
    """Read CONFIG_NAME (for example Engine or DefaultEngine.ini)."""
    from cli_anything.unreal.core.project import get_config

    require_project(state)
    data = get_config(state.session.project_dir, config_name)
    if section:
        data = {section: data.get(section, {})}
    output(data, state)


@config_group.command("set")
@click.argument("config_name")
@click.argument("section")
@click.argument("key")
@click.argument("value")
@handle_error
@click.pass_obj
def config_set(state: AppState, config_name, section, key, value):
    """Set a value in CONFIG_NAME (for example Engine or DefaultEngine.ini)."""
    from cli_anything.unreal.core.project import set_config

    require_project(state)
    state.session.snapshot(f"config set {config_name} [{section}] {key}")
    output(set_config(state.session.project_dir, config_name, section, key, value), state)


@project_group.command("generate")
@handle_error
@click.pass_obj
def project_generate(state: AppState):
    from cli_anything.unreal.core.build import generate_project_files

    require_project(state)
    output(generate_project_files(state.session.project_path, state.session.engine_root), state)
