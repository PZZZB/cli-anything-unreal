import json
import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest


CONFIRMATION_ID = "a" * 32


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "ConfirmTest" / "ConfirmTest.uproject"
    project.parent.mkdir()
    project.write_text('{"FileVersion": 3}', encoding="utf-8")
    return project


def _editor(pid: int, project: Path) -> dict:
    return {"pid": pid, "project": str(project), "cmdline": str(project)}


def _write_pending(project: Path, pid: int, confirmation_id: str = CONFIRMATION_ID) -> Path:
    from cli_anything.unreal.core.confirmations import _atomic_write_json, _pid_dir

    path = _pid_dir(project, pid) / f"pending-{confirmation_id}.json"
    _atomic_write_json(path, {
        "protocol_version": 1,
        "id": confirmation_id,
        "pid": pid,
        "title": "Delete assets?",
        "message": "Delete three assets?",
        "message_type": "yes_no",
        "choices": ["yes", "no"],
        "safe_default": "no",
        "created_at": 101.0,
    })
    return path


def test_enable_list_answer_disable_confirmation_broker(tmp_path):
    from cli_anything.unreal.core.confirmations import (
        _pid_dir,
        answer_confirmation,
        disable_confirmation_broker,
        enable_confirmation_broker,
        list_confirmations,
    )

    project = _project(tmp_path)
    pid = os.getpid()
    editors = [_editor(pid, project)]
    with patch("cli_anything.unreal.core.confirmations._matching_editors", return_value=editors):
        enabled = enable_confirmation_broker(project, pid=pid, ttl_seconds=300, now=100.0)
        pending_path = _write_pending(project, pid)
        listed = list_confirmations(project, now=102.0)

        assert enabled["status"] == "enabled"
        assert enabled["pid"] == pid
        assert listed["answerable_count"] == 1
        assert listed["confirmations"][0]["id"] == CONFIRMATION_ID
        assert listed["confirmations"][0]["choices"] == ["yes", "no"]

        answered = answer_confirmation(project, CONFIRMATION_ID, "yes", wait_seconds=0, now=103.0)
        response = json.loads(
            (_pid_dir(project, pid) / f"response-{CONFIRMATION_ID}.json").read_text(encoding="utf-8")
        )
        assert answered["status"] == "submitted"
        assert response["choice"] == "yes"

        disabled = disable_confirmation_broker(project, pid=pid)
        assert disabled["status"] == "disabled"
        assert disabled["pending_fallback_count"] == 1
        assert not (_pid_dir(project, pid) / "lease.json").exists()
        assert pending_path.exists()


def test_answer_rejects_choice_not_reported_by_dialog(tmp_path):
    from cli_anything.unreal.core.confirmations import answer_confirmation, enable_confirmation_broker
    from cli_anything.unreal.errors import UeCliError

    project = _project(tmp_path)
    pid = os.getpid()
    with patch(
        "cli_anything.unreal.core.confirmations._matching_editors",
        return_value=[_editor(pid, project)],
    ):
        enable_confirmation_broker(project, pid=pid, ttl_seconds=300)
    _write_pending(project, pid)

    with pytest.raises(UeCliError) as exc_info:
        answer_confirmation(project, CONFIRMATION_ID, "ok", wait_seconds=0)

    assert exc_info.value.code == "CONFIRMATION_INVALID_CHOICE"
    assert exc_info.value.details["allowed_choices"] == ["yes", "no"]


def test_answer_rejects_non_bridge_id_before_path_lookup(tmp_path):
    from cli_anything.unreal.core.confirmations import answer_confirmation
    from cli_anything.unreal.errors import UeCliError

    project = _project(tmp_path)

    with pytest.raises(UeCliError) as exc_info:
        answer_confirmation(project, "../lease", "yes", wait_seconds=0)

    assert exc_info.value.code == "CONFIRMATION_ID_INVALID"


def test_raise_if_editor_blocked_returns_dedicated_contract(tmp_path):
    from cli_anything.unreal.core.confirmations import (
        enable_confirmation_broker,
        raise_if_editor_blocked,
    )
    from cli_anything.unreal.errors import UeCliError

    project = _project(tmp_path)
    pid = os.getpid()
    with patch(
        "cli_anything.unreal.core.confirmations._matching_editors",
        return_value=[_editor(pid, project)],
    ):
        enable_confirmation_broker(project, pid=pid, ttl_seconds=300, now=100.0)
    _write_pending(project, pid)

    with patch("cli_anything.unreal.core.confirmations.time.time", return_value=101.0), pytest.raises(UeCliError) as exc_info:
        raise_if_editor_blocked(project)

    error = exc_info.value
    assert error.code == "EDITOR_BLOCKED_BY_CONFIRMATION"
    assert error.details["delivery_state"] == "waiting_confirmation"
    assert "confirmation list" in error.details["next_command"]
    assert "confirmation answer" in error.details["answer_command"]


