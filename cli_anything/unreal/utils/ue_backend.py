"""ue_backend.py — Engine discovery + offline command execution (UAT/UBT).

Handles finding UE installations, locating tools, and running subprocess
commands for build/cook/package operations that don't require a running editor.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Engine discovery ──────────────────────────────────────────────────


def find_engine_root(uproject_path: Optional[str] = None) -> Optional[str]:
    """Discover the Unreal Engine root directory.

    Strategy:
    1. If uproject_path given, parse EngineAssociation from .uproject:
       a. If it's a directory path, use directly
       b. If it's a version string (e.g. "5.7"), look up in registry
    2. Check UE_ENGINE_ROOT environment variable
    3. Windows registry (any registered engine, no version filter)

    Returns:
        Engine root path or None.
    """
    # Strategy 1: From .uproject
    if uproject_path:
        uproject = Path(uproject_path)
        if uproject.exists():
            try:
                data = json.loads(uproject.read_text(encoding="utf-8-sig"))
                assoc = data.get("EngineAssociation", "")
                if assoc:
                    # 1a: Path-based association (custom build)
                    if os.path.isdir(assoc):
                        return str(assoc)
                    # 1b: Version/GUID association — look up in registry
                    #     UE stores official engines in HKLM by version ("5.7"),
                    #     custom builds in HKCU by GUID ("{...}").
                    version_root = _find_engine_by_association(assoc)
                    if version_root:
                        return version_root
            except (json.JSONDecodeError, OSError):
                pass

    # Strategy 2: Environment variable
    env_root = os.environ.get("UE_ENGINE_ROOT")
    if env_root and _validate_engine_root(env_root):
        return env_root

    # Strategy 3: Windows registry (any registered engine)
    reg_root = _find_engine_from_registry()
    if reg_root:
        return reg_root

    return None


def _validate_engine_root(path: str) -> bool:
    """Check if a path is a valid UE engine root."""
    p = Path(path)
    # Must have Engine/Binaries and Engine/Build
    return (
        (p / "Engine" / "Binaries").is_dir()
        or (p / "Engine" / "Build").is_dir()
        or (p / "Engine" / "Source").is_dir()
    )


def _read_engine_version(engine_root: str) -> Optional[str]:
    """Read engine version (major.minor) from Build.version file.

    Args:
        engine_root: Path to engine root directory.

    Returns:
        Version string like "5.7" or None if not readable.
    """
    build_version_path = Path(engine_root) / "Engine" / "Build" / "Build.version"
    if not build_version_path.is_file():
        return None
    try:
        data = json.loads(build_version_path.read_text(encoding="utf-8"))
        major = data.get("MajorVersion")
        minor = data.get("MinorVersion")
        if major is not None and minor is not None:
            return f"{major}.{minor}"
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _find_engine_by_association(assoc: str) -> Optional[str]:
    """Find engine root by EngineAssociation string.

    Mirrors UE's own resolution logic:
    1. HKLM SOFTWARE\\EpicGames\\Unreal Engine\\<version> — official installs
       The subkey name IS the version (e.g. "5.7").
    2. HKCU SOFTWARE\\Epic Games\\Unreal Engine\\Builds — custom/source builds
       Value names are GUIDs like "{F9E7804A-...}", values are paths.

    Args:
        assoc: EngineAssociation from .uproject — version string ("5.7")
               or GUID ("{F9E7804A-46B1-30B0-1C7B-4B99E6AAB63F}").

    Returns:
        Engine root path or None.
    """
    if sys.platform != "win32":
        return None

    # 1. HKLM — subkey name matches version directly
    result = _find_engine_in_hklm(assoc)
    if result:
        return result

    # 2. HKCU Builds — lookup by GUID name, or scan by Build.version
    return _find_engine_in_hkcu(assoc)


def _find_engine_in_hklm(version: str) -> Optional[str]:
    """Look up engine in HKLM by version subkey name."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\EpicGames\Unreal Engine",
        )
        try:
            subkey = winreg.OpenKey(key, version)
            install_dir, _ = winreg.QueryValueEx(subkey, "InstalledDirectory")
            if _validate_engine_root(install_dir):
                return install_dir
        except OSError:
            pass
    except (ImportError, OSError):
        pass
    return None


