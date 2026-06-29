"""UMG Widget Blueprint authoring helpers."""

from __future__ import annotations

import json

from cli_anything.unreal.utils.ue_http_api import UEEditorAPI


_BRIDGE_CHECK = """
def _cli_bridge():
    if not hasattr(unreal, "CliAnythingBridgeLibrary"):
        return None, {"error": "CliAnythingBridgeLibrary is not loaded.", "suggestion": "Run editor plugin-upgrade, then relaunch the editor."}
    bridge = unreal.CliAnythingBridgeLibrary
    required = ("set_widget_blueprint_root", "add_widget_to_canvas", "get_widget_blueprint_tree")
    missing = [name for name in required if not hasattr(bridge, name)]
    if missing:
        return None, {"error": "CliAnythingBridgeLibrary is too old for UMG authoring.", "missing": missing, "suggestion": "Run editor plugin-upgrade, then relaunch the editor."}
    return bridge, None


def _cli_parse_bridge(raw):
    try:
        return json.loads(raw or "{}")
    except Exception as exc:
        return {"error": "Bridge returned invalid JSON: " + str(exc), "raw": str(raw)}
"""


_WIDGET_BLUEPRINT_RESOLVER = """
def _cli_candidate_package_name(candidate):
    package_name = str(candidate).split(":", 1)[0]
    leaf = package_name.rsplit("/", 1)[-1]
    if "." in leaf:
        package_name = package_name.rsplit(".", 1)[0]
    return package_name


def _cli_load_widget_blueprint(asset_candidates):
    tried = []

    def _try_load(candidate):
        if not candidate or candidate in tried:
            return None, None
        tried.append(candidate)
        try:
            bp = unreal.EditorAssetLibrary.load_asset(candidate)
            if bp is not None:
                return bp, candidate
        except Exception:
            pass
        return None, None

    for candidate in asset_candidates:
        bp, loaded_path = _try_load(candidate)
        if bp is not None:
            return bp, loaded_path, tried

    try:
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        for candidate in asset_candidates:
            package_name = _cli_candidate_package_name(candidate)
            for data in registry.get_assets_by_package_name(package_name, False):
                try:
                    if str(data.asset_class_path.asset_name) != "WidgetBlueprint":
                        continue
                    object_path = str(data.package_name) + "." + str(data.asset_name)
                    if object_path not in tried:
                        tried.append(object_path)
                    bp = data.get_asset()
                    if bp is not None:
                        return bp, object_path, tried
                except Exception:
                    pass
    except Exception:
        pass

    return None, None, tried
"""


def _json(value) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    return json.dumps(value, ensure_ascii=False)


def _widget_asset_path_candidates(widget_path: str) -> list[str]:
    """Return loadable WidgetBlueprint asset paths for common UE object path forms."""
    base_path = str(widget_path).strip().split(":", 1)[0]
    if not base_path:
        return [base_path]

    candidates: list[str] = []

    def add(path: str) -> None:
        if path and path not in candidates:
            candidates.append(path)

    leaf = base_path.rsplit("/", 1)[-1]
    if "." not in leaf:
        add(base_path)
        add(base_path + "." + leaf)
        return candidates

    package_path, object_name = base_path.rsplit(".", 1)
    if object_name.endswith("_C"):
        object_name = object_name[:-2]
        add(package_path + "." + object_name)
    else:
        add(base_path)
    add(package_path)
    return candidates


