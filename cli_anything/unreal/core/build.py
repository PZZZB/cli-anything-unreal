"""core/build.py — Build system wrapper for Unreal Engine.

Wraps UAT (RunUAT.bat) and UBT (Build.bat) for compile, cook,
package, and project file generation. No editor needed.
"""

import json
import os
from pathlib import Path
from typing import Optional

from cli_anything.unreal.utils.ue_backend import (
    find_engine_root,
    find_uat,
    find_build_bat,
    find_generate_project_files,
    run_uat,
    run_build,
    get_engine_version,
    find_running_build_processes,
    kill_build_processes,
)


def _check_already_building(uproject_path: str) -> dict | None:
    """Check if a build is already running for this project.

    Returns an error dict if a build is in progress, None otherwise.
    """
    processes = find_running_build_processes(uproject_path)
    if processes:
        pids = [p["pid"] for p in processes]
        names = [p["name"] for p in processes]
        return {
            "status": "error",
            "error": (
                f"Build already in progress for this project "
                f"(PIDs: {pids}, processes: {names}). "
                f"Use 'build stop' to cancel the running build first."
            ),
            "running_processes": processes,
        }
    return None


def compile_project(
    uproject_path: str,
    config: str = "Development",
    platform: str = "Win64",
    engine_root: str | None = None,
) -> dict:
    """Compile the project's C++ code.

    Output is redirected directly to a log file under
    ``<project>/Saved/Logs/``. The returned dict contains the log path, not
    the log body — callers should open the file if they need to inspect
    errors. This keeps multi-MB UE build logs out of AI context.

    Args:
        uproject_path: Path to .uproject file.
        config: Build configuration (Development, Shipping, DebugGame, etc.).
        platform: Target platform (Win64, Linux, etc.).
        engine_root: Engine root (auto-detected if None).

    Returns:
        ``{"status": "ok"|"error", "returncode": int,
           "duration_seconds": float, "log_file": str, "error"?: str}``.
    """
    # Check if a build is already running
    already = _check_already_building(uproject_path)
    if already:
        return already

    if engine_root is None:
        engine_root = find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    path = Path(uproject_path)
    project_name = path.stem

    # Use UAT BuildCookRun with -build only
    args = [
        f"-project={uproject_path}",
        f"-platform={platform}",
        f"-clientconfig={config}",
        "-build",
        "-noP4",
        "-utf8output",
    ]

    result = run_uat(
        engine_root,
        "BuildCookRun",
        args,
        log_label="compile",
        project_dir=str(path.parent),
    )

    out = {
        "status": "ok" if result["returncode"] == 0 else "error",
        "returncode": result["returncode"],
        "duration_seconds": result.get("duration_seconds", 0.0),
        "log_file": result.get("log_file", ""),
    }
    if result["returncode"] != 0:
        out["error"] = result.get(
            "error",
            f"Compile failed (exit {result['returncode']}). See log_file for details.",
        )
    return out


def cook_content(
    uproject_path: str,
    platform: str = "Win64",
    engine_root: str | None = None,
) -> dict:
    """Cook content assets for the target platform.

    Args:
        uproject_path: Path to .uproject file.
        platform: Target platform.
        engine_root: Engine root (auto-detected if None).

    Returns:
        Same shape as ``compile_project``.
    """
    # Check if a build is already running
    already = _check_already_building(uproject_path)
    if already:
        return already

    if engine_root is None:
        engine_root = find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    path = Path(uproject_path)
    args = [
        f"-project={uproject_path}",
        f"-platform={platform}",
        "-cook",
        "-noP4",
        "-utf8output",
        "-allmaps",
    ]

    result = run_uat(
        engine_root,
        "BuildCookRun",
        args,
        log_label="cook",
        project_dir=str(path.parent),
    )

    out = {
        "status": "ok" if result["returncode"] == 0 else "error",
        "returncode": result["returncode"],
        "duration_seconds": result.get("duration_seconds", 0.0),
        "log_file": result.get("log_file", ""),
    }
    if result["returncode"] != 0:
        out["error"] = result.get(
            "error",
            f"Cook failed (exit {result['returncode']}). See log_file for details.",
        )
    return out