def _find_engine_in_hkcu(assoc: str) -> Optional[str]:
    """Look up engine in HKCU Builds.

    If assoc is a GUID like "{F9E7804A-...}", look up the value by name.
    Otherwise, scan all entries and match by Build.version.
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Epic Games\Unreal Engine\Builds",
        )
        # GUID lookup: assoc is the value name
        if assoc.startswith("{") and assoc.endswith("}"):
            try:
                install_dir, _ = winreg.QueryValueEx(key, assoc)
                if isinstance(install_dir, str) and _validate_engine_root(install_dir):
                    return install_dir
            except OSError:
                pass
            return None
        # Version string: scan all entries, match by Build.version
        i = 0
        while True:
            try:
                name, install_dir, vtype = winreg.EnumValue(key, i)
                if isinstance(install_dir, str) and _validate_engine_root(install_dir):
                    engine_ver = _read_engine_version(install_dir)
                    if engine_ver == assoc:
                        return install_dir
                i += 1
            except OSError:
                break
    except (ImportError, OSError):
        pass
    return None


def _find_engine_from_registry() -> Optional[str]:
    """Try to find any engine path from Windows registry."""
    if sys.platform != "win32":
        return None
    # HKLM — official installs
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\EpicGames\Unreal Engine",
        )
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(key, i)
                subkey = winreg.OpenKey(key, subkey_name)
                install_dir, _ = winreg.QueryValueEx(
                    subkey, "InstalledDirectory"
                )
                if _validate_engine_root(install_dir):
                    return install_dir
                i += 1
            except OSError:
                break
    except (ImportError, OSError):
        pass
    # HKCU — custom builds
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Epic Games\Unreal Engine\Builds",
        )
        i = 0
        while True:
            try:
                name, install_dir, vtype = winreg.EnumValue(key, i)
                if isinstance(install_dir, str) and _validate_engine_root(install_dir):
                    return install_dir
                i += 1
            except OSError:
                break
    except (ImportError, OSError):
        pass
    return None


def find_editor_exe(engine_root: str) -> Optional[str]:
    """Locate UnrealEditor.exe (or UnrealEditor-Cmd.exe)."""
    root = Path(engine_root)
    candidates = [
        root / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe",
        root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe",
        root / "Engine" / "Binaries" / "Win64" / "UE4Editor.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def find_uat(engine_root: str) -> Optional[str]:
    """Locate RunUAT.bat."""
    root = Path(engine_root)
    candidates = [
        root / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat",
        root / "RunUAT.bat",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def find_build_bat(engine_root: str) -> Optional[str]:
    """Locate Build.bat."""
    root = Path(engine_root)
    candidates = [
        root / "Engine" / "Build" / "BatchFiles" / "Build.bat",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def find_generate_project_files(engine_root: str) -> Optional[str]:
    """Locate GenerateProjectFiles.bat."""
    root = Path(engine_root)
    candidates = [
        root / "GenerateProjectFiles.bat",
        root / "Engine" / "Build" / "BatchFiles" / "GenerateProjectFiles.bat",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def run_uat(
    engine_root: str,
    command: str,
    args: list[str] | None = None,
    log_file: str | None = None,
    log_label: str = "uat",
    project_dir: str | None = None,
    heartbeat_seconds: float = 60.0,
) -> dict:
    """Execute a UAT command synchronously.

    stdout/stderr are redirected directly to ``log_file`` (allocated under
    the project's ``Saved/Logs/`` if not provided) — never buffered in the
    caller's memory. This prevents huge build logs from polluting AI context.

    While the child runs, a heartbeat line is written to the calling
    process's stderr every ``heartbeat_seconds`` seconds (see
    ``_run_subprocess``) so AI callers tailing the stream can tell the
    build is still alive.

    This function blocks until UAT exits. For long-running builds (5-15 min
    compile, 15-30 min package), the caller is expected to wrap this in
    its own background mechanism rather than fork a detached child here —
    AI harnesses routinely use kill-on-job-close Job Objects that would
    kill any "detached" descendant when the CLI returns anyway.

    Args:
        engine_root: Path to engine root.
        command: UAT command name (e.g., "BuildCookRun").
        args: Additional arguments.
        log_file: Absolute path to write combined stdout+stderr. If None,
            a timestamped file is allocated under ``<project_dir>/Saved/Logs``
            (or the system temp dir if ``project_dir`` is None).
        log_label: Short tag used in the auto-allocated log filename
            (e.g. "compile", "cook", "package"). Also used as the
            heartbeat label.
        project_dir: Project root for default log location.
        heartbeat_seconds: Period between stderr "still alive" lines.
            Default 60s. Pass 0 to disable.

    Returns:
        ``{"returncode": int, "log_file": str, "duration_seconds": float}``.
        On startup failure (FileNotFoundError etc.): returncode=-1 and an
        extra ``"error"`` key with a short message.
    """
    uat = find_uat(engine_root)
    if not uat:
        return {
            "returncode": -1,
            "log_file": "",
            "duration_seconds": 0.0,
            "error": "RunUAT.bat not found",
        }

    cmd = [uat, command] + (args or [])
    if log_file is None:
        log_file = _allocate_log_path(project_dir, log_label)
    return _run_subprocess(
        cmd,
        log_file=log_file,
        heartbeat_seconds=heartbeat_seconds,
        heartbeat_label=log_label,
    )


def run_build(
    engine_root: str,
    target: str,
    platform: str = "Win64",
    config: str = "Development",
    extra_args: list[str] | None = None,
    log_file: str | None = None,
    log_label: str = "build",
    project_dir: str | None = None,
    heartbeat_seconds: float = 60.0,
) -> dict:
    """Execute Build.bat.

    stdout/stderr are redirected to ``log_file`` (see ``run_uat``). A
    heartbeat is written to stderr every ``heartbeat_seconds`` seconds.

    Args:
        engine_root: Path to engine root.
        target: Build target name.
        platform: Target platform.
        config: Build configuration.
        extra_args: Additional arguments.
        log_file: Absolute path to write combined output. Auto-allocated
            under ``<project_dir>/Saved/Logs`` if None.
        log_label: Short tag for the auto-allocated filename; also used
            as the heartbeat label.
        project_dir: Project root for default log location.
        heartbeat_seconds: Period between stderr heartbeats. Pass 0 to
            disable.

    Returns:
        Same shape as ``run_uat``.
    """
    build_bat = find_build_bat(engine_root)
    if not build_bat:
        return {
            "returncode": -1,
            "log_file": "",
            "duration_seconds": 0.0,
            "error": "Build.bat not found",
        }

    cmd = [build_bat, target, platform, config] + (extra_args or [])
    if log_file is None:
        log_file = _allocate_log_path(project_dir, log_label)
    return _run_subprocess(
        cmd,
        log_file=log_file,
        heartbeat_seconds=heartbeat_seconds,
        heartbeat_label=log_label,
    )


# Safety timeout: 24 hours. Not user-configurable.
# The AI should use `build stop` to cancel long-running builds.
_SAFETY_TIMEOUT = 86400


def _allocate_log_path(project_dir: str | None, label: str) -> str:
    """Build an absolute path under Saved/Logs for a new CLI log file.

    Falls back to the system temp dir when project_dir is None or not a
    directory, so we never fail just because the caller omitted it.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"cli_{label}_{ts}.log"
    if project_dir and Path(project_dir).is_dir():
        log_dir = Path(project_dir) / "Saved" / "Logs"
    else:
        import tempfile
        log_dir = Path(tempfile.gettempdir()) / "cli_anything_unreal_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return str(log_dir / filename)


