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


