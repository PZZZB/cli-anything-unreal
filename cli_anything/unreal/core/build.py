"""Build system wrapper for Unreal Engine."""

from __future__ import annotations

import re
from pathlib import Path

from cli_anything.unreal.utils.ue_backend import (
    _build_output_encoding,
    find_engine_root,
    find_generate_project_files,
    find_running_build_processes,
    find_uat,
    get_engine_version,
    kill_build_processes,
    run_build,
    run_uat,
)


_UNSAFE_PACKAGE_VALUE_CHARS = frozenset('"&|<>\0\r\n')
_GAME_TARGET_PATTERN = re.compile(
    r"\bType\s*=\s*TargetType\s*\.\s*Game\s*;"
)
_EDITOR_TARGET_PATTERN = re.compile(
    r"\bType\s*=\s*TargetType\s*\.\s*Editor\s*;"
)
_MODULE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_TARGET_LEXICAL_NOISE_PATTERN = re.compile(
    r"//[^\r\n]*|/\*.*?\*/|"
    r'@"(?:""|[^"])*"|'
    r'"(?:\\.|[^"\\\r\n])*"|'
    r"'(?:\\.|[^'\\\r\n])*'",
    re.DOTALL,
)


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


def _sanitize_target_source(source: str) -> str:
    def preserve_newlines(value: str) -> str:
        return "".join(char if char in "\r\n" else " " for char in value)

    source = _TARGET_LEXICAL_NOISE_PATTERN.sub(
        lambda match: preserve_newlines(match.group(0)),
        source,
    )
    conditional_depth = 0
    sanitized_lines = []
    for line in source.splitlines(keepends=True):
        directive = re.match(r"^\s*#\s*(if|endif)\b", line)
        if directive:
            if directive.group(1) == "if":
                conditional_depth += 1
            elif conditional_depth:
                conditional_depth -= 1
            sanitized_lines.append(preserve_newlines(line))
        elif conditional_depth:
            sanitized_lines.append(preserve_newlines(line))
        else:
            sanitized_lines.append(line)
    return "".join(sanitized_lines)


def _resolve_game_target(uproject_path: str) -> tuple[str | None, str | None]:
    project_path = Path(uproject_path)
    source_dir = project_path.parent / "Source"
    game_targets = []
    if source_dir.is_dir():
        for target_file in sorted(source_dir.rglob("*.Target.cs")):
            try:
                source = target_file.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return None, f"Could not read target file {target_file}: {exc}"
            if _GAME_TARGET_PATTERN.search(_sanitize_target_source(source)):
                game_targets.append(target_file.name.removesuffix(".Target.cs"))

    game_targets = sorted(set(game_targets))
    if len(game_targets) > 1:
        return None, (
            "Multiple Game targets found; cannot choose one for compile: "
            + ", ".join(game_targets)
        )
    if game_targets:
        return game_targets[0], None
    return project_path.stem, None


def _resolve_editor_target(uproject_path: str) -> tuple[str | None, str | None]:
    project_path = Path(uproject_path)
    source_dir = project_path.parent / "Source"
    editor_targets = []
    if source_dir.is_dir():
        for target_file in sorted(source_dir.rglob("*.Target.cs")):
            try:
                source = target_file.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                return None, f"Could not read target file {target_file}: {exc}"
            if _EDITOR_TARGET_PATTERN.search(_sanitize_target_source(source)):
                editor_targets.append(
                    target_file.name.removesuffix(".Target.cs")
                )

    editor_targets = sorted(set(editor_targets))
    if len(editor_targets) > 1:
        return None, (
            "Multiple Editor targets found; cannot choose one for module compile: "
            + ", ".join(editor_targets)
        )
    if editor_targets:
        return editor_targets[0], None
    return project_path.stem + "Editor", None


