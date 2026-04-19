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


def list_actors(
    api: UEEditorAPI,
    actor_class: str | None = None,
    name_filter: str | None = None,
) -> dict:
    """List actors in the current level with optional filtering.

    Uses ``EditorActorSubsystem.get_all_level_actors()`` for unfiltered listing,
    or ``GameplayStatics.get_all_actors_of_class()`` when a class filter is
    provided (more efficient — filtering happens engine-side).

    Parameters
    ----------
    api:
        Connected :class:`UEEditorAPI` instance.
    actor_class:
        Optional class name to filter by (e.g., ``"StaticMeshActor"``).
    name_filter:
        Optional name substring filter (case-insensitive).

    Returns
    -------
    dict
        ``{"actors": [{"path": str, "name": str, "class": str}, ...], "count": int}``
    """
    from cli_anything.unreal.core.script_runner import run_python_code

    class_repr = repr(actor_class) if actor_class else "None"
    name_repr = repr(name_filter) if name_filter else "None"

    script = f'''\
import unreal as _u

_actor_class = {class_repr}
_name_filter = {name_repr}

if _actor_class:
    _cls = getattr(_u, _actor_class, None)
    if _cls is None:
        result = {{"error": "Class not found: " + _actor_class}}
    else:
        _world = _u.EditorLevelLibrary.get_editor_world()
        _raw = _u.GameplayStatics.get_all_actors_of_class(_world, _cls)
        _actors = []
        for _a in _raw:
            _name = _a.get_name()
            if _name_filter and _name_filter.lower() not in _name.lower():
                continue
            _actors.append({{
                "path": _a.get_path_name(),
                "name": _name,
                "class": _a.__class__.__name__,
            }})
        result = {{"actors": _actors, "count": len(_actors)}}
else:
    _sub = _u.get_editor_subsystem(_u.EditorActorSubsystem)
    _actors = []
    for _a in _sub.get_all_level_actors():
        _name = _a.get_name()
        if _name_filter and _name_filter.lower() not in _name.lower():
            continue
        _actors.append({{
            "path": _a.get_path_name(),
            "name": _name,
            "class": _a.__class__.__name__,
        }})
    result = {{"actors": _actors, "count": len(_actors)}}
'''
    return run_python_code(api, script)


def list_actors_of_class(api: UEEditorAPI, actor_class: str) -> dict:
    """List actors of a specific class. Wrapper for backwards compat."""
    return list_actors(api, actor_class=actor_class)


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


def find_actor_by_name(api: UEEditorAPI, name: str) -> dict:
    """Find an actor by display name (substring match).

    Equivalent to ``list_actors(name_filter=name)``. Kept for backwards
    compatibility — prefer ``scene list -q`` in new code.
    """
    result = list_actors(api, name_filter=name)
    if "error" not in result:
        result["query"] = name
    return result


def get_actor_components(api: UEEditorAPI, actor_path: str) -> dict:
    """Get an actor's components by reading the component hierarchy.

    Uses describe to find component properties.

    Args:
        api: Connected UEEditorAPI instance.
        actor_path: Full object path.

    Returns:
        {"components": [...]}
    """
    raw_data = api.describe_object(actor_path)
    if "error" in raw_data:
        return raw_data

    # Find component-type properties
    components = []
    for prop in raw_data.get("Properties", []):
        prop_type = prop.get("Type", "") if isinstance(prop, dict) else ""
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
    unreal.log_error(f"Actor not found: {{'{actor_path}'}}")
else:
    transform = actor.get_actor_transform()
    loc = transform.translation
    rot = transform.rotation.rotator()
    scale = transform.scale3d
    unreal.log(f"TRANSFORM_DATA:{{loc.x}},{{loc.y}},{{loc.z}}|{{rot.pitch}},{{rot.yaw}},{{rot.roll}}|{{scale.x}},{{scale.y}},{{scale.z}}")
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

_LEVEL_EDITOR_SUBSYSTEM = "/Script/LevelEditor.Default__LevelEditorSubsystem"


def new_level(api, path: str, template: str | None = None) -> dict:
    """Create and open a new level via Remote Control.

    Uses ``LevelEditorSubsystem.NewLevel`` via ``call_function`` on the
    game thread.

    **Known limitation:** If Python scripts that reference world objects
    (scene list, api-discover with actor paths, run-script with actors, etc.)
    were executed in this session, PythonScriptPlugin retains C++ references
    that prevent the old world from being GC'd, causing a ``World Memory
    Leaks`` assert crash in ``-unattended`` mode.  Workaround: relaunch
    the editor with ``editor launch`` before creating a new level.
    """
    # Pre-check: if level asset already exists, refuse (avoids modal dialog)
    if api.does_asset_exist(path):
        return {
            "error": f"Level already exists: {path}",
            "hint": "Use a different path, or delete the existing level first with: asset delete " + path,
        }

    if template:
        result = api.call_function(
            _LEVEL_EDITOR_SUBSYSTEM,
            "NewLevelFromTemplate",
            {"AssetPath": path, "TemplateAssetPath": template},
        )
    else:
        result = api.call_function(
            _LEVEL_EDITOR_SUBSYSTEM,
            "NewLevel",
            {"AssetPath": path},
        )

    if "error" in result:
        return result

    success = result.get("ReturnValue", False)
    return {"status": "ok" if success else "failed", "success": success, "path": path}


def save_level(api) -> dict:
    """Save the current level via Remote Control call_function.

    Uses ``LevelEditorSubsystem.SaveCurrentLevel`` on the game thread.
    Save does not cause world teardown, so direct call_function is safe.
    """
    result = api.call_function(
        _LEVEL_EDITOR_SUBSYSTEM,
        "SaveCurrentLevel",
        {},
    )

    if "error" in result:
        return result

    success = result.get("ReturnValue", False)
    return {"status": "ok" if success else "failed", "success": success}
