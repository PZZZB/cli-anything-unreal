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
        descriptor = json.loads((plugin_dir / "CliAnythingBridge.uplugin").read_text(encoding="utf-8"))
        assert descriptor["EnabledByDefault"] is False

    def test_ensure_plugin_deployed_already_up_to_date(self, tmp_path):
        """Second deploy is a no-op when versions match."""
        from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed

        project_dir = str(tmp_path)
        ensure_plugin_deployed(project_dir)  # first install
        result = ensure_plugin_deployed(project_dir)  # second call

        assert result["deployed"] is True
        assert result["action"] == "already_up_to_date"

    def test_ensure_plugin_deployed_normalizes_old_enabled_by_default(self, tmp_path):
        """Old deployed descriptors must not keep loading before the bridge is compiled."""
        from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed

        project_dir = str(tmp_path)
        ensure_plugin_deployed(project_dir)
        uplugin = tmp_path / "Plugins" / "CliAnythingBridge" / "CliAnythingBridge.uplugin"
        data = json.loads(uplugin.read_text(encoding="utf-8"))
        data["EnabledByDefault"] = True
        uplugin.write_text(json.dumps(data), encoding="utf-8")

        result = ensure_plugin_deployed(project_dir)

        assert result["action"] == "already_up_to_date"
        assert result["descriptor_normalized"] is True
        data = json.loads(uplugin.read_text(encoding="utf-8"))
        assert data["EnabledByDefault"] is False

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

    def test_ensure_plugin_deployed_locked_update_is_pending(self, tmp_path):
        """Online editors can lock bridge DLLs; deploy should report pending update instead of raising."""
        from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed, get_bundled_version

        project_dir = str(tmp_path)
        ensure_plugin_deployed(project_dir)

        uplugin = tmp_path / "Plugins" / "CliAnythingBridge" / "CliAnythingBridge.uplugin"
        data = json.loads(uplugin.read_text())
        data["VersionName"] = "0.1"
        uplugin.write_text(json.dumps(data))

        locked = PermissionError(5, "Access is denied", str(uplugin))
        with patch("cli_anything.unreal.core.plugin_bridge.shutil.rmtree", side_effect=locked), \
             patch("cli_anything.unreal.core.plugin_bridge.shutil.copytree") as copytree:
            result = ensure_plugin_deployed(project_dir)

        assert result["deployed"] is True
        assert result["action"] == "update_pending_locked"
        assert result["version"] == "0.1"
        assert result["bundled_version"] == get_bundled_version()
        assert result["retry_suggested"] is True
        copytree.assert_not_called()

    def test_get_plugin_binary_status_missing_binary(self, tmp_path):
        """Deployed bridge source is not launch-ready until its editor DLL exists."""
        from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed, get_plugin_binary_status

        ensure_plugin_deployed(str(tmp_path))

        result = get_plugin_binary_status(str(tmp_path))

        assert result["ready"] is False
        assert result["reason"] == "missing_binary"
        assert result["dll_path"].endswith("UnrealEditor-CliAnythingBridge.dll")

    def test_get_plugin_binary_status_uses_ue4_prefix(self, tmp_path):
        """UE4 projects use UE4Editor-* binary names."""
        from cli_anything.unreal.core.plugin_bridge import ensure_plugin_deployed, get_plugin_binary_status

        engine_root = tmp_path / "UE4Engine"
        bin_dir = engine_root / "Engine" / "Binaries" / "Win64"
        bin_dir.mkdir(parents=True)
        (bin_dir / "UE4Editor.exe").write_text("fake", encoding="utf-8")
        ensure_plugin_deployed(str(tmp_path))

        result = get_plugin_binary_status(str(tmp_path), engine_root=str(engine_root))

        assert result["editor_binary_prefix"] == "UE4Editor"
        assert result["dll_path"].endswith("UE4Editor-CliAnythingBridge.dll")

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
        assert version == "1.20"

    def test_bridge_composed_viewport_capture_uses_slate_screenshot(self):
        """HUD-inclusive capture must read the composed Slate viewport region."""
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

        assert "bool bIncludeUI = false" in header
        assert "FSlateApplication::Get().TakeScreenshot" in cpp
        assert "if (bIncludeUI)" in cpp

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

    def test_bridge_declares_material_disconnect_helper(self):
        """Material node input disconnect needs C++ because UE Python has no disconnect API."""
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

        assert "DisconnectMaterialExpressionInput" in header
        assert "DisconnectMaterialExpressionInput" in cpp

    def test_bridge_declares_struct_info_helper(self):
        """api-discover needs C++ reflection for UScriptStruct types such as CustomInput."""
        root = Path(__file__).parent.parent / "bridge_plugin" / "CliAnythingBridge"
        header = (root / "Source" / "CliAnythingBridge" / "Public" / "CliAnythingBridgeLibrary.h").read_text(encoding="utf-8")
        cpp = (root / "Source" / "CliAnythingBridge" / "Private" / "CliAnythingBridgeLibrary.cpp").read_text(encoding="utf-8")

        assert "GetStructInfo" in header
        assert "GetStructInfo" in cpp
        assert "UScriptStruct" in header
        assert "TFieldIterator<FProperty> It(Struct" in cpp

    def test_bridge_declares_texture_source_helper(self):
        """TextureSource inspection needs C++ because UE Python hides Texture2D.Source."""
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

        assert "GetTextureSourceInfo" in header
        assert "GetTextureSourceInfo" in cpp
        assert "LockMipReadOnly" in cpp

    def test_bridge_declares_active_viewport_screenshot_helper(self):
        """Viewport capture must redraw and read only the active FSceneViewport."""
        root = Path(__file__).parent.parent / "bridge_plugin" / "CliAnythingBridge"
        header = (
            root
            / "Source"
            / "CliAnythingBridge"
            / "Public"
            / "CliAnythingBridgeLibrary.h"
        ).read_text(encoding="utf-8")
        cpp = (
            root
            / "Source"
            / "CliAnythingBridge"
            / "Private"
            / "CliAnythingBridgeLibrary.cpp"
        ).read_text(encoding="utf-8")

        assert "TakeActiveViewportScreenshot" in header
        assert "GetViewports()" in cpp
        assert "SceneViewport->Draw()" in cpp
        assert "SceneViewport->ReadPixels" in cpp

    def test_bridge_declares_umg_image_helper(self):
        """WidgetBlueprint Image slot/brush editing needs bridge access to WidgetTree."""
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

        assert "SetWidgetImageProperties" in header
        assert "SetWidgetImageProperties" in cpp
        assert "SetBrushResourceObject" in cpp

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