def _kill_process_tree(pid: int) -> bool:
    """Kill a process and all its descendants using taskkill /F /T.

    Uses the /T flag to terminate the entire process tree,
    which is critical for killing UAT→UBT→MSBuild→cl.exe chains.

    Args:
        pid: Process ID to kill.

    Returns:
        True if the kill command succeeded.
    """
    if sys.platform != "win32":
        try:
            import signal
            os.kill(pid, signal.SIGKILL)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    try:
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _run_subprocess(
    cmd: list[str],
    log_file: str,
    cwd: str | None = None,
    heartbeat_seconds: float = 60.0,
    heartbeat_label: str = "build",
) -> dict:
    """Run a subprocess with stdout+stderr redirected to ``log_file``.

    The child's stdout and stderr are wired directly to an on-disk file, so
    output never transits Python memory and the pipe-buffer deadlock class
    (child blocks when ~64KB of unread output fills the OS pipe) is
    impossible by construction. This is the key property for UE build
    commands, whose combined output can reach tens of MB.

    While the child runs, a heartbeat line is written to stderr every
    ``heartbeat_seconds`` seconds so AI callers watching the subprocess
    can tell the build is still alive:

        [build] elapsed 2m00s  log 1.23 MB

    ``log`` is the current size of the build log file — it grows while
    UAT is producing output, so a stalled log is a strong hint that the
    build is genuinely stuck (vs. just slow). The log path itself is
    printed once up front by the caller, not repeated in every beat.
    Setting ``heartbeat_seconds <= 0`` disables heartbeats.

    Uses Popen so we can track the PID and kill the entire process tree on
    timeout (fixes the orphan MSBuild/UBT bug).

    Args:
        cmd: Command vector.
        log_file: Absolute path to the log file. Parent dir will be created.
            Overwritten if it already exists.
        cwd: Working directory for the child.
        heartbeat_seconds: Period between "still alive" stderr prints.
            Default 60s. Pass 0 or a negative value to disable.
        heartbeat_label: Tag used in the heartbeat line (e.g. "compile").

    Returns:
        ``{"returncode": int, "log_file": str, "duration_seconds": float}``.
        ``returncode == -1`` for launch failures (with an ``"error"`` key),
        ``-2`` for timeouts (with an ``"error"`` key naming the timeout).
    """
    use_shell = sys.platform == "win32"

    # Ensure the log path is writable before spawning anything.
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()

    try:
        log_fh = open(log_path, "wb")
    except OSError as e:
        return {
            "returncode": -1,
            "log_file": str(log_path),
            "duration_seconds": 0.0,
            "error": f"Failed to open log file: {e}",
        }

    try:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                shell=use_shell,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if use_shell else 0,
            )
        except FileNotFoundError as e:
            return {
                "returncode": -1,
                "log_file": str(log_path),
                "duration_seconds": round(time.monotonic() - started, 2),
                "error": f"Command not found: {e}",
            }
        except Exception as e:
            return {
                "returncode": -1,
                "log_file": str(log_path),
                "duration_seconds": round(time.monotonic() - started, 2),
                "error": str(e),
            }

        # Poll-wait with heartbeats. We can't use proc.wait(timeout=...) in
        # a tight loop without paying context-switch cost, but polling once
        # per heartbeat_seconds is essentially free.
        do_heartbeat = heartbeat_seconds and heartbeat_seconds > 0
        poll_interval = (
            min(heartbeat_seconds, 5.0) if do_heartbeat else 5.0
        )
        next_beat = started + heartbeat_seconds if do_heartbeat else float("inf")
        deadline = started + _SAFETY_TIMEOUT

        while True:
            try:
                proc.wait(timeout=poll_interval)
                break
            except subprocess.TimeoutExpired:
                now = time.monotonic()
                if now >= deadline:
                    # Safety timeout tripped — kill the whole tree.
                    _kill_process_tree(proc.pid)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    return {
                        "returncode": -2,
                        "log_file": str(log_path),
                        "duration_seconds": round(now - started, 2),
                        "error": f"Command timed out after {_SAFETY_TIMEOUT}s",
                    }
                if do_heartbeat and now >= next_beat:
                    _emit_heartbeat(
                        heartbeat_label, now - started, log_path,
                    )
                    # Schedule the next beat relative to the last one, so
                    # drift doesn't accumulate if a poll is slow.
                    next_beat += heartbeat_seconds

        return {
            "returncode": proc.returncode,
            "log_file": str(log_path),
            "duration_seconds": round(time.monotonic() - started, 2),
        }
    finally:
        try:
            log_fh.close()
        except Exception:
            pass


