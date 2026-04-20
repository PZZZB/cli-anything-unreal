"""commands/editor.py — Editor control commands.

The ``editor_launch`` command is decomposed into smaller helper functions
for readability and testability:

  - _determine_poll_port()   — resolve which port to poll
  - _run_preflight()         — run preflight check, return early if failed
  - _check_already_running() — detect duplicate editor processes
  - _check_port_in_use()     — detect port conflicts
  - _deploy_bridge()         — auto-deploy bridge plugin
  - _build_launch_cmd()      — assemble the editor command line
  - _check_log_errors()      — scan editor log for fatal errors
  - _wait_for_api()          — poll until Remote Control API is online
"""

import re
import subprocess as sp
import sys
import time
from pathlib import Path

import click

from cli_anything.unreal.commands import AppState, handle_error, output, require_editor, require_project


@click.group("editor")
def editor_group():
    """Editor control — status, console commands, CVars."""
    pass


# ── editor status ─────────────────────────────────────────────────────

@editor_group.command("status")
@click.option("--port", type=int, help="Override port for this check")
@handle_error
@click.pass_obj
def editor_status(state: AppState, port):
    """Check if the UE editor is running and reachable."""
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    check_port = port or state.session.port
    api = UEEditorAPI(port=check_port)
    alive = api.is_alive()

    if alive:
        info = api.get_info()
        result = {
            "status": "online",
            "port": check_port,
            "info": info,
        }
        if not state.json_output:
            state.skin.success(f"Editor is online (port {check_port})")
    else:
        # API not responding — check if UE process is still alive
        # (may be blocked by a modal dialog)
        result = {
            "status": "offline",
            "port": check_port,
        }
        if sys.platform == "win32":
            try:
                from cli_anything.unreal.utils.ue_backend import (
                    find_running_editors, detect_ue_dialogs,
                )
                running = find_running_editors()
                if running:
                    result["status"] = "offline_api_blocked"
                    result["running_editors"] = [
                        {"pid": e["pid"], "project": e.get("project")} for e in running
                    ]
                    dialogs = detect_ue_dialogs()
                    if dialogs:
                        result["dialogs"] = [
                            {"title": d["title"]} for d in dialogs
                        ]

                    project_dir = getattr(state.session, "project_dir", None)
                    project_name = getattr(state.session, "project_name", None)
                    log_error = None
                    if project_dir and project_name:
                        log_file = Path(project_dir) / "Saved" / "Logs" / f"{project_name}.log"
                        log_error = _check_log_errors(log_file)
                        if log_error:
                            result["log_error"] = log_error

                    if not state.json_output:
                        state.skin.warning(
                            f"Editor process running but API not responding on port {check_port}"
                        )
                        if dialogs:
                            state.skin.warning("Modal dialog(s) detected:")
                            for d in dialogs:
                                state.skin.warning(f'  "{d["title"]}"')
                        if log_error:
                            state.skin.warning("Recent startup error from log:")
                            state.skin.warning(f"  {log_error[:500]}")
                        state.skin.hint("Editor may be blocked by a dialog. Check the editor window.")
                else:
                    if not state.json_output:
                        state.skin.error(f"Editor not reachable on port {check_port}")
            except Exception:
                if not state.json_output:
                    state.skin.error(f"Editor not reachable on port {check_port}")
        else:
            if not state.json_output:
                state.skin.error(f"Editor not reachable on port {check_port}")

    # Always attach startup precheck when project context is available.
    # This helps diagnose startup blockers even if the editor was launched externally.
    if getattr(state.session, "project_path", None):
        try:
            from cli_anything.unreal.utils.ue_backend import preflight_check

            preflight = preflight_check(state.session.project_path, state.session.engine_root)
            precheck_errors = preflight.get("engine", {}).get("errors", []) + preflight.get("project", {}).get("errors", [])
            precheck_warnings = preflight.get("engine", {}).get("warnings", []) + preflight.get("project", {}).get("warnings", [])

            result["startup_precheck"] = {
                "ready": preflight.get("ready", False),
                "errors": precheck_errors,
                "warnings": precheck_warnings,
            }

            if not preflight.get("ready", False) and not state.json_output:
                state.skin.warning("Startup precheck found blockers:")
                for e in precheck_errors:
                    state.skin.warning(f"  {e}")
                state.skin.hint("Fix precheck blockers before retrying startup.")
        except Exception:
            pass

    output(result, state)


# ── editor list ───────────────────────────────────────────────────────

