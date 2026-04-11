"""commands/material.py — Material viewing, editing & analysis commands."""

import click

from cli_anything.unreal.commands import AppState, handle_error, output, require_editor, require_project


@click.group("material")
def material_group():
    """Material viewing, editing & analysis (add/connect/delete nodes, set params, recompile)."""
    pass


@material_group.command("list")
@click.option("--path", "content_path", default="/Game/", help="Content path to search")
@handle_error
@click.pass_obj
def material_list(state: AppState, content_path):
    """List all materials in the project."""
    from cli_anything.unreal.core.materials import list_materials

    api = require_editor(state)
    result = list_materials(api, content_path, state.session.project_dir)
    output(result, state)


@material_group.command("info")
@click.argument("material_path")
@handle_error
@click.pass_obj
def material_info(state: AppState, material_path):
    """Show detailed material information (nodes, parameters, textures)."""
    from cli_anything.unreal.core.materials import get_material_info

    api = require_editor(state)
    result = get_material_info(api, material_path, state.session.project_dir)
    output(result, state)


@material_group.command("get-stats")
@click.argument("material_path")
@handle_error
@click.pass_obj
def material_stats(state: AppState, material_path):
    """Show material compilation statistics (instruction counts)."""
    from cli_anything.unreal.core.materials import get_material_stats

    api = require_editor(state)
    result = get_material_stats(api, material_path, state.session.project_dir)
    output(result, state)


@material_group.command("get-errors")
@click.argument("material_path")
@handle_error
@click.pass_obj
def material_errors(state: AppState, material_path):
    """Check material for compilation errors."""
    from cli_anything.unreal.core.materials import get_material_errors

    api = require_editor(state)
    result = get_material_errors(api, material_path, state.session.project_dir)
    output(result, state)


@material_group.command("list-textures")
@click.argument("material_path")
@handle_error
@click.pass_obj
def material_textures(state: AppState, material_path):
    """List all textures referenced by a material."""
    from cli_anything.unreal.core.materials import get_material_texture_list

    api = require_editor(state)
    result = get_material_texture_list(api, material_path, state.session.project_dir)
    output(result, state)


@material_group.command("get-connections")
@click.argument("material_path")
@handle_error
@click.pass_obj
def material_connections(state: AppState, material_path):
    """Show material node connection graph.

    Lists which node feeds each material output pin (BaseColor, Normal,
    WorldPositionOffset, etc.) and identifies orphan nodes not connected
    to any output.  Custom nodes include HLSL code previews.

    Example: material get-connections /Game/M_Water
    """
    from cli_anything.unreal.core.materials import get_material_connections

    api = require_editor(state)
    result = get_material_connections(api, material_path, state.session.project_dir)

    if not state.json_output and "error" not in result:
        state.skin.section(f"Connections: {material_path}")

        mat_outputs = result.get("material_outputs", {})
        if mat_outputs:
            state.skin.info("Material Output Pins:")
            for pin, src in mat_outputs.items():
                if isinstance(src, dict):
                    state.skin.status(f"  {pin}", f"{src['node']} ({src['node_type']})")
        else:
            state.skin.warning("No material output connections found")

        orphans = result.get("orphan_nodes", [])
        if orphans:
            state.skin.warning(f"{len(orphans)} orphan node(s) (not connected to output):")
            for name in orphans[:10]:
                state.skin.hint(f"  {name}")
            if len(orphans) > 10:
                state.skin.hint(f"  ... and {len(orphans) - 10} more")

        # Show Custom nodes with code
        nodes = result.get("nodes", [])
        customs = [n for n in nodes if n.get("type") == "MaterialExpressionCustom"]
        if customs:
            state.skin.info(f"\nCustom HLSL Nodes ({len(customs)}):")
            for c in customs:
                preview = c.get("code_preview", "(no code)")
                lines = c.get("code_lines", "?")
                state.skin.status(f"  {c['name']}", f"{lines} lines")
                if preview:
                    for line in preview.split("\n")[:3]:
                        click.echo(f"    {line}")

    output(result, state)


