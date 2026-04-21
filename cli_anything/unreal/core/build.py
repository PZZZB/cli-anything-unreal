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

    Args:
        uproject_path: Path to .uproject file.
        config: Build configuration (Development, Shipping, DebugGame, etc.).
        platform: Target platform (Win64, Linux, etc.).
        engine_root: Engine root (auto-detected if None).

    Returns:
        {"status": "ok"|"error", "returncode": int, "stdout": str, "stderr": str}
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

    result = run_uat(engine_root, "BuildCookRun", args)

    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


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
        Build result dict.
    """
    # Check if a build is already running
    already = _check_already_building(uproject_path)
    if already:
        return already

    if engine_root is None:
        engine_root = find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    args = [
        f"-project={uproject_path}",
        f"-platform={platform}",
        "-cook",
        "-noP4",
        "-utf8output",
        "-allmaps",
    ]

    result = run_uat(engine_root, "BuildCookRun", args)

    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


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
        Build result dict.
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

    result = run_uat(engine_root, "BuildCookRun", args)

    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "returncode": result["returncode"],
        "output_dir": output_dir,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


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

    Args:
        uproject_path: Path to .uproject file.
        engine_root: Engine root (auto-detected if None).

    Returns:
        Result dict.
    """
    if engine_root is None:
        engine_root = find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    gen_bat = find_generate_project_files(engine_root)
    if not gen_bat:
        # Fallback to UAT
        args = [
            f"-project={uproject_path}",
            "-game",
            "-engine",
        ]
        result = run_uat(engine_root, "GenerateProjectFiles", args)
    else:
        import subprocess
        import sys
        try:
            proc = subprocess.run(
                [gen_bat, f"-project={uproject_path}", "-game", "-engine"],
                capture_output=True, text=True,
                shell=(sys.platform == "win32"),
            )
            result = {
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        except Exception as e:
            result = {"returncode": -1, "stdout": "", "stderr": str(e)}

    return {
        "status": "ok" if result["returncode"] == 0 else "error",
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


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
