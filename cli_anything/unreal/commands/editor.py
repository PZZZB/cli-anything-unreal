"""Editor control commands."""

from __future__ import annotations

import re
import subprocess as sp
import sys
import time
from pathlib import Path

import click

from cli_anything.unreal.commands import AppError, AppState, handle_error, output, require_editor, require_project
from cli_anything.unreal.core.tasks import cancel_task, load_task, submit_task, task_progress, wait_for_task


@click.group("editor")
def editor_group():
    """Editor control commands."""


@editor_group.command("status")
@click.argument("task_id", required=False)
@handle_error
@click.pass_obj
def editor_status(state: AppState, task_id):
    if task_id:
        task = load_task(task_id)
        if task is None:
            raise AppError("TASK_NOT_FOUND", f"Task not found: {task_id}", exit_code=3)
        output(task_progress(task), state)
        return

    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    check_port = state.session.port
    api = UEEditorAPI(port=check_port)
    alive = api.is_alive()

    if alive:
        result = {"status": "online", "port": check_port, "info": api.get_info()}
    else:
        result = {"status": "not_running", "port": check_port}
        if sys.platform == "win32":
            try:
                from cli_anything.unreal.utils.ue_backend import detect_ue_dialogs, find_running_editors

                running = find_running_editors()
                if running:
                    dialogs = detect_ue_dialogs()
                    result["running_editors"] = [
                        {"pid": editor["pid"], "project": editor.get("project")}
                        for editor in running
                    ]
                    if dialogs:
                        result["status"] = "starting"
                        result["dialogs"] = [{"title": dialog["title"]} for dialog in dialogs]
                    else:
                        result["status"] = "zombie"
                    if state.session.project_dir and state.session.project_name:
                        log_file = Path(state.session.project_dir) / "Saved" / "Logs" / f"{state.session.project_name}.log"
                        log_error = _check_log_errors(log_file)
                        if log_error:
                            result["log_error"] = log_error
            except Exception:
                pass

    if state.session.project_path:
        try:
            from cli_anything.unreal.utils.ue_backend import preflight_check

            preflight = preflight_check(state.session.project_path, state.session.engine_root)
            result["startup_precheck"] = _summarize_startup_precheck(preflight)
        except Exception:
            pass

    output(result, state)


@editor_group.command("list")
@click.option("--scan-range", default="30010-30020", help="Port range to scan")
@handle_error
@click.pass_obj
def editor_list(state: AppState, scan_range):
    from cli_anything.unreal.utils.ue_backend import find_running_editors
    from cli_anything.unreal.utils.ue_http_api import scan_editor_ports

    parts = scan_range.split("-")
    start = int(parts[0])
    end = int(parts[1]) if len(parts) > 1 else start
    instances = scan_editor_ports(port_range=(start, end))
    processes = find_running_editors()
    output(
        {
            "http_instances": [{"port": item["port"], "alive": item.get("alive", True)} for item in instances],
            "processes": [{"pid": proc["pid"], "project": proc.get("project", "")} for proc in processes],
        },
        state,
    )


@editor_group.command("preflight")
@handle_error
@click.pass_obj
def editor_preflight(state: AppState):
    from cli_anything.unreal.utils.ue_backend import preflight_check

    require_project(state)
    output(preflight_check(state.session.project_path, state.session.engine_root), state)


def _summarize_startup_precheck(check: dict) -> dict:
    errors = check.get("engine", {}).get("errors", []) + check.get("project", {}).get("errors", [])
    warnings = check.get("engine", {}).get("warnings", []) + check.get("project", {}).get("warnings", [])
    for issue in check.get("bridge_plugin", {}).get("issues", []):
        warnings.append(f"Fixed: {issue}")
    return {
        "ready": check.get("ready", False),
        "errors": errors,
        "warnings": warnings,
    }


