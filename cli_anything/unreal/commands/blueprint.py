"""commands/blueprint.py — Blueprint viewing and editing commands."""

import click

from cli_anything.unreal.commands import AppState, handle_error, output, require_editor


@click.group("blueprint")
def blueprint_group():
    """Blueprint viewing and editing (requires running editor)."""
    pass


@blueprint_group.command("list")
@click.option("--path", "content_path", default="/Game/", help="Content path to search")
@handle_error
@click.pass_obj
def blueprint_list(state: AppState, content_path):
    """List all blueprints in the project."""
    from cli_anything.unreal.core.blueprint import list_blueprints

    api = require_editor(state)
    result = list_blueprints(api, content_path, state.session.project_dir)
    output(result, state)


@blueprint_group.command("info")
@click.argument("blueprint_path")
@handle_error
@click.pass_obj
def blueprint_info(state: AppState, blueprint_path):
    """Show detailed blueprint information (graphs, nodes, variables)."""
    from cli_anything.unreal.core.blueprint import get_blueprint_info

    api = require_editor(state)
    result = get_blueprint_info(api, blueprint_path, state.session.project_dir)
    output(result, state)


@blueprint_group.command("add-function")
@click.argument("blueprint_path")
@click.option("--name", "func_name", required=True, help="Name for the new function graph")
@handle_error
@click.pass_obj
def blueprint_add_function(state: AppState, blueprint_path, func_name):
    """Add a function graph to a blueprint.

    Example: blueprint add-function /Game/BP_Test --name MyFunc
    """
    from cli_anything.unreal.core.blueprint import add_function

    api = require_editor(state)
    result = add_function(api, blueprint_path, func_name,
                          project_dir=state.session.project_dir)
    output(result, state)


@blueprint_group.command("delete-function")
@click.argument("blueprint_path")
@click.option("--name", "func_name", required=True, help="Name of the function graph to remove")
@handle_error
@click.pass_obj
def blueprint_delete_function(state: AppState, blueprint_path, func_name):
    """Remove a function graph from a blueprint.

    Example: blueprint delete-function /Game/BP_Test --name MyFunc
    """
    from cli_anything.unreal.core.blueprint import remove_function

    api = require_editor(state)
    result = remove_function(api, blueprint_path, func_name,
                             project_dir=state.session.project_dir)
    output(result, state)


@blueprint_group.command("add-variable")
@click.argument("blueprint_path")
@click.option("--name", "var_name", required=True, help="Variable name")
@click.option("--type", "var_type", required=True,
              help="Variable type: bool, int, float, string, text, name, vector, rotator, transform")
@handle_error
@click.pass_obj
def blueprint_add_variable(state: AppState, blueprint_path, var_name, var_type):
    """Add a member variable to a blueprint.

    Example: blueprint add-variable /Game/BP_Test --name Health --type float
    """
    from cli_anything.unreal.core.blueprint import add_variable

    api = require_editor(state)
    result = add_variable(api, blueprint_path, var_name, var_type,
                          project_dir=state.session.project_dir)
    output(result, state)


@blueprint_group.command("delete-variable")
@click.argument("blueprint_path")
@click.option("--name", "var_name", required=True, help="Variable name")
@handle_error
@click.pass_obj
def blueprint_delete_variable(state: AppState, blueprint_path, var_name):
    """Delete a member variable from a blueprint.

    Example: blueprint delete-variable /Game/BP_Test --name Health
    """
    from cli_anything.unreal.core.blueprint import remove_variable

    api = require_editor(state)
    result = remove_variable(api, blueprint_path, var_name, project_dir=state.session.project_dir)
    output(result, state)


@blueprint_group.command("delete-unused-variables")
@click.argument("blueprint_path")
@handle_error
@click.pass_obj
def blueprint_delete_unused_variables(state: AppState, blueprint_path):
    """Remove all unused variables from a blueprint.

    Example: blueprint delete-unused-variables /Game/BP_Test
    """
    from cli_anything.unreal.core.blueprint import remove_unused_variables

    api = require_editor(state)
    result = remove_unused_variables(api, blueprint_path,
                                     project_dir=state.session.project_dir)
    output(result, state)


@blueprint_group.command("compile")
@click.argument("blueprint_path")
@handle_error
@click.pass_obj
def blueprint_compile(state: AppState, blueprint_path):
    """Compile a blueprint.

    Example: blueprint compile /Game/BP_Test
    """
    from cli_anything.unreal.core.blueprint import compile_blueprint

    api = require_editor(state)
    result = compile_blueprint(api, blueprint_path,
                               project_dir=state.session.project_dir)
    output(result, state)


@blueprint_group.command("rename-graph")
@click.argument("blueprint_path")
@click.option("--old", "old_name", required=True, help="Current graph name")
@click.option("--new", "new_name", required=True, help="New graph name")
@handle_error
@click.pass_obj
def blueprint_rename_graph(state: AppState, blueprint_path, old_name, new_name):
    """Rename a graph in a blueprint.

    Example: blueprint rename-graph /Game/BP_Test --old OldFunc --new NewFunc
    """
    from cli_anything.unreal.core.blueprint import rename_graph

    api = require_editor(state)
    result = rename_graph(api, blueprint_path, old_name, new_name,
                          project_dir=state.session.project_dir)
    output(result, state)
