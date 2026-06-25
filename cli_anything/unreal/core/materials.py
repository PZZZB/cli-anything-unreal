"""core/materials.py — Material viewing and analysis.

Provides material listing, inspection, and automated issue detection
for AI Agent analysis workflows. Requires a running UE editor with
Remote Control API plugin (default port 30010).

Uses two approaches:
1. /remote/search/assets — Fast asset search by class (for listing)
2. /remote/object/call + /remote/object/property — Direct UObject queries
3. Python script execution — For complex queries not possible via REST
"""

import json
import time
from pathlib import Path
from typing import Optional

from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed
from cli_anything.unreal.utils.ue_http_api import UEEditorAPI


def _material_asset_path_candidates(material_path: str) -> list[str]:
    """Return likely loadable material asset paths for UE object path forms."""
    base_path = str(material_path).strip().split(":", 1)[0]
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
    add(package_path + "." + object_name)
    add(package_path)
    return candidates


_MATERIAL_RESOLVER = '''
def _cli_load_material(asset_path, asset_candidates):
    tried = []

    def _try_load(candidate):
        if not candidate or candidate in tried:
            return None, None
        tried.append(candidate)
        try:
            mat = unreal.EditorAssetLibrary.load_asset(candidate)
            if mat is not None:
                return mat, candidate
        except Exception:
            pass
        try:
            data = unreal.EditorAssetLibrary.find_asset_data(candidate)
            if data and data.is_valid():
                mat = data.get_asset()
                if mat is not None:
                    return mat, candidate
        except Exception:
            pass
        return None, None

    for candidate in asset_candidates:
        mat, loaded_path = _try_load(candidate)
        if mat is not None:
            return mat, loaded_path, tried

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
                mat, loaded_path = _try_load(object_path)
                if mat is not None:
                    return mat, loaded_path, tried

        for parent_path in parent_paths:
            for data in registry.get_assets_by_path(parent_path, False, False):
                if str(data.package_name) in wanted_package_names or str(data.asset_name) in wanted_asset_names:
                    object_path = str(data.package_name) + "." + str(data.asset_name)
                    mat, loaded_path = _try_load(object_path)
                    if mat is not None:
                        return mat, loaded_path, tried
    except Exception:
        pass

    return None, None, tried
'''


# ── Python script templates (for complex queries) ─────────────────────

_SCRIPT_MATERIAL_DETAIL = '''
import unreal
import json

asset_path = "{material_path}"
mat = unreal.EditorAssetLibrary.load_asset(asset_path)
if mat is None:
    result = {{"error": "Material not found: " + asset_path}}
else:
    result = {{
        "name": mat.get_name(),
        "path": asset_path,
        "class": mat.get_class().get_name(),
    }}

    if isinstance(mat, unreal.Material):
        for _prop in ["blend_mode", "material_domain", "two_sided", "shading_model"]:
            try:
                result[_prop] = str(mat.get_editor_property(_prop))
            except:
                pass

        mel = unreal.MaterialEditingLibrary

        # ── Nodes (expressions) ── ObjectIterator because .expressions is protected in UE 5.7+
        try:
            nodes = []
            _expr_objs = []
            for expr in unreal.ObjectIterator(unreal.MaterialExpression):
                if expr.get_outer() == mat:
                    cls_name = expr.get_class().get_name()
                    node = {{"type": cls_name, "name": expr.get_name()}}
                    try:
                        _d = expr.get_editor_property("desc")
                        if _d:
                            node["desc"] = _d
                    except:
                        pass
                    # Custom expression: include HLSL code snippet
                    if cls_name == "MaterialExpressionCustom":
                        try:
                            _code = expr.get_editor_property("code")
                            if _code:
                                _lines = _code.strip().split("\\n")
                                node["code_lines"] = len(_lines)
                                node["code_preview"] = "\\n".join(_lines[:10])
                                if len(_lines) > 10:
                                    node["code_preview"] += "\\n// ... ({{}}) more lines".format(len(_lines) - 10)
                        except:
                            pass
                        try:
                            node["output_type"] = str(expr.get_editor_property("output_type"))
                        except:
                            pass
                        try:
                            _custom_inputs = []
                            for _ci in expr.get_editor_property("inputs") or []:
                                _custom_inputs.append(str(_ci.get_editor_property("input_name")))
                            node["inputs"] = _custom_inputs
                        except Exception as e:
                            node["inputs_error"] = str(e)
                    nodes.append(node)
                    _expr_objs.append(expr)
            result["nodes"] = nodes
            result["node_count"] = len(nodes)
        except Exception as e:
            result["nodes"] = []
            result["node_count"] = 0
            result["nodes_error"] = str(e)
            _expr_objs = []

        # ── Node-to-node edges via get_inputs_for_material_expression ──
        try:
            _edges = []
            for _eo in _expr_objs:
                _inputs = mel.get_inputs_for_material_expression(mat, _eo)
                for _ii, _ie in enumerate(_inputs):
                    if _ie is not None:
                        _edges.append({{
                            "from_node": _ie.get_name(),
                            "to_node": _eo.get_name(),
                            "to_input_index": _ii,
                        }})
            result["edges"] = _edges
        except Exception as e:
            result["edges"] = []
            result["edges_error"] = str(e)

        # ── Material output connections ── which node feeds each output pin
        try:
            _prop_list = [
                ("BaseColor", unreal.MaterialProperty.MP_BASE_COLOR),
                ("Metallic", unreal.MaterialProperty.MP_METALLIC),
                ("Specular", unreal.MaterialProperty.MP_SPECULAR),
                ("Roughness", unreal.MaterialProperty.MP_ROUGHNESS),
                ("Normal", unreal.MaterialProperty.MP_NORMAL),
                ("EmissiveColor", unreal.MaterialProperty.MP_EMISSIVE_COLOR),
                ("Opacity", unreal.MaterialProperty.MP_OPACITY),
                ("OpacityMask", unreal.MaterialProperty.MP_OPACITY_MASK),
                ("WorldPositionOffset", unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET),
                ("AmbientOcclusion", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION),
                ("SubsurfaceColor", unreal.MaterialProperty.MP_SUBSURFACE_COLOR),
            ]
            mat_outputs = {{}}
            for _name, _mp in _prop_list:
                try:
                    _src = mel.get_material_property_input_node(mat, _mp)
                    if _src is not None:
                        _out = ""
                        try:
                            _out = mel.get_material_property_input_node_output_name(mat, _mp)
                        except:
                            pass
                        mat_outputs[_name] = {{
                            "node": _src.get_name(),
                            "node_type": _src.get_class().get_name(),
                            "output": _out,
                        }}
                except:
                    pass
            result["material_outputs"] = mat_outputs
        except Exception as e:
            result["material_outputs_error"] = str(e)

        # ── Texture samples ──
        try:
            tex_samples = []
            for expr in unreal.ObjectIterator(unreal.MaterialExpression):
                if expr.get_outer() == mat:
                    cls_name = expr.get_class().get_name()
                    if "TextureSample" in cls_name or "TextureObject" in cls_name:
                        try:
                            tex = expr.get_editor_property("texture")
                            if tex:
                                tex_info = {{"name": tex.get_name(), "path": tex.get_path_name(), "node_type": cls_name}}
                                try:
                                    tex_info["size_x"] = tex.blueprint_get_size_x()
                                    tex_info["size_y"] = tex.blueprint_get_size_y()
                                except:
                                    pass
                                tex_samples.append(tex_info)
                            else:
                                tex_samples.append({{"name": None, "path": None, "node_type": cls_name}})
                        except:
                            pass
            result["textures"] = tex_samples
            result["texture_sample_count"] = len(tex_samples)
        except Exception as e:
            result["textures"] = []
            result["texture_sample_count"] = 0

    elif isinstance(mat, unreal.MaterialInstanceConstant):
        try:
            parent = mat.get_editor_property("parent")
            result["parent"] = str(parent.get_path_name()) if parent else None
        except:
            result["parent"] = None

        # Scalar parameters
        scalars = []
        try:
            for param in mat.get_editor_property("scalar_parameter_values"):
                scalars.append({{
                    "name": str(param.get_editor_property("parameter_info").get_editor_property("name")),
                    "value": param.get_editor_property("parameter_value"),
                }})
        except:
            pass
        result["scalar_parameters"] = scalars

        # Vector parameters
        vectors = []
        try:
            for param in mat.get_editor_property("vector_parameter_values"):
                val = param.get_editor_property("parameter_value")
                vectors.append({{
                    "name": str(param.get_editor_property("parameter_info").get_editor_property("name")),
                    "value": {{"r": val.r, "g": val.g, "b": val.b, "a": val.a}},
                }})
        except:
            pass
        result["vector_parameters"] = vectors

        # Texture parameters
        textures = []
        try:
            for param in mat.get_editor_property("texture_parameter_values"):
                tex = param.get_editor_property("parameter_value")
                textures.append({{
                    "name": str(param.get_editor_property("parameter_info").get_editor_property("name")),
                    "texture": str(tex.get_path_name()) if tex else None,
                }})
        except:
            pass
        result["texture_parameters"] = textures
'''


