"""core/blueprint.py — Blueprint viewing and editing.

Provides blueprint listing, inspection, function/variable management,
and compilation for AI Agent workflows. Requires a running UE editor
with Remote Control API plugin and Python Editor Scripting plugins.

Uses two approaches:
1. /remote/search/assets — Fast asset search by class (for listing)
2. Python script execution — For complex queries via BlueprintEditorLibrary
"""

import json

from cli_anything.unreal.utils.ue_http_api import UEEditorAPI


def _blueprint_asset_path_candidates(blueprint_path: str) -> list[str]:
    """Return likely loadable Blueprint asset paths for UE object path forms."""
    base_path = str(blueprint_path).strip().split(":", 1)[0]
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
    add(package_path)
    return candidates


_BLUEPRINT_RESOLVER = '''
def _cli_load_blueprint(asset_path, asset_candidates):
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
        try:
            data = unreal.EditorAssetLibrary.find_asset_data(candidate)
            if data and data.is_valid():
                bp = data.get_asset()
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
        wanted_package_names = set()
        wanted_asset_names = set()
        parent_paths = []
        for candidate in asset_candidates:
            package_name = str(candidate).split(":", 1)[0]
            leaf = package_name.rsplit("/", 1)[-1]
            if "." in leaf:
                object_name = package_name.rsplit(".", 1)[1]
                package_name = package_name.rsplit(".", 1)[0]
                wanted_asset_names.add(object_name)
            else:
                wanted_asset_names.add(leaf)
            wanted_package_names.add(package_name)
            parent_path = package_name.rsplit("/", 1)[0] or "/Game"
            if parent_path not in parent_paths:
                parent_paths.append(parent_path)
            for data in registry.get_assets_by_package_name(package_name, False):
                object_path = str(data.package_name) + "." + str(data.asset_name)
                bp, loaded_path = _try_load(object_path)
                if bp is not None:
                    return bp, loaded_path, tried
        for parent_path in parent_paths:
            for data in registry.get_assets_by_path(parent_path, False, False):
                if str(data.package_name) in wanted_package_names or str(data.asset_name) in wanted_asset_names:
                    object_path = str(data.package_name) + "." + str(data.asset_name)
                    bp, loaded_path = _try_load(object_path)
                    if bp is not None:
                        return bp, loaded_path, tried
    except Exception:
        pass

    return None, None, tried
'''


# ── Python script templates ──────────────────────────────────────────

_SCRIPT_BP_INFO = '''
import unreal
import json

asset_path = {blueprint_path_json}
asset_candidates = {blueprint_path_candidates_json}
bp, loaded_asset_path, tried_asset_paths = _cli_load_blueprint(asset_path, asset_candidates)
if bp is None:
    result = {{"error": "Blueprint not found: " + asset_path, "tried": tried_asset_paths}}
else:
    result = {{
        "name": bp.get_name(),
        "path": loaded_asset_path,
        "class": bp.get_class().get_name(),
    }}

    bel = unreal.BlueprintEditorLibrary

    # ── Graphs ────────────────────────────────────────────────────
    graphs = []
    # Try event graph
    try:
        event_graph = bel.find_event_graph(bp)
        if event_graph is not None:
            graphs.append({{"name": event_graph.get_name(), "type": "EventGraph"}})
    except Exception:
        pass

    # Try common function names (no get_all_graphs available)
    known_names = [
        "ConstructionScript", "UserConstructionScript",
    ]
    for gname in known_names:
        try:
            g = bel.find_graph(bp, gname)
            if g is not None:
                graphs.append({{"name": g.get_name(), "type": "Function"}})
        except Exception:
            pass

    result["graphs"] = graphs
    result["graph_count"] = len(graphs)

    # ── Nodes via ObjectIterator ─────────────────────────────────
    nodes = []
    try:
        event_graph = bel.find_event_graph(bp)
        if event_graph is not None:
            for node in unreal.ObjectIterator(unreal.EdGraphNode):
                try:
                    if node.get_outer() == event_graph:
                        nodes.append({{
                            "name": node.get_name(),
                            "class": node.get_class().get_name(),
                            "title": str(node.get_editor_property("node_comment")) if hasattr(node, "node_comment") else "",
                        }})
                except Exception:
                    pass
    except Exception:
        pass
    result["nodes"] = nodes
    result["node_count"] = len(nodes)

    # ── Variables via describe (RC API will supplement) ───────────
    # BlueprintEditorLibrary doesn't expose new_variables directly,
    # so we gather what we can from the generated class
    variables = []
    try:
        gen_class = bp.generated_class()
        if gen_class is not None:
            cdo = gen_class.get_default_object()
            if cdo is not None:
                for prop in gen_class.get_editor_property("PropertyLink") or []:
                    variables.append({{"name": str(prop)}})
    except Exception:
        pass
    result["variables"] = variables
'''

