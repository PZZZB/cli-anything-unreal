"""Build system wrapper for Unreal Engine."""

from __future__ import annotations

from pathlib import Path

from cli_anything.unreal.utils.ue_backend import (
    find_engine_root,
    find_generate_project_files,
    find_running_build_processes,
    find_uat,
    get_engine_version,
    kill_build_processes,
    run_uat,
)


_UNSAFE_PACKAGE_VALUE_CHARS = frozenset('"&|<>\0\r\n')


def validate_package_uat_value(
    value: str,
    *,
    label: str,
    require_option: bool = False,
) -> str:
    """Validate a package option before it reaches the Windows UAT wrapper."""
    if require_option and not value.startswith("-"):
        raise ValueError(
            f"{label} must start with '-' (for example --uat-arg=-pak)"
        )
    if any(char in _UNSAFE_PACKAGE_VALUE_CHARS for char in value):
        raise ValueError(
            f"Unsafe {label}: literal quotes, shell control characters, and "
            "NUL/CR/LF are not allowed"
        )
    return value


def _check_already_building(uproject_path: str) -> dict | None:
    processes = find_running_build_processes(uproject_path)
    if not processes:
        return None
    return {
        "status": "error",
        "error": "Build already in progress for this project.",
        "running_processes": processes,
    }


def _normalize_result(result: dict, action: str) -> dict:
    out = {
        "status": "ok" if result["returncode"] == 0 else "error",
        "returncode": result["returncode"],
        "duration_seconds": result.get("duration_seconds", 0.0),
        "log_file": result.get("log_file", ""),
    }
    if result.get("command"):
        out["uat_command"] = result["command"]
    if result["returncode"] != 0:
        out["error"] = result.get(
            "error",
            f"{action} failed (exit {result['returncode']}). See log_file for details.",
        )
    return out


def compile_project(
    uproject_path: str,
    config: str = "Development",
    platform: str = "Win64",
    engine_root: str | None = None,
    log_file: str | None = None,
    on_start=None,
) -> dict:
    already = _check_already_building(uproject_path)
    if already:
        return already

    engine_root = engine_root or find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

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
        log_file=log_file,
        log_label="compile",
        project_dir=str(Path(uproject_path).parent),
        on_start=on_start,
    )
    return _normalize_result(result, "Compile")


def cook_content(
    uproject_path: str,
    platform: str = "Win64",
    engine_root: str | None = None,
    log_file: str | None = None,
    on_start=None,
) -> dict:
    already = _check_already_building(uproject_path)
    if already:
        return already

    engine_root = engine_root or find_engine_root(uproject_path)
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
    result = run_uat(
        engine_root,
        "BuildCookRun",
        args,
        log_file=log_file,
        log_label="cook",
        project_dir=str(Path(uproject_path).parent),
        on_start=on_start,
    )
    return _normalize_result(result, "Cook")


def package_project(
    uproject_path: str,
    platform: str = "Win64",
    config: str = "Development",
    output_dir: str | None = None,
    engine_root: str | None = None,
    log_file: str | None = None,
    on_start=None,
    *,
    maps: list[str] | tuple[str, ...] | None = None,
    cook_flavor: str | None = None,
    uat_args: list[str] | tuple[str, ...] | None = None,
) -> dict:
    try:
        maps = [
            validate_package_uat_value(value, label="map")
            for value in (maps or ())
        ]
        if cook_flavor is not None:
            cook_flavor = validate_package_uat_value(
                cook_flavor,
                label="cook flavor",
            )
        uat_args = [
            validate_package_uat_value(
                value,
                label="UAT argument",
                require_option=True,
            )
            for value in (uat_args or ())
        ]
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    already = _check_already_building(uproject_path)
    if already:
        return already

    engine_root = engine_root or find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    path = Path(uproject_path)
    output_dir = output_dir or str(path.parent / "Packaged")
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
    if maps:
        args.append("-map=" + "+".join(maps))
    if cook_flavor:
        args.append(f"-cookflavor={cook_flavor}")
    if uat_args:
        args.extend(uat_args)
    result = run_uat(
        engine_root,
        "BuildCookRun",
        args,
        log_file=log_file,
        log_label="package",
        project_dir=str(path.parent),
        on_start=on_start,
    )
    out = _normalize_result(result, "Package")
    out["output_dir"] = output_dir
    return out