@material_group.command("analyze")
@click.argument("material_path")
@handle_error
@click.pass_obj
def material_analyze(state: AppState, material_path):
    """Analyze material for common issues (Agent core feature)."""
    from cli_anything.unreal.core.materials import analyze_material

    api = require_editor(state)
    result = analyze_material(api, material_path, state.session.project_dir)

    if not state.json_output:
        state.skin.section(f"Analysis: {material_path}")

        issues = result.get("issues", [])
        warnings = result.get("warnings", [])
        stats = result.get("stats", {})

        if issues:
            for issue in issues:
                state.skin.error(f"ISSUE: {issue}")
        if warnings:
            for warning in warnings:
                state.skin.warning(f"WARNING: {warning}")
        if not issues and not warnings:
            state.skin.success("No issues found")

        if stats:
            state.skin.status_block({
                "Texture Samples": str(stats.get("texture_sample_count", "?")),
                "Node Count": str(stats.get("node_count", "?")),
                "Textures": str(stats.get("texture_count", "?")),
            }, title="Statistics")
    else:
        output(result, state)


@material_group.command("dump-hlsl")
@click.argument("material_path")
@click.option("--platform", default="sm6",
              help="Shader platform: sm6 (default), sm5, vulkan, vulkan_es31, opengl_es31, metal")
@click.option("--shader-type", default="pixel",
              type=click.Choice(["pixel", "vertex", "all"]),
              help="Which shader stage to return")
@click.option("--full", is_flag=True, help="Return full .usf file (not just material code)")
@handle_error
@click.pass_obj
def material_hlsl(state: AppState, material_path, platform, shader_type, full):
    """Get compiled HLSL/USF shader code for a material.

    Triggers shader recompile with debug dump, reads the generated code.
    CVar r.DumpShaderDebugInfo is automatically saved and restored.

    Platforms: sm6 (DirectX SM6), sm5 (DirectX SM5), vulkan, opengl_es31, metal
    """
    from cli_anything.unreal.core.materials import get_material_hlsl

    api = require_editor(state)
    require_project(state)

    if not state.json_output:
        state.skin.info(f"Dumping HLSL for {material_path} ({platform})...")
        state.skin.hint("This triggers a shader recompile, may take a few seconds...")

    result = get_material_hlsl(
        api, material_path,
        project_dir=state.session.project_dir,
        platform=platform,
        shader_type=shader_type,
    )

    if not state.json_output and "error" not in result:
        state.skin.success(f"Got {result.get('shader_count', 0)} shaders")
        state.skin.status("Platform", result.get("platform", ""))
        state.skin.status("Available", ", ".join(result.get("available_platforms", [])))

        mat_code = result.get("material_code", "")
        if mat_code:
            state.skin.section("Material Code (CalcPixelMaterialInputs)")
            print(mat_code)
        elif full and result.get("shaders"):
            first = result["shaders"][0]
            state.skin.section(f"Full shader: {first['pass']}")
            print(first.get("code", "No code"))

    if state.json_output:
        # For JSON output, don't include full code by default (too large for token)
        if not full:
            for s in result.get("shaders", []):
                s.pop("code", None)
        output(result, state)
    elif "error" in result:
        output(result, state)


@material_group.command("add-node")
@click.argument("material_path")
@click.option("--type", "expression_class", required=True,
              help="UE expression class (e.g., MaterialExpressionConstant3Vector)")
@click.option("--pos-x", default=0, type=int, help="Node X position in graph")
@click.option("--pos-y", default=0, type=int, help="Node Y position in graph")
@handle_error
@click.pass_obj
def material_add_node(state: AppState, material_path, expression_class, pos_x, pos_y):
    """Add a new material expression node.

    Requires MaterialEditingLibrary (Python Editor Scripting plugin).

    Example: material add-node /Game/M_Test --type MaterialExpressionConstant3Vector
    """
    from cli_anything.unreal.core.materials import add_material_node

    api = require_editor(state)
    result = add_material_node(api, material_path, expression_class,
                               pos_x=pos_x, pos_y=pos_y,
                               project_dir=state.session.project_dir)
    output(result, state)


@material_group.command("delete-node")
@click.argument("material_path")
@click.option("--node", "node_name", required=True,
              help="Name of the expression node to delete")
