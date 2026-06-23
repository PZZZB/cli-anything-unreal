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

{_BRIDGE_CHECK}

bridge, bridge_error = _cli_bridge()
if bridge_error:
    result = bridge_error
else:
    bp = None
    loaded_asset_path = None
    for candidate in asset_candidates:
        bp = unreal.EditorAssetLibrary.load_asset(candidate)
        if bp:
            loaded_asset_path = candidate
            break
    if not bp:
        result = {{"error": "WidgetBlueprint not found: " + asset_path, "tried": asset_candidates}}
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

{_BRIDGE_CHECK}

bridge, bridge_error = _cli_bridge()
if bridge_error:
    result = bridge_error
else:
    bp = None
    loaded_asset_path = None
    for candidate in asset_candidates:
        bp = unreal.EditorAssetLibrary.load_asset(candidate)
        if bp:
            loaded_asset_path = candidate
            break
    if not bp:
        result = {{"error": "WidgetBlueprint not found: " + asset_path, "tried": asset_candidates}}
    else:
        result = _cli_parse_bridge(bridge.get_widget_blueprint_tree(bp))
        if result.get("status") == "ok":
            result["widget"] = loaded_asset_path
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
