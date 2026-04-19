"""commands/scene.py — Scene/Level actor query commands."""

import click

from cli_anything.unreal.commands import AppState, handle_error, output, require_editor
from cli_anything.unreal.commands._parse_value import parse_property_value


@click.group("scene")
def scene_group():
    """Scene/Level actor queries (requires running editor)."""
    pass


@scene_group.command("list")
@click.option("--class", "actor_class", default=None, help="Filter by class (e.g., StaticMeshActor)")
@click.option("--query", "-q", default=None, help="Filter by name (substring match)")
@handle_error
@click.pass_obj
def scene_list_actors(state: AppState, actor_class, query):
    """List actors in the current level (like the World Outliner).

    \b
    Examples:
        scene list                              # all actors
        scene list --class StaticMeshActor      # filter by class
        scene list -q Light                     # search by name
        scene list --class PointLight -q Fill   # combine filters
    """
    from cli_anything.unreal.core.scene import list_actors

    api = require_editor(state)
    result = list_actors(api, actor_class=actor_class, name_filter=query)

    if not state.json_output:
        actors = result.get("actors", [])
        state.skin.info(f"Found {len(actors)} actors")
        if actors:
            headers = ["Name", "Class", "Path"]
            rows = [[a["name"], a["class"], a.get("path", "")[:60]] for a in actors]
            state.skin.table(headers, rows)
    else:
        output(result, state)


@scene_group.command("property")
@click.argument("actor_path")
@click.argument("expression")
@handle_error
@click.pass_obj
def scene_property(state: AppState, actor_path, expression):
    """Get or set a property on an actor.

    Read:  scene property <path> PropertyName
    Write: scene property <path> PropertyName=NewValue

    \b
    Examples:
        scene property <actor_path> Intensity           # read
        scene property <actor_path> Intensity=5.0       # write
        scene property <actor_path> bHidden=true        # write bool
    """
    from cli_anything.unreal.core.scene import get_actor_property, set_actor_property

    api = require_editor(state)

    if "=" in expression:
        prop_name, raw_value = expression.split("=", 1)
        result = set_actor_property(api, actor_path, prop_name, parse_property_value(raw_value))
    else:
        result = get_actor_property(api, actor_path, expression)

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