@handle_error
@click.pass_obj
def material_delete_node(state: AppState, material_path, node_name):
    """Delete a material expression node by name.

    Use 'material info' to find node names first.

    Example: material delete-node /Game/M_Test --node Constant3Vector_0
    """
    from cli_anything.unreal.core.materials import delete_material_node

    api = require_editor(state)
    result = delete_material_node(api, material_path, node_name,
                                  project_dir=state.session.project_dir)
    output(result, state)


@material_group.command("connect")
@click.argument("material_path")
@click.option("--from", "from_node", required=True, help="Source node name")
@click.option("--from-output", default="", help="Source output pin name (empty for single-output)")
@click.option("--to", "to_node", required=True,
              help="Target node name, or '__material_output__' for material output pins")
@click.option("--to-input", required=True,
              help="Target input pin name, or material property (BaseColor, Normal, etc.)")
@handle_error
@click.pass_obj
def material_connect(state: AppState, material_path, from_node, from_output, to_node, to_input):
    """Connect two material expression nodes.

    To connect to material output (BaseColor, Normal, etc.):
      --to __material_output__ --to-input BaseColor

    Example: material connect /Game/M_Test --from Constant3Vector_0 --to __material_output__ --to-input BaseColor
    """
    from cli_anything.unreal.core.materials import connect_material_nodes

    api = require_editor(state)
    result = connect_material_nodes(api, material_path,
                                    from_node, from_output, to_node, to_input,
                                    project_dir=state.session.project_dir)
    output(result, state)


@material_group.command("disconnect")
@click.argument("material_path")
@click.option("--from", "from_node", required=True, help="Source node name")
@click.option("--from-output", default="", help="Source output pin name")
@click.option("--to", "to_node", required=True,
              help="Target node name, or '__material_output__'")
@click.option("--to-input", required=True,
              help="Target input pin name, or material property name")
@handle_error
@click.pass_obj
def material_disconnect(state: AppState, material_path, from_node, from_output, to_node, to_input):
    """Disconnect material expression nodes.

    Example: material disconnect /Game/M_Test --from Constant3Vector_0 --to __material_output__ --to-input BaseColor
    """
    from cli_anything.unreal.core.materials import disconnect_material_nodes

    api = require_editor(state)
    result = disconnect_material_nodes(api, material_path,
                                       from_node, from_output, to_node, to_input,
                                       project_dir=state.session.project_dir)
    output(result, state)


@material_group.command("get-param")
@click.argument("material_path")
@click.option("--name", "param_name", required=True, help="Parameter name")
@handle_error
@click.pass_obj
def material_get_param(state: AppState, material_path, param_name):
    """Get a parameter on a MaterialInstanceConstant.

    Example: material get-param /Game/MI_Test --name Roughness
    """
    from cli_anything.unreal.core.materials import get_material_param

    api = require_editor(state)
    result = get_material_param(api, material_path, param_name, project_dir=state.session.project_dir)
    output(result, state)


@material_group.command("set-param")
@click.argument("material_path")
@click.option("--name", "param_name", required=True, help="Parameter name")
@click.option("--value", "param_value", required=True,
              help='Value: scalar "0.5", vector \'{"r":1,"g":0,"b":0,"a":1}\', texture "/Game/T_Tex"')
@click.option("--type", "param_type", required=True,
              type=click.Choice(["scalar", "vector", "texture"]),
              help="Parameter type")
@handle_error
@click.pass_obj
def material_set_param(state: AppState, material_path, param_name, param_value, param_type):
    """Set a parameter on a MaterialInstanceConstant.

    Example: material set-param /Game/MI_Test --name Roughness --value 0.5 --type scalar
    """
    from cli_anything.unreal.core.materials import set_material_param

    api = require_editor(state)
    result = set_material_param(api, material_path,
                                param_name, param_value, param_type,
                                project_dir=state.session.project_dir)
    output(result, state)


@material_group.command("recompile")
@click.argument("material_path")
@handle_error
@click.pass_obj
def material_recompile(state: AppState, material_path):
    """Recompile a material (force shader recompilation).

    Example: material recompile /Game/M_Test
    """
    from cli_anything.unreal.core.materials import recompile_material

    api = require_editor(state)
    result = recompile_material(api, material_path,
                                project_dir=state.session.project_dir)
    output(result, state)
