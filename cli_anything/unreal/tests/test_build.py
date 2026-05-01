"""Tests for test_build.py — Uses synthetic data only, no UE editor required."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


TEST574_UPROJECT = r"F:\Test574\Test574.uproject"

class TestBuild:
    """Tests for core/build.py — verifies command assembly."""

    def test_build_status(self, temp_project):
        from cli_anything.unreal.core.build import build_status

        status = build_status(temp_project["uproject"])
        assert status["project"] == "TestProject"
        assert status["has_binaries"] is True
        assert "Win64" in status["platforms"]

    def test_compile_no_engine(self, temp_project):
        from cli_anything.unreal.core.build import compile_project

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[]), \
             patch("cli_anything.unreal.core.build.find_engine_root", return_value=None):
            result = compile_project(temp_project["uproject"])
            assert result["status"] == "error"
            assert "engine root" in result["error"].lower()

    def test_cook_no_engine(self, temp_project):
        from cli_anything.unreal.core.build import cook_content

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[]), \
             patch("cli_anything.unreal.core.build.find_engine_root", return_value=None):
            result = cook_content(temp_project["uproject"])
            assert result["status"] == "error"

    def test_package_no_engine(self, temp_project):
        from cli_anything.unreal.core.build import package_project

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[]), \
             patch("cli_anything.unreal.core.build.find_engine_root", return_value=None):
            result = package_project(temp_project["uproject"])
            assert result["status"] == "error"

    def test_generate_no_engine(self, temp_project):
        from cli_anything.unreal.core.build import generate_project_files

        with patch("cli_anything.unreal.core.build.find_engine_root", return_value=None):
            result = generate_project_files(temp_project["uproject"])
            assert result["status"] == "error"


# ═══════════════════════════════════════════════════════════════════════
#  Test ue_http_api.py (mocked)
# ═══════════════════════════════════════════════════════════════════════


class TestBuildSuccessPaths:
    """Tests for compile/cook/package success paths via mocked run_uat."""

    def _mock_engine_root(self):
        return r"F:\RX_ENGINE_5.7"

    def test_compile_success(self, temp_project):
        from cli_anything.unreal.core.build import compile_project

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[]), \
             patch("cli_anything.unreal.core.build.find_engine_root", return_value=self._mock_engine_root()), \
             patch("cli_anything.unreal.core.build.run_uat", return_value={
                 "returncode": 0, "log_file": r"F:\Test\Saved\Logs\cli_compile.log",
                 "duration_seconds": 12.3,
             }):
            result = compile_project(temp_project["uproject"])
            assert result["status"] == "ok"
            assert result["returncode"] == 0
            assert result["log_file"].endswith("cli_compile.log")
            assert result["duration_seconds"] == 12.3
            # stdout/stderr must not leak back into the result
            assert "stdout" not in result
            assert "stderr" not in result

    def test_compile_error_returncode(self, temp_project):
        from cli_anything.unreal.core.build import compile_project

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[]), \
             patch("cli_anything.unreal.core.build.find_engine_root", return_value=self._mock_engine_root()), \
             patch("cli_anything.unreal.core.build.run_uat", return_value={
                 "returncode": 1, "log_file": r"F:\Test\Saved\Logs\cli_compile.log",
                 "duration_seconds": 5.0,
             }):
            result = compile_project(temp_project["uproject"])
            assert result["status"] == "error"
            assert result["returncode"] == 1
            assert "log_file" in result["error"]

    def test_cook_success(self, temp_project):
        from cli_anything.unreal.core.build import cook_content

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[]), \
             patch("cli_anything.unreal.core.build.find_engine_root", return_value=self._mock_engine_root()), \
             patch("cli_anything.unreal.core.build.run_uat", return_value={
                 "returncode": 0, "log_file": r"F:\Test\Saved\Logs\cli_cook.log",
                 "duration_seconds": 30.0,
             }):
            result = cook_content(temp_project["uproject"])
            assert result["status"] == "ok"
            assert result["returncode"] == 0
            assert result["log_file"].endswith("cli_cook.log")

    def test_package_success(self, temp_project):
        from cli_anything.unreal.core.build import package_project

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[]), \
             patch("cli_anything.unreal.core.build.find_engine_root", return_value=self._mock_engine_root()), \
             patch("cli_anything.unreal.core.build.run_uat", return_value={
                 "returncode": 0, "log_file": r"F:\Test\Saved\Logs\cli_package.log",
                 "duration_seconds": 60.0,
             }):
            result = package_project(temp_project["uproject"])
            assert result["status"] == "ok"
            assert "output_dir" in result
            assert result["log_file"].endswith("cli_package.log")

    def test_package_default_output_dir(self, temp_project):
        from cli_anything.unreal.core.build import package_project

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[]), \
             patch("cli_anything.unreal.core.build.find_engine_root", return_value=self._mock_engine_root()), \
             patch("cli_anything.unreal.core.build.run_uat", return_value={
                 "returncode": 0, "log_file": "", "duration_seconds": 0.0,
             }):
            result = package_project(temp_project["uproject"])
            assert result["output_dir"].endswith("Packaged")

    def test_package_custom_output_dir(self, temp_project):
        from cli_anything.unreal.core.build import package_project

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[]), \
             patch("cli_anything.unreal.core.build.find_engine_root", return_value=self._mock_engine_root()), \
             patch("cli_anything.unreal.core.build.run_uat", return_value={
                 "returncode": 0, "log_file": "", "duration_seconds": 0.0,
             }):
            result = package_project(temp_project["uproject"], output_dir="D:/Out")
            assert result["output_dir"] == "D:/Out"

    def test_stop_build_calls_kill(self, temp_project):
        from cli_anything.unreal.core.build import stop_build

        with patch("cli_anything.unreal.core.build.kill_build_processes", return_value={
            "killed": [100, 200], "remaining": [], "status": "ok",
        }):
            result = stop_build(temp_project["uproject"])
            assert result["status"] == "ok"
            assert 100 in result["killed"]

    def test_is_building_calls_find(self, temp_project):
        from cli_anything.unreal.core.build import is_building

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[
            {"pid": 100, "name": "MSBuild.exe", "cmdline": "", "project": ""},
        ]):
            result = is_building(temp_project["uproject"])
            assert result["building"] is True

    def test_generate_project_files_uat_fallback(self, temp_project):
        """generate_project_files uses UAT fallback when bat not found."""
        from cli_anything.unreal.core.build import generate_project_files

        with patch("cli_anything.unreal.core.build.find_engine_root", return_value=self._mock_engine_root()), \
             patch("cli_anything.unreal.core.build.find_generate_project_files", return_value=None), \
             patch("cli_anything.unreal.core.build.run_uat", return_value={
                 "returncode": 0, "log_file": r"F:\Test\Saved\Logs\cli_genproj.log",
                 "duration_seconds": 4.0,
             }):
            result = generate_project_files(temp_project["uproject"])
            assert result["status"] == "ok"
            assert result["log_file"].endswith("cli_genproj.log")


# ═══════════════════════════════════════════════════════════════════════
#  Test build stop / is-building / no-timeout (new features)
# ═══════════════════════════════════════════════════════════════════════


class TestBuildStopAndDetect:
    """Tests for build stop, is-building, and timeout removal."""

    def test_compile_no_timeout_param(self, temp_project):
        """compile_project() no longer accepts timeout."""
        from cli_anything.unreal.core.build import compile_project
        import inspect

        sig = inspect.signature(compile_project)
        assert "timeout" not in sig.parameters

    def test_cook_no_timeout_param(self, temp_project):
        """cook_content() no longer accepts timeout."""
        from cli_anything.unreal.core.build import cook_content
        import inspect

        sig = inspect.signature(cook_content)
        assert "timeout" not in sig.parameters

    def test_package_no_timeout_param(self, temp_project):
        """package_project() no longer accepts timeout."""
        from cli_anything.unreal.core.build import package_project
        import inspect

        sig = inspect.signature(package_project)
        assert "timeout" not in sig.parameters

    def test_generate_no_timeout_param(self):
        """generate_project_files() no longer accepts timeout."""
        from cli_anything.unreal.core.build import generate_project_files
        import inspect

        sig = inspect.signature(generate_project_files)
        assert "timeout" not in sig.parameters

    def test_is_building_no_processes(self, temp_project):
        """is_building returns False when no build processes are running."""
        from cli_anything.unreal.core.build import is_building

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[]):
            result = is_building(temp_project["uproject"])
            assert result["building"] is False
            assert result["processes"] == []

    def test_is_building_with_processes(self, temp_project):
        """is_building returns True when build processes are detected."""
        from cli_anything.unreal.core.build import is_building

        mock_procs = [
            {"pid": 1234, "name": "MSBuild.exe", "cmdline": "MSBuild.exe project.vcxproj", "project": temp_project["uproject"]},
        ]
        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=mock_procs):
            result = is_building(temp_project["uproject"])
            assert result["building"] is True
            assert len(result["processes"]) == 1

    def test_compile_rejects_if_already_building(self, temp_project):
        """compile_project returns error when a build is already running."""
        from cli_anything.unreal.core.build import compile_project

        mock_procs = [
            {"pid": 1234, "name": "MSBuild.exe", "cmdline": "MSBuild.exe project.vcxproj", "project": temp_project["uproject"]},
        ]
        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=mock_procs):
            result = compile_project(temp_project["uproject"])
            assert result["status"] == "error"
            assert "already in progress" in result["error"].lower()

    def test_cook_rejects_if_already_building(self, temp_project):
        """cook_content returns error when a build is already running."""
        from cli_anything.unreal.core.build import cook_content

        mock_procs = [
            {"pid": 1234, "name": "MSBuild.exe", "cmdline": "MSBuild.exe project.vcxproj", "project": temp_project["uproject"]},
        ]
        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=mock_procs):
            result = cook_content(temp_project["uproject"])
            assert result["status"] == "error"
            assert "already in progress" in result["error"].lower()

    def test_package_rejects_if_already_building(self, temp_project):
        """package_project returns error when a build is already running."""
        from cli_anything.unreal.core.build import package_project

        mock_procs = [
            {"pid": 1234, "name": "MSBuild.exe", "cmdline": "MSBuild.exe project.vcxproj", "project": temp_project["uproject"]},
        ]
        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=mock_procs):
            result = package_project(temp_project["uproject"])
            assert result["status"] == "error"
            assert "already in progress" in result["error"].lower()

    def test_stop_build_no_processes(self, temp_project):
        """stop_build returns 'none' when no processes to kill."""
        from cli_anything.unreal.core.build import stop_build

        with patch("cli_anything.unreal.core.build.kill_build_processes", return_value={
            "killed": [], "remaining": [], "status": "none",
        }):
            result = stop_build(temp_project["uproject"])
            assert result["status"] == "none"
            assert result["killed"] == []

    def test_stop_build_success(self, temp_project):
        """stop_build kills processes and returns 'ok'."""
        from cli_anything.unreal.core.build import stop_build

        with patch("cli_anything.unreal.core.build.kill_build_processes", return_value={
            "killed": [1234, 5678], "remaining": [], "status": "ok",
        }):
            result = stop_build(temp_project["uproject"])
            assert result["status"] == "ok"
            assert 1234 in result["killed"]

    def test_stop_build_partial(self, temp_project):
        """stop_build returns 'partial' when some processes survive."""
        from cli_anything.unreal.core.build import stop_build

        with patch("cli_anything.unreal.core.build.kill_build_processes", return_value={
            "killed": [1234], "remaining": [9999], "status": "partial",
        }):
            result = stop_build(temp_project["uproject"])
            assert result["status"] == "partial"
            assert 9999 in result["remaining"]

    def test_run_uat_no_timeout_param(self):
        """run_uat() no longer accepts timeout parameter."""
        from cli_anything.unreal.utils.ue_backend import run_uat
        import inspect

        sig = inspect.signature(run_uat)
        assert "timeout" not in sig.parameters

    def test_run_build_no_timeout_param(self):
        """run_build() no longer accepts timeout parameter."""
        from cli_anything.unreal.utils.ue_backend import run_build
        import inspect

        sig = inspect.signature(run_build)
        assert "timeout" not in sig.parameters

    def test_run_subprocess_no_timeout_param(self):
        """_run_subprocess() no longer accepts timeout parameter."""
        from cli_anything.unreal.utils.ue_backend import _run_subprocess
        import inspect

        sig = inspect.signature(_run_subprocess)
        assert "timeout" not in sig.parameters

    def test_kill_process_tree(self):
        """_kill_process_tree calls taskkill with /F /T /PID."""
        from cli_anything.unreal.utils.ue_backend import _kill_process_tree

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = _kill_process_tree(1234)
            assert result is True
            call_args = mock_run.call_args[0][0]
            assert "taskkill" in call_args
            assert "/F" in call_args
            assert "/T" in call_args
            assert "/PID" in call_args
            assert "1234" in call_args

    def test_find_running_build_processes_no_match(self):
        """find_running_build_processes returns [] when no processes match."""
        from cli_anything.unreal.utils.ue_backend import find_running_build_processes

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")
            result = find_running_build_processes("F:/Test/Test.uproject")
            assert result == []

    def test_find_running_build_processes_with_match(self):
        """find_running_build_processes parses PowerShell JSON output."""
        from cli_anything.unreal.utils.ue_backend import find_running_build_processes

        ps_output = json.dumps([
            {"ProcessId": 100, "Name": "MSBuild.exe", "CommandLine": "MSBuild.exe /p:Project=F:\\Test\\Test.uproject"},
            {"ProcessId": 200, "Name": "cl.exe", "CommandLine": "cl.exe some.cpp"},
        ])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ps_output)
            result = find_running_build_processes()
            assert len(result) == 2
            assert result[0]["pid"] == 100
            assert result[0]["name"] == "MSBuild.exe"

    def test_find_running_build_processes_filter_by_project(self):
        """find_running_build_processes filters by .uproject path."""
        from cli_anything.unreal.utils.ue_backend import find_running_build_processes

        ps_output = json.dumps([
            {"ProcessId": 100, "Name": "MSBuild.exe", "CommandLine": "MSBuild.exe -project=F:\\Test574\\Test574.uproject"},
            {"ProcessId": 200, "Name": "MSBuild.exe", "CommandLine": "MSBuild.exe -project=F:\\Other\\Other.uproject"},
        ])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ps_output)
            result = find_running_build_processes("F:\\Test574\\Test574.uproject")
            assert len(result) == 1
            assert result[0]["pid"] == 100

    def test_find_running_build_processes_skips_idle_msbuild_daemons(self):
        """find_running_build_processes skips Rider/VS idle MSBuild node-reuse daemons."""
        from cli_anything.unreal.utils.ue_backend import find_running_build_processes

        ps_output = json.dumps([
            {"ProcessId": 100, "Name": "MSBuild.exe", "CommandLine": "MSBuild.exe /noautoresponse /nologo /nodemode:1 /nodeReuse:false"},
            {"ProcessId": 200, "Name": "MSBuild.exe", "CommandLine": "MSBuild.exe /noautoresponse /nologo /nodemode:1 /nodeReuse:false /low:false"},
            {"ProcessId": 300, "Name": "MSBuild.exe", "CommandLine": "MSBuild.exe /nr:true"},
        ])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ps_output)
            result = find_running_build_processes("F:\\Test574\\Test574.uproject")
            assert len(result) == 0

    def test_find_running_build_processes_no_false_positive_for_other_project(self):
        """find_running_build_processes returns [] when only other projects are building."""
        from cli_anything.unreal.utils.ue_backend import find_running_build_processes

        ps_output = json.dumps([
            {"ProcessId": 100, "Name": "UnrealBuildTool.exe", "CommandLine": "UnrealBuildTool.exe -project=F:\\Other\\Other.uproject"},
            {"ProcessId": 200, "Name": "cl.exe", "CommandLine": "cl.exe some.cpp"},
        ])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ps_output)
            result = find_running_build_processes("F:\\Test574\\Test574.uproject")
            assert len(result) == 0

    def test_find_running_build_processes_keeps_associated_processes_when_project_matches(self):
        """When a project matches, associated processes (cl.exe without .uproject) are kept."""
        from cli_anything.unreal.utils.ue_backend import find_running_build_processes

        ps_output = json.dumps([
            {"ProcessId": 100, "Name": "MSBuild.exe", "CommandLine": "MSBuild.exe -project=F:\\Test574\\Test574.uproject"},
            {"ProcessId": 200, "Name": "cl.exe", "CommandLine": "cl.exe some.cpp"},
        ])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ps_output)
            result = find_running_build_processes("F:\\Test574\\Test574.uproject")
            assert len(result) == 2
            pids = {p["pid"] for p in result}
            assert 100 in pids
            assert 200 in pids

    def test_kill_build_processes_all_killed(self):
        """kill_build_processes kills all found processes."""
        from cli_anything.unreal.utils.ue_backend import kill_build_processes

        mock_procs = [
            {"pid": 100, "name": "MSBuild.exe", "cmdline": "", "project": ""},
        ]
        with patch("cli_anything.unreal.utils.ue_backend.find_running_build_processes", side_effect=[
            mock_procs,  # first call: find processes
            [],          # after kill + sleep: re-check (empty)
        ]), patch("cli_anything.unreal.utils.ue_backend._kill_process_tree", return_value=True), \
             patch("time.sleep"):
            result = kill_build_processes()
            assert result["status"] == "ok"
            assert 100 in result["killed"]
            assert result["remaining"] == []

    def test_kill_build_processes_none_running(self):
        """kill_build_processes returns 'none' when no processes found."""
        from cli_anything.unreal.utils.ue_backend import kill_build_processes

        with patch("cli_anything.unreal.utils.ue_backend.find_running_build_processes", return_value=[]):
            result = kill_build_processes()
            assert result["status"] == "none"
            assert result["killed"] == []

    def test_run_subprocess_kills_tree_on_timeout(self, tmp_path):
        """_run_subprocess kills the process tree when the safety timeout is hit."""
        from cli_anything.unreal.utils.ue_backend import _run_subprocess

        mock_proc = MagicMock()
        mock_proc.pid = 9999
        # The inner poll-wait loop now catches TimeoutExpired repeatedly
        # until the safety deadline is reached — exactly one expiry is
        # enough when we force the safety timeout down to 0.
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="test", timeout=1),
            None,  # post-kill wait() succeeds
        ]
        mock_proc.returncode = -2

        log_path = tmp_path / "t.log"
        with patch("subprocess.Popen", return_value=mock_proc), \
             patch("cli_anything.unreal.utils.ue_backend._SAFETY_TIMEOUT", 0), \
             patch("cli_anything.unreal.utils.ue_backend._kill_process_tree", return_value=True) as mock_kill:
            # Disable heartbeats so the poll loop doesn't spin waiting for
            # a beat boundary.
            result = _run_subprocess(
                ["echo", "test"], log_file=str(log_path),
                heartbeat_seconds=0,
            )
            assert result["returncode"] == -2
            assert result["log_file"] == str(log_path)
            assert "timed out" in result["error"].lower()
            # Verify _kill_process_tree was called with the PID
            mock_kill.assert_called_once_with(9999)

    def test_run_subprocess_success(self, tmp_path):
        """_run_subprocess returns result dict on success."""
        from cli_anything.unreal.utils.ue_backend import _run_subprocess

        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        log_path = tmp_path / "t.log"
        with patch("subprocess.Popen", return_value=mock_proc):
            result = _run_subprocess(["echo", "hello"], log_file=str(log_path))
            assert result["returncode"] == 0
            assert result["log_file"] == str(log_path)
            assert "duration_seconds" in result
            # Output must not leak back
            assert "stdout" not in result
            assert "stderr" not in result

    def test_run_subprocess_file_not_found(self, tmp_path):
        """_run_subprocess handles FileNotFoundError gracefully."""
        from cli_anything.unreal.utils.ue_backend import _run_subprocess

        log_path = tmp_path / "t.log"
        with patch("subprocess.Popen", side_effect=FileNotFoundError("not found")):
            result = _run_subprocess(["nonexistent_command"], log_file=str(log_path))
            assert result["returncode"] == -1
            assert "not found" in result["error"]


# ═══════════════════════════════════════════════════════════════════════
#  Test build CLI commands (stop, is-building, no --timeout)
# ═══════════════════════════════════════════════════════════════════════


class TestBuildCLI:
    """Tests for build CLI — stop, is-building, and --timeout removal."""

    @staticmethod
    def _parse_json_output(output: str) -> dict:
        """Extract JSON from CLI output that may have skin.info() text before it."""
        # Find the first '{' and parse from there
        idx = output.find("{")
        if idx == -1:
            return json.loads(output)
        return json.loads(output[idx:])

    def test_build_compile_has_no_wait_and_timeout(self, temp_project):
        """build compile now has --no-wait and --timeout options."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["build", "compile", "--help"])
        assert result.exit_code == 0
        assert "--no-wait" in result.output
        assert "--timeout" in result.output

    def test_build_cook_has_no_wait_and_timeout(self, temp_project):
        """build cook now has --no-wait and --timeout options."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["build", "cook", "--help"])
        assert result.exit_code == 0
        assert "--no-wait" in result.output
        assert "--timeout" in result.output

    def test_build_package_has_no_wait_and_timeout(self, temp_project):
        """build package now has --no-wait and --timeout options."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["build", "package", "--help"])
        assert result.exit_code == 0
        assert "--no-wait" in result.output
        assert "--timeout" in result.output

    def test_build_stop_cli(self, temp_project):
        """build stop command works and calls stop_build."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        with patch("cli_anything.unreal.core.build.kill_build_processes", return_value={
            "killed": [1234], "remaining": [], "status": "ok",
        }):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "build", "stop",
            ])
            assert result.exit_code == 0
            data = self._parse_json_output(result.output)
            assert data["status"] == "success"
            assert data["result"]["status"] == "ok"
            assert 1234 in data["result"]["killed"]

    def test_build_is_building_cli_false(self, temp_project):
        """build is-building returns building=false when no processes."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[]):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "build", "is-building",
            ])
            assert result.exit_code == 0
            data = self._parse_json_output(result.output)
            assert data["result"]["building"] is False

    def test_build_is_building_cli_true(self, temp_project):
        """build is-building returns building=true when processes detected."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_procs = [
            {"pid": 1234, "name": "MSBuild.exe", "cmdline": "MSBuild.exe project.vcxproj", "project": temp_project["uproject"]},
        ]
        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=mock_procs):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "build", "is-building",
            ])
            assert result.exit_code == 0
            data = self._parse_json_output(result.output)
            assert data["result"]["building"] is True

    def test_build_stop_none_running(self, temp_project):
        """build stop when nothing is running returns status=none."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        with patch("cli_anything.unreal.core.build.kill_build_processes", return_value={
            "killed": [], "remaining": [], "status": "none",
        }):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "build", "stop",
            ])
            assert result.exit_code == 0
            data = self._parse_json_output(result.output)
            assert data["result"]["status"] == "none"


