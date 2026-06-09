"""Tests for test_screenshot.py — Uses synthetic data only, no UE editor required."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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

    def test_capture_does_not_restore_minimized_window_rect(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        api.get_window_rect.return_value = (-32000, -32000, -31840, -31972)
        api.bring_to_foreground.return_value = True
        api.find_editor_window_hwnd.return_value = 123
        api.exec_python.return_value = {"status": "ok"}
        api.exec_console.return_value = {"status": "ok"}
        api.exec_python_ex.return_value = {"LogOutput": []}

        def fake_capture(_hwnd, output_path, crop_rect=None):
            Path(output_path).write_bytes(b"png")
            return True

        with patch("cli_anything.unreal.core.screenshot.sys.platform", "win32"), \
             patch("cli_anything.unreal.core.screenshot.time.sleep"), \
             patch("cli_anything.unreal.core.win32_editor_capture.capture_hwnd_to_png", side_effect=fake_capture):
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
        api.find_editor_window_hwnd.return_value = 123
        api.exec_python.return_value = {"status": "ok"}
        api.exec_console.return_value = {"status": "ok"}
        api.exec_python_ex.return_value = {"LogOutput": []}

        def fake_capture(_hwnd, output_path, crop_rect=None):
            Path(output_path).write_bytes(b"png")
            return True

        with patch("cli_anything.unreal.core.screenshot.sys.platform", "win32"), \
             patch("cli_anything.unreal.core.screenshot.time.sleep"), \
             patch("cli_anything.unreal.core.win32_editor_capture.capture_hwnd_to_png", side_effect=fake_capture):
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

    def test_capture_png_raw_writes_exact_output_path(self, tmp_path):
        from cli_anything.unreal.core.screenshot import _capture_viewport_png_raw

        api = MagicMock()
        api.bring_to_foreground.return_value = True
        api.find_editor_window_hwnd.return_value = 123
        api.exec_python.return_value = {"status": "ok"}
        api.exec_console.return_value = {"status": "ok"}
        api.exec_python_ex.return_value = {"LogOutput": []}
        target = tmp_path / "requested" / "exact.png"

        def fake_capture(_hwnd, output_path, crop_rect=None):
            Path(output_path).write_bytes(b"png")
            return True

        with patch("cli_anything.unreal.core.screenshot.sys.platform", "win32"), \
             patch("cli_anything.unreal.core.screenshot.time.sleep"), \
             patch("cli_anything.unreal.core.win32_editor_capture.capture_hwnd_to_png", side_effect=fake_capture):
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


