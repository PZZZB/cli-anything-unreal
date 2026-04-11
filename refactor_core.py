import re

bp_path = r"F:\workspace\CLI-Anything\unreal\agent-harness\cli_anything\unreal\core\blueprint.py"
with open(bp_path, "r", encoding="utf-8") as f:
    bp_content = f.read()

script_remove_var = '''
_SCRIPT_REMOVE_VARIABLE = \'\'\'
import unreal
import json

asset_path = "{blueprint_path}"
var_name = "{var_name}"

bp = unreal.EditorAssetLibrary.load_asset(asset_path)
if bp is None:
    result = {{"error": "Blueprint not found: " + asset_path}}
else:
    bel = unreal.BlueprintEditorLibrary
    try:
        success = bel.remove_member_variable(bp, var_name)
        if success:
            result = {{
                "status": "ok",
                "action": "remove_variable",
                "blueprint": asset_path,
                "variable": var_name,
            }}
        else:
            result = {{"error": "remove_member_variable returned False for: " + var_name}}
    except Exception as e:
        result = {{"error": "Failed to remove variable: " + str(e)}}
\'\'\'
'''

bp_content = bp_content.replace("_SCRIPT_REMOVE_UNUSED_VARS = '''", script_remove_var + "\n_SCRIPT_REMOVE_UNUSED_VARS = '''")

func_remove_var = '''
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

'''

bp_content = bp_content.replace('def remove_unused_variables(', func_remove_var + '\ndef remove_unused_variables(')

with open(bp_path, "w", encoding="utf-8") as f:
    f.write(bp_content)

print("done core")
