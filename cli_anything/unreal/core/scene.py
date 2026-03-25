"""core/scene.py — Scene/Level actor queries.

Provides actor listing, property inspection, and component queries
for the currently open level. Requires a running UE editor with
Remote Control API.

Key Remote Control endpoints used:
  PUT /remote/object/call      — Call functions (GetAllLevelActors, etc.)
  PUT /remote/object/property  — Read actor/component properties
  PUT /remote/object/describe  — List all properties & functions on an object
"""

from typing import Optional

from cli_anything.unreal.utils.ue_http_api import UEEditorAPI


def list_actors(api: UEEditorAPI) -> dict:
    """List all actors in the current level.

    Uses EditorActorSubsystem.GetAllLevelActors via Remote Control.

    Returns:
        {"actors": [{"path": str, "name": str}, ...], "count": int}
    """
    result = api.call_function(
        "/Script/UnrealEd.Default__EditorActorSubsystem",
        "GetAllLevelActors",
    )

    if "error" in result:
        return result

    actor_paths = result.get("ReturnValue", [])

    actors = []
    for path in actor_paths:
        # Path looks like: /Game/Map.Map:PersistentLevel.StaticMeshActor_0
        name = path.rsplit(".", 1)[-1] if "." in path else path
        actors.append({
            "path": path,
            "name": name,
        })

    return {"actors": actors, "count": len(actors)}


def list_actors_of_class(api: UEEditorAPI, actor_class: str) -> dict:
    """List actors of a specific class in the current level.

    Args:
        actor_class: Actor class name (e.g., "StaticMeshActor", "PointLight").

    Returns:
        {"actors": [...]}
    """
    result = api.call_function(
        "/Script/UnrealEd.Default__EditorActorSubsystem",
        "GetAllLevelActorsOfClass",
        {"ActorClass": f"/Script/Engine.{actor_class}"},
    )

    if "error" in result:
        return result

    actor_paths = result.get("ReturnValue", [])
    actors = []
    for path in actor_paths:
        name = path.rsplit(".", 1)[-1] if "." in path else path
        actors.append({"path": path, "name": name})

    return {"actors": actors, "count": len(actors)}


def get_actor_property(api: UEEditorAPI, actor_path: str, property_name: str) -> dict:
    """Get a property value on an actor.

    Args:
        api: Connected UEEditorAPI instance.
        actor_path: Full object path of the actor.
        property_name: Property name to read.

    Returns:
        Property value dict.
    """
    return api.get_property(actor_path, property_name)


def set_actor_property(api: UEEditorAPI, actor_path: str,
                       property_name: str, value) -> dict:
    """Set a property value on an actor.

    Args:
        api: Connected UEEditorAPI instance.
        actor_path: Full object path of the actor.
        property_name: Property name.
        value: New value.

    Returns:
        API response.
    """
    return api.set_property(actor_path, property_name, value)


def describe_actor(api: UEEditorAPI, actor_path: str) -> dict:
    """Describe an actor — list all its properties and functions.

    Args:
        api: Connected UEEditorAPI instance.
        actor_path: Full object path.

    Returns:
        {"Name": str, "Class": str, "Properties": [...], "Functions": [...]}
    """
    return api.describe_object(actor_path)


def find_actor_by_name(api: UEEditorAPI, name: str) -> dict:
    """Find an actor by display name (substring match).

    Args:
        api: Connected UEEditorAPI instance.
        name: Actor name or substring to search for.

    Returns:
        {"actors": [...]} matching actors.
    """
    all_actors = list_actors(api)
    if "error" in all_actors:
        return all_actors

    name_lower = name.lower()
    matches = [
        a for a in all_actors["actors"]
        if name_lower in a["name"].lower()
    ]

    return {"actors": matches, "count": len(matches), "query": name}


def get_actor_components(api: UEEditorAPI, actor_path: str) -> dict:
    """Get an actor's components by reading the component hierarchy.

    Uses describe to find component properties.

    Args:
        api: Connected UEEditorAPI instance.
        actor_path: Full object path.

    Returns:
        {"components": [...]}
    """
    desc = describe_actor(api, actor_path)
    if "error" in desc:
        return desc

    # Find component-type properties
    components = []
    for prop in desc.get("Properties", []):
        prop_type = prop.get("Type", "")
        if "Component" in prop_type:
            components.append({
                "name": prop.get("Name", ""),
                "type": prop_type,
                "description": prop.get("Description", ""),
            })

    return {"components": components, "actor": actor_path}


def get_actor_material(api: UEEditorAPI, actor_path: str,
                       material_index: int = 0) -> dict:
    """Get the material assigned to an actor's mesh component.

    Tries multiple approaches:
    1. GetMaterial(index) on StaticMeshComponent0
    2. Read OverrideMaterials array
    3. GetNumMaterials to know how many slots exist

    Args:
        api: Connected UEEditorAPI instance.
        actor_path: Full object path.
        material_index: Material slot index (default 0).

    Returns:
        Material info dict.
    """
    comp_path = f"{actor_path}.StaticMeshComponent0"

    # Get total number of material slots
    num_result = api.call_function(comp_path, "GetNumMaterials")
    num_materials = num_result.get("ReturnValue", 0)

    # Get the material at the requested index
    mat_result = api.call_function(
        comp_path,
        "GetMaterial",
        {"ElementIndex": material_index},
    )

    material_path = mat_result.get("ReturnValue", "")

    result = {
        "actor": actor_path,
        "component": comp_path,
        "num_materials": num_materials,
        "material_index": material_index,
        "material_path": material_path,
    }

    # If there are multiple materials, get them all
    if num_materials > 1:
        all_materials = []
        for i in range(num_materials):
            m = api.call_function(comp_path, "GetMaterial", {"ElementIndex": i})
            all_materials.append({
                "index": i,
                "path": m.get("ReturnValue", ""),
            })
        result["all_materials"] = all_materials

    # Also try OverrideMaterials
    override = api.get_property(comp_path, "OverrideMaterials")
    if "error" not in override:
        result["override_materials"] = override

    return result


def get_actor_transform(api: UEEditorAPI, actor_path: str) -> dict:
    """Get an actor's world transform (location, rotation, scale).

    Args:
        api: Connected UEEditorAPI instance.
        actor_path: Full object path.

    Returns:
        {"location": {...}, "rotation": {...}, "scale": {...}}
    """
    # Read RootComponent transform properties
    root = f"{actor_path}.DefaultSceneRoot"

    loc = api.get_property(actor_path, "RelativeLocation")
    rot = api.get_property(actor_path, "RelativeRotation")
    scale = api.get_property(actor_path, "RelativeScale3D")

    return {
        "actor": actor_path,
        "location": loc,
        "rotation": rot,
        "scale": scale,
    }
