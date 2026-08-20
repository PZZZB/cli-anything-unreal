"""Live Coding result parsing and compatibility tests."""

import json

from cli_anything.unreal.core.live_coding import (
    get_live_coding_sync_support,
    parse_live_coding_compile_result,
)


def _engine_root(tmp_path, major: int, minor: int, patch: int):
    root = tmp_path / f"UE_{major}_{minor}"
    build_dir = root / "Engine" / "Build"
    build_dir.mkdir(parents=True)
    (build_dir / "Build.version").write_text(
        json.dumps({
            "MajorVersion": major,
            "MinorVersion": minor,
            "PatchVersion": patch,
        }),
        encoding="utf-8",
    )
    return root


def test_sync_supports_ue5_on_windows(tmp_path):
    support = get_live_coding_sync_support(
        str(_engine_root(tmp_path, 5, 5, 4)),
        platform="win32",
    )

    assert support["supported"] is True
    assert support["engine_version"] == "5.5.4"
    assert support["reason"] == "supported"


def test_sync_rejects_ue4_on_windows(tmp_path):
    support = get_live_coding_sync_support(
        str(_engine_root(tmp_path, 4, 26, 2)),
        platform="win32",
    )

    assert support["supported"] is False
    assert support["engine_version"] == "4.26.2"
    assert support["reason"] == "engine_version_unsupported"


def test_sync_rejects_non_windows_before_version_check():
    support = get_live_coding_sync_support(None, platform="linux")

    assert support["supported"] is False
    assert support["reason"] == "windows_only"


def test_parse_last_terminal_result():
    result = parse_live_coding_compile_result(
        "LogLiveCoding: Error: Live coding failed\n"
        "LogLiveCoding: Display: Starting Live Coding compile.\n"
        "LogLiveCoding: Display: Live coding succeeded, no code changes detected\n"
    )

    assert result == {
        "compile_status": "no_changes",
        "succeeded": True,
        "terminal_log_line": (
            "LogLiveCoding: Display: Live coding succeeded, no code changes detected"
        ),
    }


def test_parse_cancelled_and_missing_results():
    cancelled = parse_live_coding_compile_result(
        "LogLiveCoding: Error: Live coding canceled"
    )

    assert cancelled["compile_status"] == "cancelled"
    assert cancelled["succeeded"] is False
    assert parse_live_coding_compile_result("Starting Live Coding compile.") is None
