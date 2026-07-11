"""Tests for test_build.py — Uses synthetic data only, no UE editor required."""

import json
import os
import subprocess
import sys
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

    def test_compile_android_uses_build_bat_game_target(self, temp_project):
        from cli_anything.unreal.core.build import compile_project

        build_result = {
            "returncode": 0,
            "log_file": r"F:\Test\Saved\Logs\cli_compile.log",
            "duration_seconds": 12.3,
        }
        with patch(
            "cli_anything.unreal.core.build.find_running_build_processes",
            return_value=[],
        ), patch(
            "cli_anything.unreal.core.build.run_build",
            return_value=build_result,
            create=True,
        ) as mock_run_build, patch(
            "cli_anything.unreal.core.build.run_uat",
            return_value=build_result,
        ) as mock_run_uat:
            result = compile_project(
                temp_project["uproject"],
                platform="Android",
                engine_root=self._mock_engine_root(),
            )

        project_dir = str(Path(temp_project["uproject"]).parent)
        mock_run_build.assert_called_once_with(
            self._mock_engine_root(),
            "TestProject",
            "Android",
            "Development",
            extra_args=[
                f'-Project={temp_project["uproject"]}',
                "-WaitMutex",
            ],
            log_file=None,
            log_label="compile",
            project_dir=project_dir,
            on_start=None,
        )
        mock_run_uat.assert_not_called()
        assert result["status"] == "ok"

    def test_compile_android_uses_unique_custom_game_target(self, temp_project):
        from cli_anything.unreal.core.build import compile_project

        project_dir = Path(temp_project["uproject"]).parent
        (project_dir / "Source" / "CustomMobile.Target.cs").write_text(
            "public class CustomMobileTarget : TargetRules {\n"
            "    public CustomMobileTarget(TargetInfo Target) : base(Target) {\n"
            "        Type = TargetType.Game;\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        build_result = {
            "returncode": 0,
            "log_file": "compile.log",
            "duration_seconds": 1.0,
        }
        with patch(
            "cli_anything.unreal.core.build.find_running_build_processes",
            return_value=[],
        ), patch(
            "cli_anything.unreal.core.build.run_build",
            return_value=build_result,
            create=True,
        ) as mock_run_build, patch(
            "cli_anything.unreal.core.build.run_uat",
            return_value=build_result,
        ) as mock_run_uat:
            result = compile_project(
                temp_project["uproject"],
                platform="Android",
                engine_root=self._mock_engine_root(),
            )

        assert result["status"] == "ok"
        assert mock_run_build.call_args.args[1] == "CustomMobile"
        mock_run_uat.assert_not_called()

    def test_compile_android_ignores_inactive_and_lexical_fake_game_targets(
        self, temp_project
    ):
        from cli_anything.unreal.core.build import compile_project

        source_dir = Path(temp_project["uproject"]).parent / "Source"
        (source_dir / "FakeEditor.Target.cs").write_text(
            "// Type = TargetType.Game;\n"
            'const string Normal = "Type = TargetType.Game;";\n'
            'const string Verbatim = @"Type = TargetType.Game;";\n'
            "const char Fake = 'Type = TargetType.Game;';\n"
            "/* Type = TargetType.Game; */\n"
            "#if false\n"
            "Type = TargetType.Game;\n"
            "#if NESTED\n"
            "Type = TargetType.Game;\n"
            "#endif\n"
            "#endif\n",
            encoding="utf-8",
        )
        (source_dir / "RealMobile.Target.cs").write_text(
            "public class RealMobileTarget : TargetRules {\n"
            "    Type = TargetType.Game;\n"
            "}\n",
            encoding="utf-8",
        )
        build_result = {
            "returncode": 0,
            "log_file": "compile.log",
            "duration_seconds": 1.0,
        }
        with patch(
            "cli_anything.unreal.core.build.find_running_build_processes",
            return_value=[],
        ), patch(
            "cli_anything.unreal.core.build.run_build",
            return_value=build_result,
        ) as mock_run_build, patch(
            "cli_anything.unreal.core.build.run_uat",
            return_value=build_result,
        ) as mock_run_uat:
            result = compile_project(
                temp_project["uproject"],
                platform="Android",
                engine_root=self._mock_engine_root(),
            )

        assert result["status"] == "ok"
        assert mock_run_build.call_args.args[1] == "RealMobile"
        mock_run_uat.assert_not_called()

    def test_compile_android_rejects_multiple_game_targets(self, temp_project):
        from cli_anything.unreal.core.build import compile_project

        source_dir = Path(temp_project["uproject"]).parent / "Source"
        for name in ("ClientGame", "CustomMobile"):
            (source_dir / f"{name}.Target.cs").write_text(
                f"public class {name}Target : TargetRules {{\n"
                "    Type = TargetType.Game;\n"
                "}\n",
                encoding="utf-8",
            )

        with patch(
            "cli_anything.unreal.core.build.find_running_build_processes",
            return_value=[],
        ), patch(
            "cli_anything.unreal.core.build.run_build",
            create=True,
        ) as mock_run_build, patch(
            "cli_anything.unreal.core.build.run_uat",
        ) as mock_run_uat:
            result = compile_project(
                temp_project["uproject"],
                platform="Android",
                engine_root=self._mock_engine_root(),
            )

        assert result["status"] == "error"
        assert "multiple game targets" in result["error"].lower()
        assert "ClientGame" in result["error"]
        assert "CustomMobile" in result["error"]
        mock_run_build.assert_not_called()
        mock_run_uat.assert_not_called()

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

    def test_package_targeted_android_uat_args(self, temp_project):
        """Targeted package options must reach BuildCookRun as argv."""
        from cli_anything.unreal.core.build import package_project

        maps = [
            "/Game/Maps/Oregon_Main",
            "/Game/Maps/Oregon_Sub",
        ]
        extra_args = [
            "-pak",
            "-iostore",
            "-compressed",
            "-prereqs",
            "-nodebuginfo",
            "-unversionedcookedcontent",
            "-SkipCookingEditorContent",
            "-ini:Engine:[/Script/Engine.RendererSettings]:r.SDOC.Enable=1",
        ]
        with patch(
            "cli_anything.unreal.core.build.find_running_build_processes",
            return_value=[],
        ), patch(
            "cli_anything.unreal.core.build.find_engine_root",
            return_value=self._mock_engine_root(),
        ), patch(
            "cli_anything.unreal.core.build.run_uat",
            return_value={
                "returncode": 0,
                "log_file": r"F:\Test\Saved\Logs\cli_package.log",
                "duration_seconds": 60.0,
                "command": ["RunUAT.bat", "BuildCookRun", "-package"],
            },
        ) as mock_run:
            result = package_project(
                temp_project["uproject"],
                platform="Android",
                output_dir="D:/Out",
                maps=maps,
                cook_flavor="ASTC",
                uat_args=extra_args,
            )

        uat_args = mock_run.call_args.args[2]
        assert "-platform=Android" in uat_args
        assert "-map=/Game/Maps/Oregon_Main+/Game/Maps/Oregon_Sub" in uat_args
        assert "-cookflavor=ASTC" in uat_args
        for arg in extra_args:
            assert arg in uat_args
        assert result["uat_command"] == [
            "RunUAT.bat",
            "BuildCookRun",
            "-package",
        ]

    def test_package_preserves_legacy_positional_parameters(self, temp_project):
        """New package controls must not shift existing positional arguments."""
        from cli_anything.unreal.core.build import package_project

        on_start = MagicMock()
        with patch(
            "cli_anything.unreal.core.build.find_running_build_processes",
            return_value=[],
        ), patch(
            "cli_anything.unreal.core.build.run_uat",
            return_value={
                "returncode": 0,
                "log_file": "package.log",
                "duration_seconds": 1.0,
                "command": ["RunUAT.bat", "BuildCookRun"],
            },
        ) as mock_run:
            result = package_project(
                temp_project["uproject"],
                "Android",
                "Development",
                "D:/Out",
                "F:/Engine",
                "D:/package.log",
                on_start,
            )

        assert result["status"] == "ok"
        assert mock_run.call_args.args[0] == "F:/Engine"
        assert mock_run.call_args.kwargs["log_file"] == "D:/package.log"
        assert mock_run.call_args.kwargs["on_start"] is on_start

    def test_package_rejects_unsafe_uat_args_in_core(self, temp_project):
        """Direct core callers must not bypass argv safety validation."""
        from cli_anything.unreal.core.build import package_project

        with patch(
            "cli_anything.unreal.core.build.find_running_build_processes",
            return_value=[],
        ), patch(
            "cli_anything.unreal.core.build.find_engine_root",
            return_value=self._mock_engine_root(),
        ), patch(
            "cli_anything.unreal.core.build.run_uat",
        ) as mock_run:
            result = package_project(
                temp_project["uproject"],
                uat_args=['-x=" & echo PWNED & rem "'],
            )

        assert result["status"] == "error"
        assert "unsafe" in result["error"].lower()
        mock_run.assert_not_called()

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

    def test_stop_build_cancels_matching_async_task(
        self, temp_project, tmp_path, monkeypatch
    ):
        """Project stop must use task ownership when process scanning finds nothing."""
        from cli_anything.unreal.core.build import stop_build
        from cli_anything.unreal.core.tasks import create_task, load_task, save_task

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task(
            "build.compile",
            {"project_path": temp_project["uproject"]},
        )
        task.update({"status": "running", "worker_pid": 48788, "pid": 98612})
        save_task(task)

        killed = []

        def fake_kill(pid):
            killed.append(pid)
            return {
                "ok": True,
                "pid": pid,
                "method": "taskkill" if pid == 48788 else "taskkill_already_exited",
                "already_exited": pid == 98612,
            }

        def fake_process_info(pid):
            return {
                "query_ok": True,
                "found": True,
                "pid": pid,
                "parent_pid": 1 if pid == 48788 else 48788,
                "name": "python.exe" if pid == 48788 else "powershell.exe",
                "cmdline": (
                    f"python -m cli_anything.unreal _task-worker run {task['task_id']}"
                    if pid == 48788 else "powershell.exe -EncodedCommand AAA="
                ),
            }

        no_processes = {"killed": [], "remaining": [], "status": "none"}
        with patch(
            "cli_anything.unreal.core.build.kill_build_processes",
            return_value=no_processes,
        ), patch(
            "cli_anything.unreal.utils.ue_backend.kill_build_processes",
            return_value=no_processes,
        ), patch(
            "cli_anything.unreal.core.tasks._query_process_info",
            side_effect=fake_process_info,
        ), patch(
            "cli_anything.unreal.utils.ue_backend._kill_process_tree_result",
            side_effect=fake_kill,
        ):
            result = stop_build(temp_project["uproject"])

        saved = load_task(task["task_id"])
        assert killed == [48788, 98612]
        assert saved["status"] == "cancelled"
        assert saved["cancelled"] is True
        assert result["status"] == "ok"
        assert result["killed"] == [48788]
        assert result["remaining"] == []
        assert result["tasks"][0]["task_id"] == task["task_id"]
        assert result["tasks"][0]["status"] == "cancelled"

    def test_stop_build_reconciles_task_when_final_scan_kills_remaining_pid(
        self, temp_project, tmp_path, monkeypatch
    ):
        """A successful final scan must clear task-level cancellation failures."""
        from cli_anything.unreal.core.build import stop_build
        from cli_anything.unreal.core.tasks import create_task, load_task, save_task

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task(
            "build.compile",
            {"project_path": temp_project["uproject"]},
        )
        task.update({
            "status": "running",
            "cancelled": False,
            "cancel_result": {"killed": [], "remaining": [49001]},
        })
        save_task(task)

        with patch(
            "cli_anything.unreal.core.tasks.active_build_tasks",
            return_value=[task],
        ), patch(
            "cli_anything.unreal.core.tasks.cancel_task",
            side_effect=lambda task_id: load_task(task_id),
        ), patch(
            "cli_anything.unreal.core.build.kill_build_processes",
            return_value={"killed": [49001], "remaining": [], "status": "ok"},
        ):
            result = stop_build(temp_project["uproject"])

        saved = load_task(task["task_id"])
        assert result["status"] == "ok"
        assert result["remaining"] == []
        assert result["tasks"][0]["status"] == "cancelled"
        assert result["tasks"][0]["remaining"] == []
        assert saved["status"] == "cancelled"
        assert saved["cancelled"] is True
        assert saved["cancel_result"]["remaining"] == []
        assert saved["cancel_result"]["killed"] == [49001]


    def test_stop_build_does_not_kill_reused_task_pids(
        self, temp_project, tmp_path, monkeypatch
    ):
        """A stale running task must not kill unrelated processes reusing its PIDs."""
        from cli_anything.unreal.core.build import stop_build
        from cli_anything.unreal.core.tasks import create_task, load_task, save_task

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task(
            "build.compile",
            {"project_path": temp_project["uproject"]},
        )
        task.update({"status": "running", "worker_pid": 48788, "pid": 98612})
        save_task(task)

        def fake_process_info(pid):
            if pid == 48788:
                return {
                    "query_ok": True,
                    "found": True,
                    "pid": pid,
                    "parent_pid": 1684,
                    "name": "TiWorker.exe",
                    "cmdline": "TiWorker.exe -Embedding",
                }
            return {
                "query_ok": True,
                "found": True,
                "pid": pid,
                "parent_pid": 1234,
                "name": "python.exe",
                "cmdline": "python unrelated.py",
            }

        no_processes = {"killed": [], "remaining": [], "status": "none"}
        with patch(
            "cli_anything.unreal.core.tasks._query_process_info",
            side_effect=fake_process_info,
            create=True,
        ), patch(
            "cli_anything.unreal.utils.ue_backend._kill_process_tree_result"
        ) as kill, patch(
            "cli_anything.unreal.core.build.kill_build_processes",
            return_value=no_processes,
        ), patch(
            "cli_anything.unreal.utils.ue_backend.kill_build_processes",
            return_value=no_processes,
        ):
            result = stop_build(temp_project["uproject"])

        kill.assert_not_called()
        saved = load_task(task["task_id"])
        assert saved["status"] == "cancelled"
        assert result["status"] == "ok"
        assert result["killed"] == []
        assert all(
            process.get("ownership_mismatch")
            for process in saved["cancel_result"]["processes"]
        )

    def test_save_task_keeps_previous_record_when_write_is_interrupted(
        self, tmp_path, monkeypatch
    ):
        """Task updates must replace atomically instead of truncating live JSON."""
        from cli_anything.unreal.core.tasks import create_task, load_task, save_task

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task("build.compile", {"project_path": "P.uproject"})
        original_write = Path.write_text

        def interrupted_write(path, data, *args, **kwargs):
            if task["task_id"] in path.name:
                original_write(path, "{", encoding="utf-8")
                raise OSError("interrupted task write")
            return original_write(path, data, *args, **kwargs)

        updated = dict(task, status="running")
        with patch.object(Path, "write_text", new=interrupted_write):
            with pytest.raises(OSError, match="interrupted task write"):
                save_task(updated)

        assert load_task(task["task_id"])["status"] == "submitted"

    def test_create_task_normalizes_project_path_for_cross_cwd_stop(
        self, temp_project, tmp_path, monkeypatch
    ):
        """Task ownership must survive compile and stop running from different cwd."""
        from cli_anything.unreal.core.tasks import (
            active_build_tasks,
            create_task,
            save_task,
        )

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        project = Path(temp_project["uproject"])
        monkeypatch.chdir(project.parent)
        task = create_task("build.compile", {"project_path": project.name})
        task["status"] = "running"
        save_task(task)

        monkeypatch.chdir(tmp_path)
        matches = active_build_tasks(str(project))

        assert [item["task_id"] for item in matches] == [task["task_id"]]
        assert Path(matches[0]["payload"]["project_path"]).is_absolute()

    def test_cancel_task_reconciles_failed_kill_with_later_scan_success(
        self, temp_project, tmp_path, monkeypatch
    ):
        """A PID killed by the final scan must not remain in remaining."""
        from cli_anything.unreal.core.tasks import cancel_task, create_task, save_task

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task(
            "build.compile",
            {"project_path": temp_project["uproject"]},
        )
        task.update({"status": "running", "worker_pid": 41001, "pid": 41002})
        save_task(task)

        def fake_process_info(pid):
            return {
                "query_ok": True,
                "found": True,
                "pid": pid,
                "parent_pid": 1 if pid == 41001 else 41001,
                "name": "python.exe" if pid == 41001 else "powershell.exe",
                "cmdline": (
                    f"python -m cli_anything.unreal _task-worker run {task['task_id']}"
                    if pid == 41001 else "powershell.exe -EncodedCommand AAA="
                ),
            }

        def fake_kill(pid):
            if pid == 41001:
                return {"ok": False, "pid": pid, "error": "first kill failed"}
            return {"ok": True, "pid": pid}

        scan_result = {"killed": [41001], "remaining": [], "status": "ok"}
        with patch(
            "cli_anything.unreal.core.tasks._query_process_info",
            side_effect=fake_process_info,
            create=True,
        ), patch(
            "cli_anything.unreal.utils.ue_backend._kill_process_tree_result",
            side_effect=fake_kill,
        ), patch(
            "cli_anything.unreal.utils.ue_backend.kill_build_processes",
            return_value=scan_result,
        ):
            result = cancel_task(task["task_id"])

        assert result["status"] == "cancelled"
        assert result["cancel_result"]["killed"] == [41002, 41001]
        assert result["cancel_result"]["remaining"] == []

    def test_cancel_task_rechecks_root_identity_after_worker_exit(
        self, temp_project, tmp_path, monkeypatch
    ):
        """A root PID reused after Job close must not be killed."""
        from cli_anything.unreal.core.tasks import cancel_task, create_task, save_task

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task(
            "build.compile",
            {"project_path": temp_project["uproject"]},
        )
        task.update({"status": "running", "worker_pid": 42001, "pid": 42002})
        save_task(task)
        root_queries = {"count": 0}

        def fake_process_info(pid):
            if pid == 42001:
                return {
                    "query_ok": True,
                    "found": True,
                    "pid": pid,
                    "parent_pid": 1,
                    "name": "python.exe",
                    "cmdline": f"python _task-worker run {task['task_id']}",
                    "creation_date": "worker-created",
                }
            root_queries["count"] += 1
            if root_queries["count"] == 1:
                return {
                    "query_ok": True,
                    "found": True,
                    "pid": pid,
                    "parent_pid": 42001,
                    "name": "powershell.exe",
                    "cmdline": "powershell.exe -EncodedCommand AAA=",
                    "creation_date": "build-created",
                }
            return {
                "query_ok": True,
                "found": True,
                "pid": pid,
                "parent_pid": 999,
                "name": "unrelated.exe",
                "cmdline": "unrelated.exe",
                "creation_date": "reused-created",
            }

        killed = []

        def fake_kill(pid):
            killed.append(pid)
            return {"ok": True, "pid": pid}

        no_processes = {"killed": [], "remaining": [], "status": "none"}
        with patch(
            "cli_anything.unreal.core.tasks._query_process_info",
            side_effect=fake_process_info,
        ), patch(
            "cli_anything.unreal.utils.ue_backend._kill_process_tree_result",
            side_effect=fake_kill,
        ), patch(
            "cli_anything.unreal.utils.ue_backend.kill_build_processes",
            return_value=no_processes,
        ):
            result = cancel_task(task["task_id"])

        assert killed == [42001]
        assert root_queries["count"] >= 2
        assert result["status"] == "cancelled"
        root_result = next(
            item for item in result["cancel_result"]["processes"]
            if item["role"] == "build"
        )
        assert root_result["ownership_mismatch"] is True

    def test_cancel_task_rechecks_worker_identity_immediately_before_kill(
        self, temp_project, tmp_path, monkeypatch
    ):
        """A worker PID reused after initial discovery must not be killed."""
        from cli_anything.unreal.core.tasks import cancel_task, create_task, save_task

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task(
            "build.compile",
            {"project_path": temp_project["uproject"]},
        )
        task.update({"status": "running", "worker_pid": 42501, "pid": 42502})
        save_task(task)
        worker_queries = {"count": 0}

        def fake_process_info(pid):
            if pid == 42501:
                worker_queries["count"] += 1
                if worker_queries["count"] == 1:
                    return {
                        "query_ok": True,
                        "found": True,
                        "pid": pid,
                        "parent_pid": 1,
                        "name": "python.exe",
                        "cmdline": f"python _task-worker run {task['task_id']}",
                        "creation_date": "worker-created",
                    }
                return {
                    "query_ok": True,
                    "found": True,
                    "pid": pid,
                    "parent_pid": 999,
                    "name": "unrelated.exe",
                    "cmdline": "unrelated.exe",
                    "creation_date": "reused-created",
                }
            return {
                "query_ok": True,
                "found": True,
                "pid": pid,
                "parent_pid": 42501,
                "name": "powershell.exe",
                "cmdline": "powershell.exe -EncodedCommand AAA=",
                "creation_date": "build-created",
            }

        no_processes = {"killed": [], "remaining": [], "status": "none"}
        with patch(
            "cli_anything.unreal.core.tasks._query_process_info",
            side_effect=fake_process_info,
        ), patch(
            "cli_anything.unreal.utils.ue_backend._kill_process_tree_result"
        ) as kill, patch(
            "cli_anything.unreal.utils.ue_backend.kill_build_processes",
            return_value=no_processes,
        ):
            result = cancel_task(task["task_id"])

        kill.assert_not_called()
        assert worker_queries["count"] >= 2
        assert result["status"] == "cancelled"

    def test_cancel_task_drops_failed_pid_that_exited_before_final_check(
        self, temp_project, tmp_path, monkeypatch
    ):
        """A failed first kill is not remaining when the owned PID has exited."""
        from cli_anything.unreal.core.tasks import cancel_task, create_task, save_task

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task(
            "build.compile",
            {"project_path": temp_project["uproject"]},
        )
        task.update({"status": "running", "worker_pid": 43001})
        save_task(task)
        queries = {"count": 0}

        def fake_process_info(pid):
            queries["count"] += 1
            if queries["count"] == 1:
                return {
                    "query_ok": True,
                    "found": True,
                    "pid": pid,
                    "parent_pid": 1,
                    "name": "python.exe",
                    "cmdline": f"python _task-worker run {task['task_id']}",
                    "creation_date": "worker-created",
                }
            return {"query_ok": True, "found": False, "pid": pid}

        no_processes = {"killed": [], "remaining": [], "status": "none"}
        with patch(
            "cli_anything.unreal.core.tasks._query_process_info",
            side_effect=fake_process_info,
        ), patch(
            "cli_anything.unreal.utils.ue_backend._kill_process_tree_result",
            return_value={"ok": False, "pid": 43001, "error": "transient"},
        ), patch(
            "cli_anything.unreal.utils.ue_backend.kill_build_processes",
            return_value=no_processes,
        ):
            result = cancel_task(task["task_id"])

        assert queries["count"] >= 2
        assert result["status"] == "cancelled"
        assert result["cancel_result"]["remaining"] == []

    def test_cancel_task_keeps_pid_when_initial_identity_query_failed(
        self, temp_project, tmp_path, monkeypatch
    ):
        """An incomplete first snapshot cannot prove a live PID was reused."""
        from cli_anything.unreal.core.tasks import cancel_task, create_task, save_task

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task(
            "build.compile",
            {"project_path": temp_project["uproject"]},
        )
        task.update({"status": "running", "worker_pid": 43501})
        save_task(task)
        queries = {"count": 0}

        def fake_process_info(pid):
            queries["count"] += 1
            if queries["count"] == 1:
                return {
                    "query_ok": False,
                    "found": False,
                    "pid": pid,
                    "error": "CIM temporarily unavailable",
                }
            return {
                "query_ok": True,
                "found": True,
                "pid": pid,
                "parent_pid": 1,
                "name": "python.exe",
                "cmdline": f"python _task-worker run {task['task_id']}",
                "creation_date": "worker-created",
            }

        no_processes = {"killed": [], "remaining": [], "status": "none"}
        with patch(
            "cli_anything.unreal.core.tasks._query_process_info",
            side_effect=fake_process_info,
        ), patch(
            "cli_anything.unreal.utils.ue_backend.kill_build_processes",
            return_value=no_processes,
        ):
            result = cancel_task(task["task_id"])

        assert result["status"] == "running"
        assert result["cancelled"] is False
        assert result["cancel_result"]["remaining"] == [43501]

    def test_update_task_fields_preserves_concurrent_metadata(
        self, tmp_path, monkeypatch
    ):
        """Field updates must merge instead of replacing another process's fields."""
        from cli_anything.unreal.core.tasks import (
            create_task,
            load_task,
            update_task_fields,
        )

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task("build.compile", {"project_path": "P.uproject"})

        update_task_fields(task["task_id"], worker_pid=44001)
        update_task_fields(task["task_id"], status="running", started_at=123.0)

        saved = load_task(task["task_id"])
        assert saved["worker_pid"] == 44001
        assert saved["status"] == "running"
        assert saved["started_at"] == 123.0

    def test_finalize_build_task_respects_failed_cancel_state(
        self, tmp_path, monkeypatch
    ):
        """Worker finalization must not overwrite a lock-protected cancel failure."""
        from cli_anything.unreal.core.tasks import (
            _finalize_build_task,
            _request_task_cancel,
            create_task,
            load_task,
            update_task_fields,
        )

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task("build.compile", {"project_path": "P.uproject"})
        _request_task_cancel(task["task_id"])
        update_task_fields(
            task["task_id"],
            status="running",
            cancel_requested=True,
            cancelled=False,
            cancel_result={"killed": [], "remaining": [45001]},
        )

        result = _finalize_build_task(
            task["task_id"],
            {"status": "ok", "log_file": "build.log"},
        )

        saved = load_task(task["task_id"])
        assert result["status"] == "completed"
        assert result["cancelled"] is False
        assert saved["status"] == "completed"
        assert saved["cancel_result"]["remaining"] == [45001]

    def test_run_build_task_forwards_targeted_package_options(
        self, temp_project, tmp_path, monkeypatch
    ):
        """Async package workers must preserve targeted UAT options."""
        from cli_anything.unreal.core.tasks import (
            _run_build_task,
            create_task,
            save_task,
        )

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task(
            "build.package",
            {
                "project_path": temp_project["uproject"],
                "platform": "Android",
                "build_config": "Development",
                "output_dir": "D:/Out",
                "maps": ["/Game/Maps/Oregon_Main"],
                "cook_flavor": "ASTC",
                "uat_args": ["-pak", "-iostore"],
            },
        )
        task["status"] = "running"
        save_task(task)

        with patch(
            "cli_anything.unreal.core.build.package_project",
            return_value={"status": "ok", "log_file": "package.log"},
        ) as mock_package:
            result = _run_build_task(
                task,
                "package_project",
                estimated_total_seconds=1200,
            )

        assert result["status"] == "completed"
        kwargs = mock_package.call_args.kwargs
        assert kwargs["maps"] == ["/Game/Maps/Oregon_Main"]
        assert kwargs["cook_flavor"] == "ASTC"
        assert kwargs["uat_args"] == ["-pak", "-iostore"]

    def test_run_build_task_does_not_overwrite_cancelled_status(
        self, temp_project, tmp_path, monkeypatch
    ):
        """A worker returning after cancellation must not change it to failed."""
        from cli_anything.unreal.core.tasks import (
            _run_build_task,
            create_task,
            load_task,
            save_task,
        )

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task(
            "build.compile",
            {
                "project_path": temp_project["uproject"],
                "build_config": "Development",
                "platform": "Win64",
            },
        )
        task["status"] = "running"
        save_task(task)

        def finish_after_cancel(**kwargs):
            live = load_task(task["task_id"])
            live["status"] = "cancelled"
            live["cancel_requested"] = True
            live["cancelled"] = True
            save_task(live)
            return {"status": "error", "error": "process exited during cancel"}

        with patch(
            "cli_anything.unreal.core.build.compile_project",
            side_effect=finish_after_cancel,
        ):
            result = _run_build_task(
                task,
                "compile_project",
                estimated_total_seconds=600,
            )

        assert result["status"] == "cancelled"
        assert result["cancelled"] is True
        assert "error" not in result


    def test_run_build_task_preserves_cancel_when_build_raises(
        self, temp_project, tmp_path, monkeypatch
    ):
        """A build exception after cancellation must still finish as cancelled."""
        from cli_anything.unreal.core.tasks import (
            _run_build_task,
            create_task,
            load_task,
            save_task,
        )

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task(
            "build.compile",
            {"project_path": temp_project["uproject"]},
        )
        task["status"] = "running"
        save_task(task)

        def raise_after_cancel(**kwargs):
            live = load_task(task["task_id"])
            live["cancel_requested"] = True
            save_task(live)
            raise RuntimeError("build teardown failed")

        with patch(
            "cli_anything.unreal.core.build.compile_project",
            side_effect=raise_after_cancel,
        ):
            result = _run_build_task(
                task,
                "compile_project",
                estimated_total_seconds=600,
            )

        assert result["status"] == "cancelled"
        assert result["cancelled"] is True

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object behavior")
    def test_stop_build_closes_async_worker_job_and_descendants(
        self, temp_project, tmp_path, monkeypatch
    ):
        """Stopping the task worker must release its kill-on-close Job Object."""
        from cli_anything.unreal.core.build import stop_build
        from cli_anything.unreal.core.tasks import create_task, save_task
        from cli_anything.unreal.utils.ue_backend import _kill_process_tree

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task = create_task(
            "build.compile",
            {"project_path": temp_project["uproject"]},
        )
        child_pid_file = tmp_path / "child.pid"
        root_pid_file = tmp_path / "root.pid"
        child_script = tmp_path / "child.py"
        child_script.write_text(
            "import os, pathlib, sys, time\n"
            "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n"
            "time.sleep(60)\n",
            encoding="ascii",
        )
        worker_script = tmp_path / "worker.py"
        worker_script.write_text(
            "import pathlib, sys\n"
            "from cli_anything.unreal.utils.ue_backend import _run_subprocess\n"
            f"def on_start(proc): pathlib.Path({str(root_pid_file)!r}).write_text(str(proc.pid))\n"
            f"_run_subprocess([sys.executable, {str(child_script)!r}, "
            f"{str(child_pid_file)!r}], log_file={str(tmp_path / 'worker.log')!r}, "
            "heartbeat_seconds=0, on_start=on_start)\n",
            encoding="ascii",
        )

        worker = subprocess.Popen(
            [
                sys.executable,
                str(worker_script),
                "_task-worker",
                "run",
                task["task_id"],
            ],
            cwd=str(Path(__file__).resolve().parents[3]),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        child_pid = None
        try:
            deadline = time.time() + 10
            while time.time() < deadline and not (
                child_pid_file.exists() and root_pid_file.exists()
            ):
                time.sleep(0.1)
            assert child_pid_file.exists(), "build child did not start"
            assert root_pid_file.exists(), "build root did not start"
            child_pid = int(child_pid_file.read_text(encoding="ascii"))
            root_pid = int(root_pid_file.read_text(encoding="ascii"))

            task.update({
                "status": "running",
                "worker_pid": worker.pid,
                "pid": root_pid,
            })
            save_task(task)

            result = stop_build(temp_project["uproject"])

            worker.wait(timeout=10)
            assert result["status"] == "ok"
            assert result["remaining"] == []
            assert result["tasks"][0]["status"] == "cancelled"
            probe = subprocess.run(
                ["tasklist", "/FI", f"PID eq {child_pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert f'"{child_pid}"' not in probe.stdout
        finally:
            if worker.poll() is None:
                _kill_process_tree(worker.pid)
            if child_pid is not None:
                _kill_process_tree(child_pid)

    def test_run_uat_returns_resolved_command(self, tmp_path):
        """UAT results should expose the exact argv used for reproduction."""
        from cli_anything.unreal.utils.ue_backend import run_uat

        resolved = [
            r"F:\Engine\Build\BatchFiles\RunUAT.bat",
            "BuildCookRun",
            "-pak",
        ]
        with patch(
            "cli_anything.unreal.utils.ue_backend.find_uat",
            return_value=resolved[0],
        ), patch(
            "cli_anything.unreal.utils.ue_backend._run_subprocess",
            return_value={
                "returncode": 0,
                "log_file": str(tmp_path / "uat.log"),
                "duration_seconds": 1.0,
            },
        ) as mock_run:
            result = run_uat(
                r"F:\Engine",
                "BuildCookRun",
                ["-pak"],
                log_file=str(tmp_path / "uat.log"),
            )

        assert result["command"] == resolved
        assert mock_run.call_args.args[0] == resolved

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
            kwargs = mock_run.call_args.kwargs
            assert kwargs["capture_output"] is True
            assert kwargs["text"] is False

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
             patch("cli_anything.unreal.utils.ue_backend._kill_process_tree", return_value=True) as mock_kill, \
             patch("cli_anything.unreal.utils.ue_backend._attach_kill_on_close_job", return_value=123), \
             patch("cli_anything.unreal.utils.ue_backend._resume_suspended_process", return_value=True, create=True), \
             patch("cli_anything.unreal.utils.ue_backend._release_kill_on_close_job", return_value=True):
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

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object behavior")
    @pytest.mark.parametrize(
        ("returncode", "child_should_run"),
        [(7, False), (0, True)],
    )
    def test_run_subprocess_job_controls_descendants(
        self,
        tmp_path,
        returncode,
        child_should_run,
    ):
        """Failed builds kill descendants; successful builds preserve them."""
        from cli_anything.unreal.utils.ue_backend import (
            _kill_process_tree,
            _run_subprocess,
        )

        child_pid_path = tmp_path / "child.pid"
        parent_script = tmp_path / "spawn_child_then_exit.py"
        parent_script.write_text(
            "import pathlib, subprocess, sys\n"
            "child = subprocess.Popen([sys.executable, '-c', "
            "'import time; time.sleep(60)'])\n"
            f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid))\n"
            f"raise SystemExit({returncode})\n",
            encoding="utf-8",
        )

        result = _run_subprocess(
            [sys.executable, str(parent_script)],
            log_file=str(tmp_path / "failed-build.log"),
            heartbeat_seconds=0,
        )
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))

        def child_is_running():
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
            ]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

            handle = kernel32.OpenProcess(0x00100000, False, child_pid)
            if not handle:
                error = ctypes.get_last_error()
                if error == 87:
                    return False
                raise ctypes.WinError(error)
            try:
                wait_result = kernel32.WaitForSingleObject(handle, 0)
                if wait_result == 258:
                    return True
                if wait_result == 0:
                    return False
                raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel32.CloseHandle(handle)

        try:
            if not child_should_run:
                deadline = time.time() + 3
                while child_is_running() and time.time() < deadline:
                    time.sleep(0.1)
            assert result["returncode"] == returncode
            assert child_is_running() is child_should_run
        finally:
            if child_is_running():
                _kill_process_tree(child_pid)

    def test_run_subprocess_success(self, tmp_path):
        """_run_subprocess returns result dict on success."""
        from cli_anything.unreal.utils.ue_backend import _run_subprocess

        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        log_path = tmp_path / "t.log"
        with patch("subprocess.Popen", return_value=mock_proc), \
             patch("cli_anything.unreal.utils.ue_backend._attach_kill_on_close_job", return_value=123), \
             patch("cli_anything.unreal.utils.ue_backend._resume_suspended_process", return_value=True, create=True), \
             patch("cli_anything.unreal.utils.ue_backend._release_kill_on_close_job", return_value=True):
            result = _run_subprocess(["echo", "hello"], log_file=str(log_path))
            assert result["returncode"] == 0
            assert result["log_file"] == str(log_path)
            assert "duration_seconds" in result
            # Output must not leak back
            assert "stdout" not in result
            assert "stderr" not in result

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows argv safety")
    def test_run_subprocess_rejects_literal_quote_argv(self, tmp_path):
        """The batch wrapper must reject quote-based command injection."""
        from cli_anything.unreal.utils.ue_backend import _run_subprocess

        mock_proc = MagicMock(pid=1234, returncode=0)
        mock_proc.wait.return_value = None
        with patch("subprocess.Popen", return_value=mock_proc) as popen, patch(
            "cli_anything.unreal.utils.ue_backend._attach_kill_on_close_job",
            return_value=123,
        ), patch(
            "cli_anything.unreal.utils.ue_backend._resume_suspended_process",
            return_value=True,
        ), patch(
            "cli_anything.unreal.utils.ue_backend._release_kill_on_close_job",
            return_value=True,
        ):
            result = _run_subprocess(
                ["RunUAT.bat", '-x=" & echo PWNED & rem "'],
                log_file=str(tmp_path / "unsafe.log"),
            )

        assert result["returncode"] == -1
        assert "unsafe" in result["error"].lower()
        popen.assert_not_called()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows console encoding behavior")
    def test_run_subprocess_uses_hidden_utf8_console(self, tmp_path):
        """Detached build workers must give MSVC a UTF-8 console code page."""
        from cli_anything.unreal.utils.ue_backend import _run_subprocess

        mock_proc = MagicMock(pid=1234, returncode=0)
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc) as popen, \
             patch(
                 "cli_anything.unreal.utils.ue_backend._attach_kill_on_close_job",
                 return_value=123,
             ), patch(
                 "cli_anything.unreal.utils.ue_backend._resume_suspended_process",
                 return_value=True,
             ), patch(
                 "cli_anything.unreal.utils.ue_backend._release_kill_on_close_job",
                 return_value=True,
            ):
            result = _run_subprocess(
                [r"F:\Custom Engine\Build.bat", "Target", "Win64", "Development"],
                log_file=str(tmp_path / "utf8-console.log"),
            )

        assert result["returncode"] == 0
        launch_command = popen.call_args.args[0]
        assert isinstance(launch_command, list)
        assert launch_command[0].lower().endswith("powershell.exe")
        assert "-EncodedCommand" in launch_command
        assert popen.call_args.kwargs["shell"] is False
        assert popen.call_args.kwargs["creationflags"] & subprocess.CREATE_NEW_CONSOLE
        startupinfo = popen.call_args.kwargs["startupinfo"]
        assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
        assert startupinfo.wShowWindow == subprocess.SW_HIDE

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows command argument behavior")
    def test_run_subprocess_preserves_cmd_metacharacters(self, tmp_path):
        """Build paths and options must not be reinterpreted by cmd.exe."""
        from cli_anything.unreal.utils.ue_backend import _run_subprocess

        dump_script = tmp_path / "dump_args.py"
        dump_script.write_text(
            "import json, sys\nprint(json.dumps(sys.argv[1:]))\n",
            encoding="ascii",
        )
        batch = tmp_path / "forward_args.bat"
        batch.write_text(
            f'@echo off\n"{sys.executable}" "{dump_script}" %*\n',
            encoding="ascii",
        )
        expected = [
            "a&b",
            "%PATH%",
            "space value",
            "caret^pipe|value",
            "bang!value",
            "paren(value)<redir>",
        ]
        log_path = tmp_path / "forwarded.log"

        result = _run_subprocess(
            [str(batch), *expected],
            log_file=str(log_path),
            heartbeat_seconds=0,
        )

        assert result["returncode"] == 0
        assert json.loads(log_path.read_text(encoding="utf-8").strip()) == expected

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows console encoding behavior")
    def test_run_subprocess_preserves_localized_linker_output_as_utf8(self, tmp_path):
        """A CP936 parent must not corrupt localized MSVC-style child output."""
        import ctypes

        from cli_anything.unreal.utils.ue_backend import _run_subprocess

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        original_code_page = kernel32.GetConsoleOutputCP()
        if not original_code_page:
            pytest.skip("Test process has no Windows console")

        script = tmp_path / "localized_linker_output.py"
        script.write_text(
            "import ctypes, os\n"
            "cp = ctypes.windll.kernel32.GetConsoleOutputCP()\n"
            "encoding = f'cp{cp}' if cp else 'mbcs'\n"
            "line = '\\u6b63\\u5728\\u521b\\u5efa\\u5e93 Engine.lib "
            "\\u548c\\u5bf9\\u8c61 Engine.exp\\n'\n"
            "os.write(1, line.encode(encoding))\n",
            encoding="ascii",
        )
        log_path = tmp_path / "localized-linker.log"

        assert kernel32.SetConsoleOutputCP(936)
        try:
            result = _run_subprocess(
                [sys.executable, str(script)],
                log_file=str(log_path),
                heartbeat_seconds=0,
            )
        finally:
            kernel32.SetConsoleOutputCP(original_code_page)

        assert result["returncode"] == 0
        assert log_path.read_text(encoding="utf-8") == (
            "\u6b63\u5728\u521b\u5efa\u5e93 Engine.lib \u548c\u5bf9\u8c61 Engine.exp\n"
        )
        assert b"\xef\xbf\xbd" not in log_path.read_bytes()

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object behavior")
    def test_run_subprocess_success_disarms_kill_job(self, tmp_path):
        """Successful builds preserve descendants before releasing the Job Object."""
        from cli_anything.unreal.utils.ue_backend import _run_subprocess

        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc) as popen, \
             patch(
                 "cli_anything.unreal.utils.ue_backend._attach_kill_on_close_job",
                 return_value=123,
             ), patch(
                 "cli_anything.unreal.utils.ue_backend._resume_suspended_process",
                 return_value=True,
                 create=True,
             ) as resume_process, patch(
                 "cli_anything.unreal.utils.ue_backend._release_kill_on_close_job",
                 return_value=True,
                 create=True,
             ) as release_job:
            _run_subprocess(
                ["echo", "hello"],
                log_file=str(tmp_path / "success-job.log"),
            )

        creationflags = popen.call_args.kwargs["creationflags"]
        assert creationflags & 0x00000004
        resume_process.assert_called_once_with(1234)
        release_job.assert_called_once_with(123, preserve_processes=True)
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object behavior")
    def test_run_subprocess_fails_closed_when_job_attach_fails(self, tmp_path):
        from cli_anything.unreal.utils.ue_backend import _run_subprocess

        mock_proc = MagicMock(pid=1234, returncode=0)
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc), \
             patch("cli_anything.unreal.utils.ue_backend._attach_kill_on_close_job", return_value=None):
            result = _run_subprocess(
                ["echo", "hello"],
                log_file=str(tmp_path / "attach-failed.log"),
            )

        assert result["returncode"] == -1
        assert "Job Object" in result["error"]
        mock_proc.kill.assert_called_once()
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object behavior")
    def test_run_subprocess_fails_closed_when_resume_fails(self, tmp_path):
        from cli_anything.unreal.utils.ue_backend import _run_subprocess

        mock_proc = MagicMock(pid=1234, returncode=None)
        mock_proc.wait.return_value = None
        on_start = MagicMock()

        with patch("subprocess.Popen", return_value=mock_proc), \
             patch("cli_anything.unreal.utils.ue_backend._attach_kill_on_close_job", return_value=123), \
             patch("cli_anything.unreal.utils.ue_backend._resume_suspended_process", return_value=False), \
             patch("cli_anything.unreal.utils.ue_backend._release_kill_on_close_job", return_value=True) as release_job:
            result = _run_subprocess(
                ["echo", "hello"],
                log_file=str(tmp_path / "resume-failed.log"),
                on_start=on_start,
            )

        assert result["returncode"] == -1
        assert "resume build process" in result["error"]
        release_job.assert_called_once_with(123, preserve_processes=False)
        mock_proc.kill.assert_not_called()
        mock_proc.wait.assert_called_once()
        on_start.assert_not_called()
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object behavior")
    def test_run_subprocess_reports_disarm_failure(self, tmp_path):
        from cli_anything.unreal.utils.ue_backend import _run_subprocess

        mock_proc = MagicMock(pid=1234, returncode=0)
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc), \
             patch("cli_anything.unreal.utils.ue_backend._attach_kill_on_close_job", return_value=123), \
             patch("cli_anything.unreal.utils.ue_backend._resume_suspended_process", return_value=True, create=True), \
             patch("cli_anything.unreal.utils.ue_backend._release_kill_on_close_job", return_value=False):
            result = _run_subprocess(
                ["echo", "hello"],
                log_file=str(tmp_path / "disarm-failed.log"),
            )

        assert result["returncode"] == -1
        assert "release build Job Object" in result["error"]

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
        assert "--project" in result.output
        assert "--no-wait" in result.output
        assert "--timeout" in result.output
        assert "--log-tail-lines" not in result.output

    def test_build_compile_accepts_command_project_option(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        captured = {}

        def fake_submit_task(command, payload):
            captured["command"] = command
            captured["payload"] = payload
            return {"task_id": "compile-task"}

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.build.submit_task", side_effect=fake_submit_task):
            result = runner.invoke(cli, [
                "--output", "json",
                "build", "compile",
                "--project", temp_project["uproject"],
                "--platform", "Android",
                "--config", "Development",
                "--no-wait",
            ])

        assert result.exit_code == 0, result.output
        data = self._parse_json_output(result.output)
        assert data["status"] == "success"
        assert data["result"]["task_id"] == "compile-task"
        assert captured["command"] == "build.compile"
        assert captured["payload"]["project_path"] == temp_project["uproject"]
        assert captured["payload"]["platform"] == "Android"
        assert captured["payload"]["build_config"] == "Development"

    def test_build_compile_blocks_when_matching_editor_online(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_api = MagicMock()
        mock_api.is_alive.return_value = True

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.build.sys.platform", "win32"), \
             patch("cli_anything.unreal.commands.build.find_running_editors", return_value=[
                 {"pid": 777, "project": temp_project["uproject"]},
             ]), \
             patch("cli_anything.unreal.commands.build.UEEditorAPI", return_value=mock_api), \
             patch("cli_anything.unreal.commands.build.submit_task") as mock_submit:
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "build", "compile",
                "--platform", "Win64",
                "--config", "Development",
                "--no-wait",
            ])

        assert result.exit_code == 3
        data = self._parse_json_output(result.output)
        assert data["code"] == "EDITOR_RUNNING_LOCKS_DLLS"
        assert data["details"]["online"] is True
        assert data["details"]["running_editors"][0]["pid"] == 777
        assert "editor close" in data["suggestion"]
        mock_submit.assert_not_called()

    def test_build_compile_allows_other_project_editor(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_api = MagicMock()
        mock_api.is_alive.return_value = True

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.build.sys.platform", "win32"), \
             patch("cli_anything.unreal.commands.build.find_running_editors", return_value=[
                 {"pid": 777, "project": "F:/Other/Other.uproject"},
             ]), \
             patch("cli_anything.unreal.commands.build.UEEditorAPI", return_value=mock_api), \
             patch("cli_anything.unreal.commands.build.submit_task", return_value={"task_id": "compile-task"}):
            result = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "build", "compile",
                "--platform", "Win64",
                "--config", "Development",
                "--no-wait",
            ])

        assert result.exit_code == 0, result.output
        data = self._parse_json_output(result.output)
        assert data["status"] == "success"
        assert data["result"]["task_id"] == "compile-task"

    def test_build_wait_streams_log_file_to_stderr(self, tmp_path, capsys):
        from cli_anything.unreal.commands.build import _wait_for_task_with_log_stream

        log_file = tmp_path / "compile.log"
        log_file.write_text("first\n", encoding="utf-8")
        calls = {"count": 0}

        def fake_load_task(task_id):
            assert task_id == "t-log"
            calls["count"] += 1
            with log_file.open("a", encoding="utf-8") as fh:
                fh.write("second\n" if calls["count"] == 1 else "third\n")
            status = "running" if calls["count"] == 1 else "completed"
            return {"task_id": task_id, "command": "build.compile", "status": status}

        with patch("cli_anything.unreal.commands.build.load_task", side_effect=fake_load_task):
            task = _wait_for_task_with_log_stream("t-log", timeout=5, log_file=str(log_file))

        assert task["status"] == "completed"
        assert capsys.readouterr().err.replace("\r\n", "\n") == "first\nsecond\nthird\n"

    def test_build_cook_has_no_wait_and_timeout(self, temp_project):
        """build cook now has --no-wait and --timeout options."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["build", "cook", "--help"])
        assert result.exit_code == 0
        assert "--project" in result.output
        assert "--no-wait" in result.output
        assert "--timeout" in result.output
        assert "--log-tail-lines" not in result.output

    def test_build_package_targeted_options_reach_task_payload(
        self, temp_project
    ):
        """Package CLI should preserve reproducibility options for the worker."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        captured = {}

        def fake_submit(command, payload):
            captured["command"] = command
            captured["payload"] = payload
            return {"task_id": "t-targeted-package"}

        with patch(
            "cli_anything.unreal.commands.build.submit_task",
            side_effect=fake_submit,
        ):
            result = CliRunner().invoke(cli, [
                "--output", "json",
                "--project", temp_project["uproject"],
                "build", "package",
                "--platform", "Android",
                "--map", "/Game/Maps/Oregon_Main",
                "--map", "/Game/Maps/Oregon_Sub",
                "--cook-flavor", "ASTC",
                "--uat-arg=-pak",
                "--uat-arg=-iostore",
                "--uat-arg=-ini:Engine:[Section]:Key=Value",
                "--no-wait",
            ])

        assert result.exit_code == 0, result.output
        assert captured["command"] == "build.package"
        assert captured["payload"]["maps"] == (
            "/Game/Maps/Oregon_Main",
            "/Game/Maps/Oregon_Sub",
        )
        assert captured["payload"]["cook_flavor"] == "ASTC"
        assert captured["payload"]["uat_args"] == (
            "-pak",
            "-iostore",
            "-ini:Engine:[Section]:Key=Value",
        )

    @pytest.mark.parametrize(
        ("option", "value"),
        [
            ("--uat-arg", '-x=" & echo PWNED & rem "'),
            ("--map", '/Game/Maps/Oregon" & echo PWNED & rem "'),
            ("--cook-flavor", 'ASTC" & echo PWNED & rem "'),
        ],
        ids=["uat_arg", "map", "cook_flavor"],
    )
    def test_build_package_rejects_unsafe_freeform_values(
        self, temp_project, option, value
    ):
        """All free-form package values must reject command-shell injection."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        with patch(
            "cli_anything.unreal.commands.build.submit_task",
            return_value={"task_id": "must-not-submit"},
        ) as submit:
            result = CliRunner().invoke(cli, [
                "--project", temp_project["uproject"],
                "build", "package",
                option, value,
                "--no-wait",
            ])

        assert result.exit_code == 2
        assert "unsafe" in result.output.lower()
        submit.assert_not_called()

    def test_build_package_rejects_non_option_uat_arg(self, temp_project):
        """Additional UAT argv must be explicit option-style values."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        result = CliRunner().invoke(cli, [
            "--project", temp_project["uproject"],
            "build", "package",
            "--uat-arg", "pak",
            "--no-wait",
        ])

        assert result.exit_code == 2
        assert "must start with '-'" in result.output

    def test_build_package_has_no_wait_and_timeout(self, temp_project):
        """build package now has --no-wait and --timeout options."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["build", "package", "--help"])
        assert result.exit_code == 0
        assert "--project" in result.output
        assert "--no-wait" in result.output
        assert "--timeout" in result.output
        assert "--map" in result.output
        assert "--cook-flavor" in result.output
        assert "--uat-arg" in result.output
        assert "--log-tail-lines" not in result.output

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

    def test_build_compile_no_wait_then_stop_cancels_task(
        self, temp_project, tmp_path, monkeypatch
    ):
        """The documented async compile/stop sequence must cancel its task."""
        from click.testing import CliRunner

        from cli_anything.unreal.core.tasks import create_task, save_task
        from cli_anything.unreal.unreal_cli import cli

        monkeypatch.setenv("UE_CLI_TASK_DIR", str(tmp_path / "tasks"))
        task_holder = {}
        killed = []

        def fake_submit(command, payload):
            task = create_task(command, payload)
            task.update({"status": "running", "worker_pid": 41001, "pid": 41002})
            task_holder["task"] = task
            return save_task(task)

        def fake_kill(pid):
            killed.append(pid)
            return {
                "ok": True,
                "pid": pid,
                "already_exited": pid == 41002,
            }

        def fake_process_info(pid):
            task_id = task_holder["task"]["task_id"]
            return {
                "query_ok": True,
                "found": True,
                "pid": pid,
                "parent_pid": 1 if pid == 41001 else 41001,
                "name": "python.exe" if pid == 41001 else "powershell.exe",
                "cmdline": (
                    f"python -m cli_anything.unreal _task-worker run {task_id}"
                    if pid == 41001 else "powershell.exe -EncodedCommand AAA="
                ),
            }

        no_processes = {"killed": [], "remaining": [], "status": "none"}
        runner = CliRunner()
        with patch(
            "cli_anything.unreal.commands.build._guard_compile_against_editor_locks"
        ), patch(
            "cli_anything.unreal.commands.build.submit_task",
            side_effect=fake_submit,
        ), patch(
            "cli_anything.unreal.core.build.kill_build_processes",
            return_value=no_processes,
        ), patch(
            "cli_anything.unreal.utils.ue_backend.kill_build_processes",
            return_value=no_processes,
        ), patch(
            "cli_anything.unreal.core.tasks._query_process_info",
            side_effect=fake_process_info,
        ), patch(
            "cli_anything.unreal.utils.ue_backend._kill_process_tree_result",
            side_effect=fake_kill,
        ):
            submitted = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "build", "compile", "--no-wait",
            ])
            stopped = runner.invoke(cli, [
                "--output", "json", "--project", temp_project["uproject"],
                "build", "stop",
            ])

        assert submitted.exit_code == 0
        task_id = self._parse_json_output(submitted.output)["result"]["task_id"]
        assert stopped.exit_code == 0
        result = self._parse_json_output(stopped.output)["result"]
        assert result["status"] == "ok"
        assert result["remaining"] == []
        assert result["tasks"][0]["task_id"] == task_id
        assert result["tasks"][0]["status"] == "cancelled"
        assert killed == [41001, 41002]

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
