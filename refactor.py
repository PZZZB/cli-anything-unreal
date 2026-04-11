import re

path = r"F:\workspace\CLI-Anything\unreal\agent-harness\cli_anything\unreal\unreal_cli.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Promote 'asset' to a top-level group
asset_group = """
# ══════════════════════════════════════════════════════════════════════
#  ASSET commands
# ══════════════════════════════════════════════════════════════════════

@cli.group("asset")
def asset_group():
    \"\"\"Asset operations (exists, delete, duplicate, info, etc.).\"\"\"
    pass
"""

content = content.replace('@cli.group("project")\ndef project_group():', asset_group + '\n@cli.group("project")\ndef project_group():')

# 1.1 Replace @project_group.command(...) with @asset_group.command(...) for asset commands.
content = content.replace('@project_group.command("content")', '@asset_group.command("list")')
content = content.replace('def content_list(', 'def asset_list(')

content = content.replace('@project_group.command("asset-exists")', '@asset_group.command("exists")')
content = content.replace('def project_asset_exists(', 'def asset_exists_cmd(')

content = content.replace('@project_group.command("asset-delete")', '@asset_group.command("delete")')
content = content.replace('def project_asset_delete(', 'def asset_delete_cmd(')

content = content.replace('@project_group.command("asset-refs")', '@asset_group.command("refs")')
content = content.replace('def project_asset_refs(', 'def asset_refs_cmd(')

content = content.replace('@project_group.command("asset-duplicate")', '@asset_group.command("duplicate")')
content = content.replace('def project_asset_duplicate(', 'def asset_duplicate_cmd(')

content = content.replace('@project_group.command("asset-rename")', '@asset_group.command("rename")')
content = content.replace('def project_asset_rename(', 'def asset_rename_cmd(')

content = content.replace('@project_group.command("asset-describe")', '@asset_group.command("info")')
content = content.replace('def project_asset_describe(', 'def asset_info_cmd(')

# Wait, `asset-property` needs to be split to `get-property` and `set-property`.
asset_property_code = """@asset_group.command("get-property")
@click.argument("asset_path")
@click.argument("property_name")
@handle_error
def asset_get_property(asset_path, property_name):
    \"\"\"Get a property on a UAsset in the Content Browser.\"\"\"
    from cli_anything.unreal.core.assets import get_asset_property

    asset_path = _fix_ue_path(asset_path)
    api = _require_editor()
    result = get_asset_property(api, asset_path, property_name)
    output(result)


@asset_group.command("set-property")
@click.argument("asset_path")
@click.argument("property_name")
@click.argument("new_value")
@handle_error
def asset_set_property(asset_path, property_name, new_value):
    \"\"\"Set a property on a UAsset in the Content Browser.\"\"\"
    from cli_anything.unreal.core.assets import set_asset_property

    asset_path = _fix_ue_path(asset_path)
    api = _require_editor()
    result = set_asset_property(api, asset_path, property_name, new_value)
    output(result)"""

content = re.sub(
    r'@project_group\.command\("asset-property"\).*?def project_asset_property.*?output\(result\)\n',
    asset_property_code + '\n',
    content,
    flags=re.DOTALL
)

# 2. Scene commands
content = content.replace('@scene_group.command("actors")', '@scene_group.command("list")')
content = content.replace('def scene_actors(', 'def scene_list_actors(')

content = content.replace('@scene_group.command("components")', '@scene_group.command("list-components")')
content = content.replace('def scene_components(', 'def scene_list_components(')

content = content.replace('@scene_group.command("material")', '@scene_group.command("get-material")')
content = content.replace('def scene_material(', 'def scene_get_material(')

content = content.replace('@scene_group.command("transform")', '@scene_group.command("get-transform")')
content = content.replace('def scene_transform(', 'def scene_get_transform(')

content = content.replace('@scene_group.command("describe")', '@scene_group.command("info")')
content = content.replace('def scene_describe(', 'def scene_info_cmd(')

scene_property_code = """@scene_group.command("get-property")
@click.argument("actor_path")
@click.argument("property_name")
@handle_error
def scene_get_property(actor_path, property_name):
    \"\"\"Get a property on an actor.\"\"\"
    from cli_anything.unreal.core.scene import get_actor_property

    api = _require_editor()
    result = get_actor_property(api, actor_path, property_name)
    output(result)


@scene_group.command("set-property")
@click.argument("actor_path")
@click.argument("property_name")
@click.argument("new_value")
@handle_error
def scene_set_property(actor_path, property_name, new_value):
    \"\"\"Set a property on an actor.\"\"\"
    from cli_anything.unreal.core.scene import set_actor_property

    api = _require_editor()
    result = set_actor_property(api, actor_path, property_name, new_value)
    output(result)"""

content = re.sub(
    r'@scene_group\.command\("property"\).*?def scene_property.*?output\(result\)\n',
    scene_property_code + '\n',
    content,
    flags=re.DOTALL
)

