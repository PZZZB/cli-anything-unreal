"""commands/scene.py — Scene/Level actor query commands."""

import click

from cli_anything.unreal.commands import AppError, AppState, handle_error, output, require_editor
from cli_anything.unreal.commands._parse_value import parse_property_value
from cli_anything.unreal.errors import raise_for_legacy_error


@click.group("scene")
def scene_group():
    """Scene/Level actor queries (requires running editor)."""
    pass


@scene_group.command("list")
@click.option("--class", "actor_class", default=None, help="Filter by class (e.g., StaticMeshActor)")
@click.option("--query", "-q", default=None,
              help="Case-insensitive regex for actor name/label/path (via re.search). "
                   "Plain strings behave as substrings; anchors/alternation also work.")
@click.option("--field", "query_field",
              type=click.Choice(["all", "name", "label", "path"], case_sensitive=False),
              default="all", show_default=True,
              help="Actor field searched by --query.")
@click.option("--exact", is_flag=True,
              help="Treat --query as a case-insensitive whole-field match instead of regex partial match.")
@handle_error
@click.pass_obj
def scene_list_actors(state: AppState, actor_class, query, query_field, exact):
    """List actors in the current level (like the World Outliner).

    \b
    Examples:
        scene list                              # all actors
        scene list --class StaticMeshActor      # filter by class
        scene list -q Light                     # search name/label/path
        scene list -q SM_Env_FmlBush17 --field label --exact
        scene list --class PointLight -q Fill   # combine filters
    """
    from cli_anything.unreal.core.scene import list_actors

    api = require_editor(state)
    result = list_actors(
        api,
        actor_class=actor_class,
        name_filter=query,
        query_field=query_field,
        exact=exact,
    )
    raise_for_legacy_error(result, default_code="SCENE_LIST_FAILED")
    output(result, state)


@scene_group.command("property")
@click.argument("object_path")
@click.argument("expression")
@handle_error
@click.pass_obj
def scene_property(state: AppState, object_path, expression):
    """Get or set a property on any UObject (actor or component).

    Read:  scene property <path> PropertyName
    Write: scene property <path> PropertyName=NewValue

    The <path> can be:
      - an actor path:     .../Map.Map:PersistentLevel.ActorName
      - a component path:  .../Map.Map:PersistentLevel.ActorName.CompName
        (as returned by `editor api-discover <actor>` in components[].path)

    \b
    Examples:
        # Read Tags on actor
        scene property <actor_path> Tags
        # Write Intensity on the DirectionalLightComponent subobject
        scene property <actor_path>.LightComponent0 Intensity=5.0
        # Read instance-painted vertex data (Bridge 1.34+)
        scene property <static_mesh_component_path> LODData[0].PaintedVertices
        # Toggle bHidden on actor
        scene property <actor_path> bHidden=true
    """
    from cli_anything.unreal.core.scene import get_actor_property, set_actor_property

    api = require_editor(state)

    if "=" in expression:
        prop_name, raw_value = expression.split("=", 1)
        result = set_actor_property(api, object_path, prop_name, parse_property_value(raw_value))
        error_code = "SCENE_PROPERTY_WRITE_FAILED"
    else:
        result = get_actor_property(api, object_path, expression)
        error_code = "SCENE_PROPERTY_READ_FAILED"

    if isinstance(result, dict) and result.get("error"):
        raise AppError(
            error_code,
            str(result["error"]),
            exit_code=3,
            details=result,
        )

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
    if isinstance(result, dict) and result.get("error"):
        raise AppError(
            "SCENE_COMPONENT_LIST_FAILED",
            str(result["error"]),
            exit_code=3,
            details=result,
        )
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
    raise_for_legacy_error(result, default_code="SCENE_MATERIAL_FAILED")
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
    if isinstance(result, dict) and result.get("error"):
        raise AppError(
            "SCENE_TRANSFORM_READ_FAILED",
            str(result["error"]),
            exit_code=3,
            details=result,
        )
    output(result, state)
