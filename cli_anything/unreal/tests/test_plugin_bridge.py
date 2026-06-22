"""Tests for test_plugin_bridge.py — Uses synthetic data only, no UE editor required."""

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestPluginBridge:
    """Tests for core/plugin_bridge.py — deploy and detect logic."""

    def test_bundled_descriptor_matches_cpp_reported_version(self):
        """The descriptor VersionName must match GetPluginVersion()."""
        plugin_dir = Path(__file__).resolve().parents[1] / "bridge_plugin" / "CliAnythingBridge"
        descriptor = json.loads((plugin_dir / "CliAnythingBridge.uplugin").read_text(encoding="utf-8"))
        cpp = (
            plugin_dir
            / "Source"
            / "CliAnythingBridge"
            / "Private"
            / "CliAnythingBridgeLibrary.cpp"
        ).read_text(encoding="utf-8")
        match = re.search(r"GetPluginVersion\(\)\s*\{[^}]*TEXT\(\"([^\"]+)\"\)", cpp, re.DOTALL)

        assert match is not None
        assert match.group(1) == descriptor["VersionName"]

    def test_setup_includes_bundled_bridge_source(self):
        """Packaged installs must include the bridge source used for deployment."""
        setup_py = Path(__file__).resolve().parents[3] / "setup.py"
        setup_text = setup_py.read_text(encoding="utf-8")

        assert "bridge_plugin/CliAnythingBridge/*.uplugin" in setup_text
        assert "bridge_plugin/CliAnythingBridge/Source/CliAnythingBridge/*.cs" in setup_text
        assert "bridge_plugin/CliAnythingBridge/Source/CliAnythingBridge/Public/*.h" in setup_text
        assert "bridge_plugin/CliAnythingBridge/Source/CliAnythingBridge/Private/*.cpp" in setup_text

    def test_ensure_plugin_deployed_fresh_install(self, tmp_path):
        """First deploy copies plugin source to project Plugins/."""
        from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed, get_bundled_version

        project_dir = str(tmp_path)
        result = ensure_plugin_deployed(project_dir)

        assert result["deployed"] is True
        assert result["action"] == "fresh_install"
        assert result["version"] == get_bundled_version()

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
        from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed, get_bundled_version

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
        assert result["version"] == get_bundled_version()

    def test_get_plugin_binary_status_missing_binary(self, tmp_path):
        """Deployed bridge source is not launch-ready until its editor DLL exists."""
        from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed, get_plugin_binary_status

        ensure_plugin_deployed(str(tmp_path))

        result = get_plugin_binary_status(str(tmp_path))

        assert result["ready"] is False
        assert result["reason"] == "missing_binary"
        assert result["dll_path"].endswith("UnrealEditor-CliAnythingBridge.dll")

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
        assert version == "1.14"

    def test_bridge_declares_umg_helpers(self):
        """UMG authoring helpers live in the bridge because WidgetTree fields are protected."""
        plugin_dir = Path(__file__).resolve().parents[1] / "bridge_plugin" / "CliAnythingBridge"
        header = (
            plugin_dir
            / "Source"
            / "CliAnythingBridge"
            / "Public"
            / "CliAnythingBridgeLibrary.h"
        ).read_text(encoding="utf-8")
        cpp = (
            plugin_dir
            / "Source"
            / "CliAnythingBridge"
            / "Private"
            / "CliAnythingBridgeLibrary.cpp"
        ).read_text(encoding="utf-8")

        for name in ("SetWidgetBlueprintRoot", "AddWidgetToCanvas", "GetWidgetBlueprintTree"):
            assert name in header
            assert name in cpp

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
        from cli_anything.unreal.core.plugin_bridge import check_plugin_version, get_bundled_version

        mock_api = MagicMock()
        with patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version") as mock_loaded, \
             patch("cli_anything.unreal.core.plugin_bridge.ensure_plugin_deployed") as mock_deploy:
            mock_loaded.return_value = get_bundled_version()
            mock_deploy.return_value = {"deployed": True, "action": "already_up_to_date"}
            result = check_plugin_version(mock_api, "/tmp/project")
            assert result["match"] is True
            assert result["action_needed"] == "none"

    def test_check_plugin_version_mismatch(self):
        """check_plugin_version detects version mismatch."""
        from cli_anything.unreal.core.plugin_bridge import check_plugin_version, get_bundled_version

        mock_api = MagicMock()
        with patch("cli_anything.unreal.core.plugin_bridge.get_loaded_plugin_version") as mock_loaded, \
             patch("cli_anything.unreal.core.plugin_bridge.ensure_plugin_deployed") as mock_deploy:
            mock_loaded.return_value = "1.3"
            mock_deploy.return_value = {
                "deployed": True,
                "action": f"updated_1.3_to_{get_bundled_version()}",
                "version": get_bundled_version(),
            }
            result = check_plugin_version(mock_api, "/tmp/project")
            assert result["match"] is False
            assert result["action_needed"] == "recompile"
            assert result["loaded_version"] == "1.3"
            assert result["bundled_version"] == get_bundled_version()