_SCRIPT_ADD_FUNCTION = '''
import unreal
import json

asset_path = {blueprint_path_json}
asset_candidates = {blueprint_path_candidates_json}
func_name = "{func_name}"

bp, loaded_asset_path, tried_asset_paths = _cli_load_blueprint(asset_path, asset_candidates)
if bp is None:
    result = {{"error": "Blueprint not found: " + asset_path, "tried": tried_asset_paths}}
else:
    bel = unreal.BlueprintEditorLibrary
    try:
        graph = bel.add_function_graph(bp, func_name)
        if graph is not None:
            result = {{
                "status": "ok",
                "action": "add_function",
                "blueprint": loaded_asset_path,
                "function": func_name,
                "graph_name": graph.get_name(),
            }}
        else:
            result = {{"error": "add_function_graph returned None for: " + func_name}}
    except Exception as e:
        result = {{"error": "Failed to add function graph: " + str(e)}}
'''

_SCRIPT_REMOVE_FUNCTION = '''
import unreal
import json

asset_path = {blueprint_path_json}
asset_candidates = {blueprint_path_candidates_json}
func_name = "{func_name}"

bp, loaded_asset_path, tried_asset_paths = _cli_load_blueprint(asset_path, asset_candidates)
if bp is None:
    result = {{"error": "Blueprint not found: " + asset_path, "tried": tried_asset_paths}}
else:
    bel = unreal.BlueprintEditorLibrary
    try:
        graph = bel.find_graph(bp, func_name)
        if graph is None:
            result = {{"error": "Function graph not found: " + func_name}}
        else:
            bel.remove_function_graph(bp, func_name)
            result = {{
                "status": "ok",
                "action": "remove_function",
                "blueprint": loaded_asset_path,
                "function": func_name,
            }}
    except Exception as e:
        result = {{"error": "Failed to remove function graph: " + str(e)}}
'''

_SCRIPT_ADD_VARIABLE = '''
import unreal
import json

asset_path = {blueprint_path_json}
asset_candidates = {blueprint_path_candidates_json}
var_name = "{var_name}"
var_type = "{var_type}"

bp, loaded_asset_path, tried_asset_paths = _cli_load_blueprint(asset_path, asset_candidates)
if bp is None:
    result = {{"error": "Blueprint not found: " + asset_path, "tried": tried_asset_paths}}
else:
    bel = unreal.BlueprintEditorLibrary
    try:
        pin_type = bel.get_basic_type_by_name(var_type)
        if pin_type is None:
            result = {{"error": "Unknown variable type: " + var_type + ". Valid types: bool, int, float, string, text, name, vector, rotator, transform"}}
        else:
            success = bel.add_member_variable(bp, var_name, pin_type)
            if success:
                result = {{
                    "status": "ok",
                    "action": "add_variable",
                    "blueprint": loaded_asset_path,
                    "variable": var_name,
                    "type": var_type,
                }}
            else:
                result = {{"error": "add_member_variable returned False for: " + var_name}}
    except Exception as e:
        result = {{"error": "Failed to add variable: " + str(e)}}
'''


_SCRIPT_REMOVE_VARIABLE = '''
import unreal
import json

asset_path = {blueprint_path_json}
asset_candidates = {blueprint_path_candidates_json}
var_name = "{var_name}"

bp, loaded_asset_path, tried_asset_paths = _cli_load_blueprint(asset_path, asset_candidates)
if bp is None:
    result = {{"error": "Blueprint not found: " + asset_path, "tried": tried_asset_paths}}
else:
    bel = unreal.BlueprintEditorLibrary
    try:
        success = bel.remove_member_variable(bp, var_name)
        if success:
            result = {{
                "status": "ok",
                "action": "remove_variable",
                "blueprint": loaded_asset_path,
                "variable": var_name,
            }}
        else:
            result = {{"error": "remove_member_variable returned False for: " + var_name}}
    except Exception as e:
        result = {{"error": "Failed to remove variable: " + str(e)}}
'''

_SCRIPT_REMOVE_UNUSED_VARS = '''
import unreal
import json

asset_path = {blueprint_path_json}
asset_candidates = {blueprint_path_candidates_json}

bp, loaded_asset_path, tried_asset_paths = _cli_load_blueprint(asset_path, asset_candidates)
if bp is None:
    result = {{"error": "Blueprint not found: " + asset_path, "tried": tried_asset_paths}}
else:
    bel = unreal.BlueprintEditorLibrary
    try:
        count = bel.remove_unused_variables(bp)
        result = {{
            "status": "ok",
            "action": "remove_unused_variables",
            "blueprint": loaded_asset_path,
            "removed_count": count,
        }}
    except Exception as e:
        result = {{"error": "Failed to remove unused variables: " + str(e)}}
'''

_SCRIPT_COMPILE = '''
import unreal
import json

asset_path = {blueprint_path_json}
asset_candidates = {blueprint_path_candidates_json}

bp, loaded_asset_path, tried_asset_paths = _cli_load_blueprint(asset_path, asset_candidates)
if bp is None:
    result = {{"error": "Blueprint not found: " + asset_path, "tried": tried_asset_paths}}
else:
    bel = unreal.BlueprintEditorLibrary
    try:
        bel.compile_blueprint(bp)
        result = {{
            "status": "ok",
            "action": "compile",
            "blueprint": loaded_asset_path,
        }}
    except Exception as e:
        result = {{"error": "Failed to compile blueprint: " + str(e)}}
'''

_SCRIPT_RENAME_GRAPH = '''
import unreal
import json

asset_path = {blueprint_path_json}
asset_candidates = {blueprint_path_candidates_json}
old_name = "{old_name}"
new_name = "{new_name}"

bp, loaded_asset_path, tried_asset_paths = _cli_load_blueprint(asset_path, asset_candidates)
if bp is None:
    result = {{"error": "Blueprint not found: " + asset_path, "tried": tried_asset_paths}}
else:
    bel = unreal.BlueprintEditorLibrary
    try:
        graph = bel.find_graph(bp, old_name)
        if graph is None:
            result = {{"error": "Graph not found: " + old_name}}
        else:
            bel.rename_graph(bp, graph, new_name)
            result = {{
                "status": "ok",
                "action": "rename_graph",
                "blueprint": loaded_asset_path,
                "old_name": old_name,
                "new_name": new_name,
            }}
    except Exception as e:
        result = {{"error": "Failed to rename graph: " + str(e)}}
'''


# ── Public API ────────────────────────────────────────────────────────

def list_blueprints(
    api: UEEditorAPI,
    content_path: str = "/Game/",
    project_dir: str | None = None,
) -> dict:
    """List all blueprints in the project via Remote Control search API.

    Args:
        api: Connected UEEditorAPI instance.
        content_path: Content path to search (e.g., "/Game").
        project_dir: Project directory (unused, kept for API compat).

    Returns:
        {"blueprints": [{"path": str, "name": str, "class": str, "metadata": dict}, ...]}
    """
    pkg_path = content_path.rstrip("/")
    if not pkg_path:
        pkg_path = "/Game"

    result = api.search_assets(
        query="",
        class_names=["/Script/Engine.Blueprint"],
        package_paths=[pkg_path],
        recursive=True,
    )

    if "error" in result:
        return result

    assets = result.get("Assets", [])
    blueprints = []
    for asset in assets:
        blueprints.append({
            "path": asset.get("Path", ""),
            "name": asset.get("Name", ""),
            "class": asset.get("Class", ""),
            "metadata": asset.get("Metadata", {}),
        })

    return {"blueprints": blueprints}


def get_blueprint_info(
    api: UEEditorAPI,
    blueprint_path: str,
    project_dir: str | None = None,
) -> dict:
    """Get detailed information about a blueprint.

    Uses Python script injection to query graphs, nodes, and variables
    via BlueprintEditorLibrary.

    Args:
        api: Connected UEEditorAPI instance.
        blueprint_path: Content path (e.g., "/Game/BP_Test").
        project_dir: Project directory for temp files.

    Returns:
        Dict with blueprint info including graphs, nodes, variables.
    """
    return _exec_blueprint_script(
        api,
        _SCRIPT_BP_INFO,
        project_dir=project_dir,
        blueprint_path=blueprint_path,
    )


def add_function(
    api: UEEditorAPI,
    blueprint_path: str,
    func_name: str,
    project_dir: str | None = None,
) -> dict:
    """Add a function graph to a blueprint.

    Args:
        api: Connected UEEditorAPI instance.
        blueprint_path: Content path (e.g., "/Game/BP_Test").
        func_name: Name for the new function graph.
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "function": str, ...} or {"error": str}
    """
    return _exec_blueprint_script(
        api,
        _SCRIPT_ADD_FUNCTION,
        project_dir=project_dir,
        blueprint_path=blueprint_path,
        func_name=func_name,
    )


def remove_function(
    api: UEEditorAPI,
    blueprint_path: str,
    func_name: str,
    project_dir: str | None = None,
) -> dict:
    """Remove a function graph from a blueprint.

    Args:
        api: Connected UEEditorAPI instance.
        blueprint_path: Content path (e.g., "/Game/BP_Test").
        func_name: Name of the function graph to remove.
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "function": str, ...} or {"error": str}
    """
    return _exec_blueprint_script(
        api,
        _SCRIPT_REMOVE_FUNCTION,
        project_dir=project_dir,
        blueprint_path=blueprint_path,
        func_name=func_name,
    )