@editor_group.command("list")
@click.option("--scan-range", default="30010-30020", help="Port range to scan")
@handle_error
@click.pass_obj
def editor_list(state: AppState, scan_range):
    """Discover all running UE editor instances.

    Scans ports and checks for running editor processes.
    """
    from cli_anything.unreal.utils.ue_http_api import scan_editor_ports
    from cli_anything.unreal.utils.ue_backend import find_running_editors

    # Parse port range
    parts = scan_range.split("-")
    start = int(parts[0])
    end = int(parts[1]) if len(parts) > 1 else start

    # Scan HTTP ports
    instances = scan_editor_ports(port_range=(start, end))

    # Also find processes
    processes = find_running_editors()

    result = {
        "http_instances": [
            {"port": i["port"], "alive": i.get("alive", True)}
            for i in instances
        ],
        "processes": [
            {"pid": p["pid"], "project": p.get("project", "")}
            for p in processes
        ],
    }

    if not state.json_output:
        if instances:
            state.skin.section("Running Editor Instances (HTTP)")
            headers = ["Port", "Status"]
            rows = [[str(i["port"]), "Online"] for i in instances]
            state.skin.table(headers, rows)
        else:
            state.skin.warning(f"No editor HTTP API found on ports {start}-{end}")

        if processes:
            state.skin.section("Editor Processes")
            headers = ["PID", "Project"]
            rows = [[str(p["pid"]), p.get("project", "unknown")] for p in processes]
            state.skin.table(headers, rows)

    output(result, state)


# ── editor preflight ──────────────────────────────────────────────────

@editor_group.command("preflight")
@handle_error
@click.pass_obj
def editor_preflight(state: AppState):
    """Check if engine and project are compiled and ready to launch.

    Verifies:
    - Engine binaries exist (UnrealEditor.exe, .modules, .target)
    - Project C++ modules are compiled (UnrealEditor-{Module}.dll)
    - Binaries are not stale (newer than source code)
    """
    from cli_anything.unreal.utils.ue_backend import preflight_check

    require_project(state)
    result = preflight_check(state.session.project_path, state.session.engine_root)

    if not state.json_output:
        # Engine status
        eng = result["engine"]
        if eng["ready"]:
            state.skin.success(f"Engine OK ({result.get('engine_root', '?')})")
        else:
            state.skin.error("Engine NOT ready")
            for e in eng["errors"]:
                state.skin.error(f"  {e}")
        for w in eng.get("warnings", []):
            state.skin.warning(f"  {w}")

        # Project status
        proj = result["project"]
        if proj["ready"]:
            state.skin.success(f"Project OK ({state.session.project_name})")
        else:
            state.skin.error(f"Project NOT ready ({state.session.project_name})")
            for e in proj["errors"]:
                state.skin.error(f"  {e}")
        for w in proj.get("warnings", []):
            state.skin.warning(f"  {w}")

        if result["ready"]:
            state.skin.success("Ready to launch editor")
        else:
            state.skin.error("Cannot launch editor — fix errors above first")

    output(result, state)


# ── editor_launch helper functions ────────────────────────────────────

def _determine_poll_port(session, state) -> int:
    """Determine which port to poll for the editor API.

    If user explicitly passed --port, respect it.
    Otherwise, read from project config (DefaultRemoteControl.ini).
    """
    from cli_anything.unreal.utils.ue_backend import read_rc_port

    ctx = click.get_current_context()
    port_explicit = (
        ctx.parent
        and ctx.parent.get_parameter_source("port") == click.core.ParameterSource.COMMANDLINE
    )
    if port_explicit:
        return session.port
    else:
        rc_port = read_rc_port(session.project_dir)
        return rc_port if rc_port is not None else session.port


def _summarize_startup_precheck(check: dict) -> dict:
    """Build a compact startup-precheck summary for command outputs."""
    errors = check.get("engine", {}).get("errors", []) + check.get("project", {}).get("errors", [])
    warnings = check.get("engine", {}).get("warnings", []) + check.get("project", {}).get("warnings", [])
    return {
        "ready": check.get("ready", False),
        "errors": errors,
        "warnings": warnings,
    }


