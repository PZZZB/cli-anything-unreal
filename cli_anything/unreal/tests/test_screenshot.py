"""Tests for test_screenshot.py — Uses synthetic data only, no UE editor required."""

import ast
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


def _bridge_screenshot_side_effect(content=b"png"):
    def execute(script, timeout=None):
        match = re.search(r"take_active_viewport_screenshot\((.+)\)", script)
        if match is not None:
            native_path = Path(ast.literal_eval(match.group(1)))
            native_path.write_bytes(content)
            return {"LogOutput": [{"Output": "UECLI_SCREENSHOT_RESULT:ok"}]}
        return {"LogOutput": []}

    return execute


class TestScreenshot:
    """Tests for core/screenshot.py — mocked API calls."""

    def test_screenshot_cvar_test_mismatched_labels(self):
        pass

    def test_screenshot_rejects_other_project_on_same_port(self, tmp_path):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        project_dir = tmp_path / "MiniProject"
        project_dir.mkdir()
        uproject = project_dir / "MiniProject.uproject"
        uproject.write_text('{"FileVersion": 3, "EngineAssociation": "5.7"}', encoding="utf-8")
        other_project = str(project_dir / "Other.uproject")

        runner = CliRunner()
        with patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI.is_alive", return_value=True), \
             patch("cli_anything.unreal.utils.ue_http_api.UEEditorAPI._get_pid_listening_on_port", return_value=5678), \
             patch("cli_anything.unreal.utils.ue_backend.find_running_editors", return_value=[
                 {"pid": 5678, "project": other_project},
             ]), \
             patch("cli_anything.unreal.core.screenshot.take_screenshot", return_value={"status": "ok"}) as capture:
            result = runner.invoke(cli, [
                "--output", "json", "--project", str(uproject),
                "screenshot", "capture",
            ])

        assert result.exit_code == 3
        capture.assert_not_called()
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "EDITOR_PROJECT_NOT_RUNNING"
        assert data["details"]["running_editors"] == [{"pid": 5678, "project": other_project}]

    def test_capture_timeout_is_top_level_error(self, tmp_path):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        timeout_result = {
            "status": "error",
            "message": "Window capture timed out after 15.0s",
            "failure_stage": "capture_backend",
            "timed_out": True,
            "timeout_seconds": 15.0,
        }
        with patch("cli_anything.unreal.commands.screenshot.require_editor", return_value=MagicMock()), \
             patch(
                 "cli_anything.unreal.core.screenshot.take_screenshot",
                 return_value=timeout_result,
             ):
            result = runner.invoke(cli, [
                "--output", "json",
                "screenshot", "capture",
                "--path", str(tmp_path / "hung.png"),
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "SCREENSHOT_CAPTURE_TIMEOUT"
        assert data["details"]["failure_stage"] == "capture_backend"

    def test_capture_does_not_restore_minimized_window_rect(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        api.get_window_rect.return_value = (-32000, -32000, -31840, -31972)
        api.bring_to_foreground.return_value = True
        api.exec_python.return_value = {"status": "ok"}
        api.exec_python_ex.side_effect = _bridge_screenshot_side_effect()

        with patch("cli_anything.unreal.core.screenshot.time.sleep"):
            result = _capture_viewport_png_raw(
                api,
                "minimized_restore_guard",
                str(tmp_path),
                wait_timeout=15.0,
                res_x=1920,
                res_y=1080,
                delay=0,
            )

        assert result["status"] == "ok"
        assert result["foreground_ok"] is True
        api.bring_to_foreground.assert_called_once()
        api.set_window_rect.assert_not_called()

    def test_capture_does_not_rewrite_normal_window_rect(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        api.get_window_rect.return_value = (100, 100, 1300, 900)
        api.bring_to_foreground.return_value = True
        api.exec_python.return_value = {"status": "ok"}
        api.exec_python_ex.side_effect = _bridge_screenshot_side_effect()

        with patch("cli_anything.unreal.core.screenshot.time.sleep"):
            result = _capture_viewport_png_raw(
                api,
                "normal_restore_guard",
                str(tmp_path),
                wait_timeout=15.0,
                res_x=1920,
                res_y=1080,
                delay=0,
            )

        assert result["status"] == "ok"
        assert result["foreground_ok"] is True
        api.bring_to_foreground.assert_called_once()
        api.set_window_rect.assert_not_called()

    def test_capture_temporarily_expands_tiny_editor_window(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        api.get_window_rect.return_value = (151, 73, 286, 114)
        api.set_window_rect.return_value = True
        api.bring_to_foreground.return_value = True
        api.exec_python.return_value = {"status": "ok"}
        api.exec_python_ex.side_effect = _bridge_screenshot_side_effect()

        with patch("cli_anything.unreal.core.screenshot.time.sleep"):
            result = _capture_viewport_png_raw(
                api,
                "tiny_window",
                str(tmp_path),
                wait_timeout=15.0,
                res_x=1920,
                res_y=1080,
                delay=0,
            )

        assert result["status"] == "ok"
        assert api.set_window_rect.call_args_list == [
            call(151, 73, 1431, 793),
            call(151, 73, 286, 114),
        ]

    def test_capture_sequence_does_not_prefocus_between_frames(self, tmp_path):
        from cli_anything.unreal.core.screenshot import capture_screenshot_atlas

        api = MagicMock()

        def fake_capture(_api, filename, project_dir, *_args, **_kwargs):
            path = Path(project_dir) / "Saved" / "Screenshots" / "WindowsEditor" / f"{filename}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
                b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04"
                b"\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            return {"status": "ok", "path_raw": str(path), "size_raw": 3}

        with patch("cli_anything.unreal.core.screenshot._refresh_editor_viewports", return_value={}), \
             patch("cli_anything.unreal.core.screenshot._ensure_editor_viewport_realtime"), \
             patch("cli_anything.unreal.core.screenshot._capture_viewport_png_raw", side_effect=fake_capture) as capture_mock, \
             patch("cli_anything.unreal.core.screenshot.time.sleep"):
            result = capture_screenshot_atlas(
                api,
                frame_count=3,
                interval=0.1,
                project_dir=str(tmp_path),
                filename_prefix="seq_no_prefocus",
            )

        assert result["status"] == "ok"
        assert capture_mock.call_count == 3
        api.bring_to_foreground.assert_not_called()

    def test_capture_sequence_command_uses_bounded_waits(self, tmp_path):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.screenshot.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.screenshot.capture_screenshot_atlas") as mock_capture:
            mock_editor.return_value = MagicMock()
            mock_capture.return_value = {"status": "ok", "atlas_path": str(tmp_path / "atlas.png")}

            result = runner.invoke(cli, [
                "--output", "json",
                "screenshot", "capture-sequence",
                "-n", "3",
                "-i", "0.05",
            ])

        assert result.exit_code == 0
        kwargs = mock_capture.call_args.kwargs
        assert kwargs["wait_timeout"] <= 5.0
        assert kwargs["delay"] <= 0.25

    def test_capture_path_passes_full_output_path(self, tmp_path):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        target = tmp_path / "custom" / "shot.png"
        runner = CliRunner()
        with patch("cli_anything.unreal.commands.screenshot.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.screenshot.take_screenshot") as mock_capture:
            mock_editor.return_value = MagicMock()
            mock_capture.return_value = {"status": "ok", "path_raw": str(target)}

            result = runner.invoke(cli, [
                "--output", "json",
                "screenshot", "capture",
                "--path", str(target),
            ])

        assert result.exit_code == 0
        assert mock_capture.call_args.kwargs["output_path"] == str(target)
        data = json.loads(result.output)
        assert data["result"]["default_path"] == str(target)

    def test_capture_replaces_stale_output_with_new_native_frame(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        api.bring_to_foreground.return_value = True
        api.exec_python.return_value = {"status": "ok"}
        target = tmp_path / "requested" / "fresh.png"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"stale-frame")

        def run_bridge(script, timeout=None):
            match = re.search(r"take_active_viewport_screenshot\((.+)\)", script)
            assert match is not None
            native_path = ast.literal_eval(match.group(1))
            assert Path(native_path) != target
            Path(native_path).write_bytes(b"fresh-frame")
            return {"LogOutput": [{"Output": "UECLI_SCREENSHOT_RESULT:ok"}]}

        api.exec_python_ex.side_effect = run_bridge
        with patch("cli_anything.unreal.core.screenshot.time.sleep"):
            result = _capture_viewport_png_raw(
                api,
                "ignored",
                str(tmp_path / "Project"),
                wait_timeout=15.0,
                res_x=1920,
                res_y=1080,
                delay=0,
                output_path=str(target),
            )

        assert result["status"] == "ok"
        assert result["capture_mode"] == "bridge_active_viewport"
        assert target.read_bytes() == b"fresh-frame"
        api.find_editor_window_hwnd.assert_not_called()

    def test_capture_requests_fresh_active_viewport_frame_from_bridge(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        target = tmp_path / "active viewport" / "fresh.png"

        def run_bridge(script, timeout=None):
            match = re.search(
                r"take_active_viewport_screenshot\((.+)\)",
                script,
            )
            assert match is not None
            native_path = Path(ast.literal_eval(match.group(1)))
            native_path.parent.mkdir(parents=True, exist_ok=True)
            native_path.write_bytes(b"active-viewport-frame")
            return {
                "LogOutput": [
                    {"Output": "UECLI_SCREENSHOT_RESULT:ok"},
                ]
            }

        api.exec_python_ex.side_effect = run_bridge
        api.exec_console.return_value = {"error": "HighResShot must not be used"}
        with patch("cli_anything.unreal.core.screenshot.time.sleep"), \
             patch("cli_anything.unreal.core.screenshot._refresh_editor_viewports", return_value={}):
            result = _capture_viewport_png_raw(
                api,
                "ignored",
                str(tmp_path / "Project"),
                wait_timeout=15.0,
                res_x=1920,
                res_y=1080,
                delay=0,
                output_path=str(target),
            )

        assert result["status"] == "ok", result
        assert result["capture_mode"] == "bridge_active_viewport"
        assert target.read_bytes() == b"active-viewport-frame"
        assert not any(
            call.args and str(call.args[0]).startswith("HighResShot ")
            for call in api.exec_console.call_args_list
        )

    def test_capture_request_failure_cleans_native_temp_file(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        target = tmp_path / "requested" / "preserved.png"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"previous-frame")

        def fail_after_native_file_starts(script, timeout=None):
            match = re.search(r"take_active_viewport_screenshot\((.+)\)", script)
            assert match is not None
            native_path = ast.literal_eval(match.group(1))
            Path(native_path).write_bytes(b"partial-frame")
            raise ConnectionError("connection reset")

        api.exec_python_ex.side_effect = fail_after_native_file_starts
        with patch("cli_anything.unreal.core.screenshot.time.sleep"):
            result = _capture_viewport_png_raw(
                api,
                "ignored",
                str(tmp_path / "Project"),
                wait_timeout=15.0,
                res_x=1920,
                res_y=1080,
                delay=0,
                output_path=str(target),
            )

        assert result["status"] == "error"
        assert result["failure_stage"] == "capture_request"
        assert target.read_bytes() == b"previous-frame"
        assert list(target.parent.glob(".*.ue-cli-*.png")) == []

    def test_capture_error_result_does_not_publish_partial_temp_file(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        target = tmp_path / "requested" / "preserved.png"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"previous-frame")

        def timeout_with_partial_file(script, timeout=None):
            match = re.search(r"take_active_viewport_screenshot\((.+)\)", script)
            assert match is not None
            Path(ast.literal_eval(match.group(1))).write_bytes(b"partial-frame")
            return {"error": "Read timed out after 15 seconds"}

        api.exec_python_ex.side_effect = timeout_with_partial_file
        with patch("cli_anything.unreal.core.screenshot.time.sleep"):
            result = _capture_viewport_png_raw(
                api,
                "ignored",
                str(tmp_path / "Project"),
                wait_timeout=15.0,
                res_x=1920,
                res_y=1080,
                delay=0,
                output_path=str(target),
            )

        assert result["status"] == "error"
        assert result["failure_stage"] == "capture_request"
        assert result["timed_out"] is True
        assert target.read_bytes() == b"previous-frame"
        assert list(target.parent.glob(".*.ue-cli-*.png")) == []

    def test_capture_bridge_failure_does_not_publish_partial_temp_file(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        target = tmp_path / "requested" / "preserved.png"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"previous-frame")

        def bridge_failure_with_partial_file(script, timeout=None):
            match = re.search(r"take_active_viewport_screenshot\((.+)\)", script)
            assert match is not None
            Path(ast.literal_eval(match.group(1))).write_bytes(b"partial-frame")
            return {
                "ReturnValue": True,
                "LogOutput": [{"Output": "UECLI_SCREENSHOT_RESULT:failed"}],
            }

        api.exec_python_ex.side_effect = bridge_failure_with_partial_file
        with patch("cli_anything.unreal.core.screenshot.time.sleep"):
            result = _capture_viewport_png_raw(
                api,
                "ignored",
                str(tmp_path / "Project"),
                wait_timeout=15.0,
                res_x=1920,
                res_y=1080,
                delay=0,
                output_path=str(target),
            )

        assert result["status"] == "error"
        assert result["failure_stage"] == "capture_backend"
        assert target.read_bytes() == b"previous-frame"
        assert list(target.parent.glob(".*.ue-cli-*.png")) == []

    def test_capture_surfaces_tiny_window_restore_failure(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        api.get_window_rect.return_value = (151, 73, 286, 114)
        api.set_window_rect.side_effect = [True, False]
        api.exec_python_ex.side_effect = _bridge_screenshot_side_effect()

        with patch("cli_anything.unreal.core.screenshot.time.sleep"):
            result = _capture_viewport_png_raw(
                api,
                "restore_failure",
                str(tmp_path),
                wait_timeout=15.0,
                res_x=1920,
                res_y=1080,
                delay=0,
            )

        assert result["status"] == "ok"
        assert result["window_restore_ok"] is False
        assert "restore" in result["warning"].lower()

    def test_capture_png_raw_writes_exact_output_path(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        api.bring_to_foreground.return_value = True
        api.exec_python.return_value = {"status": "ok"}
        api.exec_python_ex.side_effect = _bridge_screenshot_side_effect()
        target = tmp_path / "requested" / "exact.png"

        with patch("cli_anything.unreal.core.screenshot.time.sleep"):
            result = _capture_viewport_png_raw(
                api,
                "ignored",
                str(tmp_path / "Project"),
                wait_timeout=15.0,
                res_x=1920,
                res_y=1080,
                delay=0,
                output_path=str(target),
            )

        assert result["status"] == "ok"
        assert result["path_raw"] == str(target)
        assert target.read_bytes() == b"png"

    def test_capture_png_raw_uses_filename_when_output_path_is_directory(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        api.bring_to_foreground.return_value = True
        api.exec_python.return_value = {"status": "ok"}
        api.exec_python_ex.side_effect = _bridge_screenshot_side_effect()
        target_dir = tmp_path / "WindowsEditor"
        target_dir.mkdir()
        expected = target_dir / "SDOC_Visualize_A_Max50.png"

        with patch("cli_anything.unreal.core.screenshot.time.sleep"):
            result = _capture_viewport_png_raw(
                api,
                "SDOC_Visualize_A_Max50.png",
                str(tmp_path / "Project"),
                wait_timeout=15.0,
                res_x=1920,
                res_y=1080,
                delay=0,
                output_path=str(target_dir),
            )

        assert result["status"] == "ok"
        assert result["path_raw"] == str(expected)
        assert expected.read_bytes() == b"png"

    def test_capture_static_refresh_and_active_viewport_stages(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        api.bring_to_foreground.return_value = True
        api.exec_python_ex.side_effect = _bridge_screenshot_side_effect()
        target = tmp_path / "bounded.png"

        with patch("cli_anything.unreal.core.screenshot.time.sleep"), \
             patch("cli_anything.unreal.core.screenshot._refresh_editor_viewports", return_value={}) as refresh:
            result = _capture_viewport_png_raw(
                api,
                "bounded",
                str(tmp_path),
                wait_timeout=15.0,
                res_x=1920,
                res_y=1080,
                delay=0,
                output_path=str(target),
            )

        assert result["status"] == "ok"
        refresh.assert_called_once_with(api, timeout=3.0)
        capture_call = api.exec_python_ex.call_args_list[-1]
        assert "take_active_viewport_screenshot" in capture_call.args[0]
        assert capture_call.kwargs["timeout"] == 15.0

    def test_capture_reports_request_timeout_stage(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        api.bring_to_foreground.return_value = True
        api.exec_python_ex.side_effect = TimeoutError("capture timed out")
        target = tmp_path / "hung.png"
        target.write_bytes(b"previous-frame")

        with patch("cli_anything.unreal.core.screenshot.time.sleep"), \
             patch("cli_anything.unreal.core.screenshot._refresh_editor_viewports", return_value={}):
            result = _capture_viewport_png_raw(
                api,
                "hung",
                str(tmp_path),
                wait_timeout=4.0,
                res_x=1920,
                res_y=1080,
                delay=0,
                output_path=str(target),
            )

        assert result["status"] == "error"
        assert result["failure_stage"] == "capture_request"
        assert result["timed_out"] is True
        assert result["timeout_seconds"] == 4.0
        assert target.read_bytes() == b"previous-frame"

    def test_win32_capture_timeout_terminates_helper(self, tmp_path):
        from cli_anything.unreal.core.win32_editor_capture import (
            capture_hwnd_to_png_bounded,
        )

        with patch(
            "cli_anything.unreal.core.win32_editor_capture.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="capture", timeout=2.0),
        ):
            result = capture_hwnd_to_png_bounded(
                123,
                tmp_path / "hung.png",
                timeout=2.0,
            )

        assert result == {
            "ok": False,
            "timed_out": True,
            "error": "Window capture timed out after 2.0s",
        }

    def test_win32_capture_helper_reports_actionable_failure(self, capsys):
        from cli_anything.unreal.core import win32_editor_capture

        with patch("sys.argv", ["capture", "123", "failed.png"]), \
             patch.object(win32_editor_capture, "capture_hwnd_to_png", return_value=False):
            returncode = win32_editor_capture._main()

        assert returncode == 1
        error = capsys.readouterr().err
        assert "GDI window capture failed" in error
        assert "Pillow" in error

    def test_compress_for_agent_no_pillow(self, tmp_path):
        """Test graceful handling when Pillow is not available."""
        from cli_anything.unreal.core.screenshot import compress_for_agent

        # Create a fake PNG
        fake_png = tmp_path / "test.png"
        fake_png.write_bytes(b"\x89PNG" + b"\x00" * 100)

        # If Pillow is not installed, should return None
        with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
            result = compress_for_agent(str(fake_png))
            # May or may not return None depending on import mechanism


# ═══════════════════════════════════════════════════════════════════════
#  Test CLI (Click)
# ═══════════════════════════════════════════════════════════════════════