# ── Shared helper snippet for property type coercion ─────────────────
# Injected into _SCRIPT_ADD_NODE and _SCRIPT_SET_NODE_PROPERTY.
# Supports: int, float, str, enum, and struct types (LinearColor, Vector, etc.)

# ── Script templates for material editing ─────────────────────────────

_SCRIPT_ADD_NODE = '''
import unreal
import json

material_path = "{material_path}"
mat = unreal.EditorAssetLibrary.load_asset(material_path)
if mat is None:
    result = {{"error": "Material not found: " + material_path}}
elif not isinstance(mat, unreal.Material):
    result = {{"error": "Asset is not a Material (cannot add nodes to MaterialInstance): " + material_path}}
else:
    mel = unreal.MaterialEditingLibrary
    try:
        expr = mel.create_material_expression(mat, unreal.{expression_class}, {pos_x}, {pos_y})
        if expr is None:
            result = {{"error": "Failed to create expression. Class 'unreal.{expression_class}' may not exist."}}
        else:
            # Set properties from --set key=value (simple types only: int, float, str, enum)
            # For struct types (LinearColor, Vector, etc.), use editor run-script instead.
            set_props = {set_props}
            set_warnings = []
            for key, value in set_props:
                try:
                    typed_value = value
                    if isinstance(value, str):
                        try:
                            typed_value = int(value)
                        except ValueError:
                            try:
                                typed_value = float(value)
                            except ValueError:
                                typed_value = value
                    try:
                        expr.set_editor_property(key, typed_value)
                    except (TypeError, ValueError):
                        if isinstance(typed_value, str) and '_' in typed_value and typed_value[0].isupper():
                            resolved = False
                            candidates = [typed_value]
                            upper = typed_value.upper()
                            if upper != typed_value:
                                candidates.append(upper)
                            for attr_name in dir(unreal):
                                if resolved:
                                    break
                                try:
                                    enum_cls = getattr(unreal, attr_name)
                                    for cand in candidates:
                                        if hasattr(enum_cls, cand):
                                            expr.set_editor_property(key, getattr(enum_cls, cand))
                                            resolved = True
                                            break
                                except Exception:
                                    continue
                            if not resolved:
                                raise
                        else:
                            raise
                except Exception as e:
                    set_warnings.append(f"{{key}}={{value}}: {{e}}")

            # Add inputs for Custom nodes from --add-input Name
            add_input_names = {add_input_names}
            if add_input_names:
                inputs = []
                for input_name in add_input_names:
                    ci = unreal.CustomInput()
                    ci.set_editor_property("input_name", input_name)
                    inputs.append(ci)
                try:
                    expr.set_editor_property("inputs", inputs)
                except Exception as e:
                    set_warnings.append(f"inputs: {{e}}")

            result = {{
                "status": "ok",
                "action": "add_node",
                "material": material_path,
                "node": {{
                    "name": expr.get_name(),
                    "type": expr.get_class().get_name(),
                }},
            }}
            if set_warnings:
                result["property_warnings"] = set_warnings
            mel.recompile_material(mat)
            mat.modify()
    except Exception as e:
        result = {{"error": "create_material_expression failed: " + str(e)}}
'''

_SCRIPT_RENAME_CUSTOM_INPUT = '''
import re
import unreal

material_path = {material_path}
node_name = {node_name}
old_name = {old_name}
new_name = {new_name}
update_code = {update_code}

def _list_nodes(_mat):
    _nodes = []
    for _expr in unreal.ObjectIterator(unreal.MaterialExpression):
        if _expr.get_outer() == _mat:
            _nodes.append(_expr.get_name())
    return _nodes

def _input_names(_expr):
    _names = []
    for _ci in _expr.get_editor_property("inputs") or []:
        _names.append(str(_ci.get_editor_property("input_name")))
    return _names

mat = unreal.EditorAssetLibrary.load_asset(material_path)
if mat is None:
    result = {{"error": "Material not found: " + material_path}}
elif not isinstance(mat, unreal.Material):
    result = {{"error": "Asset is not a Material: " + material_path}}
elif not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", new_name):
    result = {{"error": "New Custom input name is not a valid HLSL identifier: " + new_name}}
else:
    mel = unreal.MaterialEditingLibrary
    target = unreal.find_object(None, mat.get_path_name() + ":" + node_name)
    if target is None:
        for _expr in unreal.ObjectIterator(unreal.MaterialExpression):
            if _expr.get_outer() == mat and _expr.get_name() == node_name:
                target = _expr
                break

    if target is None:
        result = {{"error": "Node not found: " + node_name, "available_nodes": _list_nodes(mat)}}
    elif target.get_class().get_name() != "MaterialExpressionCustom":
        result = {{
            "error": "Node is not a MaterialExpressionCustom: " + node_name,
            "node_type": target.get_class().get_name(),
        }}
    else:
        try:
            inputs = list(target.get_editor_property("inputs") or [])
            before_names = _input_names(target)
            if old_name not in before_names:
                result = {{
                    "error": "Custom input not found: " + old_name,
                    "material": material_path,
                    "node": node_name,
                    "inputs": before_names,
                }}
            elif new_name != old_name and new_name in before_names:
                result = {{
                    "error": "Custom input already exists: " + new_name,
                    "material": material_path,
                    "node": node_name,
                    "inputs": before_names,
                }}
            else:
                warnings = []
                for _ci in inputs:
                    if str(_ci.get_editor_property("input_name")) == old_name:
                        _ci.set_editor_property("input_name", new_name)
                target.set_editor_property("inputs", inputs)

                code_updated = False
                if update_code:
                    try:
                        code = target.get_editor_property("code") or ""
                        next_code = re.sub(
                            r"(?<![A-Za-z0-9_])" + re.escape(old_name) + r"(?![A-Za-z0-9_])",
                            new_name,
                            code,
                        )
                        if next_code != code:
                            target.set_editor_property("code", next_code)
                            code_updated = True
                    except Exception as e:
                        warnings.append("code: " + str(e))

                for _obj in [target, mat]:
                    try:
                        _obj.modify()
                    except Exception:
                        pass
                    try:
                        _obj.post_edit_change()
                    except Exception:
                        pass
                try:
                    mel.recompile_material(mat)
                except Exception as e:
                    warnings.append("recompile: " + str(e))
                try:
                    unreal.EditorAssetLibrary.save_loaded_asset(mat)
                except Exception as e:
                    warnings.append("save: " + str(e))

                after_names = _input_names(target)
                result = {{
                    "status": "ok",
                    "action": "rename_custom_input",
                    "material": material_path,
                    "node": node_name,
                    "old_name": old_name,
                    "new_name": new_name,
                    "inputs_before": before_names,
                    "inputs_after": after_names,
                    "code_updated": code_updated,
                }}
                if warnings:
                    result["warnings"] = warnings
        except Exception as e:
            result = {{"error": "rename_custom_input failed: " + str(e)}}
'''

