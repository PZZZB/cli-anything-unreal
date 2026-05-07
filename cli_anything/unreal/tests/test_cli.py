"""Tests for test_cli.py — Uses synthetic data only, no UE editor required."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestCLI:
    """Tests for the Click CLI interface."""

    def test_help(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "project" in result.output
        assert "build" in result.output
        assert "material" in result.output
        assert "screenshot" in result.output
        assert "editor" in result.output

    def test_screenshot_dynamic_help_minimal_options(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["screenshot", "capture-sequence", "--help"])
        assert result.exit_code == 0
        out = result.output
        assert "--frames" in out and "--interval" in out and "--no-compress" in out
        assert "--prefix" not in out and "--output" not in out and "--cols" not in out

    def test_screenshot_dynamic_cli_passthrough(self, temp_project):
        """CLI forwards only -n/-i and fixed atlas defaults to capture_screenshot_atlas."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.screenshot.require_editor", return_value=MagicMock()), patch(
            "cli_anything.unreal.core.screenshot.capture_screenshot_atlas",
        ) as mock_atlas:
            mock_atlas.return_value = {
                "status": "ok",
                "atlas_path": str(Path(temp_project["dir"]) / "motion_seq_motion_sheet.png"),
                "read_this": "stub.jpg",
                "frame_count": 3,
            }
            result = runner.invoke(cli, [
                "--output", "json",
                "--project",
                temp_project["uproject"],
                "screenshot",
                "capture-sequence",
                "-n",
                "3",
                "-i",
                "0.4",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["status"] == "ok"
        mock_atlas.assert_called_once()
        call_kw = mock_atlas.call_args[1]
        assert mock_atlas.call_args[0][1] == 3
        assert call_kw["interval"] == 0.4
        assert call_kw["filename_prefix"] == "motion_seq"
        assert call_kw["output_atlas"] is None
        assert call_kw["cols"] is None
        assert call_kw["label_frames"] is True
        assert call_kw["jpeg_for_llm"] is True
        assert call_kw["max_atlas_edge"] == 1920

    def test_project_info(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "project", "info",
            "--project", temp_project["uproject"],
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["name"] == "TestProject"

    def test_project_config_list(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "--project", temp_project["uproject"],
            "project", "config", "list",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert len(data["result"]) == 2

    def test_project_content(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_api = MagicMock()
            mock_editor.return_value = mock_api
            mock_run.return_value = {
                "assets": [
                    {"name": "NewMaterial", "class": "Material", "path": "/Game/NewMaterial"},
                    {"name": "NewBlueprint", "class": "Blueprint", "path": "/Game/NewBlueprint"},
                    {"name": "NewTexture", "class": "Texture2D", "path": "/Game/NewTexture"},
                    {"name": "NewMesh", "class": "StaticMesh", "path": "/Game/NewMesh"},
                ],
                "count": 4,
            }
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "asset", "list",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["count"] == 4

    def test_editor_status_offline(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive", return_value=False):
            result = runner.invoke(cli, [
                "--output", "json",
                "editor", "status",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        # Empty port vs running-but-blocked API both resolve to non-online.
        assert data["result"]["status"] in ("not_running", "zombie")

    @patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive", return_value=False)
    @patch("cli_anything.unreal.utils.ue_backend.preflight_check")
    def test_editor_status_includes_startup_precheck(self, mock_preflight, _mock_alive, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_preflight.return_value = {
            "ready": False,
            "engine": {"errors": ["engine error"], "warnings": ["engine warning"]},
            "project": {"errors": ["project error"], "warnings": []},
        }

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "--project", temp_project["uproject"],
            "editor", "status",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert "startup_precheck" in data["result"]
        assert data["result"]["startup_precheck"]["ready"] is False
        assert data["result"]["startup_precheck"]["errors"] == ["engine error", "project error"]
        assert data["result"]["startup_precheck"]["warnings"] == ["engine warning"]

    def test_editor_status_offline_api_blocked_includes_log_error(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive", return_value=False), \
             patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[{"pid": 1234, "project": temp_project["uproject"]}]), \
             patch("cli_anything.unreal.utils.ue_backend.detect_ue_dialogs", return_value=[]), \
             patch("cli_anything.unreal.commands.editor._check_log_errors", return_value="Plugin 'libzstd' failed to load"), \
             patch("cli_anything.unreal.utils.ue_backend.preflight_check", return_value={
                 "ready": True,
                 "engine": {"errors": [], "warnings": []},
                 "project": {"errors": [], "warnings": []},
             }):
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "editor", "status",
            ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["status"] == "zombie"
        assert data["result"]["log_error"] == "Plugin 'libzstd' failed to load"
        assert data["result"]["running_editors"][0]["pid"] == 1234
        assert data["result"]["startup_precheck"]["ready"] is True

    @patch("cli_anything.unreal.utils.ue_backend.preflight_check")
    def test_editor_launch_preflight_failed_includes_startup_precheck(self, mock_preflight, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_preflight.return_value = {
            "ready": False,
            "engine": {"errors": ["engine error"], "warnings": ["engine warning"]},
            "project": {"errors": ["project error"], "warnings": []},
        }

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "--project", temp_project["uproject"],
            "editor", "launch", "--no-wait",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["status"] == "submitted"
        assert "task_id" in data["result"]

    @patch("cli_anything.unreal.commands.editor._check_port_in_use", return_value=None)
    @patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None)
    @patch("cli_anything.unreal.commands.editor._deploy_bridge", return_value={"deployed": False})
    @patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/MockEngine/Engine/Binaries/Win64/UnrealEditor.exe")
    @patch("cli_anything.unreal.utils.ue_backend.find_engine_root", return_value="F:/MockEngine")
    @patch("cli_anything.unreal.commands.editor.sp.Popen")
    def test_editor_launch_success_includes_startup_precheck(
        self,
        mock_popen,
        _mock_find_engine_root,
        _mock_find_editor_exe,
        _mock_deploy_bridge,
        _mock_check_already_running,
        _mock_check_port_in_use,
        temp_project,
    ):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "--project", temp_project["uproject"],
            "editor", "launch", "--no-wait",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["status"] == "submitted"
        assert "task_id" in data["result"]

    def test_session_status(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "--project", temp_project["uproject"],
            "session", "status",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"]["project"] == "TestProject"

    def test_build_status(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "--project", temp_project["uproject"],
            "build", "status",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"]["project"] == "TestProject"
        assert data["result"]["has_binaries"] is True

    def test_port_auto_detected_from_project_config(self, temp_project):
        """Port is automatically read from DefaultRemoteControl.ini when --project is specified."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        # Write a RemoteControl config with a custom port
        config_dir = Path(temp_project["dir"]) / "Config"
        rc_ini = config_dir / "DefaultRemoteControl.ini"
        rc_ini.write_text(
            "[/Script/RemoteControlCommon.RemoteControlSettings]\n"
            "RemoteControlHttpServerPort=30055\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive", return_value=False):
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "editor", "status",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"]["port"] == 30055

    def test_port_defaults_to_30010_without_config(self, temp_project):
        """Port falls back to 30010 when no RemoteControl config exists."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive", return_value=False):
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "editor", "status",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"]["port"] == 30010


# ═══════════════════════════════════════════════════════════════════════
#  Test blueprint.py (mocked)
# ═══════════════════════════════════════════════════════════════════════