def package_project(
    uproject_path: str,
    platform: str = "Win64",
    config: str = "Development",
    output_dir: str | None = None,
    engine_root: str | None = None,
) -> dict:
    """Full package pipeline: build + cook + stage + package + archive.

    Args:
        uproject_path: Path to .uproject file.
        platform: Target platform.
        config: Build configuration.
        output_dir: Archive output directory.
        engine_root: Engine root (auto-detected if None).

    Returns:
        ``{"status", "returncode", "duration_seconds", "log_file",
           "output_dir", "error"?}``.
    """
    # Check if a build is already running
    already = _check_already_building(uproject_path)
    if already:
        return already

    if engine_root is None:
        engine_root = find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    path = Path(uproject_path)
    if output_dir is None:
        output_dir = str(path.parent / "Packaged")

    args = [
        f"-project={uproject_path}",
        f"-platform={platform}",
        f"-clientconfig={config}",
        "-build",
        "-cook",
        "-stage",
        "-package",
        "-archive",
        f"-archivedirectory={output_dir}",
        "-noP4",
        "-utf8output",
    ]

    result = run_uat(
        engine_root,
        "BuildCookRun",
        args,
        log_label="package",
        project_dir=str(path.parent),
    )

    out = {
        "status": "ok" if result["returncode"] == 0 else "error",
        "returncode": result["returncode"],
        "duration_seconds": result.get("duration_seconds", 0.0),
        "log_file": result.get("log_file", ""),
        "output_dir": output_dir,
    }
    if result["returncode"] != 0:
        out["error"] = result.get(
            "error",
            f"Package failed (exit {result['returncode']}). See log_file for details.",
        )
    return out


def build_status(uproject_path: str) -> dict:
    """Check build status by examining Binaries/ and Intermediate/.

    Args:
        uproject_path: Path to .uproject file.

    Returns:
        Dict with build status information.
    """
    path = Path(uproject_path)
    project_dir = path.parent
    project_name = path.stem

    binaries_dir = project_dir / "Binaries"
    intermediate_dir = project_dir / "Intermediate"

    status = {
        "project": project_name,
        "has_binaries": binaries_dir.is_dir(),
        "has_intermediate": intermediate_dir.is_dir(),
        "platforms": {},
    }

    if binaries_dir.is_dir():
        for platform_dir in binaries_dir.iterdir():
            if platform_dir.is_dir():
                # Find the most recent binary
                binaries = list(platform_dir.glob("*.dll")) + list(platform_dir.glob("*.exe"))
                newest = None
                newest_time = 0
                for b in binaries:
                    mtime = b.stat().st_mtime
                    if mtime > newest_time:
                        newest = b.name
                        newest_time = mtime
                status["platforms"][platform_dir.name] = {
                    "binary_count": len(binaries),
                    "newest_binary": newest,
                    "newest_time": newest_time,
                }

    # Check for build logs
    saved_dir = project_dir / "Saved" / "Logs"
    if saved_dir.is_dir():
        log_files = sorted(saved_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        status["recent_logs"] = [
            {"name": l.name, "size": l.stat().st_size}
            for l in log_files[:5]
        ]

    return status


def generate_project_files(
    uproject_path: str,
    engine_root: str | None = None,
) -> dict:
    """Generate Visual Studio project files.

    Output is redirected to a log file under ``<project>/Saved/Logs/``.

    Args:
        uproject_path: Path to .uproject file.
        engine_root: Engine root (auto-detected if None).

    Returns:
        ``{"status", "returncode", "duration_seconds", "log_file", "error"?}``.
    """
    if engine_root is None:
        engine_root = find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    project_dir = str(Path(uproject_path).parent)
    gen_bat = find_generate_project_files(engine_root)
    if not gen_bat:
        # Fallback to UAT
        args = [
            f"-project={uproject_path}",
            "-game",
            "-engine",
        ]
        result = run_uat(
            engine_root,
            "GenerateProjectFiles",
            args,
            log_label="genproj",
            project_dir=project_dir,
        )
    else:
        from cli_anything.unreal.utils.ue_backend import (
            _allocate_log_path,
            _run_subprocess,
        )
        log_file = _allocate_log_path(project_dir, "genproj")
        cmd = [gen_bat, f"-project={uproject_path}", "-game", "-engine"]
        result = _run_subprocess(cmd, log_file=log_file)

    out = {
        "status": "ok" if result["returncode"] == 0 else "error",
        "returncode": result["returncode"],
        "duration_seconds": result.get("duration_seconds", 0.0),
        "log_file": result.get("log_file", ""),
    }
    if result["returncode"] != 0:
        out["error"] = result.get(
            "error",
            f"Generate project files failed (exit {result['returncode']}). "
            "See log_file for details.",
        )
    return out


def stop_build(uproject_path: str) -> dict:
    """Stop a running build by killing the process tree.

    Args:
        uproject_path: Path to .uproject file.

    Returns:
        {"status": "ok"|"partial"|"none", "killed": [pid, ...], "remaining": [pid, ...]}
    """
    result = kill_build_processes(uproject_path)
    return {
        "status": result["status"],
        "killed": result["killed"],
        "remaining": result["remaining"],
    }


def is_building(uproject_path: str) -> dict:
    """Check if the project is currently being compiled.

    Args:
        uproject_path: Path to .uproject file.

    Returns:
        {"building": bool, "processes": [{"pid": int, "name": str, ...}, ...]}
    """
    processes = find_running_build_processes(uproject_path)
    return {
        "building": len(processes) > 0,
        "processes": processes,
    }