_SCRIPT_DELETE_NODE = '''
import unreal
import json

material_path = "{material_path}"
node_name = "{node_name}"
mat = unreal.EditorAssetLibrary.load_asset(material_path)
if mat is None:
    result = {{"error": "Material not found: " + material_path}}
elif not isinstance(mat, unreal.Material):
    result = {{"error": "Asset is not a Material: " + material_path}}
else:
    mel = unreal.MaterialEditingLibrary
    # Find node by name using unreal.find_object (expressions property is protected in UE 5.7+)
    mat_obj_path = mat.get_path_name()
    target = unreal.find_object(None, mat_obj_path + ":" + node_name)
    if target is None:
        # List available nodes via ObjectIterator
        available = []
        for expr in unreal.ObjectIterator(unreal.MaterialExpression):
            if expr.get_outer() == mat:
                available.append(expr.get_name())
        result = {{"error": "Node not found: " + node_name, "available_nodes": available}}
    else:
        try:
            mel.delete_material_expression(mat, target)
            mel.recompile_material(mat)
            mat.modify()
            result = {{"status": "ok", "action": "delete_node", "material": material_path, "deleted_node": node_name}}
        except Exception as e:
            result = {{"error": "delete_material_expression failed: " + str(e)}}
'''

_SCRIPT_CONNECT = '''
import unreal
import json

material_path = "{material_path}"
from_node_name = "{from_node}"
from_output = "{from_output}"
to_node_name = "{to_node}"
to_input = "{to_input}"

mat = unreal.EditorAssetLibrary.load_asset(material_path)
if mat is None:
    result = {{"error": "Material not found: " + material_path}}
elif not isinstance(mat, unreal.Material):
    result = {{"error": "Asset is not a Material: " + material_path}}
else:
    mel = unreal.MaterialEditingLibrary
    # Find nodes by name using unreal.find_object (expressions property is protected in UE 5.7+)
    mat_obj_path = mat.get_path_name()
    from_expr = unreal.find_object(None, mat_obj_path + ":" + from_node_name)
    to_expr = unreal.find_object(None, mat_obj_path + ":" + to_node_name) if to_node_name != "__material_output__" else None

    # List available nodes for error messages
    def _list_nodes():
        nodes = []
        for expr in unreal.ObjectIterator(unreal.MaterialExpression):
            if expr.get_outer() == mat:
                nodes.append(expr.get_name())
        return nodes

    if from_expr is None:
        result = {{"error": "Source node not found: " + from_node_name, "available_nodes": _list_nodes()}}
    elif to_expr is None and to_node_name != "__material_output__":
        result = {{"error": "Target node not found: " + to_node_name, "available_nodes": _list_nodes()}}
    else:
        try:
            if to_node_name == "__material_output__":
                # Connect to material output property (BaseColor, Normal, etc.)
                prop_map = {{
                    "BaseColor": unreal.MaterialProperty.MP_BASE_COLOR,
                    "Metallic": unreal.MaterialProperty.MP_METALLIC,
                    "Specular": unreal.MaterialProperty.MP_SPECULAR,
                    "Roughness": unreal.MaterialProperty.MP_ROUGHNESS,
                    "Normal": unreal.MaterialProperty.MP_NORMAL,
                    "EmissiveColor": unreal.MaterialProperty.MP_EMISSIVE_COLOR,
                    "Opacity": unreal.MaterialProperty.MP_OPACITY,
                    "OpacityMask": unreal.MaterialProperty.MP_OPACITY_MASK,
                    "WorldPositionOffset": unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET,
                    "AmbientOcclusion": unreal.MaterialProperty.MP_AMBIENT_OCCLUSION,
                    "SubsurfaceColor": unreal.MaterialProperty.MP_SUBSURFACE_COLOR,
                }}
                mat_prop = prop_map.get(to_input)
                if mat_prop is None:
                    result = {{"error": "Unknown material property: " + to_input, "available_properties": list(prop_map.keys())}}
                else:
                    ok = mel.connect_material_property(from_expr, from_output, mat_prop)
                    if ok:
                        mel.recompile_material(mat)
                        mat.modify()
                        result = {{"status": "ok", "action": "connect", "from": from_node_name, "to": "MaterialOutput." + to_input}}
                    else:
                        result = {{"error": "connect_material_property returned False"}}
            else:
                ok = mel.connect_material_expressions(from_expr, from_output, to_expr, to_input)
                if ok:
                    mel.recompile_material(mat)
                    mat.modify()
                    result = {{"status": "ok", "action": "connect", "from": from_node_name, "from_output": from_output, "to": to_node_name, "to_input": to_input}}
                else:
                    result = {{"error": "connect_material_expressions returned False"}}
        except Exception as e:
            result = {{"error": "Connection failed: " + str(e)}}
'''

_SCRIPT_DISCONNECT = '''
import unreal
import json

material_path = "{material_path}"
from_node_name = "{from_node}"
from_output = "{from_output}"
to_node_name = "{to_node}"
to_input = "{to_input}"

mat = unreal.EditorAssetLibrary.load_asset(material_path)
if mat is None:
    result = {{"error": "Material not found: " + material_path}}
elif not isinstance(mat, unreal.Material):
    result = {{"error": "Asset is not a Material: " + material_path}}
else:
    mel = unreal.MaterialEditingLibrary
    try:
        if to_node_name == "__material_output__":
            prop_map = {{
                "BaseColor": unreal.MaterialProperty.MP_BASE_COLOR,
                "Metallic": unreal.MaterialProperty.MP_METALLIC,
                "Specular": unreal.MaterialProperty.MP_SPECULAR,
                "Roughness": unreal.MaterialProperty.MP_ROUGHNESS,
                "Normal": unreal.MaterialProperty.MP_NORMAL,
                "EmissiveColor": unreal.MaterialProperty.MP_EMISSIVE_COLOR,
                "Opacity": unreal.MaterialProperty.MP_OPACITY,
                "OpacityMask": unreal.MaterialProperty.MP_OPACITY_MASK,
                "WorldPositionOffset": unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET,
                "AmbientOcclusion": unreal.MaterialProperty.MP_AMBIENT_OCCLUSION,
                "SubsurfaceColor": unreal.MaterialProperty.MP_SUBSURFACE_COLOR,
            }}
            mat_prop = prop_map.get(to_input)
            if mat_prop is None:
                result = {{"error": "Unknown material property: " + to_input, "available_properties": list(prop_map.keys())}}
            else:
                # Disconnect by connecting None to the material property
                # (there is no delete_material_property in UE 5.7+)
                try:
                    mel.connect_material_property(None, "", mat_prop)
                except:
                    pass
                mel.recompile_material(mat)
                mat.modify()
                result = {{"status": "ok", "action": "disconnect", "from": from_node_name, "to": "MaterialOutput." + to_input}}
        else:
            # Find target node by name using unreal.find_object
            mat_obj_path = mat.get_path_name()
            to_expr = unreal.find_object(None, mat_obj_path + ":" + to_node_name)
            if to_expr is None:
                result = {{"error": "Target node not found: " + to_node_name}}
            else:
                bridge = getattr(unreal, "CliAnythingBridgeLibrary", None)
                if bridge is None or not hasattr(bridge, "disconnect_material_expression_input"):
                    result = {{
                        "error": "CliAnythingBridgeLibrary is missing DisconnectMaterialExpressionInput. material disconnect between nodes requires bridge plugin 1.15+.",
                        "suggestion": "Run editor plugin-upgrade, then relaunch the editor.",
                    }}
                else:
                    raw = bridge.disconnect_material_expression_input(mat, to_expr, to_input)
                    bridge_result = json.loads(raw) if raw else {{"error": "Bridge returned empty result"}}
                    if "error" in bridge_result:
                        result = bridge_result
                    else:
                        mel.recompile_material(mat)
                        mat.modify()
                        result = bridge_result
                        result["from"] = from_node_name
                        result["from_output"] = from_output
                        result["to"] = to_node_name
                        result["to_input"] = bridge_result.get("to_input", to_input)
    except Exception as e:
        result = {{"error": "Disconnect failed: " + str(e)}}
'''


