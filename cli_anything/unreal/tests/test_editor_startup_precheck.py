import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mini_project(tmp_path):
    project_dir = tmp_path / "MiniProject"
    project_dir.mkdir()
    uproject = project_dir / "MiniProject.uproject"
    uproject.write_text('{"FileVersion": 3, "EngineAssociation": "5.7"}', encoding="utf-8")
    return str(uproject)


def test_editor_status_offline_api_blocked_includes_log_error(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive", return_value=False), \
         patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[{"pid": 1234, "project": mini_project}]), \
         patch("cli_anything.unreal.utils.ue_backend.detect_ue_dialogs", return_value=[]), \
         patch("cli_anything.unreal.commands.editor._check_log_errors", return_value="Plugin 'libzstd' failed to load"), \
         patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
             "ready": False,
             "engine": {"errors": ["engine error"], "warnings": []},
             "project": {"errors": ["project error"], "warnings": []},
         }):
        result = runner.invoke(cli, [
            "--json", "--project", mini_project,
            "editor", "status",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "offline_api_blocked"
    assert data["log_error"] == "Plugin 'libzstd' failed to load"
    assert data["startup_precheck"]["ready"] is False
    assert data["startup_precheck"]["errors"] == ["engine error", "project error"]


def test_editor_launch_preflight_failed_includes_startup_precheck(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    with patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
        "ready": False,
        "engine": {"errors": ["engine error"], "warnings": ["engine warning"]},
        "project": {"errors": ["project error"], "warnings": []},
    }):
        result = runner.invoke(cli, [
            "--json", "--project", mini_project,
            "editor", "launch", "--no-wait",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "preflight_failed"
    assert data["startup_precheck"]["ready"] is False
    assert data["startup_precheck"]["errors"] == ["engine error", "project error"]
    assert data["startup_precheck"]["warnings"] == ["engine warning"]


def test_editor_launch_success_includes_startup_precheck(mini_project):
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    mock_proc = MagicMock()
    mock_proc.pid = 4242

    with patch("cli_anything.unreal.utils.ue_backend.find_engine_root", return_value="F:/MockEngine"), \
         patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/MockEngine/Engine/Binaries/Win64/UnrealEditor.exe"), \
         patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None), \
         patch("cli_anything.unreal.commands.editor._check_port_in_use", return_value=None), \
         patch("cli_anything.unreal.commands.editor._deploy_bridge", return_value={"deployed": False}), \
         patch("cli_anything.unreal.commands.editor.sp.Popen", return_value=mock_proc), \
         patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
             "ready": True,
             "engine": {"errors": [], "warnings": ["engine warning"]},
             "project": {"errors": [], "warnings": ["project warning"]},
         }):
        result = runner.invoke(cli, [
            "--json", "--project", mini_project,
            "editor", "launch", "--no-wait",
        ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "launched"
    assert data["pid"] == 4242
    assert data["startup_precheck"]["ready"] is True
    assert data["startup_precheck"]["errors"] == []
    assert data["startup_precheck"]["warnings"] == ["engine warning", "project warning"]
