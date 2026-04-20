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


# ── _build_launch_cmd unit tests ────────────────────────────────────


def test_build_launch_cmd_without_map():
    from cli_anything.unreal.commands.editor import _build_launch_cmd

    cmd = _build_launch_cmd("UnrealEditor.exe", "MyProject.uproject", None)
    assert cmd == ["UnrealEditor.exe", "MyProject.uproject", "-nosplash", "-unattended"]


def test_build_launch_cmd_with_map():
    from cli_anything.unreal.commands.editor import _build_launch_cmd

    cmd = _build_launch_cmd("UnrealEditor.exe", "MyProject.uproject", "/Game/Maps/Main")
    assert cmd == ["UnrealEditor.exe", "MyProject.uproject", "-nosplash", "-unattended", "/Game/Maps/Main"]


# ── plugin-upgrade relaunch uses _build_launch_cmd ──────────────────


def test_plugin_upgrade_relaunch_includes_nosplash_unattended(mini_project):
    """Verify plugin-upgrade relaunch passes -nosplash -unattended (regression test)."""
    from click.testing import CliRunner
    from cli_anything.unreal.unreal_cli import cli

    runner = CliRunner()
    mock_proc = MagicMock()
    mock_proc.pid = 9999
    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append(cmd)
        return mock_proc

    mock_api = MagicMock()
    # 1st call: editor_was_running check → True
    # 2nd call: wait-for-close loop → False (editor closed)
    # 3rd call: wait-for-api loop → True (editor back online)
    mock_api.is_alive.side_effect = [True, False, True]

    with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=mock_api), \
         patch("cli_anything.unreal.core.plugin_bridge.get_bundled_version", return_value="2.0"), \
         patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version", side_effect=["1.0", "2.0"]), \
         patch("cli_anything.unreal.core.plugin_bridge.ensure_plugin_deployed", return_value={
             "deployed": True, "action": "updated", "version": "2.0", "plugin_dir": "/tmp/plugin"
         }), \
         patch("cli_anything.unreal.core.build.compile_project", return_value={"status": "ok"}), \
         patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/Engine/Binaries/Win64/UnrealEditor.exe"), \
         patch("cli_anything.unreal.commands.editor.sp.Popen", side_effect=fake_popen), \
         patch("cli_anything.unreal.commands.editor.time.sleep"):
        result = runner.invoke(cli, [
            "--json", "--project", mini_project,
            "editor", "plugin-upgrade",
        ])

    assert result.exit_code == 0
    # The relaunch Popen call must include -nosplash and -unattended
    assert len(popen_calls) == 1
    relaunch_cmd = popen_calls[0]
    assert "-nosplash" in relaunch_cmd
    assert "-unattended" in relaunch_cmd
