"""ue_backend.py — Engine discovery + offline command execution (UAT/UBT).

Handles finding UE installations, locating tools, and running subprocess
commands for build/cook/package operations that don't require a running editor.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


# ── Default engine paths ────────────────────────────────────────────────

_DEFAULT_ENGINE_ROOTS = [
    r"F:\RX_ENGINE_5.7",
    r"C:\Program Files\Epic Games\UE_5.4",
    r"C:\Program Files\Epic Games\UE_5.3",
]


def find_engine_root(uproject_path: Optional[str] = None) -> Optional[str]:
    """Discover the Unreal Engine root directory.

    Strategy:
    1. If uproject_path given, parse EngineAssociation from .uproject
       and look up in registry / known paths
    2. Check UE_ENGINE_ROOT environment variable
    3. Check default installation paths
    4. Look for Build.version in parent directories

    Returns:
        Engine root path (e.g. F:\\RX_ENGINE_5.7) or None.
    """
    # Strategy 1: From .uproject
    if uproject_path:
        uproject = Path(uproject_path)
        if uproject.exists():
            try:
                data = json.loads(uproject.read_text(encoding="utf-8-sig"))
                assoc = data.get("EngineAssociation", "")
                # Check if it's a path-based association (custom build)
                if assoc and os.path.isdir(assoc):
                    return str(assoc)
                # Try to find via .sln file in project dir
                project_dir = uproject.parent
                for sln in project_dir.glob("*.sln"):
                    # .sln may contain engine path references
                    pass
            except (json.JSONDecodeError, OSError):
                pass

    # Strategy 2: Environment variable
    env_root = os.environ.get("UE_ENGINE_ROOT")
    if env_root and _validate_engine_root(env_root):
        return env_root

    # Strategy 3: Default paths
    for root in _DEFAULT_ENGINE_ROOTS:
        if _validate_engine_root(root):
            return root

    # Strategy 4: Windows registry (Epic Games Launcher)
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


def _find_engine_from_registry() -> Optional[str]:
    """Try to find engine path from Windows registry."""
    if sys.platform != "win32":
        return None
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
    timeout: int = 3600,
    capture: bool = True,
) -> dict:
    """Execute a UAT command.

    Args:
        engine_root: Path to engine root.
        command: UAT command name (e.g., "BuildCookRun").
        args: Additional arguments.
        timeout: Timeout in seconds.
        capture: If True, capture stdout/stderr; else stream to console.

    Returns:
        {"returncode": int, "stdout": str, "stderr": str}
    """
    uat = find_uat(engine_root)
    if not uat:
        return {"returncode": -1, "stdout": "", "stderr": "RunUAT.bat not found"}

    cmd = [uat, command] + (args or [])
    return _run_subprocess(cmd, timeout=timeout, capture=capture)


def run_build(
    engine_root: str,
    target: str,
    platform: str = "Win64",
    config: str = "Development",
    extra_args: list[str] | None = None,
    timeout: int = 3600,
) -> dict:
    """Execute Build.bat.

    Args:
        engine_root: Path to engine root.
        target: Build target name.
        platform: Target platform.
        config: Build configuration.
        extra_args: Additional arguments.
        timeout: Timeout in seconds.

    Returns:
        {"returncode": int, "stdout": str, "stderr": str}
    """
    build_bat = find_build_bat(engine_root)
    if not build_bat:
        return {"returncode": -1, "stdout": "", "stderr": "Build.bat not found"}

    cmd = [build_bat, target, platform, config] + (extra_args or [])
    return _run_subprocess(cmd, timeout=timeout)


def _run_subprocess(
    cmd: list[str],
    timeout: int = 3600,
    capture: bool = True,
    cwd: str | None = None,
) -> dict:
    """Run a subprocess and return results.

    Returns:
        {"returncode": int, "stdout": str, "stderr": str}
    """
    try:
        if capture:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=cwd,
                shell=(sys.platform == "win32"),
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        else:
            result = subprocess.run(
                cmd,
                timeout=timeout,
                cwd=cwd,
                shell=(sys.platform == "win32"),
            )
            return {
                "returncode": result.returncode,
                "stdout": "",
                "stderr": "",
            }
    except subprocess.TimeoutExpired:
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
        }
    except FileNotFoundError as e:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command not found: {e}",
        }
    except Exception as e:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
        }


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