# ═══════════════════════════════════════════════════════════════════════
#  Test _ensure_plugin_enabled and _is_plugin_enabled_in_uproject
# ═══════════════════════════════════════════════════════════════════════


class TestPluginEnableInUproject:
    """Tests for ue_backend._ensure_plugin_enabled and _is_plugin_enabled_in_uproject."""

    def test_ensure_plugin_enabled_auto_enables_bridge(self, tmp_path):
        """_ensure_plugin_enabled enables CliAnythingBridge in .uproject."""
        from cli_anything.unreal.utils.ue_backend import _ensure_plugin_enabled

        project_dir = tmp_path / "TestProj"
        project_dir.mkdir()
        uproject = project_dir / "TestProj.uproject"
        uproject.write_text(json.dumps({"FileVersion": 3}), encoding="utf-8")

        changed = _ensure_plugin_enabled(str(project_dir), "CliAnythingBridge")
        assert changed is True

        data = json.loads(uproject.read_text(encoding="utf-8"))
        plugin_names = [p["Name"] for p in data["Plugins"]]
        assert "CliAnythingBridge" in plugin_names
        assert next(p for p in data["Plugins"] if p["Name"] == "CliAnythingBridge")["Enabled"] is True

    def test_ensure_plugin_enabled_no_change_when_already_enabled(self, tmp_path):
        """_ensure_plugin_enabled returns False when plugin already enabled."""
        from cli_anything.unreal.utils.ue_backend import _ensure_plugin_enabled

        project_dir = tmp_path / "TestProj"
        project_dir.mkdir()
        uproject = project_dir / "TestProj.uproject"
        uproject.write_text(json.dumps({
            "FileVersion": 3,
            "Plugins": [{"Name": "CliAnythingBridge", "Enabled": True}],
        }), encoding="utf-8")

        changed = _ensure_plugin_enabled(str(project_dir), "CliAnythingBridge")
        assert changed is False

    def test_ensure_plugin_enabled_enables_disabled_entry(self, tmp_path):
        """_ensure_plugin_enabled changes Enabled from False to True."""
        from cli_anything.unreal.utils.ue_backend import _ensure_plugin_enabled

        project_dir = tmp_path / "TestProj"
        project_dir.mkdir()
        uproject = project_dir / "TestProj.uproject"
        uproject.write_text(json.dumps({
            "FileVersion": 3,
            "Plugins": [{"Name": "CliAnythingBridge", "Enabled": False}],
        }), encoding="utf-8")

        changed = _ensure_plugin_enabled(str(project_dir), "CliAnythingBridge")
        assert changed is True

        data = json.loads(uproject.read_text(encoding="utf-8"))
        assert next(p for p in data["Plugins"] if p["Name"] == "CliAnythingBridge")["Enabled"] is True

    def test_is_plugin_enabled_in_uproject_read_only(self, tmp_path):
        """_is_plugin_enabled_in_uproject checks without modifying."""
        from cli_anything.unreal.utils.ue_backend import _is_plugin_enabled_in_uproject

        project_dir = tmp_path / "TestProj"
        project_dir.mkdir()
        uproject = project_dir / "TestProj.uproject"

        # Not enabled
        uproject.write_text(json.dumps({"FileVersion": 3}), encoding="utf-8")
        assert _is_plugin_enabled_in_uproject(str(project_dir), "CliAnythingBridge") is False

        # Explicitly disabled
        uproject.write_text(json.dumps({
            "FileVersion": 3,
            "Plugins": [{"Name": "CliAnythingBridge", "Enabled": False}],
        }), encoding="utf-8")
        assert _is_plugin_enabled_in_uproject(str(project_dir), "CliAnythingBridge") is False

        # Enabled
        uproject.write_text(json.dumps({
            "FileVersion": 3,
            "Plugins": [{"Name": "CliAnythingBridge", "Enabled": True}],
        }), encoding="utf-8")
        assert _is_plugin_enabled_in_uproject(str(project_dir), "CliAnythingBridge") is True


# ═══════════════════════════════════════════════════════════════════════
#  Test get_material_errors with plugin path
# ═══════════════════════════════════════════════════════════════════════