def _check_already_running(session, state) -> dict | None:
    from cli_anything.unreal.utils.ue_backend import detect_ue_dialogs, find_running_editors
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    running = find_running_editors()
    project_path_norm = str(Path(session.project_path).resolve()).lower()
    api = UEEditorAPI(port=state.session.port)
    api_alive = api.is_alive()
    dialogs = detect_ue_dialogs() if sys.platform == "win32" else []
    for editor_proc in running:
        proc_project = editor_proc.get("project", "")
        if proc_project and Path(proc_project).resolve().as_posix().lower() == Path(project_path_norm).as_posix().lower():
            if api_alive:
                return {
                    "status": "already_running",
                    "pid": editor_proc["pid"],
                    "project": proc_project,
                    "message": f"Editor is already running for this project (PID {editor_proc['pid']}).",
                }
            zombie = {
                "status": "zombie",
                "pid": editor_proc["pid"],
                "project": proc_project,
                "message": f"Found UnrealEditor.exe for this project but the API is not reachable on port {state.session.port}.",
                "suggestion": "Stale process will be automatically terminated on next launch. Run editor launch to proceed.",
            }
            if dialogs:
                zombie["dialogs"] = [{"title": dialog["title"]} for dialog in dialogs]
                zombie["status"] = "starting"
                zombie["message"] = f"Editor process exists for this project but startup is still blocked or incomplete on port {state.session.port}."
                zombie["suggestion"] = "Wait briefly or dismiss any blocking dialogs before retrying."
            return zombie
    return None


def _check_port_in_use(poll_port, state) -> dict | None:
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    api_check = UEEditorAPI(port=poll_port)
    if api_check.is_alive():
        return {
            "status": "already_running",
            "port": poll_port,
            "message": f"An editor is already responding on port {poll_port}.",
        }
    return None


def _deploy_bridge(session, state) -> dict:
    from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed

    return ensure_plugin_deployed(session.project_dir)


def _build_launch_cmd(editor_exe, project_path, map_path, extra_args=None) -> list:
    cmd = [editor_exe, project_path, "-nosplash", "-unattended"]
    if map_path:
        cmd.append(map_path)
    if extra_args:
        cmd.extend(str(arg) for arg in extra_args if arg is not None and str(arg) != "")
    return cmd


_FATAL_LOG_PATTERNS = [
    "modules are missing or built with a different engine version",
    "Still incompatible or missing module:",
    "Engine modules cannot be compiled at runtime",
    "Missing or incompatible modules",
    "Plugin .* failed to load",
    "Fatal Error:",
    "Assertion failed:",
]


def _extract_log_error(text: str) -> tuple[str | None, str | None]:
    for pattern in _FATAL_LOG_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start = max(0, match.start() - 100)
            end = min(len(text), match.end() + 300)
            return text[start:end].strip(), pattern
    return None, None


def _check_log_errors(log_file: Path) -> str | None:
    if not log_file.exists():
        return None
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
        excerpt, _pattern = _extract_log_error(text)
        return excerpt
    except Exception:
        return None


def _check_log_errors_incremental(log_file: Path, offset: int) -> tuple[str | None, int]:
    if not log_file.exists():
        return None, offset
    try:
        size = log_file.stat().st_size
        if offset < 0 or offset > size:
            offset = 0
        with log_file.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            text = handle.read()
            new_offset = handle.tell()
        if not text:
            return None, new_offset
        excerpt, _pattern = _extract_log_error(text)
        return excerpt, new_offset
    except Exception:
        return None, offset


def _wait_for_api(proc, poll_port, timeout, log_file, state) -> dict:
    from cli_anything.unreal.utils.ue_backend import _emit_heartbeat
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    if not state.json_output:
        try:
            if timeout is not None:
                sys.stderr.write(f"[editor] waiting for Remote Control API on port {poll_port} (timeout {timeout}s), log {log_file}\n")
            else:
                sys.stderr.write(f"[editor] waiting for Remote Control API on port {poll_port} (no timeout), log {log_file}\n")
            sys.stderr.flush()
        except Exception:
            pass

    api = UEEditorAPI(port=poll_port)
    start_time = time.time()
    deadline = start_time + timeout if timeout is not None else float("inf")
    poll_interval = 5.0
    heartbeat_interval = 60.0
    next_beat = start_time + heartbeat_interval
    result = {}
    log_offset = log_file.stat().st_size if log_file.exists() else 0

    while time.time() < deadline:
        if proc.poll() is not None:
            return {
                "status": "crashed",
                "returncode": proc.returncode,
                "log_file": str(log_file),
                "error": f"Editor process exited with code {proc.returncode} before API came online.",
            }

        if api.is_alive():
            return {
                "status": "online",
                "port": poll_port,
                "startup_time_seconds": int(time.time() - start_time),
            }

        elapsed = time.time() - start_time
        if elapsed > 2:
            log_error, log_offset = _check_log_errors_incremental(log_file, log_offset)
            if log_error:
                return {
                    "status": "error_dialog",
                    "log_file": str(log_file),
                    "error": f"Editor appears stuck on an error dialog: {log_error}",
                }

        now = time.time()
        if now >= next_beat:
            if not state.json_output:
                _emit_heartbeat("editor", now - start_time, Path(log_file))
            next_beat += heartbeat_interval
        time.sleep(poll_interval)

    result["status"] = "timeout"
    result["log_file"] = str(log_file)
    if timeout is not None:
        result["error"] = f"Editor API did not respond within {timeout}s on port {poll_port}."
    else:
        result["error"] = f"Editor API did not respond on port {poll_port}."
    log_error, _ = _check_log_errors_incremental(log_file, log_offset)
    if not log_error:
        log_error = _check_log_errors(log_file)
    if log_error:
        result["error"] += f" Log hint: {log_error}"
    return result