def create_widget_blueprint(
    api: UEEditorAPI,
    widget_path: str,
    *,
    root_class: str = "CanvasPanel",
    root_name: str = "RootCanvas",
    force: bool = False,
    variable: bool = False,
    project_dir: str | None = None,
    timeout: float = 60.0,
) -> dict:
    """Create a Widget Blueprint with a CanvasPanel root by default."""
    script = f"""
import json
import unreal

asset_path = {_json(widget_path)}
root_class = {_json(root_class)}
root_name = {_json(root_name)}
force = {_json(force)}
variable = {_json(variable)}

{_BRIDGE_CHECK}

bridge, bridge_error = _cli_bridge()
if bridge_error:
    result = bridge_error
elif not asset_path.startswith("/Game/") or "." in asset_path.rsplit("/", 1)[-1]:
    result = {{"error": "Widget path must be a package path like /Game/UI/WBP_Hud."}}
else:
    EAL = unreal.EditorAssetLibrary
    if EAL.does_asset_exist(asset_path):
        if not force:
            result = {{"error": "Asset already exists: " + asset_path, "suggestion": "Pass --force to replace it."}}
        elif not EAL.delete_asset(asset_path):
            result = {{"error": "Failed to delete existing asset: " + asset_path}}
        else:
            unreal.SystemLibrary.collect_garbage()
            result = None
    else:
        result = None

    if result is None:
        package_path, asset_name = asset_path.rsplit("/", 1)
        try:
            EAL.make_directory(package_path)
        except Exception:
            pass
        factory = unreal.WidgetBlueprintFactory()
        factory.set_editor_property("parent_class", unreal.UserWidget)
        bp = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            asset_name, package_path, unreal.WidgetBlueprint, factory
        )
        if not bp:
            result = {{"error": "Failed to create WidgetBlueprint: " + asset_path}}
        else:
            result = _cli_parse_bridge(
                bridge.set_widget_blueprint_root(bp, root_class, root_name, variable)
            )
            if result.get("status") == "ok":
                result["action"] = "create"
                result["widget"] = asset_path
                unreal.BlueprintEditorLibrary.compile_blueprint(bp)
                EAL.save_asset(asset_path, only_if_is_dirty=False)
"""
    return _exec_umg_script(api, script, project_dir=project_dir, timeout=timeout)


def add_widget_to_canvas(
    api: UEEditorAPI,
    widget_path: str,
    *,
    widget_type: str,
    widget_name: str,
    parent: str | None = None,
    text: str | None = None,
    x: float = 0.0,
    y: float = 0.0,
    width: float = -1.0,
    height: float = -1.0,
    z_order: int = 0,
    variable: bool = False,
    project_dir: str | None = None,
    timeout: float = 60.0,
) -> dict:
    """Add a child widget to a CanvasPanel in a Widget Blueprint."""
    script = f"""
import json
import unreal

asset_path = {_json(widget_path)}
asset_candidates = {_json(_widget_asset_path_candidates(widget_path))}
widget_type = {_json(widget_type)}
widget_name = {_json(widget_name)}
parent = {_json(parent or "")}
text = {_json(text or "")}
x = float({_json(x)})
y = float({_json(y)})
width = float({_json(width)})
height = float({_json(height)})
z_order = int({_json(z_order)})
variable = {_json(variable)}

{_WIDGET_BLUEPRINT_RESOLVER}

{_BRIDGE_CHECK}

bridge, bridge_error = _cli_bridge()
if bridge_error:
    result = bridge_error
else:
    bp, loaded_asset_path, tried_asset_paths = _cli_load_widget_blueprint(asset_candidates)
    if not bp:
        result = {{"error": "WidgetBlueprint not found: " + asset_path, "tried": tried_asset_paths}}
    else:
        result = _cli_parse_bridge(
            bridge.add_widget_to_canvas(
                bp, widget_type, widget_name, parent, variable,
                x, y, width, height, z_order, text
            )
        )
        if result.get("status") == "ok":
            unreal.BlueprintEditorLibrary.compile_blueprint(bp)
            unreal.EditorAssetLibrary.save_asset(loaded_asset_path, only_if_is_dirty=False)
"""
    return _exec_umg_script(api, script, project_dir=project_dir, timeout=timeout)


