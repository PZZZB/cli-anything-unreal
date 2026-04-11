"""commands/scene.py — Scene/Level actor query commands."""

import click

from cli_anything.unreal.commands import AppState, handle_error, output, require_editor


@click.group("scene")
def scene_group():
    """Scene/Level actor queries (requires running editor)."""
    pass


@scene_group.command("list")
@click.option("--class", "actor_class", default=None, help="Filter by class (e.g., StaticMeshActor)")
@handle_error
@click.pass_obj
def scene_list_actors(state: AppState, actor_class):
    """List all actors in the current level."""
    from cli_anything.unreal.core.scene import list_actors, list_actors_of_class

    api = require_editor(state)
    if actor_class:
        result = list_actors_of_class(api, actor_class)
    else:
        result = list_actors(api)

    if not state.json_output:
        actors = result.get("actors", [])
        state.skin.info(f"Found {len(actors)} actors")
        if actors:
            headers = ["Name", "Path"]
            rows = [[a["name"], a.get("path", "")[:60]] for a in actors]
            state.skin.table(headers, rows)
    else:
        output(result, state)


@scene_group.command("find")
@click.argument("name")
@handle_error
@click.pass_obj
def scene_find(state: AppState, name):
    """Find actors by name (substring match)."""
    from cli_anything.unreal.core.scene import find_actor_by_name

    api = require_editor(state)
    result = find_actor_by_name(api, name)
    output(result, state)


@scene_group.command("info")
@click.argument("actor_path")
@click.option("--filter", "prop_filter", default=None,
              help="Case-insensitive substring filter for property names.")
@click.option("--property", "prop_name", default=None,
              help="Get full metadata for a specific property/function (legacy C++ mode).")
@handle_error
@click.pass_obj
def scene_info_cmd(state: AppState, actor_path, prop_filter, prop_name):
    """Describe an actor — list properties and methods with Python-safe names.

    Returns snake_case property names and current values that can be used
    directly in Python scripts. Use --filter to search for specific properties.
    Use --property for legacy C++ reflection metadata (PascalCase names).
    """
    if prop_name:
        # Legacy mode: use C++ describe API for full metadata on a single property
        from cli_anything.unreal.core.scene import describe_actor
        api = require_editor(state)
        result = describe_actor(api, actor_path, prop_name)
    else:
        # New mode: Python runtime inspection with snake_case names
        from cli_anything.unreal.core.script_runner import inspect_instance
        api = require_editor(state)
        result = inspect_instance(api, actor_path, mode="actor",
                                  prop_filter=prop_filter)
    output(result, state)


@scene_group.command("get-property")
@click.argument("actor_path")
@click.argument("property_name")
@handle_error
@click.pass_obj
def scene_get_property(state: AppState, actor_path, property_name):
    """Get a property on an actor."""
    from cli_anything.unreal.core.scene import get_actor_property

    api = require_editor(state)
    result = get_actor_property(api, actor_path, property_name)
    output(result, state)


@scene_group.command("set-property")
@click.argument("actor_path")
@click.argument("property_name")
@click.argument("new_value")
@handle_error
@click.pass_obj
def scene_set_property(state: AppState, actor_path, property_name, new_value):
    """Set a property on an actor."""
    from cli_anything.unreal.core.scene import set_actor_property

    api = require_editor(state)
    result = set_actor_property(api, actor_path, property_name, new_value)
    output(result, state)


@scene_group.command("list-components")
@click.argument("actor_path")
@handle_error
@click.pass_obj
def scene_list_components(state: AppState, actor_path):
    """List components on an actor."""
    from cli_anything.unreal.core.scene import get_actor_components

    api = require_editor(state)
    result = get_actor_components(api, actor_path)
    output(result, state)


@scene_group.command("get-material")
@click.argument("actor_path")
@click.option("--index", default=0, help="Material slot index")
@handle_error
@click.pass_obj
def scene_get_material(state: AppState, actor_path, index):
    """Get the material assigned to an actor's mesh."""
    from cli_anything.unreal.core.scene import get_actor_material

    api = require_editor(state)
    result = get_actor_material(api, actor_path, index)
    output(result, state)


@scene_group.command("get-transform")
@click.argument("actor_path")
@handle_error
@click.pass_obj
def scene_get_transform(state: AppState, actor_path):
    """Get an actor's transform (location, rotation, scale)."""
    from cli_anything.unreal.core.scene import get_actor_transform

    api = require_editor(state)
    result = get_actor_transform(api, actor_path)
    output(result, state)
