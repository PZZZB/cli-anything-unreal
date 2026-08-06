"""Tests for test_cli.py — Uses synthetic data only, no UE editor required."""

import ast
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

    def test_help_short_alias(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["-h"])
        assert result.exit_code == 0
        assert "project" in result.output
        assert "build" in result.output
        assert "editor" in result.output

    def test_help_short_alias_for_subcommands(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["editor", "run-script", "-h"])
        assert result.exit_code == 0
        assert "-c, --code" in result.output
        assert "--timeout" in result.output

    def test_task_wait_returns_completed_task(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        completed = {
            "task_id": "t-completed",
            "command": "editor.launch",
            "status": "completed",
            "result": {"status": "online"},
        }
        with patch(
            "cli_anything.unreal.unreal_cli.reconcile_task_state",
            return_value=completed,
        ), patch(
            "cli_anything.unreal.unreal_cli.wait_for_task",
            return_value=completed,
        ) as wait:
            result = CliRunner().invoke(cli, [
                "--output", "json", "task", "wait", "t-completed",
                "--timeout", "55",
            ])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["task_id"] == "t-completed"
        assert data["status"] == "completed"
        assert data["result"]["status"] == "online"
        wait.assert_called_once_with("t-completed", 55)

    def test_task_wait_propagates_failed_task_as_nonzero(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        running = {
            "task_id": "t-failed",
            "command": "build.compile",
            "status": "running",
        }
        failed = {
            **running,
            "status": "failed",
            "error": {"code": "COMPILE_FAILED", "message": "Build failed."},
        }
        with patch(
            "cli_anything.unreal.unreal_cli.reconcile_task_state",
            return_value=running,
        ), patch(
            "cli_anything.unreal.unreal_cli.wait_for_task",
            return_value=failed,
        ):
            result = CliRunner().invoke(cli, [
                "--output", "json", "task", "wait", "t-failed",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "failed"
        assert data["error"]["code"] == "COMPILE_FAILED"

    def test_task_wait_timeout_keeps_task_running(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        running = {
            "task_id": "t-running",
            "command": "build.compile",
            "status": "running",
            "worker_pid": 41001,
        }
        with patch(
            "cli_anything.unreal.unreal_cli.reconcile_task_state",
            side_effect=[running, running],
        ), patch(
            "cli_anything.unreal.unreal_cli.wait_for_task",
            return_value=None,
        ):
            result = CliRunner().invoke(cli, [
                "--output", "json", "task", "wait", "t-running",
                "--timeout", "1",
            ])

        assert result.exit_code == 4
        data = json.loads(result.output)
        assert data["status"] == "running"
        assert data["worker_pid"] == 41001
        assert data["wait"] == {
            "status": "timeout",
            "code": "TASK_WAIT_TIMEOUT",
            "timeout_seconds": 1,
            "task_continues": True,
        }
        assert data["next_command"] == "ue-cli task status t-running"

    def test_task_wait_missing_task_is_structured(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        with patch(
            "cli_anything.unreal.unreal_cli.reconcile_task_state",
            return_value=None,
        ), patch("cli_anything.unreal.unreal_cli.wait_for_task") as wait:
            result = CliRunner().invoke(cli, [
                "--output", "json", "task", "wait", "t-missing",
                "--timeout", "1",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "TASK_NOT_FOUND"
        wait.assert_not_called()

    def test_version_option(self):
        from click.testing import CliRunner
        from cli_anything.unreal.core.plugin_bridge import get_bundled_version
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert "ue-cli" in result.output
        assert "0.1.1" in result.output
        assert "CliAnythingBridge bundled version" in result.output
        assert get_bundled_version() in result.output

    def test_root_json_uses_cli_command_name(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--output", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "ue-cli"

    def test_list_commands_includes_umg_authoring_commands(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--list-commands"])

        assert result.exit_code == 0
        names = {item["name"] for item in json.loads(result.output)}
        assert {"umg create", "umg add-widget", "umg tree"}.issubset(names)
        assert "preflight" in names
        assert "editor open-level" in names
        assert "editor run-script" in names
        assert "editor exec" in names
        assert "editor viewport camera" in names
        assert "slate create" not in names

    def test_setup_metadata_uses_ue_cli_name(self):
        setup_py = Path(__file__).parents[3] / "setup.py"
        tree = ast.parse(setup_py.read_text(encoding="utf-8"))
        setup_call = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", None) == "setup"
        )
        entry_points = next(
            kw.value
            for kw in setup_call.keywords
            if kw.arg == "entry_points"
        )
        entry_points_value = ast.literal_eval(entry_points)
        package_name = next(
            kw.value
            for kw in setup_call.keywords
            if kw.arg == "name"
        )

        assert ast.literal_eval(package_name) == "ue-cli"
        assert entry_points_value["console_scripts"] == [
            "ue-cli=cli_anything.unreal.unreal_cli:main",
        ]

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

    def test_msys2_argv_fix_preserves_windows_output_paths(self, tmp_path):
        import sys
        from cli_anything.unreal.unreal_cli import _fix_argv_msys2

        target = str(tmp_path / "shots" / "missing.png")
        original = list(sys.argv)
        try:
            sys.argv = ["ue-cli", "screenshot", "capture", "--path", target]
            with patch.dict(os.environ, {}, clear=True):
                _fix_argv_msys2()
            assert sys.argv[-1] == target
        finally:
            sys.argv = original

    def test_msys2_argv_fix_repairs_virtual_game_paths(self, tmp_path):
        import sys
        from cli_anything.unreal.unreal_cli import _fix_argv_msys2

        git_root = tmp_path / "Git"
        git_root.mkdir(parents=True)
        mangled = str(git_root / "Game" / "Materials" / "M_Test")
        original = list(sys.argv)
        try:
            sys.argv = ["ue-cli", "material", "info", mangled]
            with patch.dict(os.environ, {"MSYSTEM": "MINGW64"}, clear=False):
                _fix_argv_msys2()
            assert sys.argv[-1] == "/Game/Materials/M_Test"
        finally:
            sys.argv = original

    def test_msys2_argv_fix_skips_non_windows(self, tmp_path):
        import sys
        from cli_anything.unreal.unreal_cli import _fix_argv_msys2

        target = str(tmp_path / "Git" / "Game" / "Materials" / "M_Test")
        original = list(sys.argv)
        try:
            sys.argv = ["ue-cli", "material", "info", target]
            with patch("cli_anything.unreal.unreal_cli.sys.platform", "linux"), \
                 patch.dict(os.environ, {"MSYSTEM": "MINGW64"}, clear=False):
                _fix_argv_msys2()
            assert sys.argv[-1] == target
        finally:
            sys.argv = original

    def test_windows_run_script_code_recovers_powershell_quotes(self):
        from cli_anything.unreal.unreal_cli import _repair_windows_run_script_code_argv

        damaged = [
            "ue-cli",
            "--project", r"F:\Test574\Test574.uproject",
            "editor", "run-script", "--no-save", "-c",
            "result = {label:SDOC_CacheTest_DynamicWall}",
        ]
        raw = (
            '"D:\\Python\\Scripts\\ue-cli.exe" --project F:\\Test574\\Test574.uproject '
            'editor run-script --no-save -c '
            '"result = {"label":"SDOC_CacheTest_DynamicWall"}"'
        )

        repaired = _repair_windows_run_script_code_argv(damaged, raw)

        assert repaired[-1] == 'result = {"label":"SDOC_CacheTest_DynamicWall"}'

    def test_windows_run_script_code_rejoins_string_spaces_and_trailing_options(self):
        from cli_anything.unreal.unreal_cli import _repair_windows_run_script_code_argv

        damaged = [
            "ue-cli", "editor", "run-script", "-c",
            "result = {label:hello", "world}", "--timeout", "45", "--no-save",
        ]
        raw = (
            'ue-cli editor run-script -c '
            '"result = {"label": "hello world"}" --timeout 45 --no-save'
        )

        repaired = _repair_windows_run_script_code_argv(damaged, raw)

        assert repaired == [
            "ue-cli", "editor", "run-script", "-c",
            'result = {"label": "hello world"}', "--timeout", "45", "--no-save",
        ]

    def test_windows_run_script_code_accepts_explicit_quote_escapes(self):
        from cli_anything.unreal.unreal_cli import _repair_windows_run_script_code_argv

        argv = ["ue-cli", "editor", "run-script", "--code=result={label:x}"]
        raw = 'ue-cli editor run-script --code="result={\\"label\\":\\"x\\"}"'

        repaired = _repair_windows_run_script_code_argv(argv, raw)

        assert repaired == [
            "ue-cli", "editor", "run-script", "--code", 'result={"label":"x"}',
        ]

    def test_windows_run_script_code_leaves_other_commands_unchanged(self):
        from cli_anything.unreal.unreal_cli import _repair_windows_run_script_code_argv

        argv = ["ue-cli", "editor", "exec", "result={label:x}"]
        raw = 'ue-cli editor exec "result={"label":"x"}"'

        assert _repair_windows_run_script_code_argv(argv, raw) is argv

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
        with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[]), \
             patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[]):
            result = runner.invoke(cli, [
                "--output", "json", "--port", "19999",
                "editor", "status",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"] == []

    def test_editor_status_scans_extra_port_as_single_probe(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[]) as scan_ports, \
             patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[]):
            result = runner.invoke(cli, [
                "--output", "json", "--port", "19999",
                "editor", "status",
            ])

        assert result.exit_code == 0
        assert [call.kwargs["port_range"] for call in scan_ports.call_args_list] == [
            (30010, 30020),
            (19999, 19999),
        ]

    @patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[])
    @patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[])
    def test_editor_status_returns_empty_list_when_no_editors_for_project(self, _mock_scan, _mock_running, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "--project", temp_project["uproject"],
            "editor", "status",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"] == []

    def test_editor_status_offline_api_blocked_includes_log_error(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[]), \
             patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[{"pid": 1234, "project": temp_project["uproject"]}]), \
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
        assert data["result"][0]["status"] == "offline"
        assert data["result"][0]["pid"] == 1234
        assert data["result"][0]["log_error"] == "Plugin 'libzstd' failed to load"

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
        with patch("cli_anything.unreal.commands.editor.submit_task", return_value={"task_id": "launch-task"}):
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "editor", "launch", "--no-wait",
            ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["status"] == "submitted"
        assert "task_id" in data["result"]

    @patch("cli_anything.unreal.utils.ue_backend.preflight_check")
    def test_top_level_preflight_alias(self, mock_preflight, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_preflight.return_value = {
            "ready": True,
            "engine": {"ready": True, "errors": [], "warnings": []},
            "project": {"ready": True, "errors": [], "warnings": []},
        }

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "--project", temp_project["uproject"],
            "preflight",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["ready"] is True
        mock_preflight.assert_called_once()

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
        with patch("cli_anything.unreal.commands.editor.submit_task", return_value={"task_id": "launch-task"}):
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

    def test_port_option(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[
            {"port": 30015, "alive": True, "info": {"ok": True}},
        ]), \
             patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=None), \
             patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[]):
            result = runner.invoke(cli, [
                "--output", "json", "--port", "30015",
                "editor", "status",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"][0]["port"] == 30015

    def test_cvar_set_accepts_bare_negative_value(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            api = MagicMock()
            api.set_cvar.return_value = {}
            mock_editor.return_value = api

            result = runner.invoke(cli, [
                "--output", "json",
                "editor", "cvar", "set",
                "r.Shadow.Virtual.ResolutionLodBiasDirectional",
                "-4",
            ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"]["value"] == "-4"
        api.set_cvar.assert_called_once_with(
            "r.Shadow.Virtual.ResolutionLodBiasDirectional",
            "-4",
        )

    def test_cvar_set_accepts_negative_value_after_separator(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            api = MagicMock()
            api.set_cvar.return_value = {}
            mock_editor.return_value = api

            result = runner.invoke(cli, [
                "--output", "json",
                "editor", "cvar", "set",
                "r.Shadow.Virtual.ResolutionLodBiasDirectional",
                "--",
                "-4",
            ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"]["value"] == "-4"
        api.set_cvar.assert_called_once_with(
            "r.Shadow.Virtual.ResolutionLodBiasDirectional",
            "-4",
        )

    def test_cvar_get_errors_when_bridge_reports_missing(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            api = MagicMock()
            api.get_cvar_info.return_value = {
                "name": "r.__missing__",
                "exists": False,
                "value": "",
            }
            mock_editor.return_value = api

            result = runner.invoke(cli, [
                "--output", "json",
                "editor", "cvar", "get",
                "r.__missing__",
            ])

        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "CVAR_NOT_FOUND"

    def test_cvar_get_errors_when_empty_value_cannot_be_verified(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            api = MagicMock()
            api.get_cvar_info.return_value = {
                "name": "r.__maybe_missing__",
                "exists": None,
                "value": "",
                "verification": "unavailable",
            }
            mock_editor.return_value = api

            result = runner.invoke(cli, [
                "--output", "json",
                "editor", "cvar", "get",
                "r.__maybe_missing__",
            ])

        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "CVAR_GET_AMBIGUOUS_EMPTY"

    def test_cvar_get_allows_verified_empty_value(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            api = MagicMock()
            api.get_cvar_info.return_value = {
                "name": "r.EmptyButReal",
                "exists": True,
                "value": "",
            }
            mock_editor.return_value = api

            result = runner.invoke(cli, [
                "--output", "json",
                "editor", "cvar", "get",
                "r.EmptyButReal",
            ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"]["name"] == "r.EmptyButReal"
        assert data["result"]["value"] == ""
        assert data["result"]["exists"] is True

    def test_cvar_get_returns_structured_timeout_without_second_wait(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            api = MagicMock()
            api.get_cvar_info.return_value = {
                "name": "r.SDOC.Enable",
                "value": "",
                "exists": None,
                "verification": "request_failed",
                "error": (
                    "HTTPConnectionPool(host='localhost', port=30010): "
                    "Read timed out. (read timeout=2)"
                ),
                "request_stage": "bridge_metadata",
            }
            mock_editor.return_value = api

            result = runner.invoke(cli, [
                "--output", "json",
                "editor", "cvar", "get",
                "r.SDOC.Enable",
                "--timeout", "2",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "CVAR_GET_TIMEOUT"
        assert data["details"]["timeout_seconds"] == 2
        assert data["details"]["request_stage"] == "bridge_metadata"
        mock_editor.assert_called_once()
        assert mock_editor.call_args.kwargs["timeout"] == 2
        request_timeout = api.get_cvar_info.call_args.kwargs["timeout"]
        assert 0 < request_timeout <= 2

    def test_cvar_get_timeout_includes_editor_readiness(self):
        from click.testing import CliRunner
        from cli_anything.unreal.commands import AppError
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch(
            "cli_anything.unreal.commands.editor.time.monotonic",
            side_effect=[100.0, 102.0],
        ), patch(
            "cli_anything.unreal.commands.editor.require_editor",
            side_effect=AppError(
                "EDITOR_UNREACHABLE",
                "Editor HTTP API not responding.",
                exit_code=4,
            ),
        ):
            result = runner.invoke(cli, [
                "--output", "json",
                "editor", "cvar", "get",
                "r.SDOC.Enable",
                "--timeout", "2",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["code"] == "CVAR_GET_TIMEOUT"
        assert data["details"]["request_stage"] == "editor_readiness"

    def test_viewport_bookmark_jump_cli(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        before = {"loc": [0, 0, 0], "rot": [0, 0, 0]}
        after = {"loc": [1, 0, 0], "rot": [0, 0, 0]}
        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.sys.platform", "win32"), \
             patch("cli_anything.unreal.commands.editor.require_editor", return_value=MagicMock()), \
             patch("cli_anything.unreal.commands.editor._get_viewport_camera", side_effect=[before, after]), \
             patch("cli_anything.unreal.commands.editor._jump_viewport_bookmark_win32", return_value={"hwnd": 123, "title": "TestProject - Unreal Editor", "focus_point": [10, 10]}) as mock_jump:
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "editor", "viewport", "bookmark", "jump", "--index", "1",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["status"] == "jumped"
        assert data["result"]["index"] == 1
        mock_jump.assert_called_once_with("TestProject", 1)

    def test_viewport_camera_cli(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        camera = {"loc": [1, 2, 3], "rot": [4, 5, 6]}
        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor", return_value=MagicMock()), \
             patch("cli_anything.unreal.commands.editor._get_viewport_camera", return_value=camera) as get_camera:
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "editor", "viewport", "camera", "--timeout", "7",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"] == camera
        get_camera.assert_called_once()
        assert get_camera.call_args.args[1] == 7

    def test_viewport_camera_script_has_version_fallback(self):
        from cli_anything.unreal.commands.editor import _VIEWPORT_CAMERA_SCRIPT

        assert "getattr(unreal.EditorLevelLibrary" in _VIEWPORT_CAMERA_SCRIPT
        assert "LevelEditorSubsystem" in _VIEWPORT_CAMERA_SCRIPT

    @pytest.mark.parametrize(
        ("mode", "expected_mode"),
        [(None, None), ("toggle", "toggle"), ("on", "on"), ("off", "off")],
    )
    def test_viewport_game_view_cli(self, temp_project, mode, expected_mode):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        response = {
            "status": "ok",
            "mode": mode or "get",
            "before": False,
            "after": mode in {"toggle", "on"},
            "changed": mode in {"toggle", "on"},
        }
        args = [
            "--output", "json", "--project", temp_project["uproject"],
            "editor", "viewport", "game-view",
        ]
        if mode:
            args.append(mode)

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor", return_value=MagicMock()), \
             patch(
                 "cli_anything.unreal.commands.editor._set_viewport_game_view",
                 return_value=response,
             ) as game_view:
            result = runner.invoke(cli, args)

        assert result.exit_code == 0
        assert json.loads(result.output)["result"] == response
        assert game_view.call_args.args[1] == expected_mode

    def test_viewport_game_view_script_reads_sets_and_verifies(self):
        from cli_anything.unreal.commands.editor import _set_viewport_game_view

        api = MagicMock()
        with patch(
            "cli_anything.unreal.core.script_runner.run_python_code",
            return_value={
                "mode": "toggle",
                "before": False,
                "after": True,
                "changed": True,
            },
        ) as run_script:
            result = _set_viewport_game_view(api, "toggle")

        assert result["after"] is True
        script = run_script.call_args.args[1]
        assert "editor_get_game_view" in script
        assert "editor_set_game_view" in script
        assert "get_active_viewport_screen_bounds" in script
        assert run_script.call_args.kwargs["save"] is False

    def test_viewport_bookmark_jump_unchanged_errors(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        camera = {"loc": [0, 0, 0], "rot": [0, 0, 0]}
        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.sys.platform", "win32"), \
             patch("cli_anything.unreal.commands.editor.require_editor", return_value=MagicMock()), \
             patch("cli_anything.unreal.commands.editor._get_viewport_camera", side_effect=[camera, camera]), \
             patch("cli_anything.unreal.commands.editor._jump_viewport_bookmark_win32", return_value={"hwnd": 123, "title": "TestProject - Unreal Editor", "focus_point": [10, 10]}):
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "editor", "viewport", "bookmark", "jump", "--index", "1",
            ])
        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["code"] == "BOOKMARK_JUMP_UNCHANGED"
        assert "viewport" in data["suggestion"].lower()

    def test_viewport_bookmark_jump_non_windows_errors(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.sys.platform", "linux"), \
             patch("cli_anything.unreal.commands.editor.require_editor") as mock_require_editor:
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "editor", "viewport", "bookmark", "jump", "--index", "1",
            ])
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["code"] == "UNSUPPORTED_PLATFORM"
        mock_require_editor.assert_not_called()

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
        with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", side_effect=[
                [],
                [{"port": 30055, "alive": True, "info": {"ok": True}}],
             ]), \
             patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=None), \
             patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[]):
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "editor", "status",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"][0]["port"] == 30055

    def test_port_defaults_to_30010_without_config(self, temp_project):
        """Port falls back to 30010 when no RemoteControl config exists."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", return_value=[
                {"port": 30010, "alive": True, "info": {"ok": True}},
             ]), \
             patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=None), \
             patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[]):
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "editor", "status",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"][0]["port"] == 30010

    def test_port_explicit_overrides_config(self, temp_project):
        """Explicit --port overrides the value from DefaultRemoteControl.ini."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        config_dir = Path(temp_project["dir"]) / "Config"
        rc_ini = config_dir / "DefaultRemoteControl.ini"
        rc_ini.write_text(
            "[/Script/RemoteControlCommon.RemoteControlSettings]\n"
            "RemoteControlHttpServerPort=30055\n",
            encoding="utf-8",
        )

        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.scan_editor_ports", side_effect=[
                [],
                [{"port": 30099, "alive": True, "info": {"ok": True}}],
             ]), \
             patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=None), \
             patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[]):
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "--port", "30099",
                "editor", "status",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["result"][0]["port"] == 30099

    @pytest.mark.parametrize("with_project", [False, True])
    def test_editor_command_recovers_stale_auto_detected_port(self, temp_project, with_project):
        """Normal commands reuse the unique live instance found by editor status."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        created_ports = []

        class FakeAPI:
            def __init__(self, port):
                self.port = port
                self.project_path = None
                created_ports.append(port)

            def is_alive(self):
                return self.port == 30011

        args = ["--output", "json"]
        if with_project:
            args.extend(["--project", temp_project["uproject"]])
        args.extend(["editor", "open-level", "/Game/Maps/TestMap"])

        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", FakeAPI), \
             patch("cli_anything.unreal.commands.editor._scan_editor_status_instances", return_value=[
                 {
                     "status": "online",
                     "pid": 84156,
                     "port": 30011,
                     "project_path": temp_project["uproject"],
                 },
             ]) as scan_status, \
             patch("cli_anything.unreal.commands._guard_editor_project", return_value=None), \
             patch("cli_anything.unreal.core.scene.open_level", return_value={"status": "opened"}) as open_level:
            result = runner.invoke(cli, args)

        assert result.exit_code == 0, result.output
        assert created_ports == [30010, 30011]
        scan_state = scan_status.call_args.args[0]
        assert scan_state.session.port == 30011
        assert scan_status.call_args.args[1] == "30010-30020"
        assert scan_status.call_args.kwargs == {"include_bridge_status": False}
        open_level.assert_called_once()
        assert open_level.call_args.args[1] == "/Game/Maps/TestMap"
        assert open_level.call_args.args[0].port == 30011

    def test_editor_command_rejects_ambiguous_live_ports(self):
        """Shared editor commands require a selector when several editors are online."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        api = MagicMock()
        api.is_alive.return_value = False
        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=api), \
             patch("cli_anything.unreal.commands.editor._scan_editor_status_instances", return_value=[
                 {
                     "status": "online",
                     "pid": 111,
                     "port": 30011,
                     "project_path": r"F:\One\One.uproject",
                 },
                 {
                     "status": "online",
                     "pid": 222,
                     "port": 30012,
                     "project_path": r"F:\Two\Two.uproject",
                 },
             ]), \
             patch("cli_anything.unreal.core.scene.open_level") as open_level:
            result = runner.invoke(cli, [
                "--output", "json",
                "editor", "open-level", "/Game/Maps/TestMap",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["code"] == "EDITOR_TARGET_AMBIGUOUS"
        assert "--project" in data["suggestion"]
        assert "--port" in data["suggestion"]
        assert "editor close" not in data["suggestion"]
        assert [item["port"] for item in data["details"]["live_editors"]] == [30011, 30012]
        open_level.assert_not_called()

    def test_editor_command_does_not_override_explicit_stale_port(self):
        """An explicit --port remains authoritative even when another editor is online."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        api = MagicMock()
        api.is_alive.return_value = False
        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", return_value=api), \
             patch("cli_anything.unreal.commands.editor._scan_editor_status_instances") as scan_status:
            result = runner.invoke(cli, [
                "--output", "json", "--port", "30010",
                "editor", "open-level", "/Game/Maps/TestMap",
            ])

        assert result.exit_code == 4
        data = json.loads(result.output)
        assert data["code"] == "EDITOR_UNREACHABLE"
        assert "30010" in data["message"]
        scan_status.assert_not_called()

    def test_editor_command_does_not_select_another_projects_live_port(self, temp_project):
        """Project-scoped commands never recover through an unrelated live editor."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        created_ports = []

        class FakeAPI:
            def __init__(self, port):
                self.port = port
                self.project_path = None
                created_ports.append(port)

            def is_alive(self):
                return False

        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI", FakeAPI), \
             patch("cli_anything.unreal.commands.editor._scan_editor_status_instances", return_value=[
                 {
                     "status": "online",
                     "pid": 99999,
                     "port": 30011,
                     "project_path": str(Path(temp_project["uproject"]).with_name("Other.uproject")),
                 },
             ]):
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "editor", "open-level", "/Game/Maps/TestMap",
            ])

        assert result.exit_code == 4
        data = json.loads(result.output)
        assert data["code"] == "EDITOR_UNREACHABLE"
        assert created_ports == [30010]


# ═══════════════════════════════════════════════════════════════════════
#  Test blueprint.py (mocked)
# ═══════════════════════════════════════════════════════════════════════