def set_widget_image(
    api: UEEditorAPI,
    widget_path: str,
    *,
    widget_name: str,
    texture_path: str | None = None,
    image_size: tuple[float, float] | list[float] | None = None,
    x: float | None = None,
    y: float | None = None,
    width: float | None = None,
    height: float | None = None,
    z_order: int | None = None,
    project_dir: str | None = None,
    timeout: float = 60.0,
) -> dict:
    """Edit an existing UMG Image widget brush resource, Brush ImageSize, and CanvasPanelSlot layout."""
    set_resource = bool(texture_path)
    set_brush_image_size = image_size is not None
    image_width = float(image_size[0]) if image_size is not None else 0.0
    image_height = float(image_size[1]) if image_size is not None else 0.0
    set_position = x is not None or y is not None
    set_size = width is not None or height is not None
    set_z_order = z_order is not None
    script = f"""
import json
import unreal

asset_path = {_json(widget_path)}
asset_candidates = {_json(_widget_asset_path_candidates(widget_path))}
widget_name = {_json(widget_name)}
texture_path = {_json(texture_path or "")}
set_resource = {_json(set_resource)}
set_brush_image_size = {_json(set_brush_image_size)}
image_width = float({_json(image_width)})
image_height = float({_json(image_height)})
set_position = {_json(set_position)}
x = float({_json(0.0 if x is None else x)})
y = float({_json(0.0 if y is None else y)})
set_size = {_json(set_size)}
width = float({_json(-1.0 if width is None else width)})
height = float({_json(-1.0 if height is None else height)})
set_z_order = {_json(set_z_order)}
z_order = int({_json(0 if z_order is None else z_order)})

{_WIDGET_BLUEPRINT_RESOLVER}

{_BRIDGE_CHECK}

def _cli_load_object(path):
    if not path:
        return None, None, []
    tried = []
    base = str(path).strip().split(":", 1)[0]
    leaf = base.rsplit("/", 1)[-1]
    candidates = [base] if "." in leaf else [base, base + "." + leaf]
    for candidate in candidates:
        if not candidate or candidate in tried:
            continue
        tried.append(candidate)
        obj = None
        try:
            obj = unreal.EditorAssetLibrary.load_asset(candidate)
        except Exception:
            obj = None
        if obj is None:
            try:
                obj = unreal.load_object(None, candidate)
            except Exception:
                obj = None
        if obj is not None:
            return obj, candidate, tried
    return None, None, tried

bridge, bridge_error = _cli_bridge()
if bridge_error:
    result = bridge_error
elif not hasattr(bridge, "set_widget_image_properties"):
    result = {{"error": "CliAnythingBridgeLibrary is too old for UMG Image editing.", "missing": ["set_widget_image_properties"], "suggestion": "Run editor plugin-upgrade, then relaunch the editor."}}
else:
    bp, loaded_asset_path, tried_asset_paths = _cli_load_widget_blueprint(asset_candidates)
    if not bp:
        result = {{"error": "WidgetBlueprint not found: " + asset_path, "tried": tried_asset_paths}}
    else:
        resource = None
        resource_path = ""
        if set_resource:
            resource, resource_path, resource_tried = _cli_load_object(texture_path)
            if resource is None:
                result = {{"error": "Brush resource not found: " + texture_path, "tried": resource_tried}}
            else:
                result = None
        else:
            result = None
        if result is None:
            call_args = [
                bp, widget_name, resource, set_resource,
                set_position, x, y, set_size, width, height, set_z_order, z_order,
            ]
            try:
                if set_brush_image_size:
                    raw = bridge.set_widget_image_properties(*(call_args + [set_brush_image_size, image_width, image_height]))
                else:
                    try:
                        raw = bridge.set_widget_image_properties(*(call_args + [False, 0.0, 0.0]))
                    except TypeError:
                        raw = bridge.set_widget_image_properties(*call_args)
                result = _cli_parse_bridge(raw)
            except TypeError as exc:
                if set_brush_image_size:
                    result = {{"error": "CliAnythingBridgeLibrary is too old for UMG ImageSize editing.", "missing": ["set_widget_image_properties(image_size)"], "suggestion": "Run editor plugin-upgrade, then relaunch the editor.", "detail": str(exc)}}
                else:
                    raise
            if result.get("status") == "ok":
                result["widget_blueprint"] = loaded_asset_path
                unreal.BlueprintEditorLibrary.compile_blueprint(bp)
                unreal.EditorAssetLibrary.save_asset(loaded_asset_path, only_if_is_dirty=False)
"""
    return _exec_umg_script(api, script, project_dir=project_dir, timeout=timeout)


def get_widget_tree(
    api: UEEditorAPI,
    widget_path: str,
    *,
    project_dir: str | None = None,
    timeout: float = 60.0,
) -> dict:
    """Return design-time UMG widget tree info."""
    script = f"""
import json
import unreal

asset_path = {_json(widget_path)}
asset_candidates = {_json(_widget_asset_path_candidates(widget_path))}

{_WIDGET_BLUEPRINT_RESOLVER}

{_BRIDGE_CHECK}

bridge, bridge_error = _cli_bridge()
if bridge_error:
    result = bridge_error
else:
    bp, loaded_asset_path, tried_asset_paths = _cli_load_widget_blueprint(asset_candidates)
    if not bp:
        result = {{"error": "WidgetBlueprint not found: " + asset_path, "tried": tried_asset_paths}}
    else:
        result = _cli_parse_bridge(bridge.get_widget_blueprint_tree(bp))
        if result.get("status") == "ok":
            result["widget"] = loaded_asset_path
"""
    return _exec_umg_script(api, script, project_dir=project_dir, timeout=timeout)


