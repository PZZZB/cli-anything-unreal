"""Live Coding capability and terminal-result helpers."""

from __future__ import annotations

import re
import sys

from cli_anything.unreal.errors import UeCliError
from cli_anything.unreal.utils.ue_backend import get_engine_version


MINIMUM_SYNC_ENGINE_VERSION = "5.0"

_TERMINAL_PATTERNS = (
    (
        "no_changes",
        True,
        re.compile(r"\bLive coding succeeded,\s*no code changes detected\b", re.IGNORECASE),
    ),
    (
        "success",
        True,
        re.compile(r"\bLive coding succeeded\b", re.IGNORECASE),
    ),
    (
        "cancelled",
        False,
        re.compile(r"\bLive coding cancell?ed\b", re.IGNORECASE),
    ),
    (
        "failed",
        False,
        re.compile(r"\bLive coding failed\b", re.IGNORECASE),
    ),
)


def get_live_coding_sync_support(
    engine_root: str | None,
    *,
    platform: str | None = None,
) -> dict:
    """Return whether the selected engine exposes ``LiveCoding.CompileSync``."""
    active_platform = platform or sys.platform
    version = get_engine_version(engine_root) if engine_root else None
    details = {
        "supported": None,
        "engine_version": version,
        "minimum_engine_version": MINIMUM_SYNC_ENGINE_VERSION,
        "platform": active_platform,
    }
    if active_platform != "win32":
        details.update(supported=False, reason="windows_only")
        return details

    if version:
        try:
            major = int(version.split(".", 1)[0])
        except (TypeError, ValueError):
            major = None
        if major is not None:
            details["supported"] = major >= 5
            details["reason"] = "supported" if major >= 5 else "engine_version_unsupported"
            return details

    details["reason"] = "engine_version_unknown"
    return details


def parse_live_coding_compile_result(log_text: str) -> dict | None:
    """Parse the last UE Live Coding terminal result from one command log delta."""
    matches: list[tuple[int, str, bool, str]] = []
    for line in str(log_text or "").splitlines():
        for status, succeeded, pattern in _TERMINAL_PATTERNS:
            match = pattern.search(line)
            if match:
                matches.append((match.start(), status, succeeded, line.strip()))
                break
    if not matches:
        return None

    _, status, succeeded, terminal_line = matches[-1]
    return {
        "compile_status": status,
        "succeeded": succeeded,
        "terminal_log_line": terminal_line,
    }


def _request_failure(result: dict) -> dict | None:
    raw = result.get("raw")
    if isinstance(raw, dict) and raw.get("error"):
        return raw
    if result.get("error") and "raw" not in result:
        return result
    return None


def _is_timeout_failure(result: dict) -> bool:
    text = " ".join(str(result.get(key, "")) for key in ("error", "traceback")).lower()
    return any(marker in text for marker in (
        "read timed out",
        "read timeout",
        "readtimeout",
        "timed out",
        "timeouterror",
    ))


def raise_live_coding_request_failure(
    result: dict,
    *,
    timeout: int,
    duration_seconds: float,
    support: dict,
    diagnostics: dict,
) -> None:
    """Raise a structured, non-retryable error for an ambiguous sync request."""
    request_failure = _request_failure(result)
    details = {
        "status": "unknown",
        "command": "LiveCoding.CompileSync",
        "completion_observable": False,
        "completion_status": "unknown",
        "delivery_state": "unknown" if request_failure else "attempted",
        "retry_safe": False,
        "timeout_seconds": timeout,
        "duration_seconds": round(duration_seconds, 3),
        "error": result.get("error") or "Live Coding command execution failed",
        "support": support,
    }
    if request_failure:
        details["request_error"] = request_failure
    details.update(diagnostics)

    if details.get("failure_kind") in {"editor_process_exited", "editor_crash_detected"}:
        raise UeCliError(
            "LIVECODING_EDITOR_CRASHED",
            "Unreal Editor crashed or exited during the Live Coding compile.",
            exit_code=3,
            suggestion=(
                "Inspect fatal_log_tail and log_file before relaunching. The compile may "
                "have partially patched code; do not retry automatically."
            ),
            details=details,
        )

    if _is_timeout_failure(request_failure or result):
        raise UeCliError(
            "LIVECODING_COMPILE_TIMEOUT",
            "Live Coding did not return a terminal result before the timeout.",
            exit_code=4,
            suggestion=(
                "Inspect the Live Coding console, editor status, and project log before "
                "deciding whether to retry; the compile may still be running."
            ),
            details=details,
        )

    raise UeCliError(
        "LIVECODING_RESULT_UNOBSERVABLE",
        "Live Coding command delivery or completion could not be observed.",
        exit_code=3,
        suggestion=(
            "Inspect editor status and the project log before deciding whether to retry; "
            "ue-cli did not redispatch the compile."
        ),
        details=details,
    )


def finalize_live_coding_compile_result(
    result: dict,
    *,
    duration_seconds: float,
    support: dict,
) -> dict:
    """Promote captured UE log output into a truthful terminal result or error."""
    terminal = parse_live_coding_compile_result(result.get("log_text", ""))
    result.update({
        "duration_seconds": round(duration_seconds, 3),
        "support": support,
    })
    if terminal is None:
        result.update({
            "status": "unknown",
            "completion_observable": False,
            "completion_status": "unknown",
            "retry_safe": False,
        })
        raise UeCliError(
            "LIVECODING_RESULT_UNOBSERVABLE",
            "LiveCoding.CompileSync returned without an observable terminal result.",
            exit_code=3,
            suggestion=(
                "Another compile may already be active or Live Coding may not have "
                "started. Inspect the Live Coding console and project log before retrying."
            ),
            details=result,
        )

    result.update({
        "status": "completed" if terminal["succeeded"] else "failed",
        "completion_observable": True,
        "completion_status": terminal["compile_status"],
        "succeeded": terminal["succeeded"],
        "terminal_log_line": terminal["terminal_log_line"],
    })
    if not terminal["succeeded"]:
        code = (
            "LIVECODING_COMPILE_CANCELLED"
            if terminal["compile_status"] == "cancelled"
            else "LIVECODING_COMPILE_FAILED"
        )
        raise UeCliError(
            code,
            f"Live Coding compile {terminal['compile_status']}.",
            exit_code=3,
            suggestion="Inspect log_text and the Live Coding console before retrying.",
            details=result,
        )
    return result
