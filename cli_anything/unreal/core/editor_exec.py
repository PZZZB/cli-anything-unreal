"""Durable, read-only observation for timed-out editor console commands."""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path

from cli_anything.unreal.core.tasks import (
    EDITOR_EXEC_TASK_COMMAND,
    FINAL_TASK_STATUSES,
    create_task,
    load_task,
    transition_task,
)
from cli_anything.unreal.utils.ue_http_api import _decode_windows_command_output


EDITOR_EXEC_OBSERVED_LOG_LIMIT_BYTES = 16 * 1024

_PYTHON_LOG_ERROR_PATTERN = re.compile(
    r"(?:^|\])\s*LogPython:\s*Error(?:\s*:|$)",
    re.IGNORECASE,
)


def _bounded_append(
    lines: deque[tuple[str, int]],
    line: str,
    used_bytes: int,
) -> tuple[int, int]:
    line_bytes = len(line.encode("utf-8", errors="replace")) + 1
    lines.append((line, line_bytes))
    used_bytes += line_bytes
    omitted = 0
    while used_bytes > EDITOR_EXEC_OBSERVED_LOG_LIMIT_BYTES and lines:
        _, removed_bytes = lines.popleft()
        used_bytes -= removed_bytes
        omitted += 1
    return used_bytes, omitted


def _scan_observation_log(payload: dict) -> dict:
    """Find one command's unique begin/end markers without redispatching it."""
    log_value = payload.get("log_file")
    if not log_value:
        return {
            "log_available": False,
            "reason": "log_file_unavailable",
            "saw_begin": False,
            "saw_end": False,
        }

    log_file = Path(str(log_value))
    try:
        size = log_file.stat().st_size
    except OSError as exc:
        return {
            "log_available": False,
            "reason": "log_file_unavailable",
            "log_file": str(log_file),
            "error": str(exc),
            "saw_begin": False,
            "saw_end": False,
        }

    requested_start = max(0, int(payload.get("log_start") or 0))
    log_truncated = size < requested_start
    start_pos = 0 if log_truncated else requested_start
    begin_marker = str(payload.get("begin_marker") or "")
    end_marker = str(payload.get("end_marker") or "")
    saw_begin = False
    saw_end = False
    inside = False
    captured: deque[tuple[str, int]] = deque()
    used_bytes = 0
    omitted_line_count = 0

    try:
        with log_file.open("rb") as handle:
            handle.seek(start_pos)
            for raw_line in handle:
                line = _decode_windows_command_output(raw_line).rstrip("\r\n")
                if begin_marker and begin_marker in line:
                    saw_begin = True
                    inside = True
                    continue
                if end_marker and end_marker in line:
                    saw_end = True
                    inside = False
                    break
                if inside:
                    used_bytes, omitted = _bounded_append(captured, line, used_bytes)
                    omitted_line_count += omitted
    except OSError as exc:
        return {
            "log_available": False,
            "reason": "log_read_failed",
            "log_file": str(log_file),
            "error": str(exc),
            "saw_begin": saw_begin,
            "saw_end": saw_end,
        }

    lines = [line for line, _ in captured]
    return {
        "log_available": True,
        "log_file": str(log_file),
        "log_truncated": log_truncated,
        "saw_begin": saw_begin,
        "saw_end": saw_end,
        "log_text": "\n".join(lines).strip(),
        "omitted_line_count": omitted_line_count,
    }


def _python_errors(scan: dict) -> list[str]:
    errors = []
    for line in str(scan.get("log_text") or "").splitlines():
        if _PYTHON_LOG_ERROR_PATTERN.search(line) and line not in errors:
            errors.append(line)
    return errors


def create_editor_exec_observation(
    *,
    command: str,
    project_path: str | None,
    log_file: Path | None,
    log_start: int,
    begin_marker: str,
    end_marker: str,
) -> dict:
    """Create and immediately reconcile a log-backed command observation task."""
    task = create_task(
        EDITOR_EXEC_TASK_COMMAND,
        {
            "project_path": project_path,
            "exec_command": command,
            "is_python_command": bool(re.match(r"\s*py(?:\s|$)", command, re.IGNORECASE)),
            "log_file": str(log_file) if log_file else None,
            "log_start": int(log_start),
            "begin_marker": begin_marker,
            "end_marker": end_marker,
        },
    )
    return reconcile_editor_exec_observation(task["task_id"], task) or task


def reconcile_editor_exec_observation(task_id: str, task: dict | None = None) -> dict | None:
    """Update one observation task from durable project-log evidence."""
    task = task or load_task(task_id)
    if task is None or task.get("command") != EDITOR_EXEC_TASK_COMMAND:
        return task
    if task.get("status") in FINAL_TASK_STATUSES:
        return task

    payload = task.get("payload", {})
    scan = _scan_observation_log(payload)
    current_status = str(task.get("status") or "submitted")
    base_result = {
        "command": payload.get("exec_command"),
        "delivery_state": "confirmed" if scan.get("saw_begin") or scan.get("saw_end") else "unknown",
        "completion_state": "completed" if scan.get("saw_end") else (
            "running" if scan.get("saw_begin") else "unknown"
        ),
        "log_file": scan.get("log_file") or payload.get("log_file"),
        "log_observation": {
            key: value
            for key, value in scan.items()
            if key not in {"log_text"}
        },
    }
    if scan.get("log_text"):
        base_result["log_text"] = scan["log_text"]
    if scan.get("omitted_line_count"):
        base_result["omitted_line_count"] = scan["omitted_line_count"]

    if scan.get("saw_end"):
        if current_status == "submitted":
            task = transition_task(
                task_id,
                expected_statuses={"submitted"},
                status="running",
                phase="executing",
                result_patch={
                    **base_result,
                    "completion_state": "running",
                },
            ) or task
        errors = _python_errors(scan) if payload.get("is_python_command") else []
        if errors:
            base_result.update(status="failed", python_error="\n".join(errors))
            return transition_task(
                task_id,
                status="failed",
                phase="exited",
                result_patch=base_result,
                error={
                    "code": "PYTHON_EXEC_FAILED",
                    "message": "Unreal Python command raised a synchronous exception.",
                },
            )
        base_result["status"] = "executed"
        return transition_task(
            task_id,
            status="completed",
            phase="exited",
            result_patch=base_result,
            error=None,
        )

    if scan.get("saw_begin"):
        return transition_task(
            task_id,
            status="running",
            phase="executing",
            result_patch=base_result,
        )

    return transition_task(
        task_id,
        status=current_status,
        phase="awaiting_delivery_evidence",
        result_patch=base_result,
    )