_SCRIPT_GET_PARAM = '''
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
'''

_SCRIPT_SET_PARAM = '''
import unreal
import json

material_path = "{material_path}"
material_candidates = {material_path_candidates_json}
param_name = "{param_name}"
param_type = "{param_type}"
param_value_raw = """{param_value}"""

mat, loaded_asset_path, tried_asset_paths = _cli_load_material(material_path, material_candidates)
if mat is None:
    result = {{"error": "Material not found: " + material_path, "tried": tried_asset_paths}}
elif not isinstance(mat, unreal.MaterialInstanceConstant):
    result = {{"error": "Asset is not a MaterialInstanceConstant (set-param only works on MI): " + loaded_asset_path}}
else:
    mel = unreal.MaterialEditingLibrary
    try:
        set_return = None
        if param_type == "scalar":
            val = float(param_value_raw)
            set_return = mel.set_material_instance_scalar_parameter_value(mat, param_name, val)
            mat.modify()
            result = {{"status": "ok", "action": "set_param", "material": loaded_asset_path, "param": param_name, "type": "scalar", "value": val, "set_return": set_return}}
        elif param_type == "vector":
            parts = json.loads(param_value_raw)
            color = unreal.LinearColor(r=float(parts.get("r", 0)), g=float(parts.get("g", 0)), b=float(parts.get("b", 0)), a=float(parts.get("a", 1)))
            set_return = mel.set_material_instance_vector_parameter_value(mat, param_name, color)
            mat.modify()
            result = {{"status": "ok", "action": "set_param", "material": loaded_asset_path, "param": param_name, "type": "vector", "value": parts, "set_return": set_return}}
        elif param_type == "texture":
            tex = unreal.EditorAssetLibrary.load_asset(param_value_raw)
            if tex is None:
                result = {{"error": "Texture not found: " + param_value_raw}}
            else:
                set_return = mel.set_material_instance_texture_parameter_value(mat, param_name, tex)
                mat.modify()
                result = {{"status": "ok", "action": "set_param", "material": loaded_asset_path, "param": param_name, "type": "texture", "value": param_value_raw, "set_return": set_return}}
        else:
            result = {{"error": "Unknown param_type: " + param_type + ". Use scalar, vector, or texture."}}
        if "error" not in result:
            save_errors = []
            saved = False
            try:
                mat.modify()
            except Exception as e:
                save_errors.append("modify: " + str(e))
            try:
                saved = bool(unreal.EditorAssetLibrary.save_loaded_asset(mat, only_if_is_dirty=False))
            except Exception as e:
                save_errors.append("save_loaded_asset: " + str(e))
            if not saved:
                try:
                    saved = bool(unreal.EditorLoadingAndSavingUtils.save_dirty_packages(False, True))
                except Exception as e:
                    save_errors.append("save_dirty_packages: " + str(e))
            result["saved"] = saved
            if save_errors:
                result["save_warnings"] = save_errors
    except Exception as e:
        result = {{"error": "set_param failed: " + str(e)}}
'''

_SCRIPT_RECOMPILE = '''
import unreal
import json

material_path = "{material_path}"
material_candidates = {material_path_candidates_json}
mat, loaded_asset_path, tried_asset_paths = _cli_load_material(material_path, material_candidates)
if mat is None:
    result = {{"error": "Material not found: " + material_path, "tried": tried_asset_paths}}
else:
    mel = unreal.MaterialEditingLibrary
    try:
        # Recompile is synchronous on the main thread for the material graph.
        mel.recompile_material(mat)
        mat.modify()
        
        errors = []
        if hasattr(unreal, "CliAnythingBridgeLibrary"):
            bridge = unreal.CliAnythingBridgeLibrary
            errors = list(bridge.get_material_compile_errors(mat))
            
        if len(errors) > 0:
            result = {{
                "status": "error", 
                "action": "recompile", 
                "material": loaded_asset_path,
                "error": "Material compilation failed.",
                "compile_errors": errors
            }}
        else:
            result = {{"status": "ok", "action": "recompile", "material": loaded_asset_path}}
    except Exception as e:
        result = {{"error": "recompile_material failed: " + str(e)}}
'''


# ── Public API ────────────────────────────────────────────────────────

def list_materials(
    api: UEEditorAPI,
    content_path: str = "/Game/",
    project_dir: str | None = None,
) -> dict:
    """List all materials in the project via Remote Control search API.

    Args:
        api: Connected UEEditorAPI instance.
        content_path: Content path to search (e.g., "/Game").
        project_dir: Project directory (unused, kept for API compat).

    Returns:
        {"materials": [{"path": str, "name": str, "class": str, "metadata": dict}, ...]}
    """
    # Normalize path — search API wants no trailing slash
    pkg_path = content_path.rstrip("/")
    if not pkg_path:
        pkg_path = "/Game"

    result = api.search_assets(
        query="",
        class_names=["/Script/Engine.Material", "/Script/Engine.MaterialInstanceConstant"],
        package_paths=[pkg_path],
        recursive=True,
    )

    if "error" in result:
        return result

    assets = result.get("Assets", [])
    materials = []
    for asset in assets:
        materials.append({
            "path": asset.get("Path", ""),
            "name": asset.get("Name", ""),
            "class": asset.get("Class", ""),
            "metadata": asset.get("Metadata", {}),
        })

    return {"materials": materials}


def get_material_info(
    api: UEEditorAPI,
    material_path: str,
    project_dir: str | None = None,
) -> dict:
    """Get detailed information about a material.

    First tries Remote Control search for basic metadata,
    then uses Python script for full node/parameter details.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path (e.g., "/Game/NewMaterial").
        project_dir: Project directory for temp files.

    Returns:
        Dict with material properties, nodes, parameters, etc.
    """
    # Step 1: Get basic info from search API
    # Normalize: "/Game/NewMaterial.NewMaterial" or "/Game/NewMaterial"
    search_name = material_path.split(".")[-1] if "." in material_path else material_path.split("/")[-1]

    search_result = api.search_assets(
        query=search_name,
        class_names=["/Script/Engine.Material", "/Script/Engine.MaterialInstanceConstant"],
        package_paths=["/Game"],
        recursive=True,
    )

    basic_info = {}
    for asset in search_result.get("Assets", []):
        # Match by name or path
        if asset.get("Name") == search_name or material_path in asset.get("Path", ""):
            basic_info = {
                "name": asset.get("Name", ""),
                "path": asset.get("Path", ""),
                "class": asset.get("Class", ""),
                **asset.get("Metadata", {}),
            }
            break

    # Step 2: Python script for deep node/expression info and material properties.
    #         This also reads blend_mode, shading_model, etc. — no need for a
    #         separate Remote Control get_property pass (which would trigger
    #         "AllowPrivateAccess" log spam on private props).
    script_result = _exec_material_script(
        api,
        _SCRIPT_MATERIAL_DETAIL,
        project_dir=project_dir,
        material_path=material_path.rsplit(".", 1)[0] if "." in material_path else material_path,
    )

    if "error" not in script_result:
        # Merge deep info into basic_info (script result has nodes, textures, etc.)
        for key in ("nodes", "node_count", "textures", "texture_sample_count",
                     "blend_mode", "material_domain", "shading_model", "two_sided",
                     "material_outputs", "edges",
                     "scalar_parameters", "vector_parameters", "texture_parameters",
                     "parent"):
            if key in script_result:
                basic_info[key] = script_result[key]
    else:
        # Python script failed — record as note, RC API data still available
        basic_info["detail_note"] = (
            f"Python script unavailable ({script_result['error']}). "
            "Node-level details require the EditorScriptingUtilities / Python plugin. "
            "Basic properties are still available via Remote Control API."
        )

    return basic_info