# ═══════════════════════════════════════════════════════════════════════
#  Real E2E tests with F:\Test574
# ═══════════════════════════════════════════════════════════════════════

TEST574_UPROJECT = r"F:\Test574\Test574.uproject"


@pytest.mark.skipif(
    not Path(TEST574_UPROJECT).exists(),
    reason="F:\\Test574\\Test574.uproject not available"
)

class TestBuildE2E:
    """Real end-to-end tests using F:\\Test574 project."""

    def test_build_status_real(self):
        """build status against real project."""
        from cli_anything.unreal.core.build import build_status

        result = build_status(TEST574_UPROJECT)
        assert result["project"] == "Test574"
        assert "platforms" in result

    def test_is_building_real(self):
        """is_building against real project (should return False)."""
        from cli_anything.unreal.core.build import is_building

        result = is_building(TEST574_UPROJECT)
        assert "building" in result
        assert "processes" in result
        # Most likely not building right now
        assert isinstance(result["building"], bool)

    @staticmethod
    def _parse_json_output(output: str) -> dict:
        idx = output.find("{")
        if idx == -1:
            return json.loads(output)
        return json.loads(output[idx:])

    def test_build_is_building_cli_real(self):
        """build is-building CLI against real project."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "--project", TEST574_UPROJECT,
            "build", "is-building",
        ])
        assert result.exit_code == 0
        data = self._parse_json_output(result.output)
        assert "building" in data["result"]

    def test_build_status_cli_real(self):
        """build status CLI against real project."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "--project", TEST574_UPROJECT,
            "build", "status",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["project"] == "Test574"

    def test_find_running_build_processes_real(self):
        """find_running_build_processes on real system."""
        from cli_anything.unreal.utils.ue_backend import find_running_build_processes

        # Without project filter
        all_procs = find_running_build_processes()
        assert isinstance(all_procs, list)

        # With project filter
        filtered = find_running_build_processes(TEST574_UPROJECT)
        assert isinstance(filtered, list)

    def test_build_stop_cli_real(self):
        """build stop CLI against real project (should report none)."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--output", "json", "--project", TEST574_UPROJECT,
            "build", "stop",
        ])
        assert result.exit_code == 0
        data = self._parse_json_output(result.output)
        assert data["result"]["status"] in ("none", "ok", "partial")

