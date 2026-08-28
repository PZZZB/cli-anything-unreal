"""core/scene.py — Scene/Level actor queries.

Provides actor listing, property inspection, and component queries
for the currently open level. Requires a running UE editor with
Remote Control API.

Key Remote Control endpoints used:
  PUT /remote/object/call      — Call functions (GetAllLevelActors, etc.)
  PUT /remote/object/property  — Read actor/component properties
  PUT /remote/object/describe  — List all properties & functions on an object
"""

import json
import re
import time


from cli_anything.unreal.utils.ue_http_api import UEEditorAPI


_BRIDGE_CDO = "/Script/CliAnythingBridge.Default__CliAnythingBridgeLibrary"
_STATIC_MESH_LOD_PROPERTY = re.compile(
    r"^LODData\[(\d+)\]\.(OverrideVertexColors|PaintedVertices)$",
    re.IGNORECASE,
)
_POST_PROCESS_WEIGHTED_BLENDABLES_PROPERTY = re.compile(
    r"^Settings\.WeightedBlendables\.Array$",
    re.IGNORECASE,
)


def _get_static_mesh_lod_property(
    api: UEEditorAPI,
    object_path: str,
    property_name: str,
    match: re.Match[str],
) -> dict:
    """Read non-reflected StaticMeshComponent LOD fields via native bridge."""
    lod_index = int(match.group(1))
    field_name = match.group(2)
    canonical_field = (
        "OverrideVertexColors"
        if field_name.casefold() == "overridevertexcolors"
        else "PaintedVertices"
    )
    response = api.call_function(
        _BRIDGE_CDO,
        "GetStaticMeshComponentLODProperty",
        {
            "Component": object_path,
            "LODIndex": lod_index,
            "PropertyName": canonical_field,
        },
        timeout=30,
    )
    raw = response.get("ReturnValue")
    if not isinstance(raw, str):
        return {
            "error": (
                f"Property expression '{property_name}' requires "
                "CliAnythingBridge 1.34 or newer."
            ),
            "object_path": object_path,
            "property": property_name,
            "detail": response.get("error", response),
            "suggestion": "Run 'editor plugin-upgrade', relaunch the editor, then retry.",
        }
    try:
        bridge_result = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "error": f"Native property reader returned invalid JSON: {exc}",
            "object_path": object_path,
            "property": property_name,
        }
    if not isinstance(bridge_result, dict):
        return {
            "error": "Native property reader returned non-object JSON.",
            "object_path": object_path,
            "property": property_name,
        }
    if bridge_result.get("error"):
        bridge_result.setdefault("object_path", object_path)
        bridge_result.setdefault("property", property_name)
        return bridge_result
    if "value" not in bridge_result:
        return {
            "error": "Native property reader response omitted value.",
            "object_path": object_path,
            "property": property_name,
            "detail": bridge_result,
        }
    return {
        property_name: bridge_result["value"],
        "read_via": "native_bridge",
    }


def _get_post_process_weighted_blendables(
    api: UEEditorAPI,
    object_path: str,
    property_name: str,
) -> dict:
    """Read reflected PostProcessVolume blendable entries through UE Python."""
    from cli_anything.unreal.core.script_runner import run_python_code

    script = f'''\
import unreal as _u

_object_path = {object_path!r}
_property_name = {property_name!r}
_object = _u.load_object(None, _object_path)

def _cli_object_path(_value):
    if _value is None:
        return None
    if isinstance(_value, _u.Object):
        return _value.get_path_name()
    return str(_value)

if _object is None:
    result = {{
        "error": "Object not found: " + _object_path,
        "object_path": _object_path,
        "property": _property_name,
    }}
else:
    try:
        _settings = _object.get_editor_property("settings")
        _weighted = _settings.get_editor_property("weighted_blendables")
        _entries = _weighted.get_editor_property("array")
        _value = []
        for _entry in _entries:
            _value.append({{
                "weight": float(_entry.get_editor_property("weight")),
                "object": _cli_object_path(_entry.get_editor_property("object")),
            }})
        result = {{
            _property_name: _value,
            "read_via": "unreal_python",
        }}
    except Exception as _exc:
        result = {{
            "error": "Property '" + _property_name + "' is not readable via Unreal Python.",
            "object_path": _object_path,
            "property": _property_name,
            "detail": str(_exc),
        }}
'''
    return run_python_code(api, script, save=False)