def get_material_stats(
    api: UEEditorAPI,
    material_path: str,
    project_dir: str | None = None,
) -> dict:
    """Get material compilation statistics.

    Gets info and extracts stats-relevant fields.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path.
        project_dir: Project directory.

    Returns:
        Dict with shader stats.
    """
    info = get_material_info(api, material_path, project_dir)
    if "error" in info:
        return info

    return {
        "path": material_path,
        "name": info.get("name", ""),
        "node_count": info.get("node_count", 0),
        "texture_sample_count": info.get("texture_sample_count", 0),
        "blend_mode": info.get("blend_mode", info.get("BlendMode", "")),
        "shading_model": info.get("shading_model", info.get("ShadingModel", "")),
        "material_domain": info.get("material_domain", info.get("MaterialDomain", "")),
    }


_PLUGIN_GET_ERRORS_SCRIPT = r'''import unreal

material_path = "{material_path}"
material_candidates = {material_path_candidates_json}
mat, loaded_asset_path, tried_asset_paths = _cli_load_material(material_path, material_candidates)
if mat is None:
    result = {{"error": "Material not found: " + material_path, "tried": tried_asset_paths}}
else:
    bridge = unreal.CliAnythingBridgeLibrary
    errors = list(bridge.get_material_compile_errors(mat))
    result = {{
        "errors": errors,
        "warnings": [],
        "material": loaded_asset_path,
        "has_errors": len(errors) > 0,
        "source": "plugin",
    }}
'''

_PLUGIN_GET_HLSL_CODE_SCRIPT = r'''import unreal
import os

mat = unreal.EditorAssetLibrary.load_asset("{material_path}")
if mat is None:
    result = {{"error": "Material not found: {material_path}"}}
else:
    bridge = unreal.CliAnythingBridgeLibrary
    # Construct output path under project Saved/CliAnything/
    _saved = unreal.Paths.project_saved_dir()
    output_path = os.path.join(_saved, "CliAnything", "{mat_name}.ush")
    output_path = output_path.replace("\\\\", "/")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    ret = bridge.get_material_hlsl_code(mat, output_path)
    if ret:
        with open(output_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = len(f.readlines())
        result = {{
            "material": "{material_path}",
            "file": output_path,
            "lines": lines,
            "source": "plugin",
        }}
    else:
        result = {{"error": "GetMaterialHLSLCode returned empty. Material may not be compiled yet."}}
'''

_PLUGIN_GET_SHADER_SOURCE_SCRIPT = r'''import unreal
import os

mat = unreal.EditorAssetLibrary.load_asset("{material_path}")
if mat is None:
    result = {{"error": "Material not found: {material_path}"}}
else:
    bridge = unreal.CliAnythingBridgeLibrary
    # Construct output dir under project Saved/CliAnything/
    _saved = unreal.Paths.project_saved_dir()
    output_dir = os.path.join(_saved, "CliAnything", "{mat_name}_shaders")
    output_dir = output_dir.replace("\\\\", "/")
    os.makedirs(output_dir, exist_ok=True)
    entries = bridge.get_material_shader_source(mat, output_dir)
    shaders = []
    for entry in entries:
        parts = entry.split("\t")
        if len(parts) >= 3:
            shaders.append({{"name": parts[0], "file": parts[1], "lines": int(parts[2])}})
        elif len(parts) >= 2:
            shaders.append({{"name": parts[0], "file": parts[1]}})
    result = {{
        "material": "{material_path}",
        "shader_count": len(shaders),
        "shaders": shaders,
        "output_dir": output_dir,
        "source": "plugin",
    }}
'''


def get_material_errors(
    api: UEEditorAPI,
    material_path: str,
    project_dir: str | None = None,
) -> dict:
    """Get current material compile errors via the CliAnythingBridge plugin.

    Reads the error state from FMaterialResource::GetCompileErrors() without
    triggering a recompile. Call ``recompile_material()`` first if you need
    fresh errors after making changes.

    Requires the bridge plugin to be compiled and loaded in the editor.
    If the plugin is not deployed, it will be auto-deployed and an error
    returned asking the caller to recompile and restart.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path (e.g. /Game/MyMaterial).
        project_dir: Project directory for auto-deploying the plugin.

    Returns:
        {"errors": [...], "warnings": [...], "has_errors": bool, "source": "plugin"}
        or {"error": "..."} if plugin not available.
    """
    if project_dir:
        deploy_result = ensure_plugin_deployed(project_dir)
        if not deploy_result["deployed"]:
            return {"error": deploy_result.get("error", "Plugin deployment failed")}

    result = _exec_material_script(
        api,
        _PLUGIN_GET_ERRORS_SCRIPT,
        timeout=15.0,
        material_path=material_path,
    )

    if "error" in result and "CliAnythingBridgeLibrary" in result.get("error", ""):
        plugin_dir = f"{project_dir}/Plugins/CliAnythingBridge" if project_dir else "<project>/Plugins/CliAnythingBridge"
        return {
            "error": (
                "Bridge plugin not loaded. "
                f"Plugin source has been deployed to {plugin_dir}. "
                "Run 'editor plugin-upgrade' to compile and activate, "
                "or manually recompile the project and restart the editor."
            )
        }

    return result


def get_material_hlsl_code(
    api: UEEditorAPI,
    material_path: str,
    output_path: str | None = None,
    project_dir: str | None = None,
) -> dict:
    """Get the material's HLSL expression source code via the Bridge plugin.

    This calls FMaterialResource::GetMaterialExpressionSource() which returns
    /Engine/Generated/Material.ush — the material's translated HLSL including
    FMaterialPixelParameters struct and all custom node code.

    Output is written to <project>/Saved/CliAnything/<MaterialName>.ush by default.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path (e.g. /Game/M_Test).
        output_path: Optional custom output path. Defaults to project Saved dir.
        project_dir: Project directory for auto-deploying the plugin.

    Returns:
        {"material": str, "file": str, "lines": int, "source": "plugin"}
    """
    if project_dir:
        deploy_result = ensure_plugin_deployed(project_dir)
        if not deploy_result["deployed"]:
            return {"error": deploy_result.get("error", "Plugin deployment failed")}

    mat_name = material_path.rsplit("/", 1)[-1].split(".")[0]

    result = _exec_material_script(
        api,
        _PLUGIN_GET_HLSL_CODE_SCRIPT,
        timeout=60.0,
        material_path=material_path,
        mat_name=mat_name,
    )

    if "error" in result and "CliAnythingBridgeLibrary" in result.get("error", ""):
        plugin_dir = f"{project_dir}/Plugins/CliAnythingBridge" if project_dir else "<project>/Plugins/CliAnythingBridge"
        return {
            "error": (
                "Bridge plugin not loaded. "
                f"Plugin source has been deployed to {plugin_dir}. "
                "Run 'editor plugin-upgrade' to compile and activate, "
                "or manually recompile the project and restart the editor."
            )
        }

    return result