def build_status(uproject_path: str) -> dict:
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
            if not platform_dir.is_dir():
                continue
            binaries = list(platform_dir.glob("*.dll")) + list(platform_dir.glob("*.exe"))
            newest = None
            newest_time = 0.0
            for binary in binaries:
                mtime = binary.stat().st_mtime
                if mtime > newest_time:
                    newest = binary.name
                    newest_time = mtime
            status["platforms"][platform_dir.name] = {
                "binary_count": len(binaries),
                "newest_binary": newest,
                "newest_time": newest_time,
            }

    saved_dir = project_dir / "Saved" / "Logs"
    if saved_dir.is_dir():
        log_files = sorted(saved_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        status["recent_logs"] = [
            {"name": log.name, "size": log.stat().st_size}
            for log in log_files[:5]
        ]

    return status


def generate_project_files(uproject_path: str, engine_root: str | None = None) -> dict:
    engine_root = engine_root or find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    project_dir = str(Path(uproject_path).parent)
    gen_bat = find_generate_project_files(engine_root)
    if gen_bat:
        from cli_anything.unreal.utils.ue_backend import _allocate_log_path, _run_subprocess

        log_file = _allocate_log_path(project_dir, "genproj")
        result = _run_subprocess([gen_bat, f"-project={uproject_path}", "-game", "-engine"], log_file=log_file)
    else:
        result = run_uat(
            engine_root,
            "GenerateProjectFiles",
            [f"-project={uproject_path}", "-game", "-engine"],
            log_label="genproj",
            project_dir=project_dir,
        )
    return _normalize_result(result, "Generate project files")


def stop_build(uproject_path: str) -> dict:
    from cli_anything.unreal.core.tasks import (
        FINAL_TASK_STATUSES,
        active_build_tasks,
        cancel_task,
        reconcile_task_cancellation,
    )

    task_results = []
    for task in active_build_tasks(uproject_path):
        cancelled = cancel_task(task["task_id"])
        if cancelled is None:
            continue
        cancel_result = cancelled.get("cancel_result", {})
        task_results.append({
            "task_id": cancelled["task_id"],
            "status": cancelled.get("status"),
            "pid": cancelled.get("pid"),
            "worker_pid": cancelled.get("worker_pid"),
            "killed": cancel_result.get("killed", []),
            "remaining": cancel_result.get("remaining", []),
        })

    result = kill_build_processes(uproject_path)
    final_scan_killed = result.get("killed", [])
    for task in task_results:
        reconciled = reconcile_task_cancellation(task["task_id"], final_scan_killed)
        if reconciled is None:
            continue
        cancel_result = reconciled.get("cancel_result", {})
        task.update({
            "status": reconciled.get("status"),
            "killed": cancel_result.get("killed", []),
            "remaining": cancel_result.get("remaining", []),
        })

    killed = list(result.get("killed", []))
    remaining = list(result.get("remaining", []))
    for task in task_results:
        killed.extend(task["killed"])
        remaining.extend(task["remaining"])
    killed = list(dict.fromkeys(killed))
    killed_set = set(killed)
    remaining = [
        pid for pid in dict.fromkeys(remaining)
        if pid not in killed_set
    ]

    if remaining or any(
        task["status"] not in FINAL_TASK_STATUSES for task in task_results
    ):
        status = "partial"
    elif task_results or killed:
        status = "ok"
    else:
        status = result["status"]

    response = {
        "status": status,
        "killed": killed,
        "remaining": remaining,
    }
    if task_results:
        response["tasks"] = task_results
    return response


def is_building(uproject_path: str) -> dict:
    processes = find_running_build_processes(uproject_path, include_cmdline=False)
    kinds: dict[str, int] = {}
    for process in processes:
        name = process.get("name", "")
        kinds[name] = kinds.get(name, 0) + 1

    result = {
        "building": len(processes) > 0,
        "count": len(processes),
        "kinds": kinds,
        "processes": processes,
    }

    saved_logs = Path(uproject_path).parent / "Saved" / "Logs"
    if saved_logs.is_dir():
        cli_logs = sorted(saved_logs.glob("cli_*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        if cli_logs:
            result["latest_log"] = str(cli_logs[0])
    return result