def add_variable(
    api: UEEditorAPI,
    blueprint_path: str,
    var_name: str,
    var_type: str,
    project_dir: str | None = None,
) -> dict:
    """Add a member variable to a blueprint.

    Args:
        api: Connected UEEditorAPI instance.
        blueprint_path: Content path (e.g., "/Game/BP_Test").
        var_name: Name for the new variable.
        var_type: Type name: bool, int, float, string, text, name,
                  vector, rotator, transform.
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "variable": str, "type": str, ...} or {"error": str}
    """
    return _exec_blueprint_script(
        api,
        _SCRIPT_ADD_VARIABLE,
        project_dir=project_dir,
        blueprint_path=blueprint_path,
        var_name=var_name,
        var_type=var_type,
    )



def remove_variable(
    api: UEEditorAPI,
    blueprint_path: str,
    var_name: str,
    project_dir: str | None = None,
) -> dict:
    """Remove a member variable from a blueprint.

    Args:
        api: Connected UEEditorAPI instance.
        blueprint_path: Content path (e.g., "/Game/BP_Test").
        var_name: Name of the variable to remove.
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "variable": str, ...} or {"error": str}
    """
    return _exec_blueprint_script(
        api,
        _SCRIPT_REMOVE_VARIABLE,
        project_dir=project_dir,
        blueprint_path=blueprint_path,
        var_name=var_name,
    )


def remove_unused_variables(
    api: UEEditorAPI,
    blueprint_path: str,
    project_dir: str | None = None,
) -> dict:
    """Remove all unused variables from a blueprint.

    Args:
        api: Connected UEEditorAPI instance.
        blueprint_path: Content path (e.g., "/Game/BP_Test").
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "removed_count": int, ...} or {"error": str}
    """
    return _exec_blueprint_script(
        api,
        _SCRIPT_REMOVE_UNUSED_VARS,
        project_dir=project_dir,
        blueprint_path=blueprint_path,
    )


def compile_blueprint(
    api: UEEditorAPI,
    blueprint_path: str,
    project_dir: str | None = None,
) -> dict:
    """Compile a blueprint.

    Args:
        api: Connected UEEditorAPI instance.
        blueprint_path: Content path (e.g., "/Game/BP_Test").
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "action": "compile", ...} or {"error": str}
    """
    return _exec_blueprint_script(
        api,
        _SCRIPT_COMPILE,
        project_dir=project_dir,
        blueprint_path=blueprint_path,
    )


def rename_graph(
    api: UEEditorAPI,
    blueprint_path: str,
    old_name: str,
    new_name: str,
    project_dir: str | None = None,
) -> dict:
    """Rename a graph in a blueprint.

    Args:
        api: Connected UEEditorAPI instance.
        blueprint_path: Content path (e.g., "/Game/BP_Test").
        old_name: Current graph name.
        new_name: New graph name.
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "old_name": str, "new_name": str, ...} or {"error": str}
    """
    return _exec_blueprint_script(
        api,
        _SCRIPT_RENAME_GRAPH,
        project_dir=project_dir,
        blueprint_path=blueprint_path,
        old_name=old_name,
        new_name=new_name,
    )


# ── Internal helpers ──────────────────────────────────────────────────

def _exec_blueprint_script(
    api: UEEditorAPI,
    script_template: str,
    project_dir: str | None = None,
    timeout: float = 30.0,
    **kwargs,
) -> dict:
    """Execute a blueprint query Python script in the editor and read results.

    Formats *script_template* with **kwargs, then executes via
    ``script_runner.run_python_code`` (which uses
    ``ExecutePythonCommandEx`` under the hood).

    Args:
        api: Connected UEEditorAPI instance.
        script_template: Python script template with {placeholders}.
        project_dir: Unused — kept for backwards compatibility.
        timeout: HTTP request timeout in seconds.
        **kwargs: Template variables.

    Returns:
        Parsed JSON result from the script.
    """
    from cli_anything.unreal.core.script_runner import run_python_code

    if "blueprint_path" in kwargs:
        blueprint_path = kwargs["blueprint_path"]
        kwargs.setdefault("blueprint_path_json", json.dumps(blueprint_path, ensure_ascii=False))
        kwargs.setdefault(
            "blueprint_path_candidates_json",
            json.dumps(_blueprint_asset_path_candidates(blueprint_path), ensure_ascii=False),
        )
    script_content = _BLUEPRINT_RESOLVER + "\n" + script_template.format(**kwargs)
    return run_python_code(api, script_content, timeout=timeout)