def get_material_shader_source(
    api: UEEditorAPI,
    material_path: str,
    output_dir: str | None = None,
    project_dir: str | None = None,
) -> dict:
    """Get the compiled shader source (.usf files) for a material via the Bridge plugin.

    This forces a synchronous recompile with bExtractShaderSource=true,
    then writes each compiled shader (BasePassPS, BasePassVS, LumenCardPS, etc.)
    to a .usf file. Output goes to <project>/Saved/CliAnything/<MaterialName>_shaders/ by default.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path (e.g. /Game/M_Test).
        output_dir: Optional custom output directory. Defaults to project Saved dir.
        project_dir: Project directory for auto-deploying the plugin.

    Returns:
        {"material": str, "shader_count": int, "shaders": [...], "output_dir": str}
    """
    if project_dir:
        deploy_result = ensure_plugin_deployed(project_dir)
        if not deploy_result["deployed"]:
            return {"error": deploy_result.get("error", "Plugin deployment failed")}

    mat_name = material_path.rsplit("/", 1)[-1].split(".")[0]

    result = _exec_material_script(
        api,
        _PLUGIN_GET_SHADER_SOURCE_SCRIPT,
        timeout=120.0,
        material_path=material_path,
        mat_name=mat_name,
    )

    if "error" in result and "CliAnythingBridgeLibrary" in result.get("error", ""):
        plugin_dir = f"{project_dir}/Plugins/CliAnythingBridge" if project_dir else "<project>/Plugins/CliAnythingBridge"
        return {
            "error": (
                "Bridge plugin not loaded. "
                f"Plugin source has been deployed to {plugin_dir}. "
                "Run 'editor plugin-upgrade' to compile and activate, "
                "or manually recompile the project and restart the editor."
            )
        }

    return result


def get_material_texture_list(
    api: UEEditorAPI,
    material_path: str,
    project_dir: str | None = None,
) -> dict:
    """List all textures referenced by a material.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path.
        project_dir: Project directory.

    Returns:
        {"textures": [...]}
    """
    info = get_material_info(api, material_path, project_dir)
    if "error" in info:
        return info

    textures = info.get("textures", [])
    tex_params = info.get("texture_parameters", [])

    # Merge texture parameters into list
    all_textures = list(textures)
    for tp in tex_params:
        all_textures.append({
            "parameter_name": tp.get("name", ""),
            "path": tp.get("texture"),
            "name": tp.get("texture", "").split(".")[-1] if tp.get("texture") else None,
        })

    return {"textures": all_textures, "material": material_path}


def get_material_connections(
    api: UEEditorAPI,
    material_path: str,
    project_dir: str | None = None,
) -> dict:
    """Get the full material node connection graph.

    Builds a complete topology from node-to-node edges (via
    ``get_inputs_for_material_expression``) and material output pin
    connections. A node is "connected" if it's reachable (directly or
    transitively) from any material output; otherwise it's "orphan".

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path (e.g., "/Game/M_Water").
        project_dir: Project directory for temp files.

    Returns:
        {
            "material": str,
            "material_outputs": {"BaseColor": {"node": ..}, ..},
            "edges": [{"from_node": str, "to_node": str, "to_input_index": int}, ..],
            "nodes": [{"name": str, "type": str, ..}, ..],
            "node_count": int,
            "connected_nodes": [str, ..],
            "orphan_nodes": [str, ..],
        }
    """
    info = get_material_info(api, material_path, project_dir)
    if "error" in info:
        return info

    mat_outputs = info.get("material_outputs", {})
    nodes = info.get("nodes", [])
    edges = info.get("edges", [])

    # Build reverse adjacency: node → set of nodes that feed into it
    # We need forward lookup: from a "sink" node, find all upstream nodes
    upstream = {}  # node_name → set of upstream node_names
    for e in edges:
        upstream.setdefault(e["to_node"], set()).add(e["from_node"])

    # Seed: nodes directly connected to material output pins
    seeds = {v["node"] for v in mat_outputs.values() if isinstance(v, dict)}

    # Also treat custom output nodes as seeds (SLW, Strata, etc.)
    for n in nodes:
        t = n.get("type", "")
        if "Output" in t and t != "MaterialExpressionCustomOutput":
            seeds.add(n["name"])

    # BFS backwards through edges to find all transitively connected nodes
    connected = set()
    queue = list(seeds)
    while queue:
        name = queue.pop()
        if name in connected:
            continue
        connected.add(name)
        for src in upstream.get(name, []):
            if src not in connected:
                queue.append(src)

    all_names = {n["name"] for n in nodes}
    orphan_names = sorted(all_names - connected)

    return {
        "material": material_path,
        "material_outputs": mat_outputs,
        "edges": edges,
        "nodes": nodes,
        "node_count": len(nodes),
        "connected_nodes": sorted(connected),
        "orphan_nodes": orphan_names,
        "orphan_count": len(orphan_names),
    }


def analyze_material(
    api: UEEditorAPI,
    material_path: str,
    project_dir: str | None = None,
) -> dict:
    """Comprehensive material analysis — detect common issues.

    Checks:
    - Instruction count warnings
    - Too many texture samples (>16)
    - Missing texture references
    - Blend mode / transparency mismatch
    - High node count
    - Large texture dimensions

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path.
        project_dir: Project directory.

    Returns:
        {"issues": [...], "warnings": [...], "stats": {...}, "info": {...}}
    """
    issues = []
    warnings = []

    # Get full material info
    info = get_material_info(api, material_path, project_dir)
    if "error" in info:
        return {"issues": [info["error"]], "warnings": [], "stats": {}, "info": info}

    # ── Analysis rules ────────────────────────────────────────────────

    # Check texture sample count
    tex_count = info.get("texture_sample_count", 0)
    if tex_count > 16:
        issues.append(
            f"Texture sample count ({tex_count}) exceeds recommended maximum of 16"
        )
    elif tex_count > 12:
        warnings.append(
            f"Texture sample count ({tex_count}) approaching limit (max 16)"
        )
    elif tex_count > 8:
        warnings.append(
            f"Texture sample count ({tex_count}) approaching mobile limit"
        )

    # Check total node count
    node_count = info.get("node_count", 0)
    if node_count > 200:
        issues.append(f"Very high node count ({node_count}) - consider simplifying")
    elif node_count > 100:
        warnings.append(f"High node count ({node_count})")

    # Check for missing textures
    for tex in info.get("textures", []):
        if tex.get("path") is None or tex.get("name") is None:
            issues.append(f"Missing texture reference in node: {tex.get('node_type', 'unknown')}")

    # Check texture sizes
    for tex in info.get("textures", []):
        size_x = tex.get("size_x", 0)
        size_y = tex.get("size_y", 0)
        if size_x > 4096 or size_y > 4096:
            warnings.append(
                f"Large texture '{tex.get('name', '?')}': {size_x}x{size_y} "
                f"(consider downscaling for performance)"
            )

    # Check blend mode
    blend_mode = info.get("blend_mode", info.get("BlendMode", ""))
    if "Translucent" in str(blend_mode) and tex_count > 4:
        warnings.append(
            "Translucent material with many texture samples may cause overdraw issues"
        )

    # Check material output connections (agent's most requested analysis)
    mat_outputs = info.get("material_outputs", {})
    if mat_outputs:
        connected_names = {v["node"] for v in mat_outputs.values() if isinstance(v, dict)}
        all_names = {n["name"] for n in info.get("nodes", [])}
        orphan_names = all_names - connected_names
        if orphan_names and len(orphan_names) > node_count * 0.5 and node_count > 5:
            warnings.append(
                f"{len(orphan_names)}/{node_count} nodes not directly connected to "
                f"any material output (may be intermediate or unused)"
            )
    elif "material_outputs_error" not in info and node_count > 0:
        warnings.append(
            "No material output connections detected — material may produce no visible output"
        )

    # Check for duplicate Custom nodes (common when rebuilding materials)
    custom_nodes = [n for n in info.get("nodes", []) if n.get("type") == "MaterialExpressionCustom"]
    if len(custom_nodes) > 5:
        warnings.append(
            f"High number of Custom HLSL nodes ({len(custom_nodes)}) — "
            "review for duplicates from prior edits"
        )

    stats = {
        "texture_sample_count": tex_count,
        "node_count": node_count,
        "texture_count": len(info.get("textures", [])),
        "blend_mode": str(blend_mode),
        "shading_model": info.get("shading_model", info.get("ShadingModel", "")),
        "material_domain": info.get("material_domain", info.get("MaterialDomain", "")),
        "connected_outputs": list(mat_outputs.keys()) if mat_outputs else [],
        "custom_node_count": len(custom_nodes),
    }

    return {
        "material": material_path,
        "issues": issues,
        "warnings": warnings,
        "stats": stats,
        "info": info,
    }


# ── Material editing (via MaterialEditingLibrary) ────────────────────

def add_material_node(
    api: UEEditorAPI,
    material_path: str,
    expression_class: str,
    pos_x: int = 0,
    pos_y: int = 0,
    set_props: list[tuple[str, str]] | None = None,
    add_input_names: list[str] | None = None,
    project_dir: str | None = None,
) -> dict:
    """Add a new material expression node.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path (e.g., "/Game/M_Test").
        expression_class: UE expression class name
            (e.g., "MaterialExpressionConstant3Vector").
        pos_x: Node X position in the material graph.
        pos_y: Node Y position in the material graph.
        set_props: List of (key, value) pairs to set on the node via set_editor_property.
        add_input_names: List of input names to add (for MaterialExpressionCustom).
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "node": {"name": str, "type": str}} or {"error": str}
    """
    return _exec_material_script(
        api,
        _SCRIPT_ADD_NODE,
        project_dir=project_dir,
        material_path=material_path,
        expression_class=expression_class,
        pos_x=str(pos_x),
        pos_y=str(pos_y),
        set_props=repr(set_props or []),
        add_input_names=repr(add_input_names or []),
    )


def delete_material_node(
    api: UEEditorAPI,
    material_path: str,
    node_name: str,
    project_dir: str | None = None,
) -> dict:
    """Delete a material expression node by name.

    Use ``material info`` to find node names first.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path.
        node_name: Name of the expression to delete (e.g., "Constant3Vector_0").
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "deleted_node": str} or {"error": str}
    """
    return _exec_material_script(
        api,
        _SCRIPT_DELETE_NODE,
        project_dir=project_dir,
        material_path=material_path,
        node_name=node_name,
    )


def rename_custom_input(
    api: UEEditorAPI,
    material_path: str,
    node_name: str,
    old_name: str,
    new_name: str,
    update_code: bool = True,
    project_dir: str | None = None,
) -> dict:
    """Rename a MaterialExpressionCustom input variable.

    Custom node HLSL variable names come from ``inputs[].input_name``.
    MaterialInstance parameter names and node display text do not rename
    those variables. This helper updates the real Custom input name and,
    by default, rewrites whole-word HLSL references from old_name to new_name.
    """
    return _exec_material_script(
        api,
        _SCRIPT_RENAME_CUSTOM_INPUT,
        project_dir=project_dir,
        material_path=repr(material_path),
        node_name=repr(node_name),
        old_name=repr(old_name),
        new_name=repr(new_name),
        update_code=repr(bool(update_code)),
    )


def connect_material_nodes(
    api: UEEditorAPI,
    material_path: str,
    from_node: str,
    from_output: str,
    to_node: str,
    to_input: str,
    project_dir: str | None = None,
) -> dict:
    """Connect two material expression nodes.

    To connect to a material output pin (BaseColor, Normal, etc.),
    use ``to_node="__material_output__"`` and ``to_input="BaseColor"``.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path.
        from_node: Source expression name.
        from_output: Source output pin name (often "" for single-output nodes).
        to_node: Target expression name, or "__material_output__".
        to_input: Target input pin name, or material property name.
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "action": "connect", ...} or {"error": str}
    """
    return _exec_material_script(
        api,
        _SCRIPT_CONNECT,
        project_dir=project_dir,
        material_path=material_path,
        from_node=from_node,
        from_output=from_output,
        to_node=to_node,
        to_input=to_input,
    )


def disconnect_material_nodes(
    api: UEEditorAPI,
    material_path: str,
    from_node: str,
    from_output: str,
    to_node: str,
    to_input: str,
    project_dir: str | None = None,
) -> dict:
    """Disconnect material expression nodes.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path.
        from_node: Source expression name.
        from_output: Source output pin name.
        to_node: Target expression name, or "__material_output__".
        to_input: Target input pin name, or material property name.
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "action": "disconnect", ...} or {"error": str}
    """
    return _exec_material_script(
        api,
        _SCRIPT_DISCONNECT,
        project_dir=project_dir,
        material_path=material_path,
        from_node=from_node,
        from_output=from_output,
        to_node=to_node,
        to_input=to_input,
    )



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


def set_material_param(
    api: UEEditorAPI,
    material_path: str,
    param_name: str,
    param_value: str,
    param_type: str = "scalar",
    project_dir: str | None = None,
) -> dict:
    """Set a parameter value on a MaterialInstanceConstant.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path to a MaterialInstanceConstant.
        param_name: Parameter name (e.g., "Roughness").
        param_value: Value as string. For scalar: "0.5".
            For vector: '{"r":1,"g":0,"b":0,"a":1}'.
            For texture: "/Game/Textures/T_Diffuse".
        param_type: "scalar", "vector", or "texture".
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", ...} or {"error": str}
    """
    return _exec_material_script(
        api,
        _SCRIPT_SET_PARAM,
        project_dir=project_dir,
        material_path=material_path,
        param_name=param_name,
        param_value=param_value,
        param_type=param_type,
    )


def recompile_material(
    api: UEEditorAPI,
    material_path: str,
    project_dir: str | None = None,
) -> dict:
    """Recompile a material.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path.
        project_dir: Project directory for temp files.

    Returns:
        {"status": "ok", "action": "recompile"} or {"error": str}
    """
    return _exec_material_script(
        api,
        _SCRIPT_RECOMPILE,
        project_dir=project_dir,
        material_path=material_path,
    )


# ── Shader / HLSL code ──────────────────────────────────────────────

# Map user-friendly platform names to UE ShaderDebugInfo directory names
SHADER_PLATFORMS = {
    "sm6":       "PCD3D_SM6",
    "sm5":       "PCD3D_SM5",
    "vulkan":    "VULKAN_SM5",
    "vulkan_sm5": "VULKAN_SM5",
    "vulkan_android": "VULKAN_SM5_ANDROID",
    "vulkan_es31": "VULKAN_ES3_1_ANDROID",
    "opengl_es31": "OPENGL_ES3_1_ANDROID",
    "metal":     "METAL_SM5",
    "metal_sm5": "METAL_SM5",
}


