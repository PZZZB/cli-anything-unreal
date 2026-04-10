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

    Uses a Python script instead of direct Remote Control API property reads,
    as UE 5.x often returns 400 Client Error for RelativeLocation/Rotation
    when accessed directly via the Remote Control property endpoint.

    Args:
        api: Connected UEEditorAPI instance.
        actor_path: Full object path.

    Returns:
        {"location": {...}, "rotation": {...}, "scale": {...}}
    """
    script = f"""
import unreal
actor = unreal.EditorAssetLibrary.load_asset('{actor_path}')
if not actor:
    # It might be in the map, try to find it
    subsystem = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = subsystem.get_all_level_actors()
    for a in actors:
        if a.get_path_name() == '{actor_path}':
            actor = a
            break

if not actor:
    unreal.log_error(f"Actor not found: {actor_path}")
else:
    transform = actor.get_actor_transform()
    loc = transform.translation
    rot = transform.rotation.rotator()
    scale = transform.scale3d
    unreal.log(f"TRANSFORM_DATA:{loc.x},{loc.y},{loc.z}|{rot.pitch},{rot.yaw},{rot.roll}|{scale.x},{scale.y},{scale.z}")
"""
    
    result = {"actor": actor_path}
    
    res = api.exec_python_ex(script)
    for log_item in res.get("LogOutput", []):
        line = log_item.get("Output", "")
        if line.startswith("TRANSFORM_DATA:"):
            try:
                parts = line.split(":", 1)[1].strip().split("|")
                lx, ly, lz = map(float, parts[0].split(","))
                rp, ry, rr = map(float, parts[1].split(","))
                sx, sy, sz = map(float, parts[2].split(","))
                result["location"] = {"X": lx, "Y": ly, "Z": lz}
                result["rotation"] = {"Pitch": rp, "Yaw": ry, "Roll": rr}
                result["scale"] = {"X": sx, "Y": sy, "Z": sz}
                return result
            except Exception as e:
                return {"error": f"Failed to parse transform data: {e}", "raw": line}

    return {"error": "Failed to get transform. Actor might not exist or script failed."}