def _run_preflight(session, state) -> dict:
    """Run preflight check and return the full check result."""
    from cli_anything.unreal.utils.ue_backend import preflight_check

    if not state.json_output:
        state.skin.info("Running preflight check...")

    check = preflight_check(session.project_path, session.engine_root)
    precheck_summary = _summarize_startup_precheck(check)

    if not check["ready"]:
        all_errors = precheck_summary["errors"]
        if state.json_output:
            output({
                "status": "preflight_failed",
                "errors": all_errors,
                "preflight": check,
                "startup_precheck": precheck_summary,
            }, state)
        else:
            state.skin.error("Preflight check FAILED — cannot launch editor")
            for e in all_errors:
                state.skin.error(f"  {e}")
            for w in precheck_summary["warnings"]:
                state.skin.warning(f"  {w}")
            state.skin.hint("Fix the errors above, then try again.")
            state.skin.hint(f"To compile: cli-anything-unreal --project {session.project_path} build compile")

    if check["ready"] and not state.json_output:
        state.skin.success("Preflight OK")

    return check


def _check_already_running(session, state) -> dict | None:
    """Check if editor is already running for this project.

    Returns a result dict if a duplicate was found (caller should return),
    None otherwise. Also warns about other UE instances.
    """
    from cli_anything.unreal.utils.ue_backend import find_running_editors

    running = find_running_editors()
    project_path_norm = str(Path(session.project_path).resolve()).lower()

    # 1. Check by process — detect any UE instance with the same .uproject
    for editor_proc in running:
        proc_project = editor_proc.get("project", "")
        if proc_project and Path(proc_project).resolve().as_posix().lower() == Path(project_path_norm).as_posix().lower():
            result = {
                "status": "already_running",
                "pid": editor_proc["pid"],
                "project": proc_project,
                "message": (
                    f"Editor is already running for this project (PID {editor_proc['pid']}). "
                    "Use 'editor close' to shut it down first, "
                    "or kill the process manually."
                ),
            }
            if not state.json_output:
                state.skin.error(f"Editor already running for {session.project_name} (PID {editor_proc['pid']})")
                state.skin.hint("Use: cli-anything-unreal editor close")
            return result

    # 1b. Warn about any other UE instances (different projects)
    if running:
        other_projects = [
            p for p in running
            if p.get("project", "") and Path(p["project"]).resolve().as_posix().lower() != Path(project_path_norm).as_posix().lower()
        ]
        if other_projects:
            if state.json_output:
                output({
                    "status": "warning",
                    "warning": "other_editors_running",
                    "running_editors": other_projects,
                    "message": (
                        f"{len(other_projects)} other UE editor(s) running. "
                        "Port conflicts may occur if they use the same Remote Control port."
                    ),
                }, state)
            else:
                state.skin.warning(f"{len(other_projects)} other UE editor(s) running:")
                for ep in other_projects:
                    state.skin.warning(f"  PID {ep['pid']}: {ep.get('project', 'unknown')}")
                state.skin.hint("Port conflicts may occur. Continue at your own risk.")

    return None


def _check_port_in_use(poll_port, state) -> dict | None:
    """Check if an editor is already listening on the target port.

    Returns a result dict if the port is in use (caller should return),
    None otherwise.
    """
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    api_check = UEEditorAPI(port=poll_port)
    if api_check.is_alive():
        result = {
            "status": "already_running",
            "port": poll_port,
            "message": (
                f"An editor is already responding on port {poll_port}. "
                "Use 'editor close' to shut it down, or use a different --port."
            ),
        }
        if not state.json_output:
            state.skin.error(f"Port {poll_port} is already in use by an editor")
            state.skin.hint("Use: cli-anything-unreal editor close")
            state.skin.hint(f"Or launch on another port: editor launch --port {poll_port + 10}")
        return result

    return None


def _deploy_bridge(session, state) -> dict:
    """Auto-deploy bridge plugin before launch. Returns deploy info."""
    from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed

    deploy = ensure_plugin_deployed(session.project_dir)
    if deploy["deployed"] and deploy["action"] != "already_up_to_date":
        if not state.json_output:
            state.skin.info(f"Bridge plugin {deploy['action']} → {deploy['plugin_dir']}")
    return deploy


def _build_launch_cmd(editor_exe, project_path, map_path) -> list:
    """Build the editor launch command line."""
    cmd = [editor_exe, project_path, "-nosplash", "-unattended"]
    if map_path:
        cmd.append(map_path)
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
    """Extract first fatal startup error excerpt from text."""
    for pattern in _FATAL_LOG_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start = max(0, match.start() - 100)
            end = min(len(text), match.end() + 300)
            return text[start:end].strip(), pattern
    return None, None


def _check_log_errors(log_file: Path) -> str | None:
    """Scan the full editor log for fatal/modal-dialog errors."""
    if not log_file.exists():
        return None
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
        excerpt, _pattern = _extract_log_error(text)
        return excerpt
    except Exception:
        return None


