"""Tests for test_plugin_bridge.py — Uses synthetic data only, no UE editor required."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestPluginBridge:
    """Tests for core/plugin_bridge.py — deploy and detect logic."""

    def test_ensure_plugin_deployed_fresh_install(self, tmp_path):
        """First deploy copies plugin source to project Plugins/."""
        from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed

        project_dir = str(tmp_path)
        result = ensure_plugin_deployed(project_dir)

        assert result["deployed"] is True
        assert result["action"] == "fresh_install"
        assert result["version"] == "1.9"

        plugin_dir = tmp_path / "Plugins" / "CliAnythingBridge"
        assert (plugin_dir / "CliAnythingBridge.uplugin").exists()
        assert (plugin_dir / "Source" / "CliAnythingBridge" / "CliAnythingBridge.Build.cs").exists()
        assert (plugin_dir / "Source" / "CliAnythingBridge" / "Public" / "CliAnythingBridgeLibrary.h").exists()
        assert (plugin_dir / "Source" / "CliAnythingBridge" / "Private" / "CliAnythingBridgeLibrary.cpp").exists()
        assert (plugin_dir / "Source" / "CliAnythingBridge" / "Private" / "CliAnythingBridgeModule.cpp").exists()

    def test_ensure_plugin_deployed_already_up_to_date(self, tmp_path):
        """Second deploy is a no-op when versions match."""
        from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed

        project_dir = str(tmp_path)
        ensure_plugin_deployed(project_dir)  # first install
        result = ensure_plugin_deployed(project_dir)  # second call

        assert result["deployed"] is True
        assert result["action"] == "already_up_to_date"

    def test_ensure_plugin_deployed_version_update(self, tmp_path):
        """Plugin is updated when bundled version is newer."""
        from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed

        project_dir = str(tmp_path)
        ensure_plugin_deployed(project_dir)

        # Tamper with the deployed version to simulate an old install
        uplugin = tmp_path / "Plugins" / "CliAnythingBridge" / "CliAnythingBridge.uplugin"
        data = json.loads(uplugin.read_text())
        data["VersionName"] = "0.1"
        uplugin.write_text(json.dumps(data))

        result = ensure_plugin_deployed(project_dir)
        assert result["deployed"] is True
        assert "updated" in result["action"]
        assert result["version"] == "1.9"

    def test_is_plugin_loaded_true(self):
        """is_plugin_loaded returns True when probe script succeeds."""
        from cli_anything.unreal.core.plugin_bridge import is_plugin_loaded

        mock_api = MagicMock()
        with patch("cli_anything.unreal.core.plugin_bridge.run_python_code") as mock_run:
            mock_run.return_value = {"loaded": True}
            assert is_plugin_loaded(mock_api) is True

    def test_is_plugin_loaded_false(self):
        """is_plugin_loaded returns False when plugin class not found."""
        from cli_anything.unreal.core.plugin_bridge import is_plugin_loaded

        mock_api = MagicMock()
        with patch("cli_anything.unreal.core.plugin_bridge.run_python_code") as mock_run:
            mock_run.return_value = {"loaded": False}
            assert is_plugin_loaded(mock_api) is False

    def test_is_plugin_loaded_error(self):
        """is_plugin_loaded returns False on communication error."""
        from cli_anything.unreal.core.plugin_bridge import is_plugin_loaded

        mock_api = MagicMock()
        with patch("cli_anything.unreal.core.plugin_bridge.run_python_code") as mock_run:
            mock_run.side_effect = Exception("connection refused")
            assert is_plugin_loaded(mock_api) is False

    def test_get_bundled_version(self):
        """get_bundled_version returns the bundled plugin version."""
        from cli_anything.unreal.core.plugin_bridge import get_bundled_version

        version = get_bundled_version()
        assert version is not None
        assert version == "1.9"

    def test_get_loaded_plugin_version(self):
        """get_loaded_plugin_version queries the running editor."""
        from cli_anything.unreal.core.plugin_bridge import get_loaded_plugin_version

        mock_api = MagicMock()
        with patch("cli_anything.unreal.core.plugin_bridge.run_python_code") as mock_run:
            mock_run.return_value = {"version": "1.3"}
            assert get_loaded_plugin_version(mock_api) == "1.3"

    def test_get_loaded_plugin_version_not_loaded(self):
        """get_loaded_plugin_version returns None when plugin not loaded."""
        from cli_anything.unreal.core.plugin_bridge import get_loaded_plugin_version

        mock_api = MagicMock()
        with patch("cli_anything.unreal.core.plugin_bridge.run_python_code") as mock_run:
            mock_run.return_value = {"version": None}
            assert get_loaded_plugin_version(mock_api) is None

    def test_check_plugin_version_match(self):
        """check_plugin_version returns match=True when versions agree."""
        from cli_anything.unreal.core.plugin_bridge import check_plugin_version

        mock_api = MagicMock()
        with patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version") as mock_loaded, \
             patch("cli_anything.unreal.core.plugin_bridge.ensure_plugin_deployed") as mock_deploy:
            mock_loaded.return_value = "1.9"
            mock_deploy.return_value = {"deployed": True, "action": "already_up_to_date"}
            result = check_plugin_version(mock_api, "/tmp/project")
            assert result["match"] is True
            assert result["action_needed"] == "none"

    def test_check_plugin_version_mismatch(self):
        """check_plugin_version detects version mismatch."""
        from cli_anything.unreal.core.plugin_bridge import check_plugin_version

        mock_api = MagicMock()
        with patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version") as mock_loaded, \
             patch("cli_anything.unreal.core.plugin_bridge.ensure_plugin_deployed") as mock_deploy:
            mock_loaded.return_value = "1.3"
            mock_deploy.return_value = {"deployed": True, "action": "updated_1.3_to_1.9", "version": "1.9"}
            result = check_plugin_version(mock_api, "/tmp/project")
            assert result["match"] is False
            assert result["action_needed"] == "recompile"
            assert result["loaded_version"] == "1.3"
            assert result["bundled_version"] == "1.9"


# ═══════════════════════════════════════════════════════════════════════
#  Test get_material_errors with plugin path
# ═══════════════════════════════════════════════════════════════════════