# 3. Material commands
content = content.replace('@material_group.command("stats")', '@material_group.command("get-stats")')
content = content.replace('@material_group.command("errors")', '@material_group.command("get-errors")')
content = content.replace('@material_group.command("textures")', '@material_group.command("list-textures")')
content = content.replace('@material_group.command("connections")', '@material_group.command("get-connections")')
content = content.replace('@material_group.command("hlsl")', '@material_group.command("dump-hlsl")')

material_get_param_code = """@material_group.command("get-param")
@click.argument("material_path")
@click.option("--name", "param_name", required=True, help="Parameter name")
@handle_error
def material_get_param(material_path, param_name):
    \"\"\"Get a parameter on a MaterialInstanceConstant.
    
    Example: material get-param /Game/MI_Test --name Roughness
    \"\"\"
    from cli_anything.unreal.core.materials import get_material_param

    material_path = _fix_ue_path(material_path)
    api = _require_editor()
    result = get_material_param(api, material_path, param_name, project_dir=_session.project_dir)
    output(result)

"""
content = content.replace('@material_group.command("set-param")', material_get_param_code + '@material_group.command("set-param")')

# 4. Blueprint commands
content = content.replace('@blueprint_group.command("remove-function")', '@blueprint_group.command("delete-function")')
content = content.replace('def blueprint_remove_function(', 'def blueprint_delete_function(')

content = content.replace('@blueprint_group.command("remove-unused-variables")', '@blueprint_group.command("delete-unused-variables")')
content = content.replace('def blueprint_remove_unused_variables(', 'def blueprint_delete_unused_variables(')

blueprint_delete_variable_code = """@blueprint_group.command("delete-variable")
@click.argument("blueprint_path")
@click.option("--name", "var_name", required=True, help="Variable name")
@handle_error
def blueprint_delete_variable(blueprint_path, var_name):
    \"\"\"Delete a member variable from a blueprint.

    Example: blueprint delete-variable /Game/BP_Test --name Health
    \"\"\"
    from cli_anything.unreal.core.blueprint import remove_variable

    blueprint_path = _fix_ue_path(blueprint_path)
    api = _require_editor()
    result = remove_variable(api, blueprint_path, var_name, project_dir=_session.project_dir)
    output(result)

"""
content = content.replace('@blueprint_group.command("delete-unused-variables")', blueprint_delete_variable_code + '@blueprint_group.command("delete-unused-variables")')

repl_help_old = '''        "project content": "List content assets",
        "project asset-exists": "Check if asset exists",
        "project asset-delete": "Delete asset (with ref check)",
        "project asset-refs": "List asset referencers",
        "project asset-duplicate": "Duplicate asset (--force to overwrite)",
        "project asset-rename": "Rename/move asset",'''
repl_help_new = '''        "asset list": "List content assets",
        "asset info <path>": "Describe a UAsset",
        "asset exists <path>": "Check if asset exists",
        "asset delete <path>": "Delete asset (with ref check)",
        "asset refs <path>": "List asset referencers",
        "asset duplicate <s_path> <d_path>": "Duplicate asset",
        "asset rename <s_path> <d_path>": "Rename/move asset",
        "asset get-property <path> <prop>": "Get asset property",
        "asset set-property <path> <prop> <val>": "Set asset property",'''
content = content.replace(repl_help_old, repl_help_new)

content = content.replace('"scene actors": "List all actors in level",', '"scene list": "List all actors in level",')
content = content.replace('"scene describe <path>": "Describe actor properties",', '"scene info <path>": "Describe actor properties",')
content = content.replace('"scene property <path> <prop>": "Get property value",', '"scene get-property <path> <prop>": "Get property value",\n        "scene set-property <path> <prop> <val>": "Set property value",')
content = content.replace('"scene components <path>": "List actor components",', '"scene list-components <path>": "List actor components",')
content = content.replace('"scene material <path>": "Get actor\'s material ★",', '"scene get-material <path>": "Get actor\'s material ★",')
content = content.replace('"scene transform <path>": "Get actor transform",', '"scene get-transform <path>": "Get actor transform",')

content = content.replace('"material stats <path>": "Compilation statistics",', '"material get-stats <path>": "Compilation statistics",')
content = content.replace('"material errors <path>": "Check for errors",', '"material get-errors <path>": "Check for errors",')
content = content.replace('"material textures <path>": "List referenced textures",', '"material list-textures <path>": "List referenced textures",')
content = content.replace('"material connections <path>": "Connection graph + orphans",', '"material get-connections <path>": "Connection graph + orphans",')
content = content.replace('"screenshot static": "Capture viewport (static)",', '"screenshot capture": "Capture viewport (static)",')
content = content.replace('"screenshot dynamic": "Time-ordered frame atlas (dynamic)",', '"screenshot capture-sequence": "Time-ordered frame atlas (dynamic)",')

# 5. Screenshot
content = content.replace('@screenshot_group.command("static")', '@screenshot_group.command("capture")')
content = content.replace('@screenshot_group.command(\n    "dynamic",', '@screenshot_group.command(\n    "capture-sequence",')

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("done")