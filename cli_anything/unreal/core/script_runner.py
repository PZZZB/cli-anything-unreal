"""script_runner.py — Generic Python script execution with result capture.

Extracted from the ``_exec_material_script`` / ``_exec_blueprint_script``
pattern so that **any** Python code can be executed inside the Unreal Editor
and its structured result returned to the CLI.

Usage
-----
::

    from cli_anything.unreal.core.script_runner import run_python_script, run_python_code

    # Execute a .py file
    result = run_python_script(api, "/tmp/build_scene.py", project_dir=proj)

    # Execute an inline code string
    result = run_python_code(api, "result = {'actors': 42}", project_dir=proj)

Script convention
-----------------
* The user script should assign a ``result`` variable (preferably a *dict*).
* The runner wraps the user code in a try/except, redirects ``sys.stdout``
  to capture all ``print()`` output, serialises the combined result via
  ``unreal.log(json.dumps(result))``, and calls
  ``PythonScriptLibrary.ExecutePythonCommandEx`` to capture the output
  inline — **no temp files or polling required**.
* If ``result`` is not defined the capture block records a generic "ok" status.
* If ``result`` is a *dict*, its keys are merged into the top-level result
  alongside the ``"stdout"`` field. If ``result`` is not a *dict* it is
  wrapped as ``{"value": …}``.
* All ``print()`` output is captured under the ``"stdout"`` key in the result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

# Sentinel used in the wrapper to distinguish "result was JSON-logged" from
# other unreal.log() calls the user script may make.
_RESULT_MARKER = "__cli_result__:"

# Keep user execution isolated so temporary names like ``mat`` or ``custom`` do
# not persist across separate Remote Control Python calls and accidentally keep
# UObjects alive in the editor process.
_USER_NS_NAME = "_cli_user_ns"

# ── Wrapper template ────────────────────────────────────────────────
# The user code is inserted at {user_code}.  The wrapper:
#   1. Runs user code inside try/except.
#   2. Captures the ``result`` variable (or a default).
#   3. Logs a single marked JSON line via ``unreal.log()``.
# The marker prefix lets the CLI-side reliably pick the result out of
# potentially many log lines the user script may emit.
_WRAPPER_TEMPLATE = '''\
import json as _cli_json, traceback as _cli_tb, unreal as _cli_unreal
import sys as _cli_sys, io as _cli_io

_cli_error = None
_cli_traceback = None
_cli_captured_stdout = ""
_cli_old_stdout = _cli_sys.stdout
_cli_string_io = _cli_io.StringIO()
_cli_sys.stdout = _cli_string_io

try:
    {user_ns_name} = {{"__builtins__": __builtins__}}
    {user_ns_name}.update({execution_context_literal})
    exec(compile({user_code_literal}, {source_name_literal}, "exec"), {user_ns_name}, {user_ns_name})
{save_block}
except Exception as _cli_exc:
    _cli_error = _cli_exc
    # Use the exception object directly — sys.exc_info() can be unreliable
    # in UE's embedded Python, causing format_exc() to return "NoneType: None".
    _cli_traceback = "".join(_cli_tb.format_exception(type(_cli_exc), _cli_exc, _cli_exc.__traceback__))
finally:
    _cli_sys.stdout = _cli_old_stdout
    _cli_captured_stdout = _cli_string_io.getvalue()

_cli_result = {{"stdout": _cli_captured_stdout}}
if _cli_error is not None:
    _cli_result.update({{
        "error": str(_cli_error),
        "error_type": type(_cli_error).__name__,
        "traceback": _cli_traceback,
    }})
else:
    try:
        _cli_user_result = {user_ns_name}["result"]
        if isinstance(_cli_user_result, dict):
            _cli_result.update(_cli_user_result)
        else:
            _cli_result["value"] = str(_cli_user_result)
    except KeyError:
        _cli_result["status"] = "ok"

_cli_unreal.log("{marker}" + _cli_json.dumps(_cli_result, default=str))
try:
    {user_ns_name}.clear()
except Exception:
    pass
try:
    del {user_ns_name}
except Exception:
    pass
try:
    del _cli_user_result
except Exception:
    pass
try:
    if isinstance(_cli_result, dict):
        _cli_result.clear()
except Exception:
    pass
try:
    del _cli_result
except Exception:
    pass
for _cli_name in (
    "_cli_error",
    "_cli_traceback",
    "_cli_captured_stdout",
    "_cli_string_io",
    "_cli_old_stdout",
):
    try:
        del globals()[_cli_name]
    except Exception:
        pass
'''

_SAVE_BLOCK = """\
    # ── Auto-save dirty packages without interactive dialog ──
    import unreal as _cli_unreal
    _cli_eal = _cli_unreal.EditorAssetLibrary
    _cli_utils = _cli_unreal.EditorLoadingAndSavingUtils
    _cli_saved = 0
    for _cli_pkg in list(_cli_utils.get_dirty_content_packages()) + list(_cli_utils.get_dirty_map_packages()):
        try:
            _cli_path = _cli_pkg.get_path_name().split('.')[0]
            if _cli_path.startswith('/Game/'):
                _cli_eal.save_asset(_cli_path)
                _cli_saved += 1
        except Exception:
            pass"""


# ── Public API ──────────────────────────────────────────────────────

def run_python_script(
    api: "UEEditorAPI",
    script_path: str,
    project_dir: str | None = None,
    timeout: float = 30.0,
    save: bool = True,
) -> dict:
    """Execute a Python script file in the editor with automatic result capture.

    Parameters
    ----------
    api:
        A connected :class:`UEEditorAPI` instance.
    script_path:
        Path to the ``.py`` file to execute.
    project_dir:
        Unused — kept for backwards compatibility.
    timeout:
        Maximum seconds to wait for the HTTP response.
    save:
        If *True* (default), automatically save all dirty packages after
        the script finishes.

    Returns
    -------
    dict
        Parsed JSON produced by the script, or an error dict on failure.
    """
    resolved_path = Path(script_path).resolve()
    code = resolved_path.read_text(encoding="utf-8")
    return _execute(
        api,
        code,
        timeout=timeout,
        save=save,
        source_path=str(resolved_path),
    )


def run_python_code(
    api: "UEEditorAPI",
    code: str,
    project_dir: str | None = None,
    timeout: float = 30.0,
    save: bool = True,
) -> dict:
    """Execute a Python code string in the editor with automatic result capture.

    Parameters
    ----------
    api:
        A connected :class:`UEEditorAPI` instance.
    code:
        Python source code to execute.
    project_dir:
        Unused — kept for backwards compatibility.
    timeout:
        Maximum seconds to wait for the HTTP response.
    save:
        If *True* (default), automatically save all dirty packages after
        the script finishes.

    Returns
    -------
    dict
        Parsed JSON produced by the script, or an error dict on failure.
    """
    return _execute(api, code, timeout=timeout, save=save)


# ── Internal helpers ────────────────────────────────────────────────

def _execute(
    api: "UEEditorAPI",
    code: str,
    *,
    timeout: float,
    save: bool = True,
    source_path: str | None = None,
) -> dict:
    """Core execution logic shared by *run_python_script* and *run_python_code*.

    Wraps *code* in the standard try/except + result-capture template,
    executes it via ``api.exec_python_ex()`` (which calls
    ``PythonScriptLibrary.ExecutePythonCommandEx``), and extracts the
    JSON result from the captured ``LogOutput``.
    """
    execution_context = {}
    source_name = "<cli_anything_user_code>"
    if source_path is not None:
        execution_context = {
            "__name__": "__main__",
            "__file__": source_path,
        }
        source_name = source_path

    wrapper = _WRAPPER_TEMPLATE.format(
        user_code_literal=json.dumps(code),
        user_ns_name=_USER_NS_NAME,
        execution_context_literal=json.dumps(execution_context),
        source_name_literal=json.dumps(source_name),
        save_block=_SAVE_BLOCK if save else "",
        marker=_RESULT_MARKER,
    )

    resp = api.exec_python_ex(wrapper, timeout=int(timeout))

    if "error" in resp:
        return {"error": resp["error"]}

    if not resp.get("ReturnValue", False):
        return {
            "error": resp.get("CommandResult", "ExecutePythonCommandEx failed"),
        }

    ue_errors = []
    ue_warnings = []
    for entry in resp.get("LogOutput", []):
        log_type = entry.get("Type", "")
        log_out = entry.get("Output", "")
        if log_type == "Error":
            ue_errors.append(log_out)
        elif log_type == "Warning":
            ue_warnings.append(log_out)

    for entry in reversed(resp.get("LogOutput", [])):
        output = entry.get("Output", "")
        if output.startswith(_RESULT_MARKER):
            try:
                res = json.loads(output[len(_RESULT_MARKER):])
                if isinstance(res, dict):
                    if ue_errors:
                        res["ue_errors"] = ue_errors
                    if ue_warnings:
                        res["ue_warnings"] = ue_warnings
                return res
            except json.JSONDecodeError as exc:
                return {"error": f"Malformed JSON result: {exc}", "raw": output}

    res = {"status": "ok", "note": "Script produced no marked result"}
    if ue_errors:
        res["ue_errors"] = ue_errors
    if ue_warnings:
        res["ue_warnings"] = ue_warnings
    return res


# ── API Discovery ────────────────────────────────────────────────────

# Shared reflection logic used by both class-name and instance templates.
# Injected as a function definition at the top of the generated script.
_DISCOVER_FUNC = '''\
import inspect as _cli_inspect, json as _cli_json, re as _cli_re, unreal as _cli_unreal

def _cli_prop_name(_prop):
    try:
        return str(_prop.get_name())
    except Exception:
        return str(getattr(_prop, "name", ""))

def _cli_prop_type(_prop):
    try:
        _fn = getattr(_prop, "get_cpp_type", None)
        if _fn:
            return str(_fn())
    except Exception:
        pass
    return str(_prop.__class__.__name__)

def _cli_prop_tooltip(_prop):
    for _name in ("get_tool_tip_text", "get_tooltip_text"):
        try:
            _fn = getattr(_prop, _name, None)
            if _fn:
                return str(_fn() or "")
        except Exception:
            pass
    return ""

def _cli_format_discovery(_data, _kind, _name, _query=None, _detail=None, _full_path=None):
    _props = _data.get("properties", [])
    _funcs = _data.get("functions", [])
    _target_name = _data.get(_kind, _name)
    if _detail:
        _names = [n.strip() for n in _detail.split(",") if n.strip()]
        _name_set = set(_names)
        _items = []
        _found = set()
        for _p in _props:
            if _p["name"] in _name_set:
                _items.append({"kind": "property", "name": _p["name"], "detail": _p})
                _found.add(_p["name"])
        for _f in _funcs:
            if _f["name"] in _name_set:
                _items.append({"kind": "function", "name": _f["name"], "detail": _f})
                _found.add(_f["name"])
        _out = {_kind: _target_name, "items": _items}
        _not_found = [n for n in _names if n not in _found]
        if _not_found:
            _out["not_found"] = _not_found
    else:
        if _query:
            try:
                _pat = _cli_re.compile(_query, _cli_re.IGNORECASE)
            except _cli_re.error as _e:
                return {"error": "Invalid regex for --query: " + str(_e), "query": _query}
            _funcs = [f for f in _funcs if _pat.search(f["name"])]
            _props = [p for p in _props if _pat.search(p["name"])]
        _out = {
            _kind: _target_name,
            "properties": [_p["name"] for _p in _props],
            "property_count": len(_props),
            "functions": [_f["name"] for _f in _funcs],
            "function_count": len(_funcs),
        }
    if _full_path:
        _out["full_path"] = _full_path
    if _kind == "struct" and _data.get("struct_path"):
        _out["struct_path"] = _data.get("struct_path")
    return _out

def _cli_python_symbol(_target, _target_name, _name):
    try:
        _value = _cli_inspect.getattr_static(_target, _name)
    except Exception:
        return None
    _is_callable = callable(_value)
    try:
        _tooltip = str(getattr(_value, "__doc__", "") or "")
    except Exception:
        _tooltip = ""
    if len(_tooltip) > 1000:
        _tooltip = _tooltip[:1000] + "..."
    return {
        "kind": "function" if _is_callable else "property",
        "name": _name,
        "detail": {
            "name": _name,
            "owner": _target_name,
            "source": "python_binding",
            "python_only": True,
            "tooltip": _tooltip,
        },
    }


def _cli_add_python_symbols(_out, _target, _target_name, _query=None, _detail=None):
    if _target is None or (not _query and not _detail):
        return _out

    if _detail:
        _missing = list(_out.get("not_found", []))
        _python_only = []
        for _name in _missing:
            _item = _cli_python_symbol(_target, _target_name, _name)
            if _item is None:
                continue
            _out.setdefault("items", []).append(_item)
            _python_only.append(_name)
        if _python_only:
            _out["python_only"] = _python_only
            _remaining = [n for n in _missing if n not in _python_only]
            if _remaining:
                _out["not_found"] = _remaining
            else:
                _out.pop("not_found", None)
        return _out

    try:
        _pat = _cli_re.compile(_query, _cli_re.IGNORECASE)
    except _cli_re.error:
        return _out

    _existing = set(_out.get("functions", [])) | set(_out.get("properties", []))
    _python_funcs = []
    _python_props = []
    try:
        _python_names = dir(_target)
    except Exception:
        return _out
    for _name in _python_names:
        if _name.startswith("_") or _name in _existing or not _pat.search(_name):
            continue
        _item = _cli_python_symbol(_target, _target_name, _name)
        if _item is None:
            continue
        if _item["kind"] == "function":
            _python_funcs.append(_name)
        else:
            _python_props.append(_name)

    if _python_funcs:
        _out.setdefault("functions", []).extend(_python_funcs)
        _out["function_count"] = len(_out["functions"])
        _out["python_only_functions"] = _python_funcs
    if _python_props:
        _out.setdefault("properties", []).extend(_python_props)
        _out["property_count"] = len(_out["properties"])
        _out["python_only_properties"] = _python_props
    return _out


def _cli_discover_struct(_struct_name, _query=None, _detail=None, _full_path=None):
    _wrapper = getattr(_cli_unreal, _struct_name, None)
    _struct = None
    if _wrapper is not None:
        try:
            _static_struct = getattr(_wrapper, "static_struct", None)
            if _static_struct:
                _struct = _static_struct()
        except Exception:
            _struct = None
    if _struct is None:
        return None

    _bridge = getattr(_cli_unreal, "CliAnythingBridgeLibrary", None)
    _get_struct_info = getattr(_bridge, "get_struct_info", None) if _bridge else None
    if _get_struct_info:
        try:
            _raw = _get_struct_info(_struct, True)
            if _raw and _raw != "{}":
                _data = _cli_json.loads(_raw)
                return _cli_format_discovery(_data, "struct", _struct_name, _query=_query, _detail=_detail, _full_path=_full_path)
        except Exception as _e:
            return {"error": "Struct reflection failed: " + _struct_name + " (" + str(_e) + ")"}

    try:
        _props = list(_struct.get_properties())
    except Exception as _e:
        return {"error": "Struct properties not readable: " + _struct_name + " (" + str(_e) + ")"}

    _details = []
    for _p in _props:
        _pname = _cli_prop_name(_p)
        if not _pname:
            continue
        _details.append({
            "name": _pname,
            "type": _cli_prop_type(_p),
            "tooltip": _cli_prop_tooltip(_p),
            "owner": _struct_name,
        })

    if _detail:
        _names = [n.strip() for n in _detail.split(",") if n.strip()]
        _name_set = set(_names)
        _items = []
        _found = set()
        for _p in _details:
            if _p["name"] in _name_set:
                _items.append({"kind": "property", "name": _p["name"], "detail": _p})
                _found.add(_p["name"])
        _out = {"struct": _struct_name, "items": _items, "functions": [], "function_count": 0}
        _not_found = [n for n in _names if n not in _found]
        if _not_found:
            _out["not_found"] = _not_found
        if _full_path:
            _out["full_path"] = _full_path
        try:
            _out["struct_path"] = str(_struct.get_path_name())
        except Exception:
            pass
        return _out

    if _query:
        try:
            _pat = _cli_re.compile(_query, _cli_re.IGNORECASE)
        except _cli_re.error as _e:
            return {"error": "Invalid regex for --query: " + str(_e), "query": _query}
        _details = [p for p in _details if _pat.search(p["name"])]

    _out = {
        "struct": _struct_name,
        "properties": [_p["name"] for _p in _details],
        "property_count": len(_details),
        "functions": [],
        "function_count": 0,
    }
    if _full_path:
        _out["full_path"] = _full_path
    try:
        _out["struct_path"] = str(_struct.get_path_name())
    except Exception:
        pass
    return _out

def _cli_discover_class(_class_name, _query=None, _detail=None, _full_path=None):
    _raw = _cli_unreal.CliAnythingBridgeLibrary.get_class_info(_class_name, True)
    if not _raw or _raw == "{}":
        _struct_result = _cli_discover_struct(_class_name, _query=_query, _detail=_detail, _full_path=_full_path)
        if _struct_result is not None:
            return _struct_result
        return {"error": "Class not found; struct not found: " + _class_name}

    _data = _cli_json.loads(_raw)

    if _detail:
        _names = [n.strip() for n in _detail.split(",") if n.strip()]
        _name_set = set(_names)
        _items = []
        _found = set()
        for _p in _data.get("properties", []):
            if _p["name"] in _name_set:
                _items.append({"kind": "property", "name": _p["name"], "detail": _p})
                _found.add(_p["name"])
        for _f in _data.get("functions", []):
            if _f["name"] in _name_set:
                _items.append({"kind": "function", "name": _f["name"], "detail": _f})
                _found.add(_f["name"])
        _not_found = [n for n in _names if n not in _found]
        _out = {"class": _class_name, "items": _items}
        if _not_found:
            _out["not_found"] = _not_found
        return _out

    _funcs = _data.get("functions", [])
    _props = _data.get("properties", [])
    if _query:
        # Case-insensitive regex match (re.search — partial match by default).
        try:
            _pat = _cli_re.compile(_query, _cli_re.IGNORECASE)
        except _cli_re.error as _e:
            return {
                "error": "Invalid regex for --query: " + str(_e),
                "query": _query,
            }
        _funcs = [f for f in _funcs if _pat.search(f["name"])]
        _props = [p for p in _props if _pat.search(p["name"])]

    return {
        "class": _class_name,
        "properties": [_p["name"] for _p in _props],
        "property_count": len(_props),
        "functions": [_f["name"] for _f in _funcs],
        "function_count": len(_funcs),
    }
'''

_API_DISCOVER_CLASS_CALL = '''\
_parts = {target!r}.split(".")
if _parts[0] != "unreal":
    _parts = ["unreal"] + _parts
_class_name = _parts[-1]
_python_target = _cli_unreal
for _part in _parts[1:]:
    _python_target = getattr(_python_target, _part, None)
    if _python_target is None:
        break

result = _cli_discover_class(_class_name, _query={query!r}, _detail={detail!r}, _full_path=".".join(_parts))
if "error" not in result:
    result = _cli_add_python_symbols(
        result, _python_target, _class_name,
        _query={query!r}, _detail={detail!r},
    )
    result["target_name"] = _class_name
    result["python_exposed"] = _python_target is not None
    if _python_target is not None:
        result["full_path"] = ".".join(_parts)
    else:
        result.pop("full_path", None)
'''

_API_DISCOVER_INSTANCE_CALL = '''\
{resolve_block}

if _cli_resolve_ok:
    _discover_result = _cli_discover_class(_resolved_class, _query={query!r}, _detail={detail!r})
    _discover_result = _cli_add_python_symbols(
        _discover_result, _resolved_python_target, _resolved_class,
        _query={query!r}, _detail={detail!r},
    )
    _discover_result.update(_instance_context)
    result = _discover_result
'''

_RESOLVE_ACTOR = '''\
_cli_resolve_ok = False
_subsystem_class = getattr(_cli_unreal, "EditorActorSubsystem", None)
if _subsystem_class is not None:
    _level_actors = _cli_unreal.get_editor_subsystem(_subsystem_class).get_all_level_actors()
else:
    _level_actors = _cli_unreal.EditorLevelLibrary.get_all_level_actors()
_target = None
for _a in _level_actors:
    if _a.get_path_name() == {actor_path!r}:
        _target = _a
        break

if _target is None:
    result = {{"error": "Actor not found: " + {actor_path!r}}}
else:
    _resolved_class = _target.__class__.__name__
    _resolved_python_target = _target.__class__
    _instance_context = {{
        "actor": _target.get_path_name(),
        "actor_name": _target.get_name(),
        "actor_label": _target.get_actor_label(),
    }}
    # Components tree — mirrors the Details panel's Components section.
    # Use the Bridge plugin's C++ helper so the output matches AActor::GetComponents()
    # exactly (including attach parents and native/BP flags).
    try:
        _comp_raw = _cli_unreal.CliAnythingBridgeLibrary.get_actor_component_tree(_target)
        _instance_context["components"] = _cli_json.loads(_comp_raw)
    except Exception as _e:
        _instance_context["components"] = []
        _instance_context["components_error"] = str(_e)
    if _instance_context["components"]:
        _instance_context["hint"] = (
            "This actor has components. To inspect a component's properties, "
            "run: api-discover <component.path> (paths are in components[].path)."
        )
    _cli_resolve_ok = True
'''

_RESOLVE_ASSET = '''\
_cli_resolve_ok = False
_cli_asset_path = {asset_path!r}


def _cli_asset_path_candidates(_path):
    _base = str(_path).strip().split(":", 1)[0]
    if not _base:
        return [_base]
    _candidates = []

    def _add(_candidate):
        if _candidate and _candidate not in _candidates:
            _candidates.append(_candidate)

    _leaf = _base.rsplit("/", 1)[-1]
    if "." in _leaf:
        _add(_base)
        _add(_base.rsplit(".", 1)[0])
    else:
        _add(_base)
        _add(_base + "." + _leaf)
    return _candidates


def _cli_is_package_object(_obj):
    try:
        return _obj.__class__.__name__ == "Package"
    except Exception:
        return False


def _cli_object_context(_obj, _requested_path):
    _ctx = {{
        "object": _requested_path,
        "object_path": _obj.get_path_name(),
    }}
    try:
        _ctx["object_name"] = _obj.get_name()
    except Exception:
        pass
    if ":" not in _requested_path:
        _ctx["asset"] = _requested_path
    return _ctx


def _cli_asset_context(_asset, _requested_path):
    _ctx = {{
        "asset": _requested_path,
        "object_path": _asset.get_path_name(),
    }}
    try:
        _ctx["object_name"] = _asset.get_name()
    except Exception:
        pass
    return _ctx

_cli_obj = None
try:
    _cli_obj = _cli_unreal.find_object(None, _cli_asset_path)
except Exception:
    _cli_obj = None

if _cli_obj is not None and not _cli_is_package_object(_cli_obj):
    _resolved_class = _cli_obj.__class__.__name__
    _resolved_python_target = _cli_obj.__class__
    _instance_context = _cli_object_context(_cli_obj, _cli_asset_path)
    _cli_resolve_ok = True
elif ":" in _cli_asset_path:
    result = {{"error": "Object not found: " + {asset_path!r}}}
else:
    _asset = None
    _loaded_asset_path = None
    _tried_asset_paths = []
    for _candidate in _cli_asset_path_candidates(_cli_asset_path):
        if not _candidate or _candidate in _tried_asset_paths:
            continue
        _tried_asset_paths.append(_candidate)
        try:
            _asset = _cli_unreal.EditorAssetLibrary.load_asset(_candidate)
        except Exception:
            _asset = None
        if _asset is None:
            try:
                _asset = _cli_unreal.load_asset(_candidate)
            except Exception:
                _asset = None
        if _asset is None:
            try:
                _asset = _cli_unreal.load_object(None, _candidate)
            except Exception:
                _asset = None
        if _asset is None:
            try:
                _asset = _cli_unreal.find_object(None, _candidate)
            except Exception:
                _asset = None
        if _asset is not None and not _cli_is_package_object(_asset):
            _loaded_asset_path = _candidate
            break
        _asset = None

    if _asset is None:
        result = {{
            "error": "Asset not found: " + {asset_path!r},
            "tried": _tried_asset_paths,
            "suggestion": "Use a package path like /Game/A or a full object path like /Game/A.A.",
        }}
    else:
        _resolved_class = _asset.__class__.__name__
        _resolved_python_target = _asset.__class__
        _instance_context = _cli_asset_context(_asset, _cli_asset_path)
        _cli_resolve_ok = True
'''


# Resolve a component subobject path of the form
#   /Game/.../Map.Map:PersistentLevel.ActorName.ComponentName
# by locating the owning actor, then matching a child UActorComponent by name.
_RESOLVE_COMPONENT = '''\
_cli_resolve_ok = False
_cli_comp_path = {component_path!r}
_cli_split = _cli_comp_path.rsplit(".", 1)
if len(_cli_split) != 2:
    result = {{"error": "Invalid component path: " + _cli_comp_path}}
else:
    _cli_actor_path, _cli_comp_name = _cli_split
    _subsystem_class = getattr(_cli_unreal, "EditorActorSubsystem", None)
    if _subsystem_class is not None:
        _level_actors = _cli_unreal.get_editor_subsystem(_subsystem_class).get_all_level_actors()
    else:
        _level_actors = _cli_unreal.EditorLevelLibrary.get_all_level_actors()
    _cli_actor = None
    for _a in _level_actors:
        if _a.get_path_name() == _cli_actor_path:
            _cli_actor = _a
            break
    if _cli_actor is None:
        result = {{"error": "Owning actor not found: " + _cli_actor_path}}
    else:
        _cli_comp = None
        for _c in _cli_actor.get_components_by_class(_cli_unreal.ActorComponent):
            if _c.get_name() == _cli_comp_name:
                _cli_comp = _c
                break
        if _cli_comp is None:
            result = {{"error": "Component not found: " + _cli_comp_name + " on " + _cli_actor_path}}
        else:
            _resolved_class = _cli_comp.__class__.__name__
            _resolved_python_target = _cli_comp.__class__
            _instance_context = {{
                "component": _cli_comp.get_path_name(),
                "component_name": _cli_comp.get_name(),
                "component_class": _resolved_class,
                "owning_actor": _cli_actor.get_path_name(),
            }}
            _cli_resolve_ok = True
'''


def api_discover(
    api: "UEEditorAPI",
    target: str,
    *,
    query: str | None = None,
    detail: str | None = None,
    timeout: float = 30.0,
) -> dict:
    """Discover the API surface of a UE class via C++ reflection.

    Uses ``CliAnythingBridgeLibrary.get_class_info()`` — the same reflection
    system the UE Details panel uses.

    **TARGET is auto-detected from the string format:**

    - Starts with ``/Game/`` → asset or loaded UObject/subobject path, class is auto-resolved.
    - Contains ``PersistentLevel`` → actor path, class is auto-resolved.
    - Otherwise → treated as a UE class name (e.g. ``DirectionalLight``).

    Instance modes resolve the class and run reflection in a single HTTP call.

    **Progressive disclosure** (like the Details panel — glance, then hover):

    1. **Overview** (default): Returns property names and function names only.
    2. **Detail** (``detail="Name1,Name2"``): Returns full info for the
       specified properties/functions — type, tooltip, category, params, etc.

    Parameters
    ----------
    api:
        A connected :class:`UEEditorAPI` instance.
    target:
        UE class name, asset/subobject path (``/Game/...``), or actor path
        (containing ``PersistentLevel``).
    query:
        Optional case-insensitive regex (via ``re.search``) for property/function
        names. Plain strings work as substrings. Only used in overview mode.
    detail:
        Comma-separated names of properties/functions to get full detail for.
    timeout:
        Maximum seconds to wait for the HTTP response.

    Returns
    -------
    dict
        Overview mode: ``class``, ``properties`` (list of names),
        ``functions`` (list of names), ``property_count``, ``function_count``.
        Detail mode: ``class``, ``items`` (list of ``{kind, name, detail}``).
        Instance modes also include ``actor``/``asset`` context fields.
    """
    # Auto-detect target type from string format
    if "PersistentLevel" in target:
        # Distinguish actor vs component subobject path:
        #   actor:     .../Map.Map:PersistentLevel.ActorName            (one "." after ":")
        #   component: .../Map.Map:PersistentLevel.ActorName.CompName   (two "." after ":")
        _after_colon = target.rsplit(":", 1)[-1] if ":" in target else target
        _is_component = _after_colon.count(".") >= 2
        if _is_component:
            resolve_block = _RESOLVE_COMPONENT.format(component_path=target)
        else:
            resolve_block = _RESOLVE_ACTOR.format(actor_path=target)
        call = _API_DISCOVER_INSTANCE_CALL.format(
            resolve_block=resolve_block,
            query=query,
            detail=detail,
        )
    elif target.startswith("/Game/") or target.startswith("/Engine/"):
        resolve_block = _RESOLVE_ASSET.format(asset_path=target)
        call = _API_DISCOVER_INSTANCE_CALL.format(
            resolve_block=resolve_block,
            query=query,
            detail=detail,
        )
    else:
        call = _API_DISCOVER_CLASS_CALL.format(
            target=target,
            query=query,
            detail=detail,
        )

    code = _DISCOVER_FUNC + call
    return _execute(api, code, timeout=timeout, save=False)