def _check_log_errors_incremental(log_file: Path, offset: int) -> tuple[str | None, int]:
    """Scan newly appended log content for fatal/modal-dialog errors."""
    if not log_file.exists():
        return None, offset
    try:
        size = log_file.stat().st_size
        if offset < 0 or offset > size:
            offset = 0  # log rotated/truncated

        with log_file.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            text = f.read()
            new_offset = f.tell()

        if not text:
            return None, new_offset

        excerpt, _pattern = _extract_log_error(text)
        return excerpt, new_offset
    except Exception:
        return None, offset


def _wait_for_api(proc, poll_port, timeout, log_file, state) -> dict:
    """Wait for editor API to come online. Returns result dict with status."""
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    if not state.json_output:
        state.skin.info(f"Waiting for Remote Control API on port {poll_port} (timeout {timeout}s)...")

    api = UEEditorAPI(port=poll_port)
    start_time = time.time()
    deadline = start_time + timeout
    poll_interval = 5.0
    last_hint_time = time.time()
    result = {}

    log_offset = 0
    try:
        if log_file.exists():
            # Start from current EOF so we only inspect fresh startup logs.
            log_offset = log_file.stat().st_size
    except Exception:
        log_offset = 0

    while time.time() < deadline:
        # Check if process died
        if proc.poll() is not None:
            stderr_out = ""
            try:
                stderr_out = proc.stderr.read().decode("utf-8", errors="replace").strip()
            except Exception:
                pass
            result["status"] = "crashed"
            result["returncode"] = proc.returncode
            error_msg = (
                f"Editor process exited with code {proc.returncode} before API came online."
            )
            if stderr_out:
                error_msg += f"\nStderr: {stderr_out}"
            log_error, log_offset = _check_log_errors_incremental(log_file, log_offset)
            if not log_error:
                log_error = _check_log_errors(log_file)
            if log_error:
                error_msg += f"\nLog: {log_error}"
            result["error"] = error_msg
            if not state.json_output:
                state.skin.error(f"Editor exited unexpectedly (code {proc.returncode})")
                if stderr_out:
                    state.skin.error(f"  {stderr_out[:500]}")
                if log_error:
                    state.skin.error(f"  {log_error[:500]}")
                state.skin.hint("Check Saved/Logs/ for full details")
            return result

        if api.is_alive():
            result["status"] = "online"
            result["port"] = poll_port
            elapsed = int(time.time() - start_time)
            result["startup_time_seconds"] = elapsed
            if not state.json_output:
                state.skin.success(f"Editor API online (took ~{elapsed}s)")
            return result

        # Check log for fatal errors even while process is running
        # (catches modal dialog popups that keep the process alive)
        elapsed = time.time() - start_time
        if elapsed > 2:
            log_error, log_offset = _check_log_errors_incremental(log_file, log_offset)
            if log_error:
                result["status"] = "error_dialog"
                result["error"] = (
                    "Editor appears stuck on an error dialog:\n"
                    f"{log_error}\n\n"
                    "Close the dialog and fix the issue before launching again."
                )
                if not state.json_output:
                    state.skin.error("Editor stuck on error dialog:")
                    state.skin.error(f"  {log_error[:500]}")
                    state.skin.hint("Close the dialog in the editor, then fix the issue.")
                return result

            # Check for modal dialogs via Windows API (Windows only)
            if sys.platform == "win32":
                try:
                    from cli_anything.unreal.utils.ue_backend import detect_ue_dialogs
                    dialogs = detect_ue_dialogs()
                    if dialogs:
                        result["status"] = "blocked_by_dialog"
                        result["dialogs"] = [
                            {"title": d["title"], "hwnd": d["hwnd"]} for d in dialogs
                        ]
                        result["error"] = (
                            "Editor is blocked by modal dialog(s). "
                            "Close them and retry. "
                            + ", ".join(f'"{d["title"]}"' for d in dialogs)
                        )
                        if not state.json_output:
                            state.skin.error("Editor blocked by modal dialog:")
                            for d in dialogs:
                                state.skin.error(f'  "{d["title"]}"')
                            state.skin.hint("Close the dialog(s) in the editor window.")
                        return result
                except Exception:
                    pass

        remaining = max(0, int(deadline - time.time()))
        if not state.json_output and time.time() - last_hint_time >= 15:
            state.skin.hint(f"  Still waiting... ({remaining}s remaining)")
            last_hint_time = time.time()
        time.sleep(poll_interval)

    # Timed out
    result["status"] = "timeout"
    result["error"] = (
        f"Editor API did not respond within {timeout}s on port {poll_port}. "
        "Editor may still be loading, or may be stuck on a dialog/popup. "
        "Check the editor window manually."
    )
    log_error, log_offset = _check_log_errors_incremental(log_file, log_offset)
    if not log_error:
        log_error = _check_log_errors(log_file)
    if log_error:
        result["error"] += f"\nLog hint: {log_error}"
    if not state.json_output:
        state.skin.warning(f"Timed out after {timeout}s")
        state.skin.hint("Editor may still be loading. Check the editor window.")

    return result


