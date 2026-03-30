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
* The runner wraps the user code in a try/except, serialises ``result`` via
  ``unreal.log(json.dumps(result))``, and calls
  ``PythonScriptLibrary.ExecutePythonCommandEx`` to capture the output
  inline — **no temp files or polling required**.
* If ``result`` is not defined the capture block records a generic "ok" status.
* If ``result`` is not a *dict* it is wrapped as ``{"status": "ok", "value": …}``.
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

_cli_error = None
try:
{indented_user_code}
{save_block}
except Exception as _cli_exc:
    _cli_error = _cli_exc

_cli_result = {{}}
if _cli_error is not None:
    _cli_result = {{
        "error": str(_cli_error),
        "error_type": type(_cli_error).__name__,
        "traceback": _cli_tb.format_exc(),
    }}
else:
    try:
        _cli_result = result  # noqa: F821
    except NameError:
        _cli_result = {{"status": "ok", "note": "Script executed (no result variable defined)"}}
    if not isinstance(_cli_result, dict):
        _cli_result = {{"status": "ok", "value": str(_cli_result)}}

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

    for entry in reversed(resp.get("LogOutput", [])):
        output = entry.get("Output", "")
        if output.startswith(_RESULT_MARKER):
            try:
                return json.loads(output[len(_RESULT_MARKER):])
            except json.JSONDecodeError as exc:
                return {"error": f"Malformed JSON result: {exc}", "raw": output}

    return {"status": "ok", "note": "Script produced no marked result"}