def list_actors(
    api: UEEditorAPI,
    actor_class: str | None = None,
    name_filter: str | None = None,
    query_field: str = "all",
    exact: bool = False,
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
        Optional actor query filter (case-insensitive).
    query_field:
        Field searched by *name_filter*: ``"name"``, ``"label"``, ``"path"``,
        or ``"all"`` for all three.
    exact:
        If True, compare the whole selected field case-insensitively instead
        of treating *name_filter* as a regex partial match.

    Returns
    -------
    dict
        ``{"actors": [{"path": str, "name": str, "label": str, "class": str}, ...], "count": int}``
    """
    from cli_anything.unreal.core.script_runner import run_python_code

    class_repr = repr(actor_class) if actor_class else "None"
    name_repr = repr(name_filter) if name_filter else "None"
    field_repr = repr(query_field or "all")
    exact_repr = repr(bool(exact))

    script = f'''\
import re as _re
import unreal as _u

_actor_class = {class_repr}
_name_filter = {name_repr}
_query_field = {field_repr}
_exact = {exact_repr}
_valid_fields = {{"name", "label", "path", "all"}}
result = None

# Case-insensitive regex for the name filter (re.search — partial match OK).
# Plain strings remain valid (they're degenerate regexes).
_name_pat = None
if _query_field not in _valid_fields:
    result = {{"error": "Invalid --field: " + str(_query_field),
               "field": _query_field,
               "valid_fields": sorted(_valid_fields)}}

if result is None and _name_filter and not _exact:
    try:
        _name_pat = _re.compile(_name_filter, _re.IGNORECASE)
    except _re.error as _e:
        result = {{"error": "Invalid regex for --query: " + str(_e),
                   "query": _name_filter}}
        _name_pat = False  # sentinel — skip the rest

def _cli_actor_label(_actor):
    try:
        return _actor.get_actor_label()
    except Exception:
        return _actor.get_name()

def _cli_all_level_actors():
    _subsystem_class = getattr(_u, "EditorActorSubsystem", None)
    if _subsystem_class is not None:
        return _u.get_editor_subsystem(_subsystem_class).get_all_level_actors()
    return _u.EditorLevelLibrary.get_all_level_actors()

def _actor_row(_actor):
    _name = _actor.get_name()
    _label = _cli_actor_label(_actor)
    _path = _actor.get_path_name()
    return {{
        "path": _path,
        "name": _name,
        "label": _label,
        "class": _actor.__class__.__name__,
    }}

def _values_for_query(_actor):
    _row = _actor_row(_actor)
    if _query_field == "all":
        return [_row["name"], _row["label"], _row["path"]], _row
    return [_row[_query_field]], _row

def _matches_actor(_actor):
    if not _name_filter:
        return True, _actor_row(_actor)
    _values, _row = _values_for_query(_actor)
    if _exact:
        _needle = _name_filter.lower()
        for _value in _values:
            if str(_value).lower() == _needle:
                return True, _row
        return False, _row
    for _value in _values:
        if _name_pat.search(str(_value)):
            return True, _row
    return False, _row

if result is not None:
    pass
elif _actor_class:
    _cls = getattr(_u, _actor_class, None)
    if _cls is None:
        result = {{"error": "Class not found: " + _actor_class}}
    else:
        _world = _u.EditorLevelLibrary.get_editor_world()
        _raw = _u.GameplayStatics.get_all_actors_of_class(_world, _cls)
        _actors = []
        for _a in _raw:
            _matched, _row = _matches_actor(_a)
            if not _matched:
                continue
            _actors.append(_row)
        result = {{"actors": _actors, "count": len(_actors)}}
else:
    _actors = []
    for _a in _cli_all_level_actors():
        _matched, _row = _matches_actor(_a)
        if not _matched:
            continue
        _actors.append(_row)
    result = {{"actors": _actors, "count": len(_actors)}}
'''
    return run_python_code(api, script, save=False)


def list_actors_of_class(api: UEEditorAPI, actor_class: str) -> dict:
    """List actors of a specific class. Wrapper for backwards compat."""
    return list_actors(api, actor_class=actor_class)


def get_actor_property(api: UEEditorAPI, object_path: str, property_name: str) -> dict:
    """Get a property value on any UObject (actor or component subobject).

    Args:
        api: Connected UEEditorAPI instance.
        object_path: Full object path — actor path or component subobject path.
        property_name: Property name to read.

    Returns:
        Property value dict.
    """
    result = api.get_property(object_path, property_name)
    if "not accessible via Remote Control" not in str(result.get("error", "")):
        return result

    lod_match = _STATIC_MESH_LOD_PROPERTY.fullmatch(property_name)
    if lod_match:
        return _get_static_mesh_lod_property(
            api,
            object_path,
            property_name,
            lod_match,
        )

    if _POST_PROCESS_WEIGHTED_BLENDABLES_PROPERTY.fullmatch(property_name):
        return _get_post_process_weighted_blendables(
            api,
            object_path,
            property_name,
        )

    # Remote Control omits some useful reflected component properties,
    # including StaticMesh. Unreal Python can still read those editor-exposed
    # properties safely, so use it as a read-only fallback.
    from cli_anything.unreal.core.script_runner import run_python_code

    script = f'''\
import re as _re
import unreal as _u

_object_path = {object_path!r}
_property_name = {property_name!r}
_object = _u.load_object(None, _object_path)

def _cli_property_name(_name):
    return _re.sub(r"(?<!^)(?=[A-Z])", "_", _name).lower()

def _cli_serialize_property(_value):
    if _value is None or isinstance(_value, (bool, int, float, str)):
        return _value
    if isinstance(_value, _u.Object):
        return _value.get_path_name()
    if isinstance(_value, (list, tuple)):
        return [_cli_serialize_property(_item) for _item in _value]
    if isinstance(_value, dict):
        return {{
            str(_key): _cli_serialize_property(_item)
            for _key, _item in _value.items()
        }}
    return str(_value)

if _object is None:
    result = {{
        "error": "Object not found: " + _object_path,
        "object_path": _object_path,
        "property": _property_name,
    }}
else:
    _candidates = [_property_name]
    _snake_name = _cli_property_name(_property_name)
    if _snake_name not in _candidates:
        _candidates.append(_snake_name)
    _read_errors = []
    _property_value = None
    _property_read = False
    for _candidate in _candidates:
        try:
            _property_value = _object.get_editor_property(_candidate)
            _property_read = True
            break
        except Exception as _exc:
            _read_errors.append({{"name": _candidate, "error": str(_exc)}})
    if _property_read:
        result = {{
            _property_name: _cli_serialize_property(_property_value),
            "read_via": "unreal_python",
        }}
    else:
        result = {{
            "error": "Property '" + _property_name + "' is not readable via Remote Control or Unreal Python.",
            "object_path": _object_path,
            "property": _property_name,
            "attempts": _read_errors,
        }}
'''
    return run_python_code(api, script, save=False)


def set_actor_property(api: UEEditorAPI, object_path: str,
                       property_name: str, value) -> dict:
    """Set a property value on any UObject (actor or component subobject).

    Args:
        api: Connected UEEditorAPI instance.
        object_path: Full object path — actor path or component subobject path.
        property_name: Property name.
        value: New value.

    Returns:
        API response.
    """
    return api.set_property(object_path, property_name, value)


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
    """Get an actor's actual component instances.

    Uses UE Python to enumerate ``Actor.get_components_by_class``. Remote
    Control ``describe`` only exposes reflected properties and can miss native
    default subobjects such as ``StaticMeshComponent0`` on ``StaticMeshActor``.

    Args:
        api: Connected UEEditorAPI instance.
        actor_path: Full object path.

    Returns:
        {"components": [...]}
    """
    from cli_anything.unreal.core.script_runner import run_python_code

    script = f'''\
import unreal as _u

_actor_path = {actor_path!r}
_subsystem_class = getattr(_u, "EditorActorSubsystem", None)
if _subsystem_class is not None:
    _level_actors = _u.get_editor_subsystem(_subsystem_class).get_all_level_actors()
else:
    _level_actors = _u.EditorLevelLibrary.get_all_level_actors()
try:
    _actor = _u.load_object(None, _actor_path)
except Exception:
    _actor = None
if _actor is None:
    for _candidate in _level_actors:
        if _candidate.get_path_name() == _actor_path:
            _actor = _candidate
            break

if _actor is None:
    result = {{"error": "Actor not found: " + _actor_path}}
else:
    _root = None
    for _property_name in ("RootComponent", "root_component"):
        try:
            _root = _actor.get_editor_property(_property_name)
        except Exception:
            continue
        if _root is not None:
            break
    if _root is None:
        _root_getter = getattr(_actor, "get_root_component", None)
        if callable(_root_getter):
            try:
                _root = _root_getter()
            except Exception:
                pass
    _components = []
    for _component in _actor.get_components_by_class(_u.ActorComponent):
        try:
            _class_name = _component.get_class().get_name()
        except Exception:
            _class_name = _component.__class__.__name__
        _components.append({{
            "name": _component.get_name(),
            "type": "U" + _class_name + "*",
            "class": _class_name,
            "path": _component.get_path_name(),
            "is_root": _component == _root,
            "description": "",
        }})
    result = {{"components": _components, "actor": _actor.get_path_name()}}
'''
    return run_python_code(api, script, save=False)


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
    from cli_anything.unreal.core.script_runner import run_python_code

    script = f'''\
import unreal as _u

_actor_path = {actor_path!r}
_subsystem_class = getattr(_u, "EditorActorSubsystem", None)
if _subsystem_class is not None:
    _level_actors = _u.get_editor_subsystem(_subsystem_class).get_all_level_actors()
else:
    _level_actors = _u.EditorLevelLibrary.get_all_level_actors()
try:
    _actor = _u.load_object(None, _actor_path)
except Exception:
    _actor = None
if _actor is None:
    for _candidate in _level_actors:
        if _candidate.get_path_name() == _actor_path:
            _actor = _candidate
            break

if _actor is None:
    result = {{
        "error": "Actor not found: " + _actor_path,
        "actor": _actor_path,
    }}
else:
    try:
        _transform = _actor.get_actor_transform()
        _location = _transform.translation
        _rotation = _transform.rotation.rotator()
        _scale = _transform.scale3d
        result = {{
            "actor": _actor.get_path_name(),
            "location": {{
                "X": _location.x,
                "Y": _location.y,
                "Z": _location.z,
            }},
            "rotation": {{
                "Pitch": _rotation.pitch,
                "Yaw": _rotation.yaw,
                "Roll": _rotation.roll,
            }},
            "scale": {{
                "X": _scale.x,
                "Y": _scale.y,
                "Z": _scale.z,
            }},
        }}
    except Exception as _exc:
        result = {{
            "error": "Failed to read actor transform: " + str(_exc),
            "actor": _actor_path,
        }}
'''
    return run_python_code(api, script, save=False)

_LEVEL_EDITOR_SUBSYSTEM = "/Script/LevelEditor.Default__LevelEditorSubsystem"


def _level_package_path(path: str) -> str:
    base = str(path).strip().split(":", 1)[0]
    leaf = base.rsplit("/", 1)[-1]
    if "." in leaf:
        base = base.rsplit(".", 1)[0]
    return base


def _current_level(api, *, timeout: float = 5.0) -> dict:
    from cli_anything.unreal.core.script_runner import run_python_code

    script = r'''
import unreal
world = unreal.EditorLevelLibrary.get_editor_world()
if world is None:
    result = {"error": "No editor world is active."}
else:
    outermost = world.get_outermost()
    result = {
        "status": "ok",
        "world": world.get_path_name(),
        "package": outermost.get_name() if outermost else "",
        "name": world.get_name(),
    }
'''
    return run_python_code(api, script, timeout=timeout, save=False)


def _open_level_preflight(api, path: str) -> dict:
    """Inspect active and already-loaded Worlds without loading the target."""
    from cli_anything.unreal.core.script_runner import run_python_code

    target_package = _level_package_path(path)
    target_name = target_package.rsplit("/", 1)[-1]
    target_object_path = f"{target_package}.{target_name}"
    script = f'''\
import unreal

_target_package = {target_package!r}
_target_object_path = {target_object_path!r}
_world = unreal.EditorLevelLibrary.get_editor_world()
if _world is None:
    result = {{"error": "No editor world is active."}}
else:
    _outermost = _world.get_outermost()
    _active_world = {{
        "status": "ok",
        "world": _world.get_path_name(),
        "package": _outermost.get_name() if _outermost else "",
        "name": _world.get_name(),
    }}
    _target = unreal.find_object(None, _target_object_path)
    _target_class = _target.get_class().get_name() if _target is not None else None
    result = {{
        "status": "ok",
        "target_package": _target_package,
        "target_object_path": _target_object_path,
        "target_loaded": _target is not None,
        "target_class": _target_class,
        "target_world_loaded": _target_class == "World",
        "active_world": _active_world,
    }}
    _target = None
    _world = None
'''
    return run_python_code(api, script, save=False)


def _verify_current_level(api, expected_path: str, *, verify_timeout: float = 5.0) -> dict:
    expected_package = _level_package_path(expected_path)
    deadline = time.monotonic() + max(0.0, float(verify_timeout))
    last = None
    while True:
        current = _current_level(api)
        last = current
        if current.get("package") == expected_package:
            return {"status": "ok", "expected_package": expected_package, "active_world": current}
        if time.monotonic() >= deadline:
            break
        time.sleep(0.25)
    return {
        "status": "failed",
        "error": "Active editor world did not match requested level.",
        "expected_package": expected_package,
        "active_world": last,
    }


def _level_transition_recovered(api, path: str, original_error: dict, *, verify_timeout: float) -> dict | None:
    verification = _verify_current_level(api, path, verify_timeout=verify_timeout)
    if verification.get("status") == "ok":
        return {
            "status": "ok",
            "success": True,
            "path": path,
            "active_world": verification.get("active_world"),
            "recovered_after_disconnect": True,
            "transition_error": original_error,
        }
    return {
        "status": "failed",
        "success": False,
        "path": path,
        "error": original_error.get("error", "Level transition failed."),
        "recovery_attempted": True,
        "active_world_verification": verification,
        "transition_error": original_error,
    }


def new_level(api, path: str, template: str | None = None, *, verify_timeout: float = 5.0) -> dict:
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
        recovered = _level_transition_recovered(api, path, result, verify_timeout=verify_timeout)
        if recovered:
            return recovered
        return result

    success = result.get("ReturnValue", False)
    if not success:
        return {"status": "failed", "success": False, "path": path}

    verification = _verify_current_level(api, path, verify_timeout=verify_timeout)
    if verification.get("status") != "ok":
        return {
            "status": "failed",
            "success": False,
            "path": path,
            **verification,
        }
    return {
        "status": "ok",
        "success": True,
        "path": path,
        "active_world": verification.get("active_world"),
    }


def open_level(api, path: str, *, verify_timeout: float = 5.0) -> dict:
    """Open an existing level via LevelEditorSubsystem.LoadLevel.

    This avoids running world-transition APIs from PythonScriptPlugin, which
    can retain references across map loads and crash unattended editor sessions.
    A loaded, non-active target World is rejected before dispatch because
    ``LoadLevel`` can fatally fail while collecting that package.
    """
    target_package = _level_package_path(path)
    preflight = _open_level_preflight(api, path)
    if preflight.get("error"):
        return {
            "status": "failed",
            "success": False,
            "code": "EDITOR_OPEN_LEVEL_SAFETY_CHECK_FAILED",
            "path": path,
            "error": "Could not verify that the level transition is safe before dispatch.",
            "dispatch_state": "not_started",
            "safety_check": preflight,
            "suggestion": "Run editor status and retry only after the editor is responsive.",
        }

    active_world = preflight.get("active_world") or {}
    if active_world.get("package") == target_package:
        return {
            "status": "ok",
            "success": True,
            "path": path,
            "active_world": active_world,
            "already_active": True,
            "dispatch_state": "skipped_already_active",
        }

    if preflight.get("target_world_loaded"):
        return {
            "status": "failed",
            "success": False,
            "code": "EDITOR_OPEN_LEVEL_UNSAFE_LOADED_WORLD",
            "path": path,
            "error": (
                "Target World is already loaded outside the active editor world; "
                "in-process LoadLevel can fatally fail during world garbage collection."
            ),
            "failure_kind": "unsafe_loaded_world_transition",
            "dispatch_state": "blocked_unsafe",
            "active_world": active_world,
            "target_world": {
                "package": preflight.get("target_package"),
                "object_path": preflight.get("target_object_path"),
                "class": preflight.get("target_class"),
                "loaded": True,
            },
            "safe_workflow": [
                "ue-cli --project <Project.uproject> editor close",
                f"ue-cli --project <Project.uproject> editor launch --map {target_package}",
            ],
            "suggestion": (
                "Close the current editor without loading the target, then start a fresh editor "
                f"directly on {target_package} with editor launch --map."
            ),
        }

    result = api.call_function(
        _LEVEL_EDITOR_SUBSYSTEM,
        "LoadLevel",
        {"AssetPath": path},
    )

    if "error" in result:
        recovered = _level_transition_recovered(api, path, result, verify_timeout=verify_timeout)
        if recovered:
            return recovered
        return result

    success = result.get("ReturnValue", False)
    if not success:
        return {"status": "failed", "success": False, "path": path}

    verification = _verify_current_level(api, path, verify_timeout=verify_timeout)
    if verification.get("status") != "ok":
        return {
            "status": "failed",
            "success": False,
            "path": path,
            **verification,
        }
    return {
        "status": "ok",
        "success": True,
        "path": path,
        "active_world": verification.get("active_world"),
    }


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