# ── editor launch ─────────────────────────────────────────────────────

@editor_group.command("launch")
@click.option("--map", "map_path", default=None, help="Level/map to open (.umap path)")
@click.option("--wait/--no-wait", default=True, help="Wait for API to come online")
@click.option("--timeout", default=600, help="Max seconds to wait for editor startup")
@handle_error
@click.pass_obj
def editor_launch(state: AppState, map_path, wait, timeout):
    """Launch UE editor with preflight build check.

    Always runs preflight check first (BuildId match, DLL existence, etc.).
    If the check fails, returns an error with instructions to compile.
    Optionally waits for the Remote Control API to come online.
    """
    from cli_anything.unreal.utils.ue_backend import find_editor_exe

    require_project(state)

    # ── Determine poll port ─────────────────────────────────────────
    poll_port = _determine_poll_port(state.session, state)

    # ── Preflight check (always runs) ─────────────────────────────────
    preflight = _run_preflight(state.session, state)
    if not preflight["ready"]:
        return

    # ── Find editor exe ─────────────────────────────────────────────
    if not state.session.engine_root:
        raise click.UsageError("Could not find engine root")

    editor_exe = find_editor_exe(state.session.engine_root)
    if not editor_exe:
        raise FileNotFoundError(f"UnrealEditor.exe not found in {state.session.engine_root}")

    # ── Check if editor is already running for this project ─────────
    dup_result = _check_already_running(state.session, state)
    if dup_result is not None:
        output(dup_result, state)
        return

    # ── Check by API port ───────────────────────────────────────────
    port_result = _check_port_in_use(poll_port, state)
    if port_result is not None:
        output(port_result, state)
        return

    # ── Auto-deploy bridge plugin before launch ────────────────────
    _deploy_bridge(state.session, state)

    # ── Build command ───────────────────────────────────────────────
    cmd = _build_launch_cmd(editor_exe, state.session.project_path, map_path)

    if not state.json_output:
        state.skin.info(f"Launching: {Path(editor_exe).name} {state.session.project_name}")
        if map_path:
            state.skin.info(f"Map: {map_path}")

    # ── Launch process ──────────────────────────────────────────────
    try:
        proc = sp.Popen(
            cmd,
            stdout=sp.DEVNULL,
            stderr=sp.PIPE,
        )
    except Exception as e:
        output({"status": "error", "error": f"Failed to launch: {e}"}, state)
        return

    result = {
        "status": "launched",
        "pid": proc.pid,
        "project": state.session.project_name,
        "editor_exe": editor_exe,
        "startup_precheck": _summarize_startup_precheck(preflight),
    }

    if not state.json_output:
        state.skin.success(f"Editor launched (PID {proc.pid})")

    # ── Wait for API ────────────────────────────────────────────────
    if wait:
        log_file = Path(state.session.project_dir) / "Saved" / "Logs" / f"{state.session.project_name}.log"
        wait_result = _wait_for_api(proc, poll_port, timeout, log_file, state)
        result.update(wait_result)

    output(result, state)


# ── editor close ──────────────────────────────────────────────────────