def get_material_hlsl(
    api: UEEditorAPI,
    material_path: str,
    project_dir: str | None = None,
    platform: str = "sm6",
    shader_type: str = "pixel",
) -> dict:
    """Get the compiled HLSL/USF shader code for a material.

    First checks if a shader dump already exists in ShaderDebugInfo.
    If not, enables r.DumpShaderDebugInfo and triggers RecompileShaders
    to generate one. The CVar is saved and restored afterwards.

    Args:
        api: Connected UEEditorAPI instance.
        material_path: Content path (e.g., "/Game/TestVP/M_TestPP").
        project_dir: Project directory (to find ShaderDebugInfo).
        platform: Shader platform: "sm6" (default), "sm5", "vulkan", etc.
        shader_type: "pixel" (PS), "vertex" (VS), "all", or specific pass name.

    Returns:
        {
            "material": str,
            "platform": str,
            "shaders": [{"pass": str, "type": str, "file": str, "lines": int}, ...],
            "material_code": str,  # Extracted CalcPixelMaterialInputs section
        }
    """
    if not project_dir:
        return {"error": "project_dir required to locate ShaderDebugInfo"}

    # Resolve platform name
    platform_dir_name = SHADER_PLATFORMS.get(platform.lower(), platform)

    # Normalize material path
    if "." in material_path:
        mat_name = material_path.split(".")[-1]
    else:
        mat_name = material_path.rsplit("/", 1)[-1]
        material_path = f"{material_path}.{mat_name}"

    debug_base = Path(project_dir) / "Saved" / "ShaderDebugInfo" / platform_dir_name

    # ── Step 1: Check if dump already exists ───────────────────────
    dump_dir = _find_shader_dump_dir(debug_base, mat_name)

    # ── Step 2: If no dump, trigger one ────────────────────────────
    if not dump_dir:
        # Save original CVar
        old_value = api.get_cvar("r.DumpShaderDebugInfo")

        try:
            api.set_cvar("r.DumpShaderDebugInfo", "1")
            time.sleep(0.5)

            # Load the material asset first
            api.call_function(
                "/Script/EditorScriptingUtilities.Default__EditorAssetLibrary",
                "LoadAsset",
                {"AssetPath": material_path.rsplit(".", 1)[0]},
            )
            time.sleep(0.5)

            # Trigger recompile - use "RecompileShaders material <name>"
            # for targeted recompile, falls back to "all" if needed
            api.exec_console(f"RecompileShaders material {mat_name}")

            # Wait for dump to appear (shader compilation is async)
            deadline = time.time() + 120  # up to 2 min for large materials
            while time.time() < deadline:
                dump_dir = _find_shader_dump_dir(debug_base, mat_name)
                if dump_dir:
                    # Verify .usf files exist
                    usf_files = list(dump_dir.rglob("*.usf"))
                    if usf_files:
                        # Wait a bit more to ensure all files are written
                        time.sleep(2)
                        break
                time.sleep(3)

        finally:
            # Restore CVar
            restore_val = str(old_value) if old_value and old_value != "0" else "0"
            api.set_cvar("r.DumpShaderDebugInfo", restore_val)

    if not dump_dir or not dump_dir.exists():
        available = []
        shader_debug_root = Path(project_dir) / "Saved" / "ShaderDebugInfo"
        if shader_debug_root.is_dir():
            available = [d.name for d in shader_debug_root.iterdir() if d.is_dir()]

        return {
            "error": f"No shader dump found for '{mat_name}' on platform '{platform_dir_name}'. "
                     "Shader compilation may still be in progress. "
                     "Try again in a minute, or run: RecompileShaders all (with r.DumpShaderDebugInfo=1)",
            "available_platforms": available,
        }

    # ── Step 3: Read shader files ──────────────────────────────────
    return _read_shader_dump(dump_dir, mat_name, material_path,
                             platform_dir_name, shader_type, project_dir)


def _find_shader_dump_dir(debug_base: Path, mat_name: str) -> Optional[Path]:
    """Find the shader dump directory for a material.

    Dump dirs are named like: MaterialName_hexhash

    Returns:
        Path to dump directory, or None.
    """
    if not debug_base.is_dir():
        return None
    for d in debug_base.iterdir():
        if d.is_dir() and d.name.startswith(f"{mat_name}_"):
            return d
    return None


def _read_shader_dump(
    dump_dir: Path,
    mat_name: str,
    material_path: str,
    platform_dir_name: str,
    shader_type: str,
    project_dir: str,
) -> dict:
    """Read shader dump files and extract material code."""

    shaders = []
    type_filter = shader_type.lower()

    for usf_file in sorted(dump_dir.rglob("*.usf")):
        rel = usf_file.relative_to(dump_dir)
        parts = list(rel.parts)

        # Directory structure: Default/VertexFactory/ShaderType/hash/file.usf
        # ShaderType is the one that contains PS/VS (e.g. TBasePassPSFNoLightMapPolicy)
        shader_class = ""
        for p in reversed(parts):
            if "PS" in p or "VS" in p or "GS" in p or "CS" in p:
                shader_class = p
                break
        if not shader_class and len(parts) >= 3:
            shader_class = parts[-3] if len(parts) >= 4 else parts[-2]

        is_ps = "PS" in shader_class and "VS" not in shader_class
        is_vs = "VS" in shader_class and "PS" not in shader_class

        if type_filter == "pixel" and not is_ps:
            continue
        elif type_filter == "vertex" and not is_vs:
            continue

        shaders.append({
            "pass": shader_class,
            "type": "PS" if is_ps else ("VS" if is_vs else "Other"),
            "file": str(usf_file),
            "lines": sum(1 for _ in open(usf_file, encoding="utf-8", errors="replace")),
        })

    # Extract material-specific code from best PS shader
    # Prefer BasePass PS (has the full material code), then PostProcess, then any PS
    material_code = ""
    first_ps = None
    for priority in ["TBasePassPS", "FPostProcessMaterial", "PS"]:
        for s in shaders:
            if s["type"] == "PS" and priority in s["pass"]:
                first_ps = s
                break
        if first_ps:
            break
    if not first_ps:
        first_ps = next((s for s in shaders if s["type"] == "PS"), None)
    if not first_ps and shaders:
        first_ps = shaders[0]

    if first_ps:
        full_code = Path(first_ps["file"]).read_text(encoding="utf-8", errors="replace")
        first_ps["code"] = full_code
        material_code = _extract_material_code(full_code)

    # Available platforms
    available_platforms = []
    shader_debug_root = Path(project_dir) / "Saved" / "ShaderDebugInfo"
    if shader_debug_root.is_dir():
        available_platforms = [d.name for d in shader_debug_root.iterdir() if d.is_dir()]

    return {
        "material": material_path,
        "platform": platform_dir_name,
        "available_platforms": available_platforms,
        "dump_dir": str(dump_dir),
        "shader_count": len(shaders),
        "shaders": shaders,
        "material_code": material_code,
    }


def _extract_material_code(hlsl_code: str) -> str:
    """Extract the material-graph-generated section from full HLSL code.

    Looks for CalcPixelMaterialInputs() which contains the compiled
    material node graph.

    Args:
        hlsl_code: Full .usf file content.

    Returns:
        Extracted material code section, or empty string.
    """
    lines = hlsl_code.split("\n")

    # Find CalcPixelMaterialInputs or CalcMaterialParameters
    start_idx = -1
    for i, line in enumerate(lines):
        if "void CalcPixelMaterialInputs" in line or "void CalcMaterialParameters" in line:
            start_idx = i
            break

    if start_idx < 0:
        return ""

    # Find the matching closing brace
    brace_depth = 0
    end_idx = start_idx
    for i in range(start_idx, len(lines)):
        brace_depth += lines[i].count("{") - lines[i].count("}")
        if brace_depth == 0 and i > start_idx:
            end_idx = i
            break

    if end_idx <= start_idx:
        # Fallback: take 200 lines from start
        end_idx = min(start_idx + 200, len(lines) - 1)

    return "\n".join(lines[start_idx:end_idx + 1])


# ── Internal helpers ──────────────────────────────────────────────────

def _exec_material_script(
    api: UEEditorAPI,
    script_template: str,
    project_dir: str | None = None,
    timeout: float = 30.0,
    **kwargs,
) -> dict:
    """Execute a material query Python script in the editor and read results.

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

    material_path = kwargs.get("material_path")
    if isinstance(material_path, str) and material_path.startswith("/"):
        kwargs.setdefault("material_path_json", json.dumps(material_path, ensure_ascii=False))
        kwargs.setdefault(
            "material_path_candidates_json",
            json.dumps(_material_asset_path_candidates(material_path), ensure_ascii=False),
        )
    script_content = _MATERIAL_RESOLVER + "\n" + script_template.format(**kwargs)
    return run_python_code(api, script_content, timeout=timeout)
