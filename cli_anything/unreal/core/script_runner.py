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
* The runner automatically appends capture logic that serialises ``result``
  to a temporary JSON file.
* If ``result`` is not defined the capture block records a generic "ok" status.
* If ``result`` is not a *dict* it is wrapped as ``{"status": "ok", "value": …}``.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

# ── Wrapper template that surrounds the user script ─────────────────
# The user code is inserted at the {user_code} placeholder, wrapped in
# a top-level try/except so that **any** exception (including syntax-
# level import errors) is captured and written to the JSON output file
# instead of silently disappearing (which previously caused timeouts).
_WRAPPER_TEMPLATE = r'''# ── CLI script wrapper (injected by script_runner) ──
import json as _cli_json, traceback as _cli_tb

_cli_output_path = r"{output_path}"
_cli_error = None
try:
{indented_user_code}
{save_block}
except Exception as _cli_exc:
    _cli_error = _cli_exc

# ── Capture result ──
_cli_result = {{}}
if _cli_error is not None:
    _cli_result = {{
        "error": str(_cli_error),
        "error_type": type(_cli_error).__name__,
        "traceback": _cli_tb.format_exc(),
    }}
else:
    try:
        _cli_result = result  # noqa: F821 — may be defined in user script
    except NameError:
        _cli_result = {{"status": "ok", "note": "Script executed (no result variable defined)"}}
    if not isinstance(_cli_result, dict):
        _cli_result = {{"status": "ok", "value": str(_cli_result)}}

with open(_cli_output_path, "w", encoding="utf-8") as _cli_f:
    _cli_json.dump(_cli_result, _cli_f, indent=2, default=str)
'''

_SAVE_BLOCK = """\
    # ── Auto-save dirty packages (injected by --save) ──
    import unreal as _cli_unreal
    _cli_unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)"""


# ── Public API ──────────────────────────────────────────────────────

def run_python_script(
    api: "UEEditorAPI",
    script_path: str,
    project_dir: str | None = None,
    timeout: float = 30.0,
    save: bool = True,
) -> dict:
    """Execute a Python script file in the editor with automatic result capture.

    The runner reads *script_path*, appends output-capture logic, writes a
    temporary wrapper script, executes it via ``api.exec_python_file``, and
    polls for the resulting JSON file.

    Parameters
    ----------
    api:
        A connected :class:`UEEditorAPI` instance.
    script_path:
        Path to the ``.py`` file to execute.
    project_dir:
        If given, temp files are written to ``<project_dir>/Saved/Temp``.
        Otherwise ``%TEMP%/cli-anything-unreal`` is used.
    timeout:
        Maximum seconds to wait for the script's JSON output.
    save:
        If *True* (default), automatically save all dirty packages after
        the script finishes (calls
        ``EditorLoadingAndSavingUtils.save_dirty_packages``).  Has no
        effect when nothing is dirty.

    Returns
    -------
    dict
        Parsed JSON produced by the script, or an error dict on timeout.
    """
    code = Path(script_path).read_text(encoding="utf-8")
    return _execute(api, code, project_dir=project_dir, timeout=timeout,
                    label="script", save=save)


def run_python_code(
    api: "UEEditorAPI",
    code: str,
    project_dir: str | None = None,
    timeout: float = 30.0,
    save: bool = True,
) -> dict:
    """Execute a Python code string in the editor with automatic result capture.

    Convenience wrapper — writes *code* to a temporary ``.py`` file and
    delegates to the same execution pipeline as :func:`run_python_script`.

    Parameters
    ----------
    api:
        A connected :class:`UEEditorAPI` instance.
    code:
        Python source code to execute.
    project_dir:
        If given, temp files are written to ``<project_dir>/Saved/Temp``.
    timeout:
        Maximum seconds to wait for the script's JSON output.
    save:
        If *True* (default), automatically save all dirty packages after
        the script finishes.

    Returns
    -------
    dict
        Parsed JSON produced by the script, or an error dict on timeout.
    """
    return _execute(api, code, project_dir=project_dir, timeout=timeout,
                    label="code", save=save)


# ── Internal helpers ────────────────────────────────────────────────

def _execute(
    api: "UEEditorAPI",
    code: str,
    *,
    project_dir: str | None,
    timeout: float,
    label: str,
    save: bool = True,
) -> dict:
    """Core execution logic shared by *run_python_script* and *run_python_code*."""

    # 1. Determine temp directory
    if project_dir:
        temp_dir = Path(project_dir) / "Saved" / "Temp"
    else:
        temp_dir = Path(tempfile.gettempdir()) / "cli-anything-unreal"
    temp_dir.mkdir(parents=True, exist_ok=True)

    # 2. Unique file names
    ts = int(time.time() * 1000)
    pid = os.getpid()
    output_path = str(temp_dir / f"_run_{pid}_{ts}.json")
    wrapper_path = str(temp_dir / f"_run_{pid}_{ts}.py")

    # 3. Build wrapper script: user code inside try/except + capture tail
    #    Indent every line of user code by 4 spaces so it sits inside the
    #    try-block of _WRAPPER_TEMPLATE.
    indented = "\n".join(
        ("    " + line) if line.strip() else line
        for line in code.splitlines()
    )
    wrapper = _WRAPPER_TEMPLATE.format(
        output_path=output_path.replace("\\", "\\\\"),
        indented_user_code=indented,
        save_block=_SAVE_BLOCK if save else "",
    )

    Path(wrapper_path).write_text(wrapper, encoding="utf-8")

    try:
        # 4. Execute inside the editor
        api_result = api.exec_python_file(wrapper_path)

        # 5. Poll for JSON output
        deadline = time.time() + timeout
        while time.time() < deadline:
            if Path(output_path).exists():
                try:
                    data = json.loads(
                        Path(output_path).read_text(encoding="utf-8")
                    )
                    return data
                except json.JSONDecodeError:
                    time.sleep(0.5)
                    continue
            time.sleep(0.5)

        return {
            "error": "Script execution timed out or produced no output",
            "api_result": api_result,
        }
    finally:
        # 6. Cleanup
        try:
            Path(wrapper_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)
        except Exception:
            pass