@editor_group.command("close")
@handle_error
@click.pass_obj
def editor_close(state: AppState):
    """Close the running UE editor (requests quit via console command).

    Sends 'quit' console command to the editor via Remote Control API.
    The editor will close gracefully (may prompt to save unsaved changes).
    """
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    api = UEEditorAPI(port=state.session.port)
    if not api.is_alive():
        output({"status": "offline", "port": state.session.port,
                "message": "No editor running on this port."}, state)
        return

    if not state.json_output:
        state.skin.info(f"Sending save + quit to editor on port {state.session.port}...")

    # Save all dirty packages before quitting (prevents recovery dialog on next launch)
    try:
        api.call_function(
            "/Script/EditorScriptingUtilities.Default__EditorLoadingAndSavingUtils",
            "SaveDirtyPackages",
            {"bPromptUserToSave": False, "bSaveMapPackages": True, "bSaveContentPackages": True},
        )
        time.sleep(1)
    except Exception:
        pass

    # Send quit command
    api.exec_console("quit")

    # Wait for editor to actually close
    deadline = time.time() + 30
    while time.time() < deadline:
        if not api.is_alive():
            output({"status": "closed", "port": state.session.port}, state)
            if not state.json_output:
                state.skin.success("Editor closed.")
            return
        time.sleep(2)

    output({
        "status": "timeout",
        "port": state.session.port,
        "message": "Editor did not close within 30s. It may be waiting for save confirmation.",
    }, state)


# ── editor exec ───────────────────────────────────────────────────────

@editor_group.command("exec")
@click.argument("command")
@click.option("--timeout", default=30, type=int,
              help="Max seconds to wait for results (Python commands only).")
@click.option("--no-save", "no_save", is_flag=True, default=False,
              help="Skip auto-saving dirty packages after Python script execution.")
@handle_error
@click.pass_obj
def editor_exec(state: AppState, command, timeout, no_save):
    """Execute a console command in the editor.

    When the command starts with ``py `` the CLI automatically switches to
    a reliable script-execution mode: the Python code is written to a temp
    file, executed via ``exec_python_file``, and the result is captured as
    structured JSON.  The script may assign a ``result`` dict variable which
    will be returned; otherwise a generic "ok" status is produced.

    By default, dirty packages are saved after Python script execution.
    Use --no-save to skip this.

    For non-Python console commands the behaviour is unchanged.
    """
    api = require_editor(state)

    # Python command detection — upgrade to reliable script execution mode
    if command.strip().startswith("py "):
        py_code = command.strip()[3:].strip().strip('"').strip("'")
        from cli_anything.unreal.core.script_runner import run_python_code
        result = run_python_code(
            api, py_code,
            project_dir=state.session.project_dir,
            timeout=timeout,
            save=not no_save,
        )
    else:
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


# ── editor run-script ─────────────────────────────────────────────────

@editor_group.command("run-script")
@click.argument("script_path", type=click.Path(exists=True))
@click.option("--timeout", default=30, type=int,
              help="Max seconds to wait for results.")
@click.option("--no-save", "no_save", is_flag=True, default=False,
              help="Skip auto-saving dirty packages after script execution.")
@handle_error
@click.pass_obj
def editor_run_script(state: AppState, script_path, timeout, no_save):
    """Execute a Python script file in the editor with result capture.

    The script should set a ``result`` dict variable.  It will be
    automatically captured and returned as structured JSON output.

    If no ``result`` variable is defined the command returns a generic
    "ok" status.  Non-dict values are wrapped automatically.

    By default, dirty packages are saved after execution.
    Use --no-save to skip this.

    \b
    Example:
        editor run-script build_scene.py --timeout 60
    """
    from cli_anything.unreal.core.script_runner import run_python_script
    api = require_editor(state)
    result = run_python_script(
        api, script_path,
        project_dir=state.session.project_dir,
        timeout=timeout,
        save=not no_save,
    )
    output(result, state)


# ── editor api-discover ───────────────────────────────────────────────

@editor_group.command("api-discover")
@click.argument("target")
@click.option("--query", "-q", default=None,
              help=(
                  "Case-insensitive regex filter for property/function names "
                  "(via re.search). Examples: -q intensity | -q 'create|connect' | "
                  "-q '^Set' | -q 'Color$'."
              ))
@click.option("--detail", "-d", default=None, metavar="NAMES",
              help="Comma-separated names to get full detail for (properties or functions).")
@click.option("--timeout", default=30, type=int,
              help="Max seconds to wait for results.")
@handle_error
@click.pass_obj
def editor_api_discover(state: AppState, target, query, detail, timeout):
    """Discover the API surface of a UE class via C++ reflection.

    Progressive disclosure — like the Details panel: glance, then hover.

    \b
    TARGET is auto-detected:
      - Class name:     DirectionalLight, unreal.Actor
      - Asset path:     /Game/Materials/M_Water  (auto-detects class)
      - Actor path:     /Game/Maps/L.L:PersistentLevel.Light_0  (auto-detects class)

    \b
    Then drill into details with -d:
      editor api-discover DirectionalLight -d bHidden,Intensity

    \b
    Examples:
        editor api-discover unreal.MaterialEditingLibrary
        editor api-discover MaterialEditingLibrary -q connect
        editor api-discover /Game/Materials/M_Water
        editor api-discover /Game/Maps/L.L:PersistentLevel.Light_0 -d bHidden
    """
    from cli_anything.unreal.core.script_runner import api_discover
    api = require_editor(state)
    result = api_discover(
        api, target,
        query=query,
        detail=detail,
        timeout=timeout,
    )
    output(result, state)