@editor_group.command("launch")
@click.option("--map", "map_path", default=None, help="Level/map to open (.umap path)")
@click.option("--no-wait", is_flag=True, default=False)
@click.option("--timeout", default=None, type=int, help="Max seconds to wait for editor startup")
@click.option(
    "--extra-arg",
    "extra_args",
    multiple=True,
    metavar="ARG",
    help="Extra UE command-line argument forwarded verbatim to UnrealEditor.exe "
         "(repeat for multiple, e.g. --extra-arg -vulkan --extra-arg -ResX=1280).",
)
@handle_error
@click.pass_obj
def editor_launch(state: AppState, map_path, no_wait, timeout, extra_args):
    require_project(state)
    duplicate = _check_already_running(state.session, state)
    if duplicate is not None:
        if duplicate.get("status") == "already_running":
            raise AppError("ALREADY_RUNNING", duplicate["message"], exit_code=3, details=duplicate)
        # zombie or starting — auto-kill the stale process and proceed
        from cli_anything.unreal.utils.ue_backend import _kill_process_tree
        _kill_process_tree(int(duplicate["pid"]))
        time.sleep(2)

    payload = {
        "project_path": state.session.project_path,
        "port": state.session.port,
        "map_path": map_path,
        "timeout": timeout,
        "extra_args": list(extra_args) if extra_args else [],
    }
    task = submit_task("editor.launch", payload)
    if no_wait:
        output({"task_id": task["task_id"], "status": "submitted", "suggested_poll_interval_seconds": 5}, state)
        return

    final_task = wait_for_task(task["task_id"], timeout)
    if final_task is None:
        current = load_task(task["task_id"]) or task
        output(
            {
                "task_id": task["task_id"],
                "status": "timeout",
                "progress": task_progress(current).get("progress", 0),
                "suggested_poll_interval_seconds": 5,
            },
            state,
        )
        return

    progress = task_progress(final_task)
    if final_task.get("status") == "failed":
        error = final_task.get("error", {})
        raise AppError(error.get("code", "TASK_EXECUTION_FAILED"), error.get("message", "Editor launch failed"), exit_code=3, details=progress)
    output(progress, state)


@editor_group.command("cancel")
@click.argument("task_id")
@handle_error
@click.pass_obj
def editor_cancel(state: AppState, task_id):
    task = cancel_task(task_id)
    if task is None:
        raise AppError("TASK_NOT_FOUND", f"Task not found: {task_id}", exit_code=3)
    output(task_progress(task), state)


@editor_group.command("close")
@handle_error
@click.pass_obj
def editor_close(state: AppState):
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    api = UEEditorAPI(port=state.session.port)
    if not api.is_alive():
        output({"status": "offline", "port": state.session.port, "message": "No editor running on this port."}, state)
        return

    try:
        api.call_function(
            "/Script/EditorScriptingUtilities.Default__EditorLoadingAndSavingUtils",
            "SaveDirtyPackages",
            {"bPromptUserToSave": False, "bSaveMapPackages": True, "bSaveContentPackages": True},
        )
        time.sleep(1)
    except Exception:
        pass

    api.exec_console("quit")
    deadline = time.time() + 30
    while time.time() < deadline:
        if not api.is_alive():
            output({"status": "closed", "port": state.session.port}, state)
            return
        time.sleep(2)

    output({"status": "timeout", "port": state.session.port, "message": "Editor did not close within 30s."}, state)


