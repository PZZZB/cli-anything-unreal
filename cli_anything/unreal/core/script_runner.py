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
_cli_captured_stdout = ""
_cli_old_stdout = _cli_sys.stdout
_cli_string_io = _cli_io.StringIO()
_cli_sys.stdout = _cli_string_io

try:
{indented_user_code}
{save_block}
except Exception as _cli_exc:
    _cli_error = _cli_exc
finally:
    _cli_sys.stdout = _cli_old_stdout
    _cli_captured_stdout = _cli_string_io.getvalue()

_cli_result = {{"stdout": _cli_captured_stdout}}
if _cli_error is not None:
    _cli_result.update({{
        "error": str(_cli_error),
        "error_type": type(_cli_error).__name__,
        "traceback": _cli_tb.format_exc(),
    }})
else:
    try:
        _cli_user_result = result  # noqa: F821
        if isinstance(_cli_user_result, dict):
            _cli_result.update(_cli_user_result)
        else:
            _cli_result["value"] = str(_cli_user_result)
    except NameError:
        _cli_result["status"] = "ok"

_cli_unreal.log("{marker}" + _cli_json.dumps(_cli_result, default=str))
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
    code = Path(script_path).read_text(encoding="utf-8")
    return _execute(api, code, timeout=timeout, save=save)


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
) -> dict:
    """Core execution logic shared by *run_python_script* and *run_python_code*.

    Wraps *code* in the standard try/except + result-capture template,
    executes it via ``api.exec_python_ex()`` (which calls
    ``PythonScriptLibrary.ExecutePythonCommandEx``), and extracts the
    JSON result from the captured ``LogOutput``.
    """
    indented = "\n".join(
        ("    " + line) if line.strip() else line
        for line in code.splitlines()
    )
    wrapper = _WRAPPER_TEMPLATE.format(
        indented_user_code=indented,
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

_API_DISCOVER_TEMPLATE = '''\
import json as _cli_json, inspect as _cli_inspect, re as _cli_re, unreal as _cli_unreal

def _cli_discover(_target_str, _method_filter=None, _max_methods=50):
    # Resolve target object
    _parts = _target_str.split(".")
    if _parts[0] != "unreal":
        _parts = ["unreal"] + _parts
    _full_path = ".".join(_parts)

    _obj = _cli_unreal
    for _part in _parts[1:]:
        _obj = getattr(_obj, _part, None)
        if _obj is None:
            return {{"error": "Cannot resolve " + _full_path, "target_name": _target_str}}

    _doc = _cli_inspect.getdoc(_obj) or ""
    _methods = []
    _properties = []
    _sig_re = _cli_re.compile(r"^[\\w.]+\\(([^)]*)\\)\\s*(?:->\\s*(.+))?", _cli_re.MULTILINE)

    for _name, _member in _cli_inspect.getmembers(_obj):
        if _name.startswith("__"):
            continue
        if _method_filter and _method_filter.lower() not in _name.lower():
            continue

        if _cli_inspect.isbuiltin(_member) or _cli_inspect.ismethoddescriptor(_member) or _cli_inspect.isroutine(_member):
            _m_doc = _cli_inspect.getdoc(_member) or ""
            _sig = ""
            _m = _sig_re.search(_m_doc)
            if _m:
                _params = _m.group(1).strip()
                _ret = _m.group(2).strip() if _m.group(2) else ""
                _sig = "(" + _params + ")" + (" -> " + _ret if _ret else "")
            _methods.append({{"name": _name, "signature": _sig, "docstring": _m_doc}})
        else:
            _p_doc = _cli_inspect.getdoc(_member) or ""
            _properties.append({{"name": _name, "type": type(_member).__name__, "docstring": _p_doc}})

    if len(_methods) > _max_methods:
        _methods = _methods[:_max_methods]

    return {{
        "target_name": _parts[-1],
        "full_path": _full_path,
        "docstring": _doc,
        "methods": _methods,
        "properties": _properties,
        "method_count": len(_methods),
        "property_count": len(_properties),
    }}

result = _cli_discover({target!r}, _method_filter={method_filter!r}, _max_methods={max_methods})
'''

def api_discover(
    api: "UEEditorAPI",
    target: str,
    method_filter: str | None = None,
    max_methods: int = 50,
    timeout: float = 30.0,
) -> dict:
    """Discover the API surface of an ``unreal.*`` class or module.

    Generates a Python probe script that uses ``inspect`` to enumerate
    methods and properties, parses docstrings for signatures, and
    returns the result as structured JSON.

    Parameters
    ----------
    api:
        A connected :class:`UEEditorAPI` instance.
    target:
        Python class or module name (e.g. ``"unreal.EditorLevelLibrary"``
        or ``"EditorLevelLibrary"``).
    method_filter:
        Optional case-insensitive substring filter for method names.
    max_methods:
        Maximum number of methods to return (default 50).
    timeout:
        Maximum seconds to wait for the HTTP response.

    Returns
    -------
    dict
        API surface information including methods with signatures,
        properties, and docstrings.
    """
    code = _API_DISCOVER_TEMPLATE.format(
        target=target,
        method_filter=method_filter,
        max_methods=max_methods,
    )
    return _execute(api, code, timeout=timeout, save=False)


# ── Instance Inspection ─────────────────────────────────────────────

_INSTANCE_INSPECT_TEMPLATE = '''\
import json as _cli_json, unreal as _cli_unreal

def _cli_inspect_instance(_target_path, _mode="actor", _prop_filter=None):
    _obj = None
    if _mode == "actor":
        _subsystem = _cli_unreal.get_editor_subsystem(_cli_unreal.EditorActorSubsystem)
        for _a in _subsystem.get_all_level_actors():
            if _a.get_path_name() == _target_path:
                _obj = _a
                break
    else:
        _obj = _cli_unreal.EditorAssetLibrary.load_asset(_target_path)

    if _obj is None:
        return {{"error": "Instance not found: " + _target_path}}

    _instance_name = _obj.get_name()
    _class_name = _obj.__class__.__name__
    _properties = {{}}
    _methods = []

    for _attr_name in dir(_obj):
        if _attr_name.startswith("_"):
            continue
        if _prop_filter and _prop_filter.lower() not in _attr_name.lower():
            continue
        try:
            _attr_val = getattr(_obj, _attr_name)
            if callable(_attr_val):
                _methods.append(_attr_name)
            else:
                _properties[_attr_name] = str(_attr_val)
        except Exception:
            continue

    return {{
        "instance_name": _instance_name,
        "class_name": _class_name,
        "properties": _properties,
        "methods": _methods,
        "property_count": len(_properties),
        "method_count": len(_methods),
    }}

result = _cli_inspect_instance({target_path!r}, _mode={mode!r}, _prop_filter={prop_filter!r})
'''

def inspect_instance(
    api: "UEEditorAPI",
    target_path: str,
    mode: str = "actor",
    prop_filter: str | None = None,
    timeout: float = 30.0,
) -> dict:
    """Inspect a UE object instance using Python runtime reflection.

    Returns snake_case property names and current values that are safe
    to use directly in Python scripts — unlike the C++ ``/remote/object/describe``
    API which returns PascalCase names that cause ``AttributeError`` in Python.

    Parameters
    ----------
    api:
        A connected :class:`UEEditorAPI` instance.
    target_path:
        Object path. For actors, the full path like
        ``"/Game/Map.Map:PersistentLevel.DirectionalLight_0"``.
        For assets, a content path like ``"/Game/M_Material"``.
    mode:
        ``"actor"`` to search in the current level,
        ``"asset"`` to load from the content browser.
    prop_filter:
        Optional case-insensitive substring filter for property names.
    timeout:
        Maximum seconds to wait for the HTTP response.

    Returns
    -------
    dict
        Instance info with ``properties`` (snake_case names → str values)
        and ``methods`` (snake_case names).
    """
    code = _INSTANCE_INSPECT_TEMPLATE.format(
        target_path=target_path,
        mode=mode,
        prop_filter=prop_filter,
    )
    return _execute(api, code, timeout=timeout, save=False)