# ── editor enable-remote ──────────────────────────────────────────────

@editor_group.command("enable-remote")
@handle_error
@click.pass_obj
def editor_enable_remote(state: AppState):
    """Enable Remote Control features for CLI use.

    Creates/updates DefaultRemoteControl.ini to allow:
    - Remote console command execution (exec, cvar set)
    - Remote Python execution

    Requires editor restart to take effect.
    """
    from cli_anything.unreal.utils.ue_backend import ensure_remote_control_config

    require_project(state)
    result = ensure_remote_control_config(state.session.project_dir)

    if not state.json_output:
        if result["status"] == "ok":
            state.skin.success("Remote Control already configured")
        elif result["status"] == "created":
            state.skin.success("Created DefaultRemoteControl.ini")
        else:
            state.skin.success("Updated DefaultRemoteControl.ini")
        for change in result.get("changes", []):
            state.skin.info(f"  {change}")
        if result["status"] != "ok":
            state.skin.warning("Restart the editor for changes to take effect")

    output(result, state)


# ── editor plugin-version ────────────────────────────────────────────

@editor_group.command("plugin-version")
@handle_error
@click.pass_obj
def editor_plugin_version(state: AppState):
    """Check CliAnythingBridge plugin version (bundled vs loaded).

    Reports the version bundled with the CLI package and the version
    currently loaded in the running editor (if any). Use this to detect
    when a plugin upgrade is needed.

    \b
    Example:
        editor plugin-version
        # → {"bundled": "1.5", "loaded": "1.3", "match": false}
    """
    from cli_anything.unreal.core.plugin_bridge import get_bundled_version, get_loaded_plugin_version

    bundled = get_bundled_version()
    loaded = None

    if state.session.project_dir:
        api = require_editor(state)
        loaded = get_loaded_plugin_version(api)

    result = {
        "bundled_version": bundled,
        "loaded_version": loaded,
        "match": loaded is not None and loaded == bundled,
    }

    if not state.json_output:
        if loaded is None:
            state.skin.info(f"Bundled: {bundled}, Loaded: not loaded")
        elif loaded == bundled:
            state.skin.success(f"Plugin version {bundled} (up to date)")
        else:
            state.skin.warning(f"Version mismatch: bundled={bundled}, loaded={loaded}")
            state.skin.hint("Run 'editor plugin-upgrade' to upgrade")

    output(result, state)


# ── editor plugin-upgrade ────────────────────────────────────────────