@editor_group.command("exec")
@click.argument("command")
@handle_error
@click.pass_obj
def editor_exec(state: AppState, command):
    """Execute a console command in the editor.

    Sends a UE console command directly (e.g. stat unit, renderdoc.captureframe).
    For Python execution, use ``editor run-script -c "code"`` instead.
    """
    api = require_editor(state)

    result = api.exec_console(command)
    if "error" in result and "400" in str(result["error"]):
        result["hint"] = (
            "Console command execution may be disabled in Remote Control settings. "
            "Run: cli-anything-unreal editor enable-remote"
        )
    elif not result or result == {}:
        result = {
            "status": "executed",
            "command": command,
            "note": "Command executed. Console output is not captured by Remote Control API. "
                    "Check editor Output Log for results.",
        }
    output(result, state)


@editor_group.command("run-script")
@click.argument("script_path", type=click.Path(exists=True), required=False, default=None)
@click.option("-c", "--code", default=None, help="Inline Python code to execute (alternative to script file).")
@click.option("--timeout", default=30, type=int, help="Max seconds to wait for results.")
@click.option("--no-save", "no_save", is_flag=True, default=False, help="Skip auto-saving dirty packages after script execution.")
@handle_error
@click.pass_obj
def editor_run_script(state: AppState, script_path, code, timeout, no_save):
    """Execute Python in the editor with structured result capture.

    Provide either a script file path OR inline code via -c:

    \b
        editor run-script myscript.py
        editor run-script -c "result = {'hello': 'world'}"

    The script should set a ``result`` dict variable.  It will be
    automatically captured and returned as structured JSON output.

    By default, dirty packages are saved after execution.
    Use --no-save to skip this.
    """
    if not script_path and not code:
        raise AppError("MISSING_INPUT", "Provide a script file path or use -c for inline code.",
                       suggestion="editor run-script myscript.py  OR  editor run-script -c \"code\"")
    if script_path and code:
        raise AppError("AMBIGUOUS_INPUT", "Provide either a script file path or -c, not both.")

    from cli_anything.unreal.core.script_runner import run_python_code, run_python_script
    api = require_editor(state)

    if code:
        result = run_python_code(
            api, code,
            project_dir=state.session.project_dir,
            timeout=timeout,
            save=not no_save,
        )
    else:
        result = run_python_script(
            api, script_path,
            project_dir=state.session.project_dir,
            timeout=timeout,
            save=not no_save,
        )
    output(result, state)


@editor_group.command("api-discover")
@click.argument("target")
@click.option("--query", "-q", default=None, help="Case-insensitive regex filter for property/function names.")
@click.option("--detail", "-d", default=None, metavar="NAMES", help="Comma-separated names to get full detail for.")
@click.option("--timeout", default=30, type=int, help="Max seconds to wait for results.")
@handle_error
@click.pass_obj
def editor_api_discover(state: AppState, target, query, detail, timeout):
    """Discover the API surface of a UE class via C++ reflection.

    TARGET is auto-detected: class name, asset path, or actor path.
    Use -d to drill into specific properties/functions.
    """
    from cli_anything.unreal.core.script_runner import api_discover
    api = require_editor(state)
    result = api_discover(api, target, query=query, detail=detail, timeout=timeout)
    output(result, state)


@editor_group.command("enable-remote")
@handle_error
@click.pass_obj
def editor_enable_remote(state: AppState):
    """Enable Remote Control features for CLI use.

    Creates/updates DefaultRemoteControl.ini to allow remote console
    command execution and remote Python execution. Requires editor
    restart to take effect.
    """
    from cli_anything.unreal.utils.ue_backend import ensure_remote_control_config

    require_project(state)
    result = ensure_remote_control_config(state.session.project_dir)
    output(result, state)


@editor_group.command("plugin-version")
@handle_error
@click.pass_obj
def editor_plugin_version(state: AppState):
    """Check CliAnythingBridge plugin version (bundled vs loaded).

    Reports the version bundled with the CLI package and the version
    currently loaded in the running editor (if any).
    """
    from cli_anything.unreal.core.plugin_bridge import get_bundled_version, get_loaded_plugin_version

    bundled = get_bundled_version()
    loaded = None

    if state.session.project_dir:
        api = require_editor(state)
        loaded = get_loaded_plugin_version(api)

    output({
        "bundled_version": bundled,
        "loaded_version": loaded,
        "match": loaded is not None and loaded == bundled,
    }, state)