def _format_elapsed(seconds: float) -> str:
    """Format a duration as ``1h02m`` / ``12m34s`` / ``45s``."""
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}h{(s % 3600) // 60:02d}m"
    if s >= 60:
        return f"{s // 60}m{s % 60:02d}s"
    return f"{s}s"


def _format_size(nbytes: int) -> str:
    """Format a byte count as KB/MB/GB."""
    if nbytes >= 1024 ** 3:
        return f"{nbytes / 1024 ** 3:.2f} GB"
    if nbytes >= 1024 ** 2:
        return f"{nbytes / 1024 ** 2:.2f} MB"
    if nbytes >= 1024:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes} B"


def _emit_heartbeat(label: str, elapsed: float, log_path: Path) -> None:
    """Write ``[label] elapsed <t>  log <size>`` to stderr.

    Semantics:
      - elapsed — wall-clock time since the child was spawned. Lets the
        AI see "still running" without inferring it from stream silence.
      - log — current size of the build log file. Grows while UAT is
        producing output; a stalled value is a strong signal that the
        build is genuinely stuck. Naming it ``log`` (not ``size``) makes
        this unambiguous on a single line of output.

    The log *path* is deliberately omitted: callers are expected to
    print it once before the build starts, and repeating it every
    heartbeat wastes AI tokens without adding signal.

    Swallows all exceptions — a heartbeat failure must never disturb the
    actual build.
    """
    try:
        size = log_path.stat().st_size if log_path.exists() else 0
        sys.stderr.write(
            f"[{label}] elapsed {_format_elapsed(elapsed)}  "
            f"log {_format_size(size)}\n"
        )
        sys.stderr.flush()
    except Exception:
        pass


def get_engine_version(engine_root: str) -> Optional[str]:
    """Read engine version from Build.version."""
    version_file = Path(engine_root) / "Engine" / "Build" / "Build.version"
    if version_file.exists():
        try:
            data = json.loads(version_file.read_text(encoding="utf-8"))
            major = data.get("MajorVersion", "?")
            minor = data.get("MinorVersion", "?")
            patch = data.get("PatchVersion", "?")
            return f"{major}.{minor}.{patch}"
        except (json.JSONDecodeError, OSError):
            pass
    return None


# ── Remote Control config ────────────────────────────────────────────────

_REMOTE_CONTROL_INI_SECTION = "/Script/RemoteControlCommon.RemoteControlSettings"
_REMOTE_CONTROL_REQUIRED_SETTINGS = {
    "bRestrictServerAccess": "True",
    "bAllowConsoleCommandRemoteExecution": "True",
    "bEnableRemotePythonExecution": "True",
    'AllowedOrigin': '"*"',
}


def ensure_remote_control_config(project_dir: str) -> dict:
    """Ensure the project has Remote Control configured for CLI use.

    Creates or updates DefaultRemoteControl.ini to enable:
    - Remote console command execution
    - Remote Python execution
    - Allow all origins

    Args:
        project_dir: Path to project root directory.

    Returns:
        {"status": "ok"|"created"|"updated", "file": str, "changes": [...]}
    """
    config_dir = Path(project_dir) / "Config"
    config_file = config_dir / "DefaultRemoteControl.ini"
    changes = []

    if not config_dir.is_dir():
        config_dir.mkdir(parents=True, exist_ok=True)

    if not config_file.exists():
        # Create new config
        lines = [f"\n[{_REMOTE_CONTROL_INI_SECTION}]"]
        for key, value in _REMOTE_CONTROL_REQUIRED_SETTINGS.items():
            lines.append(f"{key}={value}")
        lines.append("")
        config_file.write_text("\n".join(lines), encoding="utf-8")
        changes.append("Created DefaultRemoteControl.ini with all settings")
        return {"status": "created", "file": str(config_file), "changes": changes}

    # Read existing config and check/update settings
    content = config_file.read_text(encoding="utf-8-sig")
    updated = False

    for key, required_value in _REMOTE_CONTROL_REQUIRED_SETTINGS.items():
        if key not in content:
            # Key missing — append before the last line of the section
            # Simple approach: append to file
            if _REMOTE_CONTROL_INI_SECTION not in content:
                content += f"\n[{_REMOTE_CONTROL_INI_SECTION}]\n"
            content += f"{key}={required_value}\n"
            changes.append(f"Added {key}={required_value}")
            updated = True
        elif f"{key}=False" in content or f"{key}=false" in content:
            content = content.replace(f"{key}=False", f"{key}={required_value}")
            content = content.replace(f"{key}=false", f"{key}={required_value}")
            changes.append(f"Changed {key} from False to {required_value}")
            updated = True

    if updated:
        config_file.write_text(content, encoding="utf-8")
        return {"status": "updated", "file": str(config_file), "changes": changes}

    return {"status": "ok", "file": str(config_file), "changes": []}


