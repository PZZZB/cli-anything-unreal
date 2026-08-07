"""Typed application errors shared by CLI and domain layers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UeCliError(Exception):
    """A known operation failure that maps to the public CLI error protocol."""

    code: str
    message: str
    exit_code: int = 1
    suggestion: str | None = None
    details: dict | list | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)


def raise_for_legacy_error(
    result: object,
    *,
    default_code: str,
    exit_code: int = 3,
    default_message: str = "Operation failed.",
    suggestion: str | None = None,
) -> None:
    """Raise a typed error for one explicitly selected legacy result boundary.

    Some domain functions still return ``{"error": ...}`` while they are being
    migrated.  Callers must opt in at an operation boundary; generic output and
    task-status payloads intentionally do not infer failure from an ``error`` key.
    """

    if not isinstance(result, dict) or "error" not in result:
        return

    raw_message = result.get("error")
    message = str(raw_message) if raw_message not in (None, "") else default_message
    code = str(result.get("code") or default_code)
    resolved_suggestion = suggestion or result.get("suggestion") or result.get("hint")
    raise UeCliError(
        code=code,
        message=message,
        exit_code=exit_code,
        suggestion=str(resolved_suggestion) if resolved_suggestion else None,
        details=result,
    )