def get_live_widget_tree(
    api: UEEditorAPI,
    target: str,
    *,
    limit: int = 20,
    project_dir: str | None = None,
    timeout: float = 60.0,
) -> dict:
    """Inspect live UUserWidget instances and their child widgets at runtime."""
    safe_limit = max(1, int(limit))
    script = f"""
import json
import unreal

target = {_json(target)}
target_lower = str(target).lower()
limit = int({_json(safe_limit)})


def _safe_str(value):
    try:
        return str(value)
    except Exception:
        return ""


def _call(obj, name, *args):
    try:
        fn = getattr(obj, name, None)
        if callable(fn):
            return fn(*args)
    except Exception:
        return None
    return None


def _editor_prop(obj, *names):
    for name in names:
        try:
            return obj.get_editor_property(name)
        except Exception:
            pass
        try:
            return getattr(obj, name)
        except Exception:
            pass
    return None


def _name(obj):
    return _safe_str(_call(obj, "get_name") or getattr(obj, "name", ""))


def _path(obj):
    return _safe_str(_call(obj, "get_path_name"))


def _class_obj(obj):
    return _call(obj, "get_class")


def _class_name(obj):
    cls = _class_obj(obj)
    if cls is None:
        return ""
    return _safe_str(_call(cls, "get_name") or cls)


def _class_path(obj):
    cls = _class_obj(obj)
    return _path(cls) if cls is not None else ""


def _vec2(value):
    if value is None:
        return None
    for x_name, y_name in (("x", "y"), ("X", "Y")):
        try:
            return [float(getattr(value, x_name)), float(getattr(value, y_name))]
        except Exception:
            pass
    try:
        if len(value) >= 2:
            return [float(value[0]), float(value[1])]
    except Exception:
        pass
    return None


def _anchors(value):
    if value is None:
        return None
    minimum = _vec2(getattr(value, "minimum", None) or getattr(value, "Minimum", None))
    maximum = _vec2(getattr(value, "maximum", None) or getattr(value, "Maximum", None))
    if minimum is None and maximum is None:
        return None
    return {{"minimum": minimum, "maximum": maximum}}


def _is_child_of(obj, unreal_class):
    if obj is None or unreal_class is None:
        return False
    try:
        cls = _class_obj(obj)
        parent = unreal_class.static_class()
        return bool(cls and cls.is_child_of(parent))
    except Exception:
        return False


def _iter_objects(unreal_class=None):
    if unreal_class is not None:
        try:
            return list(unreal.ObjectIterator(unreal_class))
        except Exception:
            pass
    try:
        return list(unreal.ObjectIterator())
    except Exception:
        return []


def _matches_target(obj):
    if not target_lower:
        return True
    texts = [_name(obj), _path(obj), _class_name(obj), _class_path(obj)]
    for text in texts:
        if target_lower in _safe_str(text).lower():
            return True
    return False


def _outer_chain_contains(obj, wanted):
    cur = obj
    for _idx in range(64):
        cur = _call(cur, "get_outer")
        if cur is None:
            return False
        if cur == wanted:
            return True
    return False


def _belongs_to_instance(widget, instance, instance_path):
    if widget == instance:
        return False
    widget_path = _path(widget)
    if instance_path and (
        widget_path.startswith(instance_path + ".")
        or widget_path.startswith(instance_path + ":")
        or widget_path.startswith(instance_path + "/")
    ):
        return True
    return _outer_chain_contains(widget, instance)


def _slot_info(widget):
    slot = _editor_prop(widget, "slot", "Slot")
    if slot is None:
        slot = _call(widget, "get_slot")
    if slot is None:
        return None
    info = {{"type": _class_name(slot), "path": _path(slot)}}
    if "CanvasPanelSlot" in info["type"]:
        position = _vec2(_call(slot, "get_position"))
        size = _vec2(_call(slot, "get_size"))
        alignment = _vec2(_call(slot, "get_alignment"))
        anchors = _anchors(_call(slot, "get_anchors"))
        if position is not None:
            info["position"] = position
        if size is not None:
            info["size"] = size
        if alignment is not None:
            info["alignment"] = alignment
        if anchors is not None:
            info["anchors"] = anchors
        z_order = _call(slot, "get_z_order")
        if z_order is not None:
            try:
                info["z_order"] = int(z_order)
            except Exception:
                info["z_order"] = _safe_str(z_order)
        auto_size = _call(slot, "get_auto_size")
        if auto_size is not None:
            info["auto_size"] = bool(auto_size)
    return info


def _geometry_info(widget):
    geometry = _call(widget, "get_cached_geometry")
    if geometry is None:
        return None
    info = {{}}
    local_size = _vec2(_call(geometry, "get_local_size"))
    absolute_size = _vec2(_call(geometry, "get_absolute_size"))
    absolute_position = _vec2(_call(geometry, "get_absolute_position"))
    if local_size is not None:
        info["local_size"] = local_size
    if absolute_size is not None:
        info["absolute_size"] = absolute_size
    if absolute_position is not None:
        info["absolute_position"] = absolute_position
    return info or None


def _brush_info(widget):
    if "Image" not in _class_name(widget):
        return None
    brush = _call(widget, "get_brush")
    if brush is None:
        brush = _editor_prop(widget, "brush", "Brush")
    if brush is None:
        return None
    info = {{}}
    resource = _call(brush, "get_resource_object") or _editor_prop(brush, "resource_object", "ResourceObject")
    if resource is not None:
        info["resource"] = _path(resource) or _name(resource)
        info["resource_class"] = _class_name(resource)
    image_size = _vec2(_call(brush, "get_image_size") or _editor_prop(brush, "image_size", "ImageSize"))
    if image_size is not None:
        info["image_size"] = image_size
    draw_as = _editor_prop(brush, "draw_as", "DrawAs")
    if draw_as is not None:
        info["draw_as"] = _safe_str(draw_as)
    return info or None


def _widget_info(widget):
    parent = _call(widget, "get_parent")
    info = {{
        "name": _name(widget),
        "path": _path(widget),
        "class": _class_name(widget),
    }}
    if parent is not None:
        info["parent"] = {{"name": _name(parent), "path": _path(parent), "class": _class_name(parent)}}
    slot = _slot_info(widget)
    if slot is not None:
        info["slot"] = slot
    geometry = _geometry_info(widget)
    if geometry is not None:
        info["cached_geometry"] = geometry
    brush = _brush_info(widget)
    if brush is not None:
        info["brush"] = brush
    desired_size = _vec2(_call(widget, "get_desired_size"))
    if desired_size is not None:
        info["desired_size"] = desired_size
    visibility = _call(widget, "get_visibility")
    if visibility is not None:
        info["visibility"] = _safe_str(visibility)
    child_count = _call(widget, "get_children_count")
    if child_count is not None:
        try:
            info["children_count"] = int(child_count)
        except Exception:
            pass
    return info


user_widget_class = getattr(unreal, "UserWidget", None)
widget_class = getattr(unreal, "Widget", None)

instances = []
for obj in _iter_objects(user_widget_class):
    if user_widget_class is not None and not _is_child_of(obj, user_widget_class):
        continue
    if not _matches_target(obj):
        continue
    instances.append(obj)
    if len(instances) >= limit:
        break

all_widgets = []
for widget in _iter_objects(widget_class):
    if widget_class is not None and not _is_child_of(widget, widget_class):
        continue
    all_widgets.append(widget)

out_instances = []
for instance in instances:
    instance_path = _path(instance)
    widgets = []
    for widget in all_widgets:
        if _belongs_to_instance(widget, instance, instance_path):
            widgets.append(_widget_info(widget))
    widget_paths = set([item.get("path") for item in widgets if item.get("path")])
    root_widgets = []
    for item in widgets:
        parent_path = (item.get("parent") or {{}}).get("path")
        if not parent_path or parent_path not in widget_paths:
            root_widgets.append(item.get("name"))
    out_instances.append({{
        "name": _name(instance),
        "path": instance_path,
        "class": _class_name(instance),
        "class_path": _class_path(instance),
        "widget_count": len(widgets),
        "root_widgets": root_widgets,
        "widgets": widgets,
    }})

if not out_instances:
    result = {{
        "error": "Live UserWidget not found: " + str(target),
        "target": target,
        "suggestion": "Run PIE or open the UI so live UUserWidget instances exist, then pass an instance name/path or generated class name.",
    }}
else:
    result = {{
        "status": "ok",
        "target": target,
        "count": len(out_instances),
        "instances": out_instances,
    }}
"""
    return _exec_umg_script(api, script, project_dir=project_dir, timeout=timeout)


def _exec_umg_script(
    api: UEEditorAPI,
    script_content: str,
    project_dir: str | None = None,
    timeout: float = 60.0,
) -> dict:
    from cli_anything.unreal.core.script_runner import run_python_code

    return run_python_code(api, script_content, timeout=timeout)