def check_remote_control_config(project_dir: str) -> dict:
    """Check if Remote Control is properly configured.

    Returns:
        {"configured": bool, "issues": [...], "file": str|None}
    """
    config_file = Path(project_dir) / "Config" / "DefaultRemoteControl.ini"
    issues = []

    if not config_file.exists():
        return {
            "configured": False,
            "issues": [
                "DefaultRemoteControl.ini not found. "
                "Remote console commands and Python execution will be blocked. "
                "Run: cli-anything-unreal editor enable-remote"
            ],
            "file": None,
        }

    content = config_file.read_text(encoding="utf-8-sig")

    if "bAllowConsoleCommandRemoteExecution=True" not in content:
        issues.append(
            "bAllowConsoleCommandRemoteExecution is not True. "
            "Console commands (exec, cvar set) will fail."
        )

    if "bEnableRemotePythonExecution=True" not in content:
        issues.append(
            "bEnableRemotePythonExecution is not True. "
            "Python script execution will fail."
        )

    port = _parse_rc_port(content)

    return {
        "configured": len(issues) == 0,
        "issues": issues,
        "file": str(config_file),
        "port": port,
    }


def _parse_rc_port(ini_content: str) -> int | None:
    """Parse RemoteControlHttpServerPort from an INI file content string.

    Returns:
        Port number (int) if found, None otherwise.
    """
    for line in ini_content.splitlines():
        line = line.strip()
        if line.startswith("RemoteControlHttpServerPort="):
            try:
                return int(line.split("=", 1)[1].strip())
            except (ValueError, IndexError):
                return None
    return None


def read_rc_port(project_dir: str) -> int | None:
    """Read the Remote Control HTTP port from project config.

    Looks for ``RemoteControlHttpServerPort`` in
    ``Config/DefaultRemoteControl.ini``.

    Args:
        project_dir: Path to the UE project root.

    Returns:
        Port number (int) if configured, None to use the default.
    """
    config_file = Path(project_dir) / "Config" / "DefaultRemoteControl.ini"
    if not config_file.exists():
        return None
    try:
        content = config_file.read_text(encoding="utf-8-sig")
    except Exception:
        return None
    return _parse_rc_port(content)


# ── Build status checks ─────────────────────────────────────────────────

def check_engine_build(engine_root: str) -> dict:
    """Check if the engine has been compiled and is ready to run.

    Checks for:
    1. UnrealEditor.exe exists
    2. UnrealEditor.modules exists (module mappings + BuildId)
    3. UnrealEditor.target exists (build config)
    4. Build.version is valid

    Args:
        engine_root: Path to engine root.

    Returns:
        {"ready": bool, "build_id": str, "errors": [...], "warnings": [...], "details": {...}}
    """
    root = Path(engine_root)
    bin_dir = root / "Engine" / "Binaries" / "Win64"
    errors = []
    warnings = []
    details = {"engine_root": engine_root}
    build_id = ""

    # Check 1: UnrealEditor.exe
    editor_exe = bin_dir / "UnrealEditor.exe"
    if not editor_exe.exists():
        errors.append(
            f"UnrealEditor.exe not found at {bin_dir}. "
            "Engine has not been compiled. Build the engine from source first."
        )
    else:
        size = editor_exe.stat().st_size
        details["editor_exe_size"] = size
        if size < 100_000:
            warnings.append(
                f"UnrealEditor.exe is unusually small ({size} bytes). "
                "Engine build may be incomplete."
            )

    # Check 2: UnrealEditor.modules (BuildId + module mappings)
    modules_file = bin_dir / "UnrealEditor.modules"
    if not modules_file.exists():
        errors.append(
            "UnrealEditor.modules not found. "
            "Engine modules have not been compiled."
        )
    else:
        try:
            modules_data = json.loads(modules_file.read_text(encoding="utf-8"))
            build_id = modules_data.get("BuildId", "")
            module_count = len(modules_data.get("Modules", {}))
            details["engine_build_id"] = build_id
            details["engine_module_count"] = module_count
            if module_count < 10:
                warnings.append(
                    f"Only {module_count} engine modules found. "
                    "Build may be incomplete."
                )
        except (json.JSONDecodeError, OSError):
            warnings.append("Could not parse UnrealEditor.modules")

    # Check 3: UnrealEditor.target (build metadata)
    target_file = bin_dir / "UnrealEditor.target"
    if not target_file.exists():
        warnings.append(
            "UnrealEditor.target not found. "
            "Engine may not have a complete build."
        )

    # Check 4: Build.version
    version = get_engine_version(engine_root)
    if version:
        details["engine_version"] = version
    else:
        warnings.append("Could not read engine version from Build.version")

    details["ready"] = len(errors) == 0
    return {
        "ready": len(errors) == 0,
        "build_id": build_id,
        "errors": errors,
        "warnings": warnings,
        "details": details,
    }