def validate_module_name(value: str) -> str:
    if not _MODULE_NAME_PATTERN.fullmatch(value):
        raise ValueError(
            f"Invalid module name {value!r}; expected a C++ identifier such as Renderer"
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


def _build_failure_diagnostics(log_file: str | None) -> dict:
    """Extract bounded, factual diagnostics from a failed UAT/UBT log."""
    if not log_file:
        return {}
    path = Path(log_file)
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - 2 * 1024 * 1024))
            text = handle.read().decode(_build_output_encoding(), errors="replace")
    except OSError:
        return {}

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    compiler_diagnostics = []
    for line in lines:
        if re.search(
            r"\bfatal error\b|\berror (?:C|LNK)\d+\b|:\s*error:",
            line,
            re.IGNORECASE,
        ):
            compiler_diagnostics.append(line)
    compiler_diagnostics = list(dict.fromkeys(compiler_diagnostics))[-20:]
    if compiler_diagnostics:
        return {
            "failure_kind": "compiler_diagnostics",
            "diagnostics": compiler_diagnostics,
        }

    if not re.search(r"failed to compile with bk tools|bk-ubt-tool", text, re.IGNORECASE):
        return {}

    result = {
        "failure_kind": "distributed_executor_failed_without_diagnostic",
        "executor": "bk_dist",
        "diagnostic": (
            "bk_dist failed without emitting a compiler diagnostic; inspect the "
            "actions JSON or rerun through the project's normal build path for the failing action."
        ),
    }
    action_matches = re.findall(
        r"(?:Parallel executor to run|Building)\s+(\d+)\s+action",
        text,
        re.IGNORECASE,
    )
    if action_matches:
        result["action_count"] = int(action_matches[-1])
    exit_matches = re.findall(r"exit code:\s*(-?\d+)", text, re.IGNORECASE)
    if exit_matches:
        result["executor_exit_code"] = int(exit_matches[-1])
    actions_matches = re.findall(
        r"(?:--actions_json_file\s+|failed to run actions with json file:\s*)([^\s\"']+|\"[^\"]+\"|'[^']+')",
        text,
        re.IGNORECASE,
    )
    if actions_matches:
        result["actions_json_file"] = actions_matches[-1].strip("\"'")
    return result


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
        out.update(_build_failure_diagnostics(result.get("log_file")))
    return out


def compile_project(
    uproject_path: str,
    config: str = "Development",
    platform: str = "Win64",
    engine_root: str | None = None,
    log_file: str | None = None,
    on_start=None,
    modules: list[str] | tuple[str, ...] | None = None,
) -> dict:
    try:
        modules = [validate_module_name(value) for value in (modules or ())]
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    if modules and platform.lower() != "win64":
        return {
            "status": "error",
            "error": "Module-targeted compile is supported only for Win64 Editor targets.",
        }

    already = _check_already_building(uproject_path)
    if already:
        return already

    engine_root = engine_root or find_engine_root(uproject_path)
    if not engine_root:
        return {"status": "error", "error": "Could not find engine root"}

    if modules:
        target, target_error = _resolve_editor_target(uproject_path)
        if target_error:
            return {"status": "error", "error": target_error}
        result = run_build(
            engine_root,
            target,
            platform,
            config,
            extra_args=[
                f"-Project={uproject_path}",
                *(f"-Module={module}" for module in modules),
                "-WaitMutex",
            ],
            log_file=log_file,
            log_label="compile",
            project_dir=str(Path(uproject_path).parent),
            on_start=on_start,
        )
        return _normalize_result(result, "Compile")

    if platform.lower() != "win64":
        target, target_error = _resolve_game_target(uproject_path)
        if target_error:
            return {"status": "error", "error": target_error}
        result = run_build(
            engine_root,
            target,
            platform,
            config,
            extra_args=[f"-Project={uproject_path}", "-WaitMutex"],
            log_file=log_file,
            log_label="compile",
            project_dir=str(Path(uproject_path).parent),
            on_start=on_start,
        )
        return _normalize_result(result, "Compile")

    args = [
        f"-project={uproject_path}",
        f"-platform={platform}",
        f"-clientconfig={config}",
        "-build",
        "-noP4",
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
    from cli_anything.unreal.core.tasks import active_build_tasks

    processes = find_running_build_processes(uproject_path, include_cmdline=False)
    kinds: dict[str, int] = {}
    for process in processes:
        name = process.get("name", "")
        kinds[name] = kinds.get(name, 0) + 1

    tasks = []
    for task in active_build_tasks(uproject_path):
        evidence = {
            key: task[key]
            for key in (
                "task_id",
                "command",
                "status",
                "worker_pid",
                "pid",
                "log_file",
            )
            if key in task
        }
        tasks.append(evidence)

    result = {
        "building": bool(processes or tasks),
        "count": len(processes),
        "kinds": kinds,
        "processes": processes,
        "active_task_count": len(tasks),
        "active_tasks": tasks,
    }

    saved_logs = Path(uproject_path).parent / "Saved" / "Logs"
    if saved_logs.is_dir():
        cli_logs = sorted(saved_logs.glob("cli_*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        if cli_logs:
            result["latest_log"] = str(cli_logs[0])
    return result