@editor_group.command("plugin-upgrade")
@handle_error
@click.pass_obj
def editor_plugin_upgrade(state: AppState):
    """Upgrade the CliAnythingBridge plugin if a newer version is available.

    Workflow: deploy updated plugin source, compile the project,
    restart the editor if it was running, verify the new version.
    """
    from cli_anything.unreal.core.plugin_bridge import (
        ensure_plugin_deployed,
        get_bundled_version,
        get_loaded_plugin_version,
    )

    require_project(state)
    project_dir = state.session.project_dir

    import shutil
    plugin_dir = Path(project_dir) / "Plugins" / "CliAnythingBridge"
    bundled = get_bundled_version()

    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI
    api = UEEditorAPI(port=state.session.port)
    editor_was_running = api.is_alive()
    loaded = None

    if editor_was_running:
        loaded = get_loaded_plugin_version(api)
        if loaded == bundled:
            output({"status": "up_to_date", "version": bundled}, state)
            return

        api.exec_console("exit")
        time.sleep(5)
        for _ in range(15):
            if not api.is_alive():
                break
            time.sleep(2)
        else:
            if api.is_alive():
                raise AppError("UPGRADE_FAILED", "Editor did not shut down within timeout — aborting upgrade")

    if plugin_dir.exists():
        shutil.rmtree(str(plugin_dir))

    deploy = ensure_plugin_deployed(project_dir)
    if not deploy["deployed"]:
        raise AppError("DEPLOY_FAILED", deploy.get("error", "Deployment failed"))

    plugin_intermediate = plugin_dir / "Intermediate"
    plugin_binaries = plugin_dir / "Binaries"
    if plugin_intermediate.exists():
        shutil.rmtree(str(plugin_intermediate))
    if plugin_binaries.exists():
        shutil.rmtree(str(plugin_binaries))

    from cli_anything.unreal.core.build import compile_project
    build_result = compile_project(state.session.project_path, engine_root=state.session.engine_root)
    if build_result.get("status") == "error":
        raise AppError("COMPILE_FAILED", build_result.get("error", "Build failed"), details={
            "log_file": build_result.get("log_file", ""),
        })

    if editor_was_running:
        from cli_anything.unreal.utils.ue_backend import find_editor_exe
        engine_root = state.session.engine_root
        editor_exe = find_editor_exe(engine_root) if engine_root else None
        if editor_exe:
            cmd = _build_launch_cmd(editor_exe, state.session.project_path, None)
            sp.Popen(cmd, stdout=sp.DEVNULL, stderr=sp.DEVNULL)
            for _ in range(60):
                time.sleep(2)
                if api.is_alive():
                    break

            new_loaded = get_loaded_plugin_version(api)
            if new_loaded == bundled:
                output({
                    "status": "upgraded",
                    "version": bundled,
                    "previous_version": loaded,
                }, state)
            else:
                output({
                    "status": "version_mismatch",
                    "expected": bundled,
                    "loaded": new_loaded,
                }, state)
            return

    output({
        "status": "deployed",
        "action": deploy.get("action"),
        "version": deploy.get("version", bundled),
        "plugin_dir": deploy.get("plugin_dir"),
        "needs_restart": editor_was_running,
    }, state)


@editor_group.group("cvar")
def cvar_group():
    """Get and set console variables."""


@cvar_group.command("get")
@click.argument("name")
@handle_error
@click.pass_obj
def cvar_get(state: AppState, name):
    """Get a console variable value."""
    api = require_editor(state)
    value = api.get_cvar(name)
    output({"name": name, "value": value}, state)


@cvar_group.command("set")
@click.argument("name")
@click.argument("value")
@handle_error
@click.pass_obj
def cvar_set(state: AppState, name, value):
    """Set a console variable value."""
    api = require_editor(state)
    result = api.set_cvar(name, value)
    if "error" in result and "400" in str(result["error"]):
        raise AppError(
            "CVAR_SET_FAILED",
            "CVar set failed. Remote console command execution is disabled.",
            suggestion="Run: cli-anything-unreal editor enable-remote, then restart editor.",
            details={"name": name, "value": value},
        )
    output({"name": name, "value": value, "status": "ok", **result}, state)


@editor_group.command("new-level")
@click.argument("level_path")
@click.option("--template", default=None, help="Optional path to a template level to clone")
@handle_error
@click.pass_obj
def editor_new_level(state: AppState, level_path, template):
    """Create and open a new level."""
    from cli_anything.unreal.core.scene import new_level
    api = require_editor(state)
    result = new_level(api, level_path, template)
    output(result, state)


@editor_group.command("save-level")
@handle_error
@click.pass_obj
def editor_save_level(state: AppState):
    """Save the current level."""
    from cli_anything.unreal.core.scene import save_level
    api = require_editor(state)
    result = save_level(api)
    output(result, state)