def check_project_build(uproject_path: str, engine_build_id: str = "") -> dict:
    """Check if a project's C++ code has been compiled and matches the engine.

    For Blueprint-only projects (no Source/ dir), compilation is not needed
    BUT the project's UnrealEditor.modules BuildId must match the engine's.

    Checks for:
    1. Whether the project has C++ code (Source/ directory)
    2. UnrealEditor-{ProjectName}.dll exists in Binaries/Win64/
    3. BuildId in project's UnrealEditor.modules matches engine BuildId
    4. DLL is not stale (newer than Source/ files)

    Args:
        uproject_path: Path to .uproject file.
        engine_build_id: Engine's BuildId for version matching.

    Returns:
        {"ready": bool, "needs_compile": bool, "errors": [...], "warnings": [...], "details": {...}}
    """
    path = Path(uproject_path)
    project_dir = path.parent
    project_name = path.stem
    errors = []
    warnings = []
    details = {"project": project_name, "project_path": str(path)}

    # ── Check BuildId match (critical for custom engine builds) ─────
    project_modules_file = project_dir / "Binaries" / "Win64" / "UnrealEditor.modules"
    project_build_id = ""

    if project_modules_file.exists():
        try:
            mod_data = json.loads(project_modules_file.read_text(encoding="utf-8"))
            project_build_id = mod_data.get("BuildId", "")
            details["project_build_id"] = project_build_id
            details["project_module_names"] = list(mod_data.get("Modules", {}).keys())
        except (json.JSONDecodeError, OSError):
            pass

    if engine_build_id and project_build_id:
        if engine_build_id != project_build_id:
            errors.append(
                f"BuildId MISMATCH: engine='{engine_build_id[:8]}...' vs project='{project_build_id[:8]}...'. "
                f"Project was compiled with a different engine version. "
                f"Launching will fail with 'modules built with a different engine version'. "
                f"Recompile: cli-anything-unreal --project {uproject_path} build compile"
            )
            details["build_id_match"] = False
        else:
            details["build_id_match"] = True
    elif engine_build_id and not project_build_id:
        if (project_dir / "Binaries" / "Win64").is_dir():
            warnings.append(
                "Could not read project BuildId from UnrealEditor.modules. "
                "Cannot verify engine/project version match."
            )

    # ── Check if project has C++ code ───────────────────────────────
    source_dir = project_dir / "Source"
    has_source = source_dir.is_dir()
    details["has_cpp_source"] = has_source

    if not has_source:
        # Blueprint-only project — no C++ compilation needed
        # But BuildId still must match if binaries exist
        ready = len(errors) == 0
        return {
            "ready": ready,
            "needs_compile": not ready,
            "errors": errors,
            "warnings": warnings,
            "details": {**details, "note": "Blueprint-only project, no C++ compilation needed"},
        }

    # Count source files
    cpp_files = list(source_dir.rglob("*.cpp"))
    h_files = list(source_dir.rglob("*.h"))
    details["cpp_files"] = len(cpp_files)
    details["header_files"] = len(h_files)

    # Check for compiled DLL
    bin_dir = project_dir / "Binaries" / "Win64"
    if not bin_dir.is_dir():
        errors.append(
            f"Binaries/Win64/ directory not found. "
            f"Project '{project_name}' has never been compiled. "
            f"Run: cli-anything-unreal build compile --project {uproject_path}"
        )
        return {
            "ready": False,
            "needs_compile": True,
            "errors": errors,
            "warnings": warnings,
            "details": details,
        }

    # Find project DLLs — they follow the pattern UnrealEditor-{ModuleName}.dll
    # Read module names from .uproject
    try:
        uproject_data = json.loads(path.read_text(encoding="utf-8-sig"))
        modules = [m["Name"] for m in uproject_data.get("Modules", [])]
    except Exception:
        modules = [project_name]

    details["expected_modules"] = modules
    missing_modules = []
    stale_modules = []

    # Find newest source file timestamp
    newest_source_time = 0
    for src in cpp_files + h_files:
        mtime = src.stat().st_mtime
        if mtime > newest_source_time:
            newest_source_time = mtime

    for module_name in modules:
        dll_path = bin_dir / f"UnrealEditor-{module_name}.dll"
        if not dll_path.exists():
            missing_modules.append(module_name)
        else:
            dll_time = dll_path.stat().st_mtime
            details[f"dll_{module_name}_size"] = dll_path.stat().st_size
            # Check if DLL is older than source
            if newest_source_time > dll_time:
                stale_modules.append(module_name)

    if missing_modules:
        errors.append(
            f"Compiled modules not found: {', '.join(missing_modules)}. "
            f"Project C++ code has not been compiled. "
            f"Run: cli-anything-unreal build compile --project {uproject_path}"
        )

    if stale_modules:
        warnings.append(
            f"Modules may be stale (source newer than binary): {', '.join(stale_modules)}. "
            f"Consider recompiling."
        )

    # Check for .target file
    target_file = bin_dir / f"{project_name}Editor.target"
    if not target_file.exists():
        # Try alternative naming
        targets = list(bin_dir.glob("*.target"))
        if not targets:
            warnings.append(
                f"{project_name}Editor.target not found. "
                "Build metadata may be missing."
            )
        else:
            details["target_files"] = [t.name for t in targets]

    needs_compile = len(missing_modules) > 0 or len(errors) > 0
    return {
        "ready": len(errors) == 0 and not needs_compile,
        "needs_compile": needs_compile,
        "errors": errors,
        "warnings": warnings,
        "details": details,
    }


