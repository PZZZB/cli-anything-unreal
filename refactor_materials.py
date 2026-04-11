import re

mat_path = r"F:\workspace\CLI-Anything\unreal\agent-harness\cli_anything\unreal\core\materials.py"
with open(mat_path, "r", encoding="utf-8") as f:
    mat_content = f.read()

script_get_param = '''
_SCRIPT_GET_PARAM = \'\'\'
import unreal
import json

material_path = "{material_path}"
param_name = "{param_name}"

mat = unreal.EditorAssetLibrary.load_asset(material_path)
if mat is None:
    result = {{"error": "Material not found: " + material_path}}
elif not isinstance(mat, unreal.MaterialInstanceConstant):
    result = {{"error": "Asset is not a MaterialInstanceConstant (get-param only works on MI): " + material_path}}
else:
    mel = unreal.MaterialEditingLibrary
    try:
        found = False
        val = None
        param_type = None

        # Check scalar
        for param in mat.get_editor_property("scalar_parameter_values"):
            if str(param.get_editor_property("parameter_info").get_editor_property("name")) == param_name:
                val = param.get_editor_property("parameter_value")
                param_type = "scalar"
                found = True
                break
        
        # Check vector
        if not found:
            for param in mat.get_editor_property("vector_parameter_values"):
                if str(param.get_editor_property("parameter_info").get_editor_property("name")) == param_name:
                    c = param.get_editor_property("parameter_value")
                    val = {{"r": c.r, "g": c.g, "b": c.b, "a": c.a}}
                    param_type = "vector"
                    found = True
                    break

        # Check texture
        if not found:
            for param in mat.get_editor_property("texture_parameter_values"):
                if str(param.get_editor_property("parameter_info").get_editor_property("name")) == param_name:
                    tex = param.get_editor_property("parameter_value")
                    val = str(tex.get_path_name()) if tex else None
                    param_type = "texture"
                    found = True
                    break

        if found:
            result = {{"status": "ok", "action": "get_param", "material": material_path, "param": param_name, "type": param_type, "value": val}}
        else:
            result = {{"error": "Parameter not found: " + param_name}}
            
    except Exception as e:
        result = {{"error": "get_param failed: " + str(e)}}
\'\'\'
'''

mat_content = mat_content.replace("_SCRIPT_SET_PARAM = '''", script_get_param + "\n_SCRIPT_SET_PARAM = '''")

func_get_param = '''
def get_material_param(
    api: UEEditorAPI,
    material_path: str,
    param_name: str,
    project_dir: str | None = None,
) -> dict:
    """Get a parameter value on a MaterialInstanceConstant.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path to a MaterialInstanceConstant.
        param_name: Parameter name (e.g., "Roughness").
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "value": ...} or {"error": str}
    """
    return _exec_material_script(
        api,
        _SCRIPT_GET_PARAM,
        project_dir=project_dir,
        material_path=material_path,
        param_name=param_name,
    )

'''

mat_content = mat_content.replace('def set_material_param(', func_get_param + '\ndef set_material_param(')

with open(mat_path, "w", encoding="utf-8") as f:
    f.write(mat_content)

print("done materials")