def test_list_reports_non_brokered_window_as_not_answerable(tmp_path):
    from cli_anything.unreal.core.confirmations import list_confirmations

    project = _project(tmp_path)
    pid = os.getpid()
    dialog = {"title": "Restore Packages", "hwnd": 44, "process_id": pid}
    with patch(
        "cli_anything.unreal.core.confirmations._matching_editors",
        return_value=[_editor(pid, project)],
    ), patch(
        "cli_anything.unreal.utils.ue_backend.detect_ue_dialogs",
        return_value=[dialog],
    ):
        result = list_confirmations(project, now=100.0)

    item = result["confirmations"][0]
    assert item["source"] == "window"
    assert item["answerable"] is False
    assert item["title"] == "Restore Packages"


def test_http_request_checks_confirmation_before_dispatch(tmp_path):
    from cli_anything.unreal.errors import UeCliError
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    project = _project(tmp_path)
    api = UEEditorAPI(port=30010)
    api.project_path = str(project)
    blocked = UeCliError("EDITOR_BLOCKED_BY_CONFIRMATION", "blocked")

    with patch(
        "cli_anything.unreal.core.confirmations.raise_if_editor_blocked",
        side_effect=blocked,
    ), patch("cli_anything.unreal.utils.ue_http_api.requests.put") as request:
        with pytest.raises(UeCliError) as exc_info:
            api._put("/remote/object/call", {})

    assert exc_info.value.code == "EDITOR_BLOCKED_BY_CONFIRMATION"
    request.assert_not_called()


def test_inflight_http_request_returns_when_confirmation_appears(tmp_path):
    from cli_anything.unreal.errors import UeCliError
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    project = _project(tmp_path)
    api = UEEditorAPI(port=30010)
    api.project_path = str(project)
    request_started = threading.Event()
    release_request = threading.Event()
    blocked = UeCliError("EDITOR_BLOCKED_BY_CONFIRMATION", "blocked")
    checks = 0

    def check_blocked(*, include_windows=False):
        nonlocal checks
        checks += 1
        if checks >= 2:
            raise blocked

    def slow_request(*_args, **_kwargs):
        request_started.set()
        release_request.wait(timeout=1.0)
        raise AssertionError("request should still be blocked")

    try:
        with patch.object(api, "_raise_if_editor_blocked", side_effect=check_blocked), patch(
            "cli_anything.unreal.utils.ue_http_api.requests.put",
            side_effect=slow_request,
        ):
            with pytest.raises(UeCliError) as exc_info:
                api._put("/remote/object/call", {})
        assert request_started.is_set()
        assert not release_request.is_set()
        assert exc_info.value.code == "EDITOR_BLOCKED_BY_CONFIRMATION"
    finally:
        release_request.set()


def test_confirmation_commands_are_registered():
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    result = CliRunner().invoke(cli, ["--list-commands"])

    assert result.exit_code == 0
    names = {item["name"] for item in json.loads(result.output)}
    assert {
        "confirmation enable",
        "confirmation list",
        "confirmation answer",
        "confirmation disable",
    }.issubset(names)


def test_editor_status_returns_confirmation_block_before_scanning(tmp_path):
    from click.testing import CliRunner
    from cli_anything.unreal.errors import UeCliError
    from cli_anything.unreal.unreal_cli import cli

    project = _project(tmp_path)
    blocked = UeCliError(
        "EDITOR_BLOCKED_BY_CONFIRMATION",
        "Editor is waiting for confirmation.",
        exit_code=4,
    )
    with patch(
        "cli_anything.unreal.core.confirmations.raise_if_editor_blocked",
        side_effect=blocked,
    ), patch(
        "cli_anything.unreal.commands.editor._scan_editor_status_instances",
    ) as scan:
        result = CliRunner().invoke(cli, [
            "--output", "json", "--project", str(project),
            "editor", "status",
        ])

    assert result.exit_code == 4
    assert json.loads(result.output)["code"] == "EDITOR_BLOCKED_BY_CONFIRMATION"
    scan.assert_not_called()


def test_editor_command_returns_confirmation_block_before_health_probe(tmp_path):
    from click.testing import CliRunner
    from cli_anything.unreal.errors import UeCliError
    from cli_anything.unreal.unreal_cli import cli

    project = _project(tmp_path)
    blocked = UeCliError(
        "EDITOR_BLOCKED_BY_CONFIRMATION",
        "Editor is waiting for confirmation.",
        exit_code=4,
    )
    with patch(
        "cli_anything.unreal.core.confirmations.raise_if_editor_blocked",
        side_effect=blocked,
    ), patch(
        "cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive",
    ) as health_probe:
        result = CliRunner().invoke(cli, [
            "--output", "json", "--project", str(project),
            "editor", "cvar", "get", "t.MaxFPS",
        ])

    assert result.exit_code == 4
    assert json.loads(result.output)["code"] == "EDITOR_BLOCKED_BY_CONFIRMATION"
    health_probe.assert_not_called()