@editor_group.command("plugin-upgrade")
@handle_error
@click.pass_obj
def editor_plugin_upgrade(state: AppState):
    """Upgrade the CliAnythingBridge plugin if a newer version is available.

    Workflow:
    1. Deploy updated plugin source to the project
    2. Compile the project (if editor is running, close it first)
    3. Restart the editor
    4. Verify the new version is loaded

    \b
    Example:
        editor plugin-upgrade
    """
    from cli_anything.unreal.core.plugin_bridge import (
        check_plugin_version,
        ensure_plugin_deployed,
        get_bundled_version,
        get_loaded_plugin_version,
    )

    require_project(state)
    project_dir = state.session.project_dir

    import shutil
    from pathlib import Path
    plugin_dir = Path(project_dir) / "Plugins" / "CliAnythingBridge"

    bundled = get_bundled_version()

    # Check if editor is running — if so, compare versions before touching files
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI
    api = UEEditorAPI(port=state.session.port)
    editor_was_running = api.is_alive()

    if editor_was_running:
        # Check loaded version vs bundled
        loaded = get_loaded_plugin_version(api)
        if loaded == bundled:
            if not state.json_output:
                state.skin.success(f"Plugin already at version {bundled} — no upgrade needed")
            output({"status": "up_to_date", "version": bundled}, state)
            return

        if not state.json_output:
            state.skin.info(f"Upgrading plugin: {loaded} → {bundled}")
            state.skin.info("Closing editor to recompile...")

        # Close editor
        api.exec_console("exit")
        time.sleep(5)

        # Wait for editor to close
        for _ in range(15):
            if not api.is_alive():
                break
            time.sleep(2)
        else:
            if api.is_alive():
                output({"error": "Editor did not shut down within timeout — aborting upgrade"}, state)
                return

    # Step 1: Force-deploy plugin source.
    # Delete existing plugin directory to ensure fresh copy,
    # since VersionName alone doesn't detect source file changes.
    if plugin_dir.exists():
        shutil.rmtree(str(plugin_dir))

    deploy = ensure_plugin_deployed(project_dir)
    if not deploy["deployed"]:
        output({"error": deploy.get("error", "Deployment failed")}, state)
        return

    if not state.json_output:
        state.skin.info(f"Deployed plugin v{deploy.get('version', bundled)} to {deploy.get('plugin_dir', '')}")

    # Clean plugin Intermediate/Binaries to force full recompile
    plugin_intermediate = plugin_dir / "Intermediate"
    plugin_binaries = plugin_dir / "Binaries"
    if plugin_intermediate.exists():
        shutil.rmtree(str(plugin_intermediate))
    if plugin_binaries.exists():
        shutil.rmtree(str(plugin_binaries))

    if not state.json_output:
        state.skin.info("Compiling project...")

    # Step 2: Compile
    from cli_anything.unreal.core.build import compile_project
    build_result = compile_project(
        state.session.project_path,
        engine_root=state.session.engine_root,
        timeout=600,
    )
    if build_result.get("status") == "error":
        output({
            "status": "compile_failed",
            "error": build_result.get("error", "Build failed"),
            "details": (build_result.get("stderr", "") or "")[-500:],
        }, state)
        return

    if not state.json_output:
        state.skin.success("Compilation succeeded")

    # Step 3: Relaunch editor if it was running before
    if editor_was_running:
        if not state.json_output:
            state.skin.info("Relaunching editor...")

        from cli_anything.unreal.utils.ue_backend import find_editor_exe
        engine_root = state.session.engine_root
        editor_exe = find_editor_exe(engine_root) if engine_root else None
        if editor_exe:
            cmd = _build_launch_cmd(editor_exe, state.session.project_path, None)
            sp.Popen(cmd, stdout=sp.DEVNULL, stderr=sp.DEVNULL)

            if not state.json_output:
                state.skin.info("Waiting for editor to come online...")

            # Wait for API
            for _ in range(60):
                time.sleep(2)
                if api.is_alive():
                    break

            # Verify new version
            new_loaded = get_loaded_plugin_version(api)
            if new_loaded == bundled:
                if not state.json_output:
                    state.skin.success(f"Plugin upgraded to v{bundled}")
                output({
                    "status": "upgraded",
                    "version": bundled,
                    "previous_version": loaded if editor_was_running else None,
                }, state)
            else:
                if not state.json_output:
                    state.skin.warning(f"Plugin loaded but version is {new_loaded} (expected {bundled})")
                output({
                    "status": "version_mismatch",
                    "expected": bundled,
                    "loaded": new_loaded,
                }, state)
            return

    # Editor wasn't running — just report deploy result
    if not state.json_output:
        state.skin.success(f"Plugin source deployed v{deploy.get('version', bundled)}")
        if deploy.get("action") != "already_up_to_date":
            state.skin.hint("Run 'editor launch' to start the editor with the new plugin")

    output({
        "status": "deployed",
        "action": deploy.get("action"),
        "version": deploy.get("version", bundled),
        "plugin_dir": deploy.get("plugin_dir"),
        "needs_restart": editor_was_running,
    }, state)


# ── CVar sub-group ────────────────────────────────────────────────────

@editor_group.group("cvar")
def cvar_group():
    """Get and set console variables."""
    pass


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
        output({
            "name": name,
            "value": value,
            "status": "failed",
            "error": "CVar set failed. Remote console command execution is disabled.",
            "fix": "Run: cli-anything-unreal --project <path> editor enable-remote, then restart editor.",
        }, state)
    else:
        output({"name": name, "value": value, "status": "ok", **result}, state)


# ── editor new-level / save-level ────────────────────────────────────

@editor_group.command("new-level")
@click.argument("level_path")
@click.option("--template", default=None, help="Optional path to a template level to clone")
@handle_error
@click.pass_obj
def editor_new_level(state: AppState, level_path, template):
    """Create and open a new level.

    Uses safe legacy API to prevent HTTP connection crashes.

    \b
    Examples:
        editor new-level /Game/Maps/NewLevel
        editor new-level /Game/Maps/NewLevel --template /Game/Maps/Template
    """
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