def preflight_check(uproject_path: str, engine_root: str | None = None) -> dict:
    """Full preflight check before launching editor.

    Checks both engine build and project build status.

    Args:
        uproject_path: Path to .uproject file.
        engine_root: Engine root (auto-detected if None).

    Returns:
        {"ready": bool, "engine": {...}, "project": {...}}
    """
    if engine_root is None:
        engine_root = find_engine_root(uproject_path)

    result = {"ready": False}

    if not engine_root:
        result["engine"] = {
            "ready": False,
            "errors": ["Could not find engine root. Set UE_ENGINE_ROOT or use --engine-root."],
            "warnings": [],
            "details": {},
        }
        result["project"] = {"ready": False, "errors": [], "warnings": [], "details": {}}
        return result

    engine_check = check_engine_build(engine_root)
    project_check = check_project_build(
        uproject_path,
        engine_build_id=engine_check.get("build_id", ""),
    )

    # Check Remote Control config
    project_dir = str(Path(uproject_path).parent)
    rc_check = check_remote_control_config(project_dir)
    if not rc_check["configured"]:
        # Auto-fix: create/update the config
        fix_result = ensure_remote_control_config(project_dir)
        rc_check["auto_fixed"] = fix_result["status"] in ("created", "updated")
        rc_check["fix_result"] = fix_result
        if fix_result["status"] in ("created", "updated"):
            for issue in rc_check["issues"]:
                project_check.setdefault("warnings", []).append(
                    f"Fixed: {issue} (editor restart needed)"
                )

    result["engine"] = engine_check
    result["project"] = project_check
    result["remote_control"] = rc_check
    result["ready"] = engine_check["ready"] and project_check["ready"]
    result["engine_root"] = engine_root

    return result


def find_running_editors() -> list[dict]:
    """Find running UnrealEditor processes and their project paths.

    Uses PowerShell (preferred) with WMIC fallback on Windows.

    Returns a list of dicts: [{"pid": int, "project": str, "cmdline": str}, ...]
    """
    if sys.platform != "win32":
        return []

    editors = []

    # ── Method 1: PowerShell (reliable on modern Windows) ──────────
    try:
        ps_cmd = (
            'Get-CimInstance Win32_Process -Filter "Name like \'%UnrealEditor%\'" '
            '| Select-Object ProcessId, CommandLine '
            '| ConvertTo-Json -Compress'
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            # PowerShell returns a single object if 1 result, array if multiple
            if isinstance(data, dict):
                data = [data]
            for proc in data:
                cmdline = proc.get("CommandLine", "")
                pid = proc.get("ProcessId", 0)
                project = ""
                for token in cmdline.split():
                    if token.endswith(".uproject") or token.endswith('.uproject"'):
                        project = token.strip('"')
                        break
                editors.append({
                    "pid": int(pid),
                    "project": project,
                    "cmdline": cmdline,
                })
            return editors
    except Exception:
        pass

    # ── Method 2: WMIC fallback ────────────────────────────────────
    try:
        result = subprocess.run(
            ["wmic", "process", "where",
             "name like '%UnrealEditor%'",
             "get", "ProcessId,CommandLine", "/format:csv"],
            capture_output=True, text=True, timeout=10,
            shell=True,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if not line or "ProcessId" in line or "Node" in line:
                    continue
                parts = line.split(",")
                if len(parts) >= 3:
                    cmdline = ",".join(parts[1:-1])
                    pid = parts[-1].strip()
                    project = ""
                    for token in cmdline.split():
                        if token.endswith(".uproject") or token.endswith('.uproject"'):
                            project = token.strip('"')
                            break
                    editors.append({
                        "pid": int(pid) if pid.isdigit() else 0,
                        "project": project,
                        "cmdline": cmdline,
                    })
    except Exception:
        pass

    return editors


def detect_ue_dialogs() -> list[dict]:
    """Detect modal dialogs blocking a running Unreal Editor on Windows.

    Uses the Windows API (EnumWindows) to find child windows of UE
    that look like modal dialogs (e.g., "Overwrite", "Save Changes",
    "Warning", "Fatal Error" popups).

    Returns:
        List of dicts: [{"title": str, "hwnd": int}, ...].
        Empty list if no dialogs found or not on Windows.
    """
    if sys.platform != "win32":
        return []

    import ctypes
    import ctypes.wintypes

    user32 = ctypes.windll.user32

    DIALOG_KEYWORDS = [
        "overwrite", "override", "save changes", "save asset",
        "warning", "error", "fatal", "assertion", "missing",
        "confirmation", "delete", "replace",
        # Recovery / autosave
        "autosave", "recover", "auto-save", "unsaved",
        "crash", "restore", "unexpected shutdown",
    ]

    results: list[dict] = []
    seen_hwnds: set[int] = set()

    def _get_title(hwnd):
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    ue_main_windows: list[int] = []

    def _enum_main_windows(hwnd, _lparam):
        title = _get_title(hwnd)
        if "UnrealEditor" in title:
            ue_main_windows.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    user32.EnumWindows(WNDENUMPROC(_enum_main_windows), 0)

    def _enum_children(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if hwnd in seen_hwnds:
            return True
        seen_hwnds.add(hwnd)
        title = _get_title(hwnd)
        if not title:
            return True
        title_lower = title.lower()
        for kw in DIALOG_KEYWORDS:
            if kw in title_lower:
                results.append({"title": title, "hwnd": hwnd})
                break
        return True

    for main_hwnd in ue_main_windows:
        seen_hwnds.clear()
        user32.EnumChildWindows(main_hwnd, WNDENUMPROC(_enum_children), 0)

    return results


# ── Build process detection & management ────────────────────────────────

_BUILD_PROCESS_NAMES = [
    "MSBuild.exe",
    "UnrealBuildTool.exe",
    "bk-ubt-tool.exe",
    "cl.exe",
    "link.exe",
]


def find_running_build_processes(
    uproject_path: str | None = None,
    include_cmdline: bool = True,
) -> list[dict]:
    """Find running build processes (MSBuild, UBT, cl.exe, etc.).

    If uproject_path is given, only returns processes whose command line
    references that .uproject file.

    Args:
        uproject_path: Filter by this project's .uproject path.
        include_cmdline: If True (default), each returned dict includes the
            full ``cmdline`` string from Win32_Process. If False, ``cmdline``
            is omitted entirely — useful for AI callers who only need
            {pid, name, project} and would otherwise pay a large token
            cost for every cl.exe's multi-KB compile command line.

    Returns a list of dicts:
        include_cmdline=True:  [{"pid", "name", "cmdline", "project"}, ...]
        include_cmdline=False: [{"pid", "name", "project"}, ...]
    """
    if sys.platform != "win32":
        return []

    processes = []

    # Build PowerShell filter for process names
    name_filters = " or ".join(f"Name = '{n}'" for n in _BUILD_PROCESS_NAMES)

    try:
        ps_cmd = (
            f'Get-CimInstance Win32_Process -Filter "{name_filters}" '
            '| Select-Object ProcessId, Name, CommandLine '
            '| ConvertTo-Json -Compress'
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, dict):
                data = [data]
            for proc in data:
                pid = proc.get("ProcessId", 0)
                name = proc.get("Name", "")
                cmdline = proc.get("CommandLine", "") or ""

                # Extract .uproject path from command line
                project = ""
                for token in cmdline.split():
                    if ".uproject" in token:
                        # Handle -project=X.uproject and plain X.uproject
                        if "=" in token:
                            token = token.split("=", 1)[1]
                        token = token.strip('"').strip("'")
                        if token.endswith(".uproject"):
                            project = token
                            break

                # Filter by project if requested
                if uproject_path:
                    # If cmdline contains a .uproject, it must match
                    norm_project = project.replace("/", "\\").lower()
                    norm_uproject = uproject_path.replace("/", "\\").lower()
                    if project:
                        # This process has a .uproject in its cmdline
                        if norm_project != norm_uproject:
                            continue
                    else:
                        # No .uproject in cmdline (e.g., bk-ubt-tool, cl.exe).
                        # Include if any process in the result set DOES reference
                        # this project (they're likely part of the same build).
                        # We defer this check — collect all first, filter after.
                        pass

                processes.append({
                    "pid": int(pid),
                    "name": name,
                    "cmdline": cmdline,
                    "project": project,
                })
            # Post-filter: if uproject_path given, processes without
            # .uproject in their cmdline (e.g., bk-ubt-tool, cl.exe)
            # are only included if at least one process explicitly
            # references this project.
            if uproject_path:
                has_matching_project = any(
                    p["project"] and
                    p["project"].replace("/", "\\").lower() ==
                    uproject_path.replace("/", "\\").lower()
                    for p in processes
                )
                if has_matching_project:
                    # Keep all — project-specific + associated processes
                    pass
                else:
                    # No process explicitly references this project.
                    # Only include processes that have no .uproject at all
                    # and might be related (ambiguous, safer to exclude).
                    processes = [p for p in processes if not p["project"]]
            if not include_cmdline:
                processes = [
                    {k: v for k, v in p.items() if k != "cmdline"}
                    for p in processes
                ]
            return processes
    except Exception:
        pass

    return processes


def kill_build_processes(uproject_path: str | None = None) -> dict:
    """Kill all build processes for a project (or all build processes).

    Finds running build processes via find_running_build_processes(),
    kills each with _kill_process_tree(), waits, and re-checks.

    Args:
        uproject_path: If given, only kill processes for this project.
            If None, kill all build processes.

    Returns:
        {"killed": [pid, ...], "remaining": [pid, ...], "status": "ok"|"partial"|"none"}
    """
    processes = find_running_build_processes(uproject_path)

    if not processes:
        return {"killed": [], "remaining": [], "status": "none"}

    killed = []
    failed = []

    for proc in processes:
        if _kill_process_tree(proc["pid"]):
            killed.append(proc["pid"])
        else:
            failed.append(proc["pid"])

    # Wait for processes to actually terminate
    import time
    time.sleep(3)

    # Re-check: some processes may have spawned new children
    remaining_procs = find_running_build_processes(uproject_path)
    remaining_pids = [p["pid"] for p in remaining_procs if p["pid"] not in killed]

    # Second pass: kill any remaining
    if remaining_pids:
        time.sleep(5)
        for pid in remaining_pids:
            _kill_process_tree(pid)
        time.sleep(3)
        # Final check
        final_procs = find_running_build_processes(uproject_path)
        remaining_pids = [p["pid"] for p in final_procs]

    status = "ok"
    if remaining_pids:
        status = "partial"
    elif not killed:
        status = "none"

    return {
        "killed": killed,
        "remaining": remaining_pids,
        "status": status,
    }
