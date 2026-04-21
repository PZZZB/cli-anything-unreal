"""test_core.py — Unit tests for cli-anything-unreal core modules.

Uses synthetic data only — no UE editor or engine installation required.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary UE project structure."""
    project_name = "TestProject"
    project_dir = tmp_path / project_name

    # Create .uproject
    uproject = {
        "FileVersion": 3,
        "EngineAssociation": "5.7",
        "Category": "",
        "Description": "",
        "Modules": [
            {
                "Name": "TestProject",
                "Type": "Runtime",
                "LoadingPhase": "Default",
            }
        ],
        "Plugins": [
            {"Name": "PythonScriptPlugin", "Enabled": True},
            {"Name": "RemoteControl", "Enabled": True},
            {"Name": "EditorScriptingUtilities", "Enabled": True},
            {"Name": "ModelingToolsEditorMode", "Enabled": False},
        ],
    }

    project_dir.mkdir()
    uproject_path = project_dir / f"{project_name}.uproject"
    uproject_path.write_text(json.dumps(uproject, indent=2), encoding="utf-8")

    # Create Config/
    config_dir = project_dir / "Config"
    config_dir.mkdir()

    default_engine = config_dir / "DefaultEngine.ini"
    default_engine.write_text(
        "[/Script/Engine.RendererSettings]\n"
        "r.DefaultFeature.AutoExposure.Method=2\n"
        "r.DefaultFeature.MotionBlur=False\n"
        "\n"
        "[/Script/Engine.Engine]\n"
        "+ActiveGameNameRedirects=(OldGameName=\"TP4\",NewGameName=\"/Script/TestProject\")\n"
        "+ActiveClassRedirects=(OldClassName=\"TP4GameMode\",NewClassName=\"TestProjectGameMode\")\n",
        encoding="utf-8",
    )

    default_game = config_dir / "DefaultGame.ini"
    default_game.write_text(
        "[/Script/UnrealEd.ProjectPackagingSettings]\n"
        "BuildConfiguration=PPBC_Shipping\n"
        "BlueprintNativizationMethod=Disabled\n",
        encoding="utf-8",
    )

    # Create Content/
    content_dir = project_dir / "Content"
    content_dir.mkdir()
    (content_dir / "TestMaterial.uasset").write_bytes(b"\x00" * 100)
    (content_dir / "TestTexture.uasset").write_bytes(b"\x00" * 200)

    sub_dir = content_dir / "Materials"
    sub_dir.mkdir()
    (sub_dir / "M_Base.uasset").write_bytes(b"\x00" * 150)
    (sub_dir / "M_Metal.uasset").write_bytes(b"\x00" * 180)

    # Create Source/
    source_dir = project_dir / "Source" / project_name
    source_dir.mkdir(parents=True)
    (source_dir / "TestProject.cpp").write_text("// test", encoding="utf-8")
    (source_dir / "TestProject.h").write_text("// test", encoding="utf-8")
    (source_dir / "TestProjectGameMode.cpp").write_text("// test", encoding="utf-8")
    (source_dir / "TestProjectGameMode.h").write_text("// test", encoding="utf-8")

    # Create Binaries/
    bin_dir = project_dir / "Binaries" / "Win64"
    bin_dir.mkdir(parents=True)
    (bin_dir / "TestProject.dll").write_bytes(b"\x00" * 50)

    return {
        "dir": str(project_dir),
        "uproject": str(uproject_path),
        "name": project_name,
    }


@pytest.fixture
def mock_engine_root(tmp_path):
    """Create a mock engine root structure."""
    engine_root = tmp_path / "RX_ENGINE_5.7"
    (engine_root / "Engine" / "Binaries" / "Win64").mkdir(parents=True)
    (engine_root / "Engine" / "Build" / "BatchFiles").mkdir(parents=True)
    (engine_root / "Engine" / "Source").mkdir(parents=True)

    # Create editor exe
    editor_exe = engine_root / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    editor_exe.write_bytes(b"\x00")

    # RunUAT.bat
    uat = engine_root / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat"
    uat.write_text("@echo off\necho UAT %*", encoding="utf-8")

    # Build.bat
    build_bat = engine_root / "Engine" / "Build" / "BatchFiles" / "Build.bat"
    build_bat.write_text("@echo off\necho Build %*", encoding="utf-8")

    # Build.version
    version_dir = engine_root / "Engine" / "Build"
    version_file = version_dir / "Build.version"
    version_file.write_text(json.dumps({
        "MajorVersion": 5,
        "MinorVersion": 7,
        "PatchVersion": 0,
    }), encoding="utf-8")

    return str(engine_root)


# ═══════════════════════════════════════════════════════════════════════
#  Test project.py
# ═══════════════════════════════════════════════════════════════════════

class TestProject:
    """Tests for core/project.py."""

    def test_parse_uproject(self, temp_project):
        from cli_anything.unreal.core.project import parse_uproject

        data = parse_uproject(temp_project["uproject"])
        assert data["FileVersion"] == 3
        assert data["EngineAssociation"] == "5.7"
        assert len(data["Modules"]) == 1
        assert data["Modules"][0]["Name"] == "TestProject"

    def test_parse_uproject_not_found(self):
        from cli_anything.unreal.core.project import parse_uproject

        with pytest.raises(FileNotFoundError):
            parse_uproject("/nonexistent/path.uproject")

    def test_get_project_info(self, temp_project):
        from cli_anything.unreal.core.project import get_project_info

        info = get_project_info(temp_project["uproject"])
        assert info["name"] == "TestProject"
        assert info["engine_association"] == "5.7"
        assert len(info["modules"]) == 1
        assert info["plugin_count"] == 4
        assert info["enabled_plugins"] == 3
        assert info["has_content"] is True
        assert info["has_config"] is True
        assert info["has_binaries"] is True
        assert info["source"]["cpp_files"] == 2
        assert info["source"]["header_files"] == 2

    def test_list_configs(self, temp_project):
        from cli_anything.unreal.core.project import list_configs

        configs = list_configs(temp_project["dir"])
        assert len(configs) == 2
        names = [c["name"] for c in configs]
        assert "DefaultEngine" in names
        assert "DefaultGame" in names

    def test_get_config(self, temp_project):
        from cli_anything.unreal.core.project import get_config

        config = get_config(temp_project["dir"], "DefaultEngine")
        assert "/Script/Engine.RendererSettings" in config
        section = config["/Script/Engine.RendererSettings"]
        assert section["r.DefaultFeature.AutoExposure.Method"] == "2"

    def test_get_config_not_found(self, temp_project):
        from cli_anything.unreal.core.project import get_config

        with pytest.raises(FileNotFoundError):
            get_config(temp_project["dir"], "NonExistent")

    def test_get_config_array_keys(self, temp_project):
        from cli_anything.unreal.core.project import get_config

        config = get_config(temp_project["dir"], "DefaultEngine")
        engine_section = config.get("/Script/Engine.Engine", {})
        # +ActiveGameNameRedirects should be parsed as array
        assert "ActiveGameNameRedirects" in engine_section
        assert isinstance(engine_section["ActiveGameNameRedirects"], list)

    def test_set_config(self, temp_project):
        from cli_anything.unreal.core.project import set_config, get_config

        result = set_config(
            temp_project["dir"],
            "DefaultEngine",
            "/Script/Engine.RendererSettings",
            "r.DefaultFeature.AutoExposure.Method",
            "1",
        )
        assert result["status"] == "ok"

        # Verify the change
        config = get_config(temp_project["dir"], "DefaultEngine")
        section = config["/Script/Engine.RendererSettings"]
        assert section["r.DefaultFeature.AutoExposure.Method"] == "1"

    def test_set_config_new_section(self, temp_project):
        from cli_anything.unreal.core.project import set_config, get_config

        result = set_config(
            temp_project["dir"],
            "DefaultEngine",
            "/Script/NewPlugin.Settings",
            "bEnabled",
            "True",
        )
        assert result["status"] == "ok"

        config = get_config(temp_project["dir"], "DefaultEngine")
        assert "/Script/NewPlugin.Settings" in config
        assert config["/Script/NewPlugin.Settings"]["bEnabled"] == "True"

    def test_list_content(self, temp_project):
        from cli_anything.unreal.core.project import list_content

        assets = list_content(temp_project["dir"])
        assert len(assets) == 4  # 2 root + 2 in Materials/
        names = [a["name"] for a in assets]
        assert "TestMaterial" in names
        assert "M_Base" in names

    def test_list_content_filter_ext(self, temp_project):
        from cli_anything.unreal.core.project import list_content

        assets = list_content(temp_project["dir"], filter_ext=".uasset")
        assert len(assets) == 4

        assets = list_content(temp_project["dir"], filter_ext=".umap")
        assert len(assets) == 0

    def test_list_content_filter_path(self, temp_project):
        from cli_anything.unreal.core.project import list_content

        assets = list_content(temp_project["dir"], filter_path="Materials")
        assert len(assets) == 2
        for a in assets:
            assert "Materials" in a["relative_path"]

    def test_list_content_has_content_path(self, temp_project):
        from cli_anything.unreal.core.project import list_content

        assets = list_content(temp_project["dir"])
        mat_assets = [a for a in assets if a["name"] == "M_Base"]
        assert len(mat_assets) == 1
        assert mat_assets[0]["content_path"] == "/Game/Materials/M_Base"


# ═══════════════════════════════════════════════════════════════════════
#  Test ue_backend.py
# ═══════════════════════════════════════════════════════════════════════

class TestBackend:
    """Tests for utils/ue_backend.py."""

    def test_validate_engine_root(self, mock_engine_root):
        from cli_anything.unreal.utils.ue_backend import _validate_engine_root

        assert _validate_engine_root(mock_engine_root) is True
        assert _validate_engine_root("/nonexistent/path") is False

    def test_find_editor_exe(self, mock_engine_root):
        from cli_anything.unreal.utils.ue_backend import find_editor_exe

        exe = find_editor_exe(mock_engine_root)
        assert exe is not None
        assert "UnrealEditor.exe" in exe

    def test_find_uat(self, mock_engine_root):
        from cli_anything.unreal.utils.ue_backend import find_uat

        uat = find_uat(mock_engine_root)
        assert uat is not None
        assert "RunUAT" in uat

    def test_find_build_bat(self, mock_engine_root):
        from cli_anything.unreal.utils.ue_backend import find_build_bat

        bat = find_build_bat(mock_engine_root)
        assert bat is not None
        assert "Build.bat" in bat

    def test_get_engine_version(self, mock_engine_root):
        from cli_anything.unreal.utils.ue_backend import get_engine_version

        version = get_engine_version(mock_engine_root)
        assert version == "5.7.0"

    def test_find_engine_root_env_var(self, mock_engine_root):
        from cli_anything.unreal.utils.ue_backend import find_engine_root

        with patch.dict(os.environ, {"UE_ENGINE_ROOT": mock_engine_root}):
            root = find_engine_root()
            assert root == mock_engine_root

    def test_find_engine_root_no_engine(self):
        from cli_anything.unreal.utils.ue_backend import find_engine_root

        with patch.dict(os.environ, {}, clear=True):
            # Should not crash even if no engine found
            root = find_engine_root("/nonexistent.uproject")

    def test_find_engine_root_version_hklm(self, tmp_path):
        """EngineAssociation '5.7' resolves via HKLM subkey name."""
        from cli_anything.unreal.utils.ue_backend import find_engine_root

        uproject = tmp_path / "Test.uproject"
        uproject.write_text('{"EngineAssociation": "5.7"}', encoding="utf-8")

        mock_install_dir = r"C:\Program Files\Epic Games\UE_5.7"
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_in_hklm", return_value=mock_install_dir),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_in_hkcu", return_value=None),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_from_registry", return_value=None),
        ):
            root = find_engine_root(str(uproject))
            assert root == mock_install_dir

    def test_find_engine_root_guid_hkcu(self, tmp_path):
        """EngineAssociation '{GUID}' resolves via HKCU Builds."""
        from cli_anything.unreal.utils.ue_backend import find_engine_root

        guid = "{F9E7804A-46B1-30B0-1C7B-4B99E6AAB63F}"
        uproject = tmp_path / "Test.uproject"
        uproject.write_text(f'{{"EngineAssociation": "{guid}"}}', encoding="utf-8")

        mock_install_dir = r"F:\RX_ENGINE_5.7"
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_in_hklm", return_value=None),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_in_hkcu", return_value=mock_install_dir),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_from_registry", return_value=None),
        ):
            root = find_engine_root(str(uproject))
            assert root == mock_install_dir

    def test_find_engine_root_path_assoc(self, tmp_path):
        """EngineAssociation that is a directory path is used directly."""
        from cli_anything.unreal.utils.ue_backend import find_engine_root

        engine_dir = tmp_path / "MyEngine"
        engine_dir.mkdir()
        (engine_dir / "Engine" / "Build").mkdir(parents=True)

        uproject = tmp_path / "Test.uproject"
        uproject.write_text(f'{{"EngineAssociation": "{str(engine_dir).replace(chr(92), "/")}"}}', encoding="utf-8")

        with patch.dict(os.environ, {}, clear=True):
            root = find_engine_root(str(uproject))
            assert root is not None

    def test_find_engine_by_association_hklm_direct(self):
        """_find_engine_in_hklm opens subkey by version name directly."""
        from cli_anything.unreal.utils.ue_backend import _find_engine_in_hklm

        mock_winreg = MagicMock()
        mock_subkey = MagicMock()
        mock_subkey.__enter__ = lambda s: s
        mock_subkey.__exit__ = MagicMock(return_value=False)
        mock_winreg.OpenKey.return_value = mock_subkey
        mock_winreg.HKEY_LOCAL_MACHINE = MagicMock()
        mock_winreg.QueryValueEx.return_value = (r"C:\Program Files\Epic Games\UE_5.7", MagicMock())

        with patch.dict("sys.modules", {"winreg": mock_winreg}), \
             patch("cli_anything.unreal.utils.ue_backend._validate_engine_root", return_value=True):
            result = _find_engine_in_hklm("5.7")
            assert result == r"C:\Program Files\Epic Games\UE_5.7"
            # Verify it opened the version subkey directly
            mock_winreg.OpenKey.assert_called()

    def test_find_engine_by_association_hkcu_guid(self):
        """_find_engine_in_hkcu looks up GUID by value name."""
        from cli_anything.unreal.utils.ue_backend import _find_engine_in_hkcu

        guid = "{F9E7804A-46B1-30B0-1C7B-4B99E6AAB63F}"
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.HKEY_CURRENT_USER = MagicMock()
        mock_winreg.QueryValueEx.return_value = (r"F:\RX_ENGINE_5.7", MagicMock())

        with patch.dict("sys.modules", {"winreg": mock_winreg}), \
             patch("cli_anything.unreal.utils.ue_backend._validate_engine_root", return_value=True):
            result = _find_engine_in_hkcu(guid)
            assert result == r"F:\RX_ENGINE_5.7"
            mock_winreg.QueryValueEx.assert_called_with(mock_key, guid)

    def test_find_engine_by_association_hklm_takes_priority(self, tmp_path):
        """When both HKLM and HKCU match, HKLM wins."""
        from cli_anything.unreal.utils.ue_backend import find_engine_root

        uproject = tmp_path / "Test.uproject"
        uproject.write_text('{"EngineAssociation": "5.7"}', encoding="utf-8")

        hklm_dir = r"C:\Program Files\Epic Games\UE_5.7"
        hkcu_dir = r"F:\RX_ENGINE_5.7"
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_in_hklm", return_value=hklm_dir),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_in_hkcu", return_value=hkcu_dir),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_from_registry", return_value=None),
        ):
            root = find_engine_root(str(uproject))
            assert root == hklm_dir

    def test_find_engine_by_association_hkcu_fallback(self, tmp_path):
        """When HKLM has no match, falls back to HKCU Build.version scan."""
        from cli_anything.unreal.utils.ue_backend import find_engine_root

        uproject = tmp_path / "Test.uproject"
        uproject.write_text('{"EngineAssociation": "5.7"}', encoding="utf-8")

        hkcu_dir = r"F:\RX_ENGINE_5.7"
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_in_hklm", return_value=None),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_in_hkcu", return_value=hkcu_dir),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_from_registry", return_value=None),
        ):
            root = find_engine_root(str(uproject))
            assert root == hkcu_dir

    def test_find_engine_by_association_no_match(self, tmp_path):
        """No matching engine returns None."""
        from cli_anything.unreal.utils.ue_backend import find_engine_root

        uproject = tmp_path / "Test.uproject"
        uproject.write_text('{"EngineAssociation": "99.9"}', encoding="utf-8")

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_in_hklm", return_value=None),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_in_hkcu", return_value=None),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_from_registry", return_value=None),
        ):
            root = find_engine_root(str(uproject))
            assert root is None

    def test_find_engine_root_no_uproject_uses_registry(self):
        """Without uproject, falls back to registry."""
        from cli_anything.unreal.utils.ue_backend import find_engine_root

        mock_dir = r"C:\Program Files\Epic Games\UE_5.7"
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("cli_anything.unreal.utils.ue_backend._find_engine_from_registry", return_value=mock_dir),
        ):
            root = find_engine_root()
            assert root == mock_dir

    def test_read_engine_version(self, tmp_path):
        """_read_engine_version reads MajorVersion.MinorVersion from Build.version."""
        from cli_anything.unreal.utils.ue_backend import _read_engine_version

        engine = tmp_path / "Engine"
        build_dir = engine / "Build"
        build_dir.mkdir(parents=True)
        (build_dir / "Build.version").write_text(
            '{"MajorVersion": 5, "MinorVersion": 7, "PatchVersion": 0}', encoding="utf-8"
        )
        assert _read_engine_version(str(tmp_path)) == "5.7"

    def test_read_engine_version_missing_file(self, tmp_path):
        """_read_engine_version returns None if Build.version is missing."""
        from cli_anything.unreal.utils.ue_backend import _read_engine_version

        assert _read_engine_version(str(tmp_path)) is None

    def test_find_engine_in_hkcu_version_scan(self):
        """_find_engine_in_hkcu scans entries by Build.version when assoc is not GUID."""
        from cli_anything.unreal.utils.ue_backend import _find_engine_in_hkcu

        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.HKEY_CURRENT_USER = MagicMock()

        # First entry: version doesn't match
        # Second entry: version matches
        mock_winreg.EnumValue.side_effect = [
            ("{GUID1}", r"F:\Engine1", 1),
            ("{GUID2}", r"F:\Engine2", 1),
            OSError,  # end enumeration
        ]

        def mock_read_version(path):
            return "5.5" if "Engine1" in path else "5.7"

        with patch.dict("sys.modules", {"winreg": mock_winreg}), \
             patch("cli_anything.unreal.utils.ue_backend._validate_engine_root", return_value=True), \
             patch("cli_anything.unreal.utils.ue_backend._read_engine_version", side_effect=mock_read_version):
            result = _find_engine_in_hkcu("5.7")
            assert result == r"F:\Engine2"

    def test_find_engine_from_registry_checks_both_hives(self):
        """_find_engine_from_registry checks HKLM first, then HKCU."""
        from cli_anything.unreal.utils.ue_backend import _find_engine_from_registry

        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value = mock_key
        mock_winreg.HKEY_LOCAL_MACHINE = MagicMock()
        mock_winreg.HKEY_CURRENT_USER = MagicMock()

        # HKLM has no entries (EnumKey raises OSError immediately)
        mock_winreg.EnumKey.side_effect = OSError
        # HKCU has one entry
        mock_winreg.EnumValue.side_effect = [
            ("{GUID1}", r"F:\CustomEngine", 1),
            OSError,
        ]

        with patch.dict("sys.modules", {"winreg": mock_winreg}), \
             patch("cli_anything.unreal.utils.ue_backend._validate_engine_root", return_value=True):
            result = _find_engine_from_registry()
            assert result == r"F:\CustomEngine"


# ═══════════════════════════════════════════════════════════════════════
#  Test session.py
# ═══════════════════════════════════════════════════════════════════════

class TestSession:
    """Tests for core/session.py."""

    def test_new_session(self):
        from cli_anything.unreal.core.session import Session

        sess = Session()
        assert not sess.is_loaded
        assert sess.port == 30010

    def test_load_project(self, temp_project):
        from cli_anything.unreal.core.session import Session

        sess = Session()
        sess.load_project(temp_project["uproject"])
        assert sess.is_loaded
        assert sess.project_name == "TestProject"
        assert sess.project_dir == temp_project["dir"]

    def test_load_project_not_found(self):
        from cli_anything.unreal.core.session import Session

        sess = Session()
        with pytest.raises(FileNotFoundError):
            sess.load_project("/nonexistent.uproject")

    def test_snapshot_and_undo(self, temp_project):
        from cli_anything.unreal.core.session import Session

        sess = Session()
        sess.load_project(temp_project["uproject"])

        sess.snapshot("change 1")
        sess._state["test_key"] = "value1"

        sess.snapshot("change 2")
        sess._state["test_key"] = "value2"

        # Undo change 2
        result = sess.undo()
        assert result is not None
        assert result["description"] == "change 2"
        assert sess._state.get("test_key") == "value1"

        # Undo change 1
        result = sess.undo()
        assert result is not None
        assert "test_key" not in sess._state

    def test_redo(self, temp_project):
        from cli_anything.unreal.core.session import Session

        sess = Session()
        sess.load_project(temp_project["uproject"])

        sess.snapshot("change 1")
        sess._state["key"] = "v1"

        sess.undo()
        assert "key" not in sess._state

        result = sess.redo()
        assert result is not None
        # After redo, state should be back

    def test_undo_empty(self):
        from cli_anything.unreal.core.session import Session

        sess = Session()
        assert sess.undo() is None

    def test_redo_empty(self):
        from cli_anything.unreal.core.session import Session

        sess = Session()
        assert sess.redo() is None

    def test_status(self, temp_project):
        from cli_anything.unreal.core.session import Session

        sess = Session()
        sess.load_project(temp_project["uproject"])
        status = sess.status()
        assert status["project"] == "TestProject"
        assert status["undo_available"] == 0

    def test_save_and_load_session(self, temp_project, tmp_path):
        from cli_anything.unreal.core.session import Session

        sess = Session()
        sess.load_project(temp_project["uproject"])
        sess.port = 30015

        save_path = str(tmp_path / "session.json")
        sess.save_session(save_path)

        sess2 = Session()
        sess2.load_session(save_path)
        assert sess2.project_name == "TestProject"
        assert sess2.port == 30015

    def test_max_undo(self, temp_project):
        from cli_anything.unreal.core.session import Session, MAX_UNDO

        sess = Session()
        sess.load_project(temp_project["uproject"])

        for i in range(MAX_UNDO + 10):
            sess.snapshot(f"change {i}")

        assert len(sess._undo_stack) == MAX_UNDO

    def test_history(self, temp_project):
        from cli_anything.unreal.core.session import Session

        sess = Session()
        sess.load_project(temp_project["uproject"])

        sess.snapshot("first")
        sess.snapshot("second")
        sess.snapshot("third")

        history = sess.list_history()
        assert len(history) == 3
        assert history[0]["description"] == "third"
        assert history[2]["description"] == "first"


# ═══════════════════════════════════════════════════════════════════════
#  Test build.py (command assembly, no real build)
# ═══════════════════════════════════════════════════════════════════════

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

class TestHTTPAPI:
    """Tests for utils/ue_http_api.py — mocked HTTP calls."""

    def test_api_init(self):
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        api = UEEditorAPI(port=30015)
        assert api.port == 30015
        assert api.base_url == "http://localhost:30015"

    def test_is_alive_false(self):
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        api = UEEditorAPI(port=19999)  # unlikely to be in use
        assert api.is_alive() is False

    @patch("requests.get")
    def test_is_alive_true(self, mock_get):
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        mock_get.return_value = MagicMock(status_code=200)
        api = UEEditorAPI()
        assert api.is_alive() is True

    @patch("requests.put")
    def test_exec_console(self, mock_put):
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{}'
        mock_response.json.return_value = {}
        mock_response.raise_for_status.return_value = None
        mock_put.return_value = mock_response

        api = UEEditorAPI()
        result = api.exec_console("stat fps")
        assert "error" not in result

    @patch("requests.put")
    def test_get_cvar(self, mock_put):
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ReturnValue": 1}'
        mock_response.json.return_value = {"ReturnValue": 1}
        mock_response.raise_for_status.return_value = None
        mock_put.return_value = mock_response

        api = UEEditorAPI()
        val = api.get_cvar("r.VSync")
        assert val == "1"

    def test_scan_editor_ports_empty(self):
        from cli_anything.unreal.utils.ue_http_api import scan_editor_ports

        # Scan a very unlikely port range
        instances = scan_editor_ports(port_range=(19990, 19991))
        assert instances == []


# ═══════════════════════════════════════════════════════════════════════
#  Test materials.py (mocked API)
# ═══════════════════════════════════════════════════════════════════════

class TestMaterials:
    """Tests for core/materials.py — mocked editor API."""

    def _make_mock_api(self, assets=None, describe=None, properties=None):
        """Helper to create a mock API with common defaults."""
        mock_api = MagicMock()
        mock_api.search_assets.return_value = assets or {"Assets": []}
        mock_api.describe_object.return_value = describe or {"Properties": [], "Functions": []}
        mock_api.get_property.return_value = properties or {"error": "not found"}
        return mock_api

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_get_material_info_with_nodes(self, mock_exec_script):
        """Test that material info merges node data from Python script."""
        from cli_anything.unreal.core.materials import get_material_info

        mock_api = self._make_mock_api(
            assets={
                "Assets": [{"Name": "TestMat", "Path": "/Game/TestMat.TestMat",
                            "Class": "/Script/Engine.Material",
                            "Metadata": {}}]
            },
            describe={
                "Properties": [{"Name": "BlendMode", "Type": "EBlendMode"}],
                "Functions": [],
            },
        )

        # Simulate Python script returning full node data
        mock_exec_script.return_value = {
            "name": "TestMat",
            "path": "/Game/TestMat",
            "class": "Material",
            "blend_mode": "BlendMode.BLEND_Opaque",
            "material_domain": "MaterialDomain.MD_Surface",
            "shading_model": "ShadingModel.MSM_DefaultLit",
            "two_sided": False,
            "nodes": [
                {"type": "MaterialExpressionTextureSampleParameter2D", "name": "BaseColor_Tex", "desc": "Base Color"},
                {"type": "MaterialExpressionConstant3Vector", "name": "Tint_Color", "desc": "Tint"},
                {"type": "MaterialExpressionMultiply", "name": "Multiply_0", "desc": ""},
                {"type": "MaterialExpressionTextureSample", "name": "Normal_Tex", "desc": "Normal Map"},
            ],
            "node_count": 4,
            "textures": [
                {"name": "T_BaseColor", "path": "/Game/Textures/T_BaseColor", "node_type": "MaterialExpressionTextureSampleParameter2D", "size_x": 2048, "size_y": 2048},
                {"name": "T_Normal", "path": "/Game/Textures/T_Normal", "node_type": "MaterialExpressionTextureSample", "size_x": 2048, "size_y": 2048},
            ],
            "texture_sample_count": 2,
        }

        result = get_material_info(mock_api, "/Game/TestMat")

        # Verify nodes are present
        assert "nodes" in result
        assert len(result["nodes"]) == 4
        assert result["node_count"] == 4
        # Verify node types
        node_types = [n["type"] for n in result["nodes"]]
        assert "MaterialExpressionTextureSampleParameter2D" in node_types
        assert "MaterialExpressionMultiply" in node_types
        # Verify textures merged
        assert "textures" in result
        assert len(result["textures"]) == 2
        assert result["texture_sample_count"] == 2
        # Verify material properties merged
        assert result["blend_mode"] == "BlendMode.BLEND_Opaque"
        assert result["shading_model"] == "ShadingModel.MSM_DefaultLit"
        assert result["two_sided"] is False

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_get_material_info_material_instance(self, mock_exec_script):
        """Test material info for MaterialInstanceConstant with parameters."""
        from cli_anything.unreal.core.materials import get_material_info

        mock_api = self._make_mock_api(
            assets={
                "Assets": [{"Name": "MI_Test", "Path": "/Game/MI_Test.MI_Test",
                            "Class": "/Script/Engine.MaterialInstanceConstant",
                            "Metadata": {}}]
            },
            describe={"Properties": [{"Name": "Parent", "Type": "UMaterialInterface*"}], "Functions": []},
        )

        mock_exec_script.return_value = {
            "name": "MI_Test",
            "path": "/Game/MI_Test",
            "class": "MaterialInstanceConstant",
            "parent": "/Game/M_Master.M_Master",
            "scalar_parameters": [
                {"name": "Roughness", "value": 0.5},
                {"name": "Metallic", "value": 1.0},
            ],
            "vector_parameters": [
                {"name": "BaseColor", "value": {"r": 0.8, "g": 0.2, "b": 0.1, "a": 1.0}},
            ],
            "texture_parameters": [
                {"name": "DiffuseTexture", "texture": "/Game/Textures/T_Diffuse"},
            ],
        }

        result = get_material_info(mock_api, "/Game/MI_Test")

        assert result["parent"] == "/Game/M_Master.M_Master"
        assert len(result["scalar_parameters"]) == 2
        assert result["scalar_parameters"][0]["name"] == "Roughness"
        assert result["scalar_parameters"][0]["value"] == 0.5
        assert len(result["vector_parameters"]) == 1
        assert result["vector_parameters"][0]["value"]["r"] == 0.8
        assert len(result["texture_parameters"]) == 1
        assert result["texture_parameters"][0]["texture"] == "/Game/Textures/T_Diffuse"

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_get_material_info_script_fallback(self, mock_exec_script):
        """Test graceful fallback when Python script is unavailable."""
        from cli_anything.unreal.core.materials import get_material_info

        mock_api = self._make_mock_api(
            assets={
                "Assets": [{"Name": "TestMat", "Path": "/Game/TestMat.TestMat",
                            "Class": "/Script/Engine.Material",
                            "Metadata": {}}]
            },
            describe={
                "Properties": [{"Name": "BlendMode", "Type": "EBlendMode"}],
                "Functions": [{"Name": "SetBlendMode"}],
            },
        )

        # Script fails (Python plugin not enabled)
        mock_exec_script.return_value = {
            "error": "Script execution timed out or produced no output",
        }

        result = get_material_info(mock_api, "/Game/TestMat")

        # Should still have RC API data
        assert result["name"] == "TestMat"
        # Should have detail_note explaining script failure
        assert "detail_note" in result
        assert "Python script unavailable" in result["detail_note"]
        # Should NOT have nodes (script failed)
        assert "nodes" not in result

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_analyze_material_structure(self, mock_exec_script):
        """Test that analyze_material returns correct structure."""
        from cli_anything.unreal.core.materials import analyze_material

        mock_exec_script.return_value = {"error": "timeout"}

        mock_api = self._make_mock_api(
            assets={
                "Assets": [{"Name": "TestMat", "Path": "/Game/TestMat.TestMat",
                            "Class": "/Script/Engine.Material",
                            "Metadata": {"BlendMode": "BLEND_Opaque", "ShadingModel": "MSM_DefaultLit"}}]
            },
            describe={
                "Properties": [{"Name": "BlendMode", "Type": "EBlendMode"}],
                "Functions": [],
            },
        )

        result = analyze_material(mock_api, "/Game/TestMat")

        assert "issues" in result
        assert "warnings" in result
        assert "stats" in result
        assert isinstance(result["issues"], list)
        assert isinstance(result["warnings"], list)

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_analyze_material_high_textures(self, mock_exec_script):
        """Test detection of high texture sample count."""
        from cli_anything.unreal.core.materials import analyze_material

        mock_exec_script.return_value = {
            "node_count": 50,
            "texture_sample_count": 18,
            "textures": [{"name": f"T_{i}", "path": f"/Game/T_{i}", "node_type": "MaterialExpressionTextureSample"} for i in range(18)],
            "nodes": [{"type": "MaterialExpressionTextureSample", "name": f"TS_{i}"} for i in range(18)],
        }

        mock_api = self._make_mock_api(
            assets={
                "Assets": [{"Name": "HeavyMat", "Path": "/Game/HeavyMat.HeavyMat",
                            "Class": "/Script/Engine.Material",
                            "Metadata": {"BlendMode": "BLEND_Opaque"}}]
            },
            describe={"Properties": [], "Functions": []},
        )

        result = analyze_material(mock_api, "/Game/HeavyMat")
        assert "issues" in result
        assert "stats" in result
        assert result["stats"]["texture_sample_count"] == 18
        # Should detect >16 texture samples as an issue
        assert any("exceeds" in issue.lower() or "texture sample" in issue.lower()
                    for issue in result["issues"])

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_analyze_material_high_node_count(self, mock_exec_script):
        """Test detection of very high node count."""
        from cli_anything.unreal.core.materials import analyze_material

        mock_exec_script.return_value = {
            "node_count": 250,
            "texture_sample_count": 4,
            "textures": [],
            "nodes": [{"type": "MaterialExpressionAdd", "name": f"Add_{i}"} for i in range(250)],
        }

        mock_api = self._make_mock_api(
            assets={
                "Assets": [{"Name": "ComplexMat", "Path": "/Game/ComplexMat.ComplexMat",
                            "Class": "/Script/Engine.Material",
                            "Metadata": {}}]
            },
            describe={"Properties": [], "Functions": []},
        )

        result = analyze_material(mock_api, "/Game/ComplexMat")
        assert any("node count" in issue.lower() for issue in result["issues"])

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_analyze_material_missing_texture(self, mock_exec_script):
        """Test detection of missing texture references."""
        from cli_anything.unreal.core.materials import analyze_material

        mock_exec_script.return_value = {
            "node_count": 3,
            "texture_sample_count": 2,
            "textures": [
                {"name": "T_Good", "path": "/Game/T_Good", "node_type": "MaterialExpressionTextureSample"},
                {"name": None, "path": None, "node_type": "MaterialExpressionTextureSample"},
            ],
            "nodes": [],
        }

        mock_api = self._make_mock_api(
            assets={
                "Assets": [{"Name": "BrokenMat", "Path": "/Game/BrokenMat.BrokenMat",
                            "Class": "/Script/Engine.Material",
                            "Metadata": {}}]
            },
            describe={"Properties": [], "Functions": []},
        )

        result = analyze_material(mock_api, "/Game/BrokenMat")
        assert any("missing texture" in issue.lower() for issue in result["issues"])

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_analyze_material_error(self, mock_exec_script):
        """Test handling of material not found."""
        from cli_anything.unreal.core.materials import analyze_material

        mock_exec_script.return_value = {"error": "timeout"}

        mock_api = self._make_mock_api(
            describe={"errorMessage": "Object not found"},
        )

        result = analyze_material(mock_api, "/Game/Missing")
        # With no assets found and describe failing, should get error in info
        assert "issues" in result or "error" in result.get("info", {})

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_material_texture_list_with_nodes(self, mock_exec_script):
        """Test texture list merges node textures and parameter textures."""
        from cli_anything.unreal.core.materials import get_material_texture_list

        mock_exec_script.return_value = {
            "textures": [
                {"name": "T_Diffuse", "path": "/Game/T_Diffuse", "node_type": "MaterialExpressionTextureSample"},
            ],
            "texture_sample_count": 1,
            "texture_parameters": [
                {"name": "DetailTexture", "texture": "/Game/T_Detail"},
            ],
        }

        mock_api = self._make_mock_api(
            assets={
                "Assets": [{"Name": "M_Test", "Path": "/Game/M_Test.M_Test",
                            "Class": "/Script/Engine.Material", "Metadata": {}}]
            },
            describe={"Properties": [], "Functions": []},
        )

        result = get_material_texture_list(mock_api, "/Game/M_Test")
        assert "textures" in result
        assert len(result["textures"]) == 2  # 1 node texture + 1 parameter texture

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_material_info_cli(self, mock_exec_script):
        """Test material info via CLI with --json output."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_exec_script.return_value = {
            "nodes": [
                {"type": "MaterialExpressionConstant", "name": "Const_0"},
            ],
            "node_count": 1,
        }

        runner = CliRunner()
        # This will fail to connect to editor — but we patch the whole chain
        with patch("cli_anything.unreal.commands.material.require_editor") as mock_editor:
            mock_api = self._make_mock_api(
                assets={
                    "Assets": [{"Name": "M_Test", "Path": "/Game/M_Test.M_Test",
                                "Class": "/Script/Engine.Material", "Metadata": {}}]
                },
                describe={"Properties": [{"Name": "BlendMode", "Type": "EBlendMode"}], "Functions": []},
            )
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--json", "material", "info", "/Game/M_Test",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "nodes" in data
            assert data["node_count"] == 1


# ═══════════════════════════════════════════════════════════════════════
#  Test material connections (core/materials.py get_material_connections)
# ═══════════════════════════════════════════════════════════════════════

class TestMaterialConnections:
    """Tests for get_material_connections — BFS connected/orphan logic."""

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_connections_with_edges(self, mock_exec_script):
        """Nodes reachable from material outputs via edges are connected."""
        from cli_anything.unreal.core.materials import get_material_connections

        mock_api = MagicMock()
        # A -> B -> MaterialOutput.BaseColor, C is orphan
        mock_exec_script.return_value = {
            "name": "TestMat", "path": "/Game/TestMat", "class": "Material",
            "nodes": [
                {"type": "MaterialExpressionConstant", "name": "A"},
                {"type": "MaterialExpressionMultiply", "name": "B"},
                {"type": "MaterialExpressionConstant", "name": "C_Orphan"},
            ],
            "node_count": 3,
            "material_outputs": {
                "BaseColor": {"node": "B", "node_type": "MaterialExpressionMultiply", "output": ""},
            },
            "edges": [
                {"from_node": "A", "to_node": "B", "to_input_index": 0},
            ],
            "textures": [], "texture_sample_count": 0,
        }

        result = get_material_connections(mock_api, "/Game/TestMat")

        assert set(result["connected_nodes"]) == {"A", "B"}
        assert result["orphan_nodes"] == ["C_Orphan"]
        assert result["orphan_count"] == 1
        assert len(result["edges"]) == 1

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_connections_custom_output_node(self, mock_exec_script):
        """Custom output nodes (e.g. SLW) are treated as seeds."""
        from cli_anything.unreal.core.materials import get_material_connections

        mock_api = MagicMock()
        # D -> SLWOutput (custom output), no standard material_outputs
        mock_exec_script.return_value = {
            "name": "M_SLW", "path": "/Game/M_SLW", "class": "Material",
            "nodes": [
                {"type": "MaterialExpressionConstant3Vector", "name": "D"},
                {"type": "MaterialExpressionSingleLayerWaterMaterialOutput", "name": "SLWOutput"},
                {"type": "MaterialExpressionConstant", "name": "E_Orphan"},
            ],
            "node_count": 3,
            "material_outputs": {},
            "edges": [
                {"from_node": "D", "to_node": "SLWOutput", "to_input_index": 0},
            ],
            "textures": [], "texture_sample_count": 0,
        }

        result = get_material_connections(mock_api, "/Game/M_SLW")

        assert set(result["connected_nodes"]) == {"D", "SLWOutput"}
        assert result["orphan_nodes"] == ["E_Orphan"]

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_connections_deep_chain(self, mock_exec_script):
        """Multi-hop chains are fully traversed."""
        from cli_anything.unreal.core.materials import get_material_connections

        mock_api = MagicMock()
        # Tex -> Custom -> Multiply -> Output.WPO
        mock_exec_script.return_value = {
            "name": "M", "path": "/Game/M", "class": "Material",
            "nodes": [
                {"type": "MaterialExpressionTextureSample", "name": "Tex"},
                {"type": "MaterialExpressionCustom", "name": "Custom"},
                {"type": "MaterialExpressionMultiply", "name": "Mul"},
            ],
            "node_count": 3,
            "material_outputs": {
                "WorldPositionOffset": {"node": "Mul", "node_type": "MaterialExpressionMultiply", "output": ""},
            },
            "edges": [
                {"from_node": "Tex", "to_node": "Custom", "to_input_index": 0},
                {"from_node": "Custom", "to_node": "Mul", "to_input_index": 0},
            ],
            "textures": [], "texture_sample_count": 0,
        }

        result = get_material_connections(mock_api, "/Game/M")

        assert set(result["connected_nodes"]) == {"Tex", "Custom", "Mul"}
        assert result["orphan_nodes"] == []

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_connections_no_edges_fallback(self, mock_exec_script):
        """When no edges data, only material_outputs seeds are connected."""
        from cli_anything.unreal.core.materials import get_material_connections

        mock_api = MagicMock()
        mock_exec_script.return_value = {
            "name": "M", "path": "/Game/M", "class": "Material",
            "nodes": [
                {"type": "MaterialExpressionConstant", "name": "X"},
                {"type": "MaterialExpressionConstant", "name": "Y"},
            ],
            "node_count": 2,
            "material_outputs": {
                "BaseColor": {"node": "X", "node_type": "MaterialExpressionConstant", "output": ""},
            },
            "textures": [], "texture_sample_count": 0,
        }

        result = get_material_connections(mock_api, "/Game/M")

        assert result["connected_nodes"] == ["X"]
        assert result["orphan_nodes"] == ["Y"]


# ═══════════════════════════════════════════════════════════════════════
#  Test material editing (core/materials.py editing functions)
# ═══════════════════════════════════════════════════════════════════════

class TestMaterialEditing:
    """Tests for material editing functions — mocked script execution."""

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_add_node(self, mock_exec):
        from cli_anything.unreal.core.materials import add_material_node

        mock_exec.return_value = {
            "status": "ok",
            "action": "add_node",
            "material": "/Game/M_Test",
            "node": {"name": "Constant3Vector_0", "type": "MaterialExpressionConstant3Vector"},
        }

        api = MagicMock()
        result = add_material_node(api, "/Game/M_Test", "MaterialExpressionConstant3Vector", pos_x=100, pos_y=-200)

        assert result["status"] == "ok"
        assert result["node"]["type"] == "MaterialExpressionConstant3Vector"
        # Verify _exec_material_script was called with correct template args
        call_kwargs = mock_exec.call_args
        assert "MaterialExpressionConstant3Vector" in str(call_kwargs)

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_add_node_invalid_class(self, mock_exec):
        from cli_anything.unreal.core.materials import add_material_node

        mock_exec.return_value = {
            "error": "Failed to create expression. Class 'unreal.FakeClass' may not exist."
        }

        api = MagicMock()
        result = add_material_node(api, "/Game/M_Test", "FakeClass")
        assert "error" in result

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_delete_node(self, mock_exec):
        from cli_anything.unreal.core.materials import delete_material_node

        mock_exec.return_value = {
            "status": "ok",
            "action": "delete_node",
            "material": "/Game/M_Test",
            "deleted_node": "Constant3Vector_0",
        }

        api = MagicMock()
        result = delete_material_node(api, "/Game/M_Test", "Constant3Vector_0")
        assert result["status"] == "ok"
        assert result["deleted_node"] == "Constant3Vector_0"

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_delete_node_not_found(self, mock_exec):
        from cli_anything.unreal.core.materials import delete_material_node

        mock_exec.return_value = {
            "error": "Node not found: BadName",
            "available_nodes": ["Constant3Vector_0", "TextureSample_0"],
        }

        api = MagicMock()
        result = delete_material_node(api, "/Game/M_Test", "BadName")
        assert "error" in result
        assert "available_nodes" in result

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_connect_nodes(self, mock_exec):
        from cli_anything.unreal.core.materials import connect_material_nodes

        mock_exec.return_value = {
            "status": "ok",
            "action": "connect",
            "from": "Constant3Vector_0",
            "to": "MaterialOutput.BaseColor",
        }

        api = MagicMock()
        result = connect_material_nodes(
            api, "/Game/M_Test",
            "Constant3Vector_0", "", "__material_output__", "BaseColor",
        )
        assert result["status"] == "ok"
        assert "BaseColor" in result["to"]

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_connect_between_expressions(self, mock_exec):
        from cli_anything.unreal.core.materials import connect_material_nodes

        mock_exec.return_value = {
            "status": "ok",
            "action": "connect",
            "from": "Multiply_0",
            "from_output": "",
            "to": "TextureSample_0",
            "to_input": "UVs",
        }

        api = MagicMock()
        result = connect_material_nodes(
            api, "/Game/M_Test",
            "Multiply_0", "", "TextureSample_0", "UVs",
        )
        assert result["status"] == "ok"
        assert result["to"] == "TextureSample_0"

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_disconnect_nodes(self, mock_exec):
        from cli_anything.unreal.core.materials import disconnect_material_nodes

        mock_exec.return_value = {
            "status": "ok",
            "action": "disconnect",
            "from": "Constant3Vector_0",
            "to": "MaterialOutput.BaseColor",
        }

        api = MagicMock()
        result = disconnect_material_nodes(
            api, "/Game/M_Test",
            "Constant3Vector_0", "", "__material_output__", "BaseColor",
        )
        assert result["status"] == "ok"

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_set_param_scalar(self, mock_exec):
        from cli_anything.unreal.core.materials import set_material_param

        mock_exec.return_value = {
            "status": "ok",
            "action": "set_param",
            "material": "/Game/MI_Test",
            "param": "Roughness",
            "type": "scalar",
            "value": 0.5,
        }

        api = MagicMock()
        result = set_material_param(api, "/Game/MI_Test", "Roughness", "0.5", "scalar")
        assert result["status"] == "ok"
        assert result["value"] == 0.5

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_set_param_vector(self, mock_exec):
        from cli_anything.unreal.core.materials import set_material_param

        mock_exec.return_value = {
            "status": "ok",
            "action": "set_param",
            "material": "/Game/MI_Test",
            "param": "BaseColor",
            "type": "vector",
            "value": {"r": 1.0, "g": 0.0, "b": 0.0, "a": 1.0},
        }

        api = MagicMock()
        result = set_material_param(
            api, "/Game/MI_Test", "BaseColor",
            '{"r":1,"g":0,"b":0,"a":1}', "vector",
        )
        assert result["status"] == "ok"
        assert result["value"]["r"] == 1.0

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_set_param_texture(self, mock_exec):
        from cli_anything.unreal.core.materials import set_material_param

        mock_exec.return_value = {
            "status": "ok",
            "action": "set_param",
            "material": "/Game/MI_Test",
            "param": "DiffuseTexture",
            "type": "texture",
            "value": "/Game/Textures/T_Diffuse",
        }

        api = MagicMock()
        result = set_material_param(
            api, "/Game/MI_Test", "DiffuseTexture",
            "/Game/Textures/T_Diffuse", "texture",
        )
        assert result["status"] == "ok"

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_set_param_on_non_mi(self, mock_exec):
        from cli_anything.unreal.core.materials import set_material_param

        mock_exec.return_value = {
            "error": "Asset is not a MaterialInstanceConstant (set-param only works on MI): /Game/M_Test"
        }

        api = MagicMock()
        result = set_material_param(api, "/Game/M_Test", "Roughness", "0.5", "scalar")
        assert "error" in result
        assert "MaterialInstanceConstant" in result["error"]

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_recompile(self, mock_exec):
        from cli_anything.unreal.core.materials import recompile_material

        mock_exec.return_value = {
            "status": "ok",
            "action": "recompile",
            "material": "/Game/M_Test",
        }

        api = MagicMock()
        result = recompile_material(api, "/Game/M_Test")
        assert result["status"] == "ok"

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_recompile_not_found(self, mock_exec):
        from cli_anything.unreal.core.materials import recompile_material

        mock_exec.return_value = {"error": "Material not found: /Game/Missing"}

        api = MagicMock()
        result = recompile_material(api, "/Game/Missing")
        assert "error" in result

    # ── CLI command tests ──────────────────────────────────────────────

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_add_node_cli(self, mock_exec):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_exec.return_value = {
            "status": "ok",
            "action": "add_node",
            "material": "/Game/M_Test",
            "node": {"name": "Constant_0", "type": "MaterialExpressionConstant"},
        }

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.material.require_editor") as mock_editor:
            mock_editor.return_value = MagicMock()
            result = runner.invoke(cli, [
                "--json", "material", "add-node", "/Game/M_Test",
                "--type", "MaterialExpressionConstant",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"
            assert data["node"]["type"] == "MaterialExpressionConstant"

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_connect_cli(self, mock_exec):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_exec.return_value = {
            "status": "ok",
            "action": "connect",
            "from": "Constant3Vector_0",
            "to": "MaterialOutput.BaseColor",
        }

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.material.require_editor") as mock_editor:
            mock_editor.return_value = MagicMock()
            result = runner.invoke(cli, [
                "--json", "material", "connect", "/Game/M_Test",
                "--from", "Constant3Vector_0",
                "--to", "__material_output__",
                "--to-input", "BaseColor",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_set_param_cli(self, mock_exec):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_exec.return_value = {
            "status": "ok",
            "action": "set_param",
            "param": "Roughness",
            "type": "scalar",
            "value": 0.8,
        }

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.material.require_editor") as mock_editor:
            mock_editor.return_value = MagicMock()
            result = runner.invoke(cli, [
                "--json", "material", "set-param", "/Game/MI_Test",
                "--name", "Roughness",
                "--value", "0.8",
                "--type", "scalar",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    def test_recompile_cli(self, mock_exec):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_exec.return_value = {
            "status": "ok",
            "action": "recompile",
            "material": "/Game/M_Test",
        }

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.material.require_editor") as mock_editor:
            mock_editor.return_value = MagicMock()
            result = runner.invoke(cli, [
                "--json", "material", "recompile", "/Game/M_Test",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════
#  Test screenshot.py (mocked)
# ═══════════════════════════════════════════════════════════════════════

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
                "--json",
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
        assert data.get("status") == "ok"
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
            "--json", "project", "info",
            "--project", temp_project["uproject"],
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "TestProject"

    def test_project_config_list(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--json", "--project", temp_project["uproject"],
            "project", "config", "list",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2

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
                "--json", "--project", temp_project["uproject"],
                "asset", "list",
            ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 4

    def test_editor_status_offline(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--json", "--port", "19999",
            "editor", "status",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        # Empty port vs running-but-blocked API both resolve to non-online.
        assert data["status"] in ("offline", "offline_api_blocked")

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
            "--json", "--project", temp_project["uproject"],
            "editor", "status",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "startup_precheck" in data
        assert data["startup_precheck"]["ready"] is False
        assert data["startup_precheck"]["errors"] == ["engine error", "project error"]
        assert data["startup_precheck"]["warnings"] == ["engine warning"]

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
                "--json", "--project", temp_project["uproject"],
                "editor", "status",
            ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "offline_api_blocked"
        assert data["log_error"] == "Plugin 'libzstd' failed to load"
        assert data["running_editors"][0]["pid"] == 1234
        assert data["startup_precheck"]["ready"] is True

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
            "--json", "--project", temp_project["uproject"],
            "editor", "launch", "--no-wait",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "preflight_failed"
        assert data["startup_precheck"]["ready"] is False
        assert data["startup_precheck"]["errors"] == ["engine error", "project error"]
        assert data["startup_precheck"]["warnings"] == ["engine warning"]

    @patch("cli_anything.unreal.commands.editor._check_port_in_use", return_value=None)
    @patch("cli_anything.unreal.commands.editor._check_already_running", return_value=None)
    @patch("cli_anything.unreal.commands.editor._deploy_bridge", return_value={"deployed": False})
    @patch("cli_anything.unreal.commands.editor._run_preflight")
    @patch("cli_anything.unreal.utils.ue_backend.find_editor_exe", return_value="F:/MockEngine/Engine/Binaries/Win64/UnrealEditor.exe")
    @patch("cli_anything.unreal.utils.ue_backend.find_engine_root", return_value="F:/MockEngine")
    @patch("cli_anything.unreal.commands.editor.sp.Popen")
    def test_editor_launch_success_includes_startup_precheck(
        self,
        mock_popen,
        _mock_find_engine_root,
        _mock_find_editor_exe,
        mock_run_preflight,
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

        mock_run_preflight.return_value = {
            "ready": True,
            "engine": {"errors": [], "warnings": ["engine warning"]},
            "project": {"errors": [], "warnings": ["project warning"]},
        }

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--json", "--project", temp_project["uproject"],
            "editor", "launch", "--no-wait",
        ])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "launched"
        assert data["pid"] == 12345
        assert data["startup_precheck"]["ready"] is True
        assert data["startup_precheck"]["errors"] == []
        assert data["startup_precheck"]["warnings"] == ["engine warning", "project warning"]

    def test_session_status(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--json", "--project", temp_project["uproject"],
            "session", "status",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["project"] == "TestProject"

    def test_build_status(self, temp_project):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--json", "--project", temp_project["uproject"],
            "build", "status",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["project"] == "TestProject"
        assert data["has_binaries"] is True

    def test_port_option(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--json", "--port", "30015",
            "editor", "status",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["port"] == 30015


# ═══════════════════════════════════════════════════════════════════════
#  Test blueprint.py (mocked)
# ═══════════════════════════════════════════════════════════════════════

class TestBlueprint:
    """Tests for core/blueprint.py — mocked script execution."""

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_list_blueprints(self, mock_exec):
        from cli_anything.unreal.core.blueprint import list_blueprints

        mock_api = MagicMock()
        mock_api.search_assets.return_value = {
            "Assets": [
                {"Name": "BP_Player", "Path": "/Game/BP_Player.BP_Player",
                 "Class": "/Script/Engine.Blueprint", "Metadata": {}},
                {"Name": "BP_Enemy", "Path": "/Game/BP_Enemy.BP_Enemy",
                 "Class": "/Script/Engine.Blueprint", "Metadata": {}},
            ]
        }

        result = list_blueprints(mock_api, "/Game/")
        assert "blueprints" in result
        assert len(result["blueprints"]) == 2
        assert result["blueprints"][0]["name"] == "BP_Player"

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_list_blueprints_empty(self, mock_exec):
        from cli_anything.unreal.core.blueprint import list_blueprints

        mock_api = MagicMock()
        mock_api.search_assets.return_value = {"Assets": []}

        result = list_blueprints(mock_api, "/Game/")
        assert result["blueprints"] == []

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_get_blueprint_info(self, mock_exec):
        from cli_anything.unreal.core.blueprint import get_blueprint_info

        mock_exec.return_value = {
            "name": "BP_Test",
            "path": "/Game/BP_Test",
            "class": "Blueprint",
            "graphs": [{"name": "EventGraph", "type": "EventGraph"}],
            "graph_count": 1,
            "nodes": [{"name": "K2Node_Event_0", "class": "K2Node_Event"}],
            "node_count": 1,
            "variables": [],
        }

        api = MagicMock()
        result = get_blueprint_info(api, "/Game/BP_Test")
        assert result["name"] == "BP_Test"
        assert result["graph_count"] == 1
        assert result["node_count"] == 1

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_get_blueprint_info_not_found(self, mock_exec):
        from cli_anything.unreal.core.blueprint import get_blueprint_info

        mock_exec.return_value = {"error": "Blueprint not found: /Game/Missing"}

        api = MagicMock()
        result = get_blueprint_info(api, "/Game/Missing")
        assert "error" in result

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_add_function(self, mock_exec):
        from cli_anything.unreal.core.blueprint import add_function

        mock_exec.return_value = {
            "status": "ok",
            "action": "add_function",
            "blueprint": "/Game/BP_Test",
            "function": "MyFunc",
            "graph_name": "MyFunc",
        }

        api = MagicMock()
        result = add_function(api, "/Game/BP_Test", "MyFunc")
        assert result["status"] == "ok"
        assert result["function"] == "MyFunc"

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_add_function_error(self, mock_exec):
        from cli_anything.unreal.core.blueprint import add_function

        mock_exec.return_value = {"error": "Blueprint not found: /Game/Missing"}

        api = MagicMock()
        result = add_function(api, "/Game/Missing", "MyFunc")
        assert "error" in result

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_remove_function(self, mock_exec):
        from cli_anything.unreal.core.blueprint import remove_function

        mock_exec.return_value = {
            "status": "ok",
            "action": "remove_function",
            "blueprint": "/Game/BP_Test",
            "function": "MyFunc",
        }

        api = MagicMock()
        result = remove_function(api, "/Game/BP_Test", "MyFunc")
        assert result["status"] == "ok"
        assert result["function"] == "MyFunc"

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_remove_function_not_found(self, mock_exec):
        from cli_anything.unreal.core.blueprint import remove_function

        mock_exec.return_value = {"error": "Function graph not found: BadFunc"}

        api = MagicMock()
        result = remove_function(api, "/Game/BP_Test", "BadFunc")
        assert "error" in result

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_add_variable(self, mock_exec):
        from cli_anything.unreal.core.blueprint import add_variable

        mock_exec.return_value = {
            "status": "ok",
            "action": "add_variable",
            "blueprint": "/Game/BP_Test",
            "variable": "Health",
            "type": "float",
        }

        api = MagicMock()
        result = add_variable(api, "/Game/BP_Test", "Health", "float")
        assert result["status"] == "ok"
        assert result["variable"] == "Health"
        assert result["type"] == "float"

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_add_variable_bad_type(self, mock_exec):
        from cli_anything.unreal.core.blueprint import add_variable

        mock_exec.return_value = {
            "error": "Unknown variable type: badtype. Valid types: bool, int, float, string, text, name, vector, rotator, transform"
        }

        api = MagicMock()
        result = add_variable(api, "/Game/BP_Test", "Var1", "badtype")
        assert "error" in result

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_remove_unused_variables(self, mock_exec):
        from cli_anything.unreal.core.blueprint import remove_unused_variables

        mock_exec.return_value = {
            "status": "ok",
            "action": "remove_unused_variables",
            "blueprint": "/Game/BP_Test",
            "removed_count": 3,
        }

        api = MagicMock()
        result = remove_unused_variables(api, "/Game/BP_Test")
        assert result["status"] == "ok"
        assert result["removed_count"] == 3

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_compile_blueprint(self, mock_exec):
        from cli_anything.unreal.core.blueprint import compile_blueprint

        mock_exec.return_value = {
            "status": "ok",
            "action": "compile",
            "blueprint": "/Game/BP_Test",
        }

        api = MagicMock()
        result = compile_blueprint(api, "/Game/BP_Test")
        assert result["status"] == "ok"
        assert result["action"] == "compile"

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_compile_blueprint_not_found(self, mock_exec):
        from cli_anything.unreal.core.blueprint import compile_blueprint

        mock_exec.return_value = {"error": "Blueprint not found: /Game/Missing"}

        api = MagicMock()
        result = compile_blueprint(api, "/Game/Missing")
        assert "error" in result

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_rename_graph(self, mock_exec):
        from cli_anything.unreal.core.blueprint import rename_graph

        mock_exec.return_value = {
            "status": "ok",
            "action": "rename_graph",
            "blueprint": "/Game/BP_Test",
            "old_name": "OldFunc",
            "new_name": "NewFunc",
        }

        api = MagicMock()
        result = rename_graph(api, "/Game/BP_Test", "OldFunc", "NewFunc")
        assert result["status"] == "ok"
        assert result["old_name"] == "OldFunc"
        assert result["new_name"] == "NewFunc"

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_rename_graph_not_found(self, mock_exec):
        from cli_anything.unreal.core.blueprint import rename_graph

        mock_exec.return_value = {"error": "Graph not found: BadGraph"}

        api = MagicMock()
        result = rename_graph(api, "/Game/BP_Test", "BadGraph", "NewName")
        assert "error" in result

    # ── CLI command tests ──────────────────────────────────────────────

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_blueprint_list_cli(self, mock_exec):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.blueprint.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.search_assets.return_value = {
                "Assets": [
                    {"Name": "BP_Test", "Path": "/Game/BP_Test.BP_Test",
                     "Class": "/Script/Engine.Blueprint", "Metadata": {}},
                ]
            }
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, ["--json", "blueprint", "list"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "blueprints" in data
            assert len(data["blueprints"]) == 1

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_blueprint_info_cli(self, mock_exec):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_exec.return_value = {
            "name": "BP_Test",
            "path": "/Game/BP_Test",
            "graphs": [{"name": "EventGraph", "type": "EventGraph"}],
            "graph_count": 1,
            "nodes": [],
            "node_count": 0,
        }

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.blueprint.require_editor") as mock_editor:
            mock_editor.return_value = MagicMock()
            result = runner.invoke(cli, [
                "--json", "blueprint", "info", "/Game/BP_Test",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["name"] == "BP_Test"

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_blueprint_add_function_cli(self, mock_exec):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_exec.return_value = {
            "status": "ok",
            "action": "add_function",
            "blueprint": "/Game/BP_Test",
            "function": "MyFunc",
        }

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.blueprint.require_editor") as mock_editor:
            mock_editor.return_value = MagicMock()
            result = runner.invoke(cli, [
                "--json", "blueprint", "add-function", "/Game/BP_Test",
                "--name", "MyFunc",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_blueprint_add_variable_cli(self, mock_exec):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_exec.return_value = {
            "status": "ok",
            "action": "add_variable",
            "variable": "Health",
            "type": "float",
        }

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.blueprint.require_editor") as mock_editor:
            mock_editor.return_value = MagicMock()
            result = runner.invoke(cli, [
                "--json", "blueprint", "add-variable", "/Game/BP_Test",
                "--name", "Health", "--type", "float",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"
            assert data["variable"] == "Health"

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_blueprint_compile_cli(self, mock_exec):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_exec.return_value = {
            "status": "ok",
            "action": "compile",
            "blueprint": "/Game/BP_Test",
        }

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.blueprint.require_editor") as mock_editor:
            mock_editor.return_value = MagicMock()
            result = runner.invoke(cli, [
                "--json", "blueprint", "compile", "/Game/BP_Test",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"

    @patch("cli_anything.unreal.core.blueprint._exec_blueprint_script")
    def test_blueprint_rename_graph_cli(self, mock_exec):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_exec.return_value = {
            "status": "ok",
            "action": "rename_graph",
            "old_name": "OldFunc",
            "new_name": "NewFunc",
        }

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.blueprint.require_editor") as mock_editor:
            mock_editor.return_value = MagicMock()
            result = runner.invoke(cli, [
                "--json", "blueprint", "rename-graph", "/Game/BP_Test",
                "--old", "OldFunc", "--new", "NewFunc",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"
            assert data["new_name"] == "NewFunc"


# ═══════════════════════════════════════════════════════════════════════
#  Script Runner
# ═══════════════════════════════════════════════════════════════════════

class TestScriptRunner:
    """Tests for core.script_runner — generic Python execution with result capture.

    The script runner now uses ``api.exec_python_ex()`` under the hood, which
    calls ``PythonScriptLibrary.ExecutePythonCommandEx`` via Remote Control.

    Tests mock ``api.exec_python_ex`` to simulate the UE response format::

        {"ReturnValue": True, "CommandResult": "None",
         "LogOutput": [{"Type": "Info", "Output": "..."}]}
    """

    @staticmethod
    def _make_exec_python_ex_mock(mock_api):
        """Wire up ``mock_api.exec_python_ex`` to locally execute the wrapper
        code (with a fake ``unreal`` module) and return a realistic response.

        Captures ``unreal.log()`` calls from the wrapper to produce
        ``LogOutput`` entries, just like the real UE editor.
        """
        import types

        def _fake_exec_python_ex(code, *, timeout=None):
            log_entries = []
            fake_unreal = types.ModuleType("unreal")
            fake_unreal.log = lambda msg: log_entries.append(
                {"Type": "Info", "Output": msg}
            )

            import sys
            old_unreal = sys.modules.get("unreal")
            sys.modules["unreal"] = fake_unreal
            try:
                exec(compile(code, "<exec_python_ex>", "exec"))
                return {
                    "ReturnValue": True,
                    "CommandResult": "None",
                    "LogOutput": log_entries,
                }
            except Exception as exc:
                return {
                    "ReturnValue": False,
                    "CommandResult": str(exc),
                    "LogOutput": log_entries,
                }
            finally:
                if old_unreal is not None:
                    sys.modules["unreal"] = old_unreal
                else:
                    sys.modules.pop("unreal", None)

        mock_api.exec_python_ex.side_effect = _fake_exec_python_ex

    # -- run_python_script / run_python_code internals ------------------

    def test_run_python_script_captures_result(self, tmp_path):
        """When user script defines ``result``, it should be captured."""
        from cli_anything.unreal.core.script_runner import run_python_script

        script = tmp_path / "test.py"
        script.write_text("result = {'hello': 'world', 'count': 42}\n", encoding="utf-8")

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_script(mock_api, str(script), timeout=5, save=False)
        assert result["hello"] == "world"
        assert result["count"] == 42

    def test_run_python_code_captures_result(self):
        """``run_python_code`` with inline code and a result variable."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(mock_api, "result = {'actors': 99}",
                                 timeout=5, save=False)
        assert result["actors"] == 99

    def test_no_result_variable(self):
        """When user script does NOT define ``result``, a generic ok is returned."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(mock_api, "x = 1 + 1",
                                 timeout=5, save=False)
        assert result["status"] == "ok"

    # -- stdout hijack tests ---------------------------------------------

    def test_stdout_captured(self):
        """print() output should be captured in the 'stdout' field."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            'print("Hello World")',
            timeout=5, save=False,
        )
        assert result["stdout"] == "Hello World\n"
        assert result["status"] == "ok"

    def test_stdout_captured_with_result_dict(self):
        """Both stdout and result dict keys should be present."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            'print("Hello World"); result = {"data": 123}',
            timeout=5, save=False,
        )
        assert result["stdout"] == "Hello World\n"
        assert result["data"] == 123

    def test_stdout_captured_with_result_non_dict(self):
        """Non-dict result should be wrapped as 'value' alongside stdout."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            'print("test"); result = 42',
            timeout=5, save=False,
        )
        assert result["stdout"] == "test\n"
        assert result["value"] == "42"

    def test_stdout_empty_when_no_print(self):
        """stdout field should be empty string when no print() is called."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            "result = {'data': 1}",
            timeout=5, save=False,
        )
        assert result["stdout"] == ""
        assert result["data"] == 1

    def test_stdout_multiple_prints(self):
        """Multiple print() calls should all be captured."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            'print("line1"); print("line2"); result = {"ok": True}',
            timeout=5, save=False,
        )
        assert result["stdout"] == "line1\nline2\n"
        assert result["ok"] is True

    def test_stdout_preserved_on_error(self):
        """stdout should still be captured even when script raises an exception."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            'print("before error"); raise ValueError("boom")',
            timeout=5, save=False,
        )
        assert result["stdout"] == "before error\n"
        assert "error" in result
        assert result["error_type"] == "ValueError"

    # -- api_discover tests ----------------------------------------------

    @staticmethod
    def _make_discover_mock(mock_api, fake_unreal_mod):
        """Wire up mock_api.exec_python_ex for api_discover tests.

        Uses the caller-provided fake_unreal_mod (already in sys.modules)
        and collects unreal.log() calls to produce LogOutput entries.
        Uses an explicit namespace for exec() to avoid scope issues.
        """
        def _fake_exec(code, *, timeout=None):
            log_entries = []
            # Override the log method on the already-in-sys.modules fake
            original_log = fake_unreal_mod.log
            fake_unreal_mod.log = lambda msg: log_entries.append(
                {"Type": "Info", "Output": msg}
            )
            try:
                ns = {"__builtins__": __builtins__}
                exec(compile(code, "<discover>", "exec"), ns)
            except Exception as exc:
                return {
                    "ReturnValue": False,
                    "CommandResult": str(exc),
                    "LogOutput": log_entries,
                }
            finally:
                fake_unreal_mod.log = original_log
            return {
                "ReturnValue": True,
                "CommandResult": "None",
                "LogOutput": log_entries,
            }

        mock_api.exec_python_ex.side_effect = _fake_exec

    @staticmethod
    def _make_fake_bridge(class_info_map):
        """Create a fake CliAnythingBridgeLibrary with get_class_info.

        class_info_map: dict mapping class_name -> dict with "properties" and "functions".
        """
        import json as _json
        class FakeBridge:
            @staticmethod
            def get_class_info(class_name, include_inherited):
                data = class_info_map.get(class_name)
                if data is None:
                    return "{}"
                return _json.dumps(data)
        return FakeBridge

    def test_api_discover_basic(self):
        """api_discover overview should return property/function names only."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types, sys

        bridge_data = {
            "EditorLevelLibrary": {
                "class": "EditorLevelLibrary",
                "properties": [
                    {"name": "some_property", "type": "int32", "owner": "EditorLevelLibrary",
                     "category": "EditorLevelLibrary", "read": True, "write": True}
                ],
                "functions": [
                    {"name": "get_all_level_actors", "owner": "EditorLevelLibrary",
                     "tooltip": "Returns all actors.", "return_type": "TArray",
                     "params": []},
                    {"name": "get_editor_world", "owner": "EditorLevelLibrary",
                     "tooltip": "Returns the Editor World.", "return_type": "UWorld*",
                     "params": []},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api, "unreal.EditorLevelLibrary",
                timeout=5,
            )
            assert result["target_name"] == "EditorLevelLibrary"
            assert result["full_path"] == "unreal.EditorLevelLibrary"
            # Overview returns plain name lists
            assert result["properties"] == ["some_property"]
            assert "get_all_level_actors" in result["functions"]
            assert "get_editor_world" in result["functions"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_short_name(self):
        """api_discover should accept short names (without 'unreal.' prefix)."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types, sys

        bridge_data = {
            "Actor": {
                "class": "Actor",
                "properties": [],
                "functions": [],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(mock_api, "Actor", timeout=5)
            assert result["full_path"] == "unreal.Actor"
            assert result["target_name"] == "Actor"
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_query(self):
        """api_discover with query should only return matching names."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types, sys

        bridge_data = {
            "FakeLib": {
                "class": "FakeLib",
                "properties": [],
                "functions": [
                    {"name": "get_all_level_actors", "owner": "FakeLib",
                     "tooltip": "Get actors.", "return_type": "TArray", "params": []},
                    {"name": "get_editor_world", "owner": "FakeLib",
                     "tooltip": "Get world.", "return_type": "UWorld*", "params": []},
                    {"name": "spawn_actor", "owner": "FakeLib",
                     "tooltip": "Spawn.", "return_type": "AActor*", "params": []},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api, "unreal.FakeLib",
                query="get",
                timeout=5,
            )
            # Overview returns plain name lists, filtered
            assert "get_all_level_actors" in result["functions"]
            assert "get_editor_world" in result["functions"]
            assert "spawn_actor" not in result["functions"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_query_regex_alternation(self):
        """query is a regex — alternation picks up multiple prefixes."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()
        import types, sys

        bridge_data = {
            "FakeLib": {
                "class": "FakeLib", "properties": [],
                "functions": [
                    {"name": "create_material_expression", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                    {"name": "connect_material_property", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                    {"name": "recompile_material", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api, "unreal.FakeLib",
                query="create|connect",
                timeout=5,
            )
            assert set(result["functions"]) == {
                "create_material_expression", "connect_material_property",
            }
            # recompile_material must NOT be matched — it's the negative control
            assert "recompile_material" not in result["functions"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_query_regex_anchor(self):
        """query supports anchors (^ for prefix)."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()
        import types, sys

        bridge_data = {
            "FakeLib": {
                "class": "FakeLib", "properties": [],
                "functions": [
                    {"name": "SetIntensity", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                    {"name": "SetColor", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                    {"name": "GetIntensity", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api, "unreal.FakeLib",
                query="^Set",
                timeout=5,
            )
            assert set(result["functions"]) == {"SetIntensity", "SetColor"}
            # GetIntensity is NOT ^Set — even though it contains "Set" as a
            # substring, the regex anchor rules it out
            assert "GetIntensity" not in result["functions"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_query_invalid_regex(self):
        """An invalid regex returns a structured error, not a raw traceback."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()
        import types, sys

        bridge_data = {
            "FakeLib": {
                "class": "FakeLib", "properties": [],
                "functions": [
                    {"name": "anything", "owner": "FakeLib",
                     "tooltip": "", "return_type": "", "params": []},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(
                mock_api, "unreal.FakeLib",
                query="[unclosed",
                timeout=5,
            )
            assert "error" in result
            assert "Invalid regex" in result["error"]
            # Raw filter is echoed back so agents can see what they sent
            assert result.get("query") == "[unclosed"
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_detail_single(self):
        """api_discover detail for a single property/function name."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types, sys

        bridge_data = {
            "SomeClass": {
                "class": "SomeClass",
                "properties": [
                    {"name": "MyProp", "type": "float", "owner": "SomeClass",
                     "category": "SomeClass", "tooltip": "A float property.", "read": True, "write": True}
                ],
                "functions": [
                    {"name": "do_thing", "owner": "SomeClass",
                     "tooltip": "Does a thing.", "return_type": "bool",
                     "params": [{"name": "x", "type": "int32"}]},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)

            # Overview: names only
            result_summary = api_discover(mock_api, "unreal.SomeClass", timeout=5)
            assert result_summary["properties"] == ["MyProp"]
            assert result_summary["functions"] == ["do_thing"]

            # Detail for one property
            result_prop = api_discover(mock_api, "unreal.SomeClass", detail="MyProp", timeout=5)
            assert result_prop["items"][0]["kind"] == "property"
            assert result_prop["items"][0]["detail"]["tooltip"] == "A float property."

            # Detail for one function
            result_func = api_discover(mock_api, "unreal.SomeClass", detail="do_thing", timeout=5)
            assert result_func["items"][0]["kind"] == "function"
            assert result_func["items"][0]["detail"]["params"][0]["name"] == "x"
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_detail_multiple(self):
        """api_discover detail with comma-separated names returns multiple items."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types, sys

        bridge_data = {
            "SomeClass": {
                "class": "SomeClass",
                "properties": [
                    {"name": "Prop1", "type": "float", "owner": "SomeClass",
                     "category": "SomeClass", "tooltip": "P1", "read": True, "write": True}
                ],
                "functions": [
                    {"name": "Func1", "owner": "SomeClass",
                     "tooltip": "F1", "return_type": "void", "params": []},
                ],
            }
        }

        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(mock_api, "unreal.SomeClass", detail="Prop1,Func1,NotFound", timeout=5)
            names = [item["name"] for item in result["items"]]
            assert "Prop1" in names
            assert "Func1" in names
            assert result["not_found"] == ["NotFound"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_unresolvable_target(self):
        """api_discover should return error for unresolvable target."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api = MagicMock()

        import types, sys

        # Empty bridge — get_class_info returns "{}" for everything
        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge({})

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        try:
            self._make_discover_mock(mock_api, fake_unreal)
            result = api_discover(mock_api, "unreal.NonExistentClass", timeout=5)
            assert "error" in result
            assert "Class not found" in result["error"]
        finally:
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

    def test_api_discover_cli(self):
        """editor api-discover CLI should route through api_discover."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.api_discover") as mock_discover:
            mock_editor.return_value = MagicMock()
            mock_discover.return_value = {
                "target_name": "EditorLevelLibrary",
                "full_path": "unreal.EditorLevelLibrary",
                "class": "EditorLevelLibrary",
                "functions": [{"name": "get_editor_world"}],
                "properties": [],
                "function_count": 1,
                "property_count": 0,
                "total_functions_available": 1,
                "truncated": False,
            }

            result = runner.invoke(cli, [
                "--json", "editor", "api-discover", "unreal.EditorLevelLibrary",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["target_name"] == "EditorLevelLibrary"
            mock_discover.assert_called_once()

    def test_api_discover_cli_with_options(self):
        """editor api-discover CLI with -m and -d options."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.api_discover") as mock_discover:
            mock_editor.return_value = MagicMock()
            mock_discover.return_value = {
                "target_name": "Actor",
                "items": [{"kind": "function", "name": "GetOwner", "detail": {}}],
            }

            result = runner.invoke(cli, [
                "--json", "editor", "api-discover",
                "unreal.Actor", "-q", "spawn", "-d", "GetOwner",
            ])
            assert result.exit_code == 0
            mock_discover.assert_called_once()
            call_kw = mock_discover.call_args[1]
            assert call_kw["query"] == "spawn"
            assert call_kw["detail"] == "GetOwner"

    # -- Instance path tests (actor / asset) ----------------------------------

    def _setup_instance_discover(self, bridge_data, *, actors=None, assets=None):
        """Helper: set up fake unreal module with actor/asset support.

        Returns (mock_api, fake_unreal, cleanup) where cleanup restores sys.modules.
        """
        import types, sys

        mock_api = MagicMock()
        fake_unreal = types.ModuleType("unreal")
        fake_unreal.log = lambda msg: None
        fake_unreal.CliAnythingBridgeLibrary = self._make_fake_bridge(bridge_data)

        # Mock EditorActorSubsystem + get_all_level_actors
        fake_actors = actors or []
        fake_subsystem = MagicMock()
        fake_subsystem.get_all_level_actors.return_value = fake_actors
        fake_unreal.EditorActorSubsystem = type("EditorActorSubsystem", (), {})
        fake_unreal.get_editor_subsystem = lambda cls: fake_subsystem

        # Mock EditorAssetLibrary
        assets_map = assets or {}
        fake_asset_lib = MagicMock()
        fake_asset_lib.does_asset_exist.side_effect = lambda p: p in assets_map
        fake_asset_lib.load_asset.side_effect = lambda p: assets_map.get(p)
        fake_unreal.EditorAssetLibrary = fake_asset_lib

        old_unreal = sys.modules.get("unreal")
        sys.modules["unreal"] = fake_unreal
        self._make_discover_mock(mock_api, fake_unreal)

        def cleanup():
            if old_unreal is not None:
                sys.modules["unreal"] = old_unreal
            else:
                sys.modules.pop("unreal", None)

        return mock_api, fake_unreal, cleanup

    def test_inspect_instance_actor(self):
        """api_discover with an actor path should resolve class and return actor context."""
        from cli_anything.unreal.core.script_runner import api_discover

        bridge_data = {
            "PointLight": {
                "class": "PointLight",
                "properties": [
                    {"name": "Intensity", "type": "float", "owner": "PointLight",
                     "read": True, "write": True},
                ],
                "functions": [],
            }
        }

        fake_actor = MagicMock()
        fake_actor.get_path_name.return_value = "/Game/Maps/L.L:PersistentLevel.Light_0"
        fake_actor.get_name.return_value = "Light_0"
        fake_actor.get_actor_label.return_value = "Light_0"
        fake_actor.__class__ = type("PointLight", (), {})

        mock_api, _, cleanup = self._setup_instance_discover(
            bridge_data, actors=[fake_actor],
        )
        try:
            result = api_discover(
                mock_api,
                "/Game/Maps/L.L:PersistentLevel.Light_0",
                timeout=5,
            )
            assert "error" not in result
            assert result["class"] == "PointLight"
            assert result["actor"] == "/Game/Maps/L.L:PersistentLevel.Light_0"
            assert result["actor_name"] == "Light_0"
            assert "Intensity" in result["properties"]
        finally:
            cleanup()

    def test_inspect_instance_actor_not_found(self):
        """api_discover should return error for non-existent actor path."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api, _, cleanup = self._setup_instance_discover(
            {}, actors=[],  # no actors in level
        )
        try:
            result = api_discover(
                mock_api,
                "/Game/Maps/L.L:PersistentLevel.DoesNotExist",
                timeout=5,
            )
            assert "error" in result
            assert "not found" in result["error"].lower()
        finally:
            cleanup()

    def test_inspect_instance_actor_with_filter(self):
        """api_discover actor path + query should filter results."""
        from cli_anything.unreal.core.script_runner import api_discover

        bridge_data = {
            "StaticMeshActor": {
                "class": "StaticMeshActor",
                "properties": [
                    {"name": "StaticMeshComponent", "type": "UStaticMeshComponent*",
                     "owner": "StaticMeshActor", "read": True, "write": False},
                    {"name": "bHidden", "type": "bool",
                     "owner": "StaticMeshActor", "read": True, "write": True},
                ],
                "functions": [
                    {"name": "SetMobility", "owner": "StaticMeshActor",
                     "params": [], "return_type": "void"},
                ],
            }
        }

        fake_actor = MagicMock()
        fake_actor.get_path_name.return_value = "/Game/Maps/L.L:PersistentLevel.Cube_0"
        fake_actor.get_name.return_value = "Cube_0"
        fake_actor.get_actor_label.return_value = "Cube_0"
        fake_actor.__class__ = type("StaticMeshActor", (), {})

        mock_api, _, cleanup = self._setup_instance_discover(
            bridge_data, actors=[fake_actor],
        )
        try:
            result = api_discover(
                mock_api,
                "/Game/Maps/L.L:PersistentLevel.Cube_0",
                query="mesh",
                timeout=5,
            )
            assert "error" not in result
            # "mesh" filter should keep StaticMeshComponent but not bHidden
            assert "StaticMeshComponent" in result["properties"]
            assert "bHidden" not in result["properties"]
        finally:
            cleanup()

    def test_inspect_instance_asset(self):
        """api_discover with an asset path should resolve class and return asset context."""
        from cli_anything.unreal.core.script_runner import api_discover

        bridge_data = {
            "MaterialInstanceConstant": {
                "class": "MaterialInstanceConstant",
                "properties": [
                    {"name": "Parent", "type": "UMaterialInterface*",
                     "owner": "MaterialInstanceConstant", "read": True, "write": False},
                ],
                "functions": [],
            }
        }

        fake_asset = MagicMock()
        fake_asset.__class__ = type("MaterialInstanceConstant", (), {})
        fake_asset.get_path_name.return_value = "/Game/Materials/MI_Water.MI_Water"

        mock_api, _, cleanup = self._setup_instance_discover(
            bridge_data, assets={"/Game/Materials/MI_Water": fake_asset},
        )
        try:
            result = api_discover(
                mock_api,
                "/Game/Materials/MI_Water",
                timeout=5,
            )
            assert "error" not in result
            assert result["class"] == "MaterialInstanceConstant"
            assert result["asset"] == "/Game/Materials/MI_Water"
            assert "Parent" in result["properties"]
        finally:
            cleanup()

    def test_inspect_instance_asset_not_found(self):
        """api_discover should return error for non-existent asset path."""
        from cli_anything.unreal.core.script_runner import api_discover

        mock_api, _, cleanup = self._setup_instance_discover(
            {}, assets={},  # no assets
        )
        try:
            result = api_discover(
                mock_api,
                "/Game/Materials/DoesNotExist",
                timeout=5,
            )
            assert "error" in result
            assert "not found" in result["error"].lower()
        finally:
            cleanup()


    def test_non_dict_result_wrapped(self):
        """A non-dict ``result`` should be wrapped as {"value": ...}."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(mock_api, "result = 'just a string'",
                                 timeout=5, save=False)
        assert result["value"] == "just a string"

    def test_exec_failure_returns_error(self):
        """When exec_python_ex returns ``ReturnValue: false``, an error is returned."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        mock_api.exec_python_ex.return_value = {
            "ReturnValue": False,
            "CommandResult": "SyntaxError: invalid syntax",
            "LogOutput": [],
        }

        result = run_python_code(mock_api, "result = {}", timeout=5)
        assert "error" in result
        assert "SyntaxError" in result["error"]

    def test_http_error_returns_error(self):
        """When exec_python_ex returns an HTTP error, it is forwarded."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        mock_api.exec_python_ex.return_value = {
            "error": "ConnectionError: editor not reachable"
        }

        result = run_python_code(mock_api, "result = {}", timeout=5)
        assert "error" in result
        assert "ConnectionError" in result["error"]

    def test_no_temp_files_created(self, tmp_path):
        """The new transport should not create temp files."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        temp_dir = tmp_path / "Saved" / "Temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        run_python_code(mock_api, "result = {'clean': True}",
                        project_dir=str(tmp_path), timeout=5, save=False)

        remaining = list(temp_dir.iterdir())
        assert remaining == [], f"Unexpected temp files: {remaining}"

    # -- CLI integration tests ------------------------------------------

    def test_editor_exec_py_uses_script_runner(self):
        """``editor exec 'py ...'`` should route through run_python_code."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_editor.return_value = MagicMock()
            mock_run.return_value = {"status": "ok", "actors": 42}

            result = runner.invoke(cli, [
                "--json", "editor", "exec", "py result = {'actors': 42}",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["actors"] == 42
            mock_run.assert_called_once()

    def test_editor_exec_non_py_unchanged(self):
        """Non-Python console commands still go through exec_console."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.exec_console.return_value = {}
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--json", "editor", "exec", "stat fps",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "executed"
            mock_api.exec_console.assert_called_once_with("stat fps")

    def test_editor_run_script_cli(self, tmp_path):
        """``editor run-script`` should call run_python_script."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        script = tmp_path / "test_scene.py"
        script.write_text("result = {'scene': 'built'}\n", encoding="utf-8")

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.editor.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_script") as mock_run:
            mock_editor.return_value = MagicMock()
            mock_run.return_value = {"status": "ok", "scene": "built"}

            result = runner.invoke(cli, [
                "--json", "editor", "run-script", str(script),
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["scene"] == "built"
            mock_run.assert_called_once()

    def test_script_error_captured(self):
        """When user script raises an exception, error details are returned."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        result = run_python_code(
            mock_api,
            "raise ValueError('something went wrong')",
            timeout=5,
            save=False,
        )
        assert "error" in result
        assert "something went wrong" in result["error"]
        assert result["error_type"] == "ValueError"
        assert "traceback" in result

    def test_script_attribute_error_captured(self):
        """Simulate the real-world AttributeError from the UE module scenario."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        code = "import os\n_ = os.nonexistent_attr\n"
        result = run_python_code(mock_api, code, timeout=5, save=False)
        assert "error" in result
        assert result["error_type"] == "AttributeError"

    def test_run_python_code_isolates_user_globals_between_calls(self):
        """Separate invocations should not leak user globals into later runs."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        self._make_exec_python_ex_mock(mock_api)

        first = run_python_code(mock_api, "sticky = 123\nresult = {'ok': True}", timeout=5, save=False)
        second = run_python_code(mock_api, "result = {'sticky_present': 'sticky' in globals()}", timeout=5, save=False)

        assert first["ok"] is True
        assert second["sticky_present"] is False


# ═══════════════════════════════════════════════════════════════════════
#  Test scene.py (mocked API)
# ═══════════════════════════════════════════════════════════════════════

class TestScene:
    """Tests for core/scene.py — mocked editor API."""

    def _mock_api(self):
        api = MagicMock()
        return api

    def test_list_actors(self):
        from cli_anything.unreal.core.scene import list_actors

        api = self._mock_api()
        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {
                "actors": [
                    {"path": "/Game/Map.Map:PersistentLevel.StaticMeshActor_0",
                     "name": "StaticMeshActor_0", "class": "StaticMeshActor"},
                    {"path": "/Game/Map.Map:PersistentLevel.PointLight_1",
                     "name": "PointLight_1", "class": "PointLight"},
                ],
                "count": 2,
            }
            result = list_actors(api)
        assert result["count"] == 2
        assert result["actors"][0]["name"] == "StaticMeshActor_0"
        assert result["actors"][1]["name"] == "PointLight_1"

    def test_list_actors_error(self):
        from cli_anything.unreal.core.scene import list_actors

        api = self._mock_api()
        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {"error": "Not connected"}
            result = list_actors(api)
        assert "error" in result

    def test_list_actors_empty(self):
        from cli_anything.unreal.core.scene import list_actors

        api = self._mock_api()
        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {"actors": [], "count": 0}
            result = list_actors(api)
        assert result["count"] == 0
        assert result["actors"] == []

    def test_list_actors_of_class(self):
        from cli_anything.unreal.core.scene import list_actors_of_class

        api = self._mock_api()
        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {
                "actors": [
                    {"path": "/Game/Map.Map:PersistentLevel.PointLight_0",
                     "name": "PointLight_0", "class": "PointLight"},
                    {"path": "/Game/Map.Map:PersistentLevel.PointLight_1",
                     "name": "PointLight_1", "class": "PointLight"},
                ],
                "count": 2,
            }
            result = list_actors_of_class(api, "PointLight")
        assert result["count"] == 2
        mock_run.assert_called_once()

    def test_list_actors_of_class_error(self):
        from cli_anything.unreal.core.scene import list_actors_of_class

        api = self._mock_api()
        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {"error": "Class not found: BadClass"}
            result = list_actors_of_class(api, "BadClass")
        assert "error" in result

    def test_get_actor_property(self):
        from cli_anything.unreal.core.scene import get_actor_property

        api = self._mock_api()
        api.get_property.return_value = {"RelativeLocation": {"X": 100, "Y": 200, "Z": 50}}

        result = get_actor_property(api, "/Game/Map:Actor_0", "RelativeLocation")
        assert result["RelativeLocation"]["X"] == 100
        api.get_property.assert_called_once_with("/Game/Map:Actor_0", "RelativeLocation")

    def test_set_actor_property(self):
        from cli_anything.unreal.core.scene import set_actor_property

        api = self._mock_api()
        api.set_property.return_value = {"status": "ok"}

        result = set_actor_property(api, "/Game/Map:Actor_0", "bHidden", True)
        assert result["status"] == "ok"
        api.set_property.assert_called_once_with("/Game/Map:Actor_0", "bHidden", True)

        from cli_anything.unreal.core.scene import find_actor_by_name

        api = self._mock_api()
        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {
                "actors": [
                    {"path": "/Game/Map.Map:PersistentLevel.Cube_0",
                     "name": "Cube_0", "class": "StaticMeshActor"},
                    {"path": "/Game/Map.Map:PersistentLevel.CubeRed_1",
                     "name": "CubeRed_1", "class": "StaticMeshActor"},
                ],
                "count": 2,
            }
            result = find_actor_by_name(api, "Cube")
        assert result["count"] == 2
        assert result["query"] == "Cube"
        names = [a["name"] for a in result["actors"]]
        assert "Cube_0" in names
        assert "CubeRed_1" in names

    def test_find_actor_by_name_no_match(self):
        from cli_anything.unreal.core.scene import find_actor_by_name

        api = self._mock_api()
        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {"actors": [], "count": 0}
            result = find_actor_by_name(api, "Cube")
        assert result["count"] == 0
        assert result["query"] == "Cube"

    def test_find_actor_case_insensitive(self):
        from cli_anything.unreal.core.scene import find_actor_by_name

        api = self._mock_api()
        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {
                "actors": [
                    {"path": "/Game/Map.Map:PersistentLevel.MyCube_0",
                     "name": "MyCube_0", "class": "StaticMeshActor"},
                ],
                "count": 1,
            }
            result = find_actor_by_name(api, "mycube")
        assert result["count"] == 1

    def test_find_actor_error(self):
        from cli_anything.unreal.core.scene import find_actor_by_name

        api = self._mock_api()
        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {"error": "No level loaded"}
            result = find_actor_by_name(api, "Cube")
        assert "error" in result

    def test_get_actor_components(self):
        from cli_anything.unreal.core.scene import get_actor_components

        api = self._mock_api()
        api.describe_object.return_value = {
            "Properties": [
                {"Name": "StaticMeshComponent0", "Type": "UStaticMeshComponent*"},
                {"Name": "RootComponent", "Type": "USceneComponent*"},
                {"Name": "bHidden", "Type": "bool"},
            ],
        }

        result = get_actor_components(api, "/Game/Map:Actor_0")
        assert len(result["components"]) == 2
        comp_names = [c["name"] for c in result["components"]]
        assert "StaticMeshComponent0" in comp_names
        assert "RootComponent" in comp_names

    def test_get_actor_components_error(self):
        from cli_anything.unreal.core.scene import get_actor_components

        api = self._mock_api()
        api.describe_object.return_value = {"error": "Object not found"}

        result = get_actor_components(api, "/Game/Map:Missing")
        assert "error" in result

    def test_get_actor_material_single(self):
        from cli_anything.unreal.core.scene import get_actor_material

        api = self._mock_api()
        api.call_function.side_effect = [
            {"ReturnValue": 1},  # GetNumMaterials
            {"ReturnValue": "/Game/M_Test"},  # GetMaterial(0)
        ]
        api.get_property.return_value = {"error": "not found"}

        result = get_actor_material(api, "/Game/Map:Actor_0", 0)
        assert result["num_materials"] == 1
        assert result["material_path"] == "/Game/M_Test"
        assert "all_materials" not in result

    def test_get_actor_material_multiple(self):
        from cli_anything.unreal.core.scene import get_actor_material

        api = self._mock_api()
        api.call_function.side_effect = [
            {"ReturnValue": 3},  # GetNumMaterials
            {"ReturnValue": "/Game/M_0"},  # GetMaterial(0) — initial query
            {"ReturnValue": "/Game/M_0"},  # GetMaterial(0) in loop
            {"ReturnValue": "/Game/M_1"},  # GetMaterial(1) in loop
            {"ReturnValue": "/Game/M_2"},  # GetMaterial(2) in loop
        ]
        api.get_property.return_value = {"error": "not found"}

        result = get_actor_material(api, "/Game/Map:Actor_0", 0)
        assert result["num_materials"] == 3
        assert len(result["all_materials"]) == 3
        assert result["all_materials"][1]["path"] == "/Game/M_1"

    def test_get_actor_transform(self):
        from cli_anything.unreal.core.scene import get_actor_transform

        api = self._mock_api()
        api.exec_python_ex.return_value = {
            "LogOutput": [{"Output": "TRANSFORM_DATA:100.0,200.0,0.0|0.0,45.0,0.0|1.0,1.0,1.0"}]
        }

        result = get_actor_transform(api, "/Game/Map:Actor_0")
        assert result["actor"] == "/Game/Map:Actor_0"
        assert result["location"]["X"] == 100
        assert result["rotation"]["Yaw"] == 45
        assert result["scale"]["X"] == 1


# ═══════════════════════════════════════════════════════════════════════
#  Test assets.py (mocked API)
# ═══════════════════════════════════════════════════════════════════════

class TestAssets:
    """Tests for core/assets.py — mocked API calls."""

    def _mock_api(self):
        api = MagicMock()
        return api

    def test_asset_exists_true(self):
        from cli_anything.unreal.core.assets import asset_exists

        api = self._mock_api()
        api.does_asset_exist.return_value = True

        result = asset_exists(api, "/Game/M_Test")
        assert result["exists"] is True
        assert result["asset"] == "/Game/M_Test"

    def test_asset_exists_false(self):
        from cli_anything.unreal.core.assets import asset_exists

        api = self._mock_api()
        api.does_asset_exist.return_value = False

        result = asset_exists(api, "/Game/Missing")
        assert result["exists"] is False

    def test_asset_refs_found(self):
        from cli_anything.unreal.core.assets import asset_refs

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.find_asset_referencers.return_value = ["/Game/MI_Child", "/Game/Maps/Level1"]

        result = asset_refs(api, "/Game/M_Test")
        assert result["count"] == 2
        assert "/Game/MI_Child" in result["referencers"]

    def test_asset_refs_not_found(self):
        from cli_anything.unreal.core.assets import asset_refs

        api = self._mock_api()
        api.does_asset_exist.return_value = False

        result = asset_refs(api, "/Game/Missing")
        assert "error" in result

    def test_asset_refs_no_refs(self):
        from cli_anything.unreal.core.assets import asset_refs

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.find_asset_referencers.return_value = []

        result = asset_refs(api, "/Game/M_Unused")
        assert result["count"] == 0
        assert result["referencers"] == []

    def test_asset_delete_not_found(self):
        from cli_anything.unreal.core.assets import asset_delete

        api = self._mock_api()
        api.does_asset_exist.return_value = False

        result = asset_delete(api, "/Game/Missing")
        assert result["status"] == "not_found"
        assert result["deleted"] is False

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_delete_no_refs(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_delete

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.find_asset_referencers.return_value = []
        mock_exec.return_value = {"deleted": True}

        result = asset_delete(api, "/Game/M_Old")
        assert result["status"] == "ok"
        assert result["deleted"] is True

    def test_asset_delete_has_refs_no_force(self):
        from cli_anything.unreal.core.assets import asset_delete

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.find_asset_referencers.return_value = ["/Game/MI_Child"]

        result = asset_delete(api, "/Game/M_Old")
        assert result["status"] == "has_references"
        assert result["deleted"] is False
        assert "hint" in result

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_delete_has_refs_force(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_delete

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.find_asset_referencers.return_value = ["/Game/MI_Child"]
        mock_exec.return_value = {"deleted": True}

        result = asset_delete(api, "/Game/M_Old", force=True)
        assert result["status"] == "ok"
        assert result["deleted"] is True
        assert result["had_references"] is True

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_delete_failed(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_delete

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.find_asset_referencers.return_value = []
        mock_exec.return_value = {"deleted": False}

        result = asset_delete(api, "/Game/M_Old")
        assert result["status"] == "failed"
        assert result["deleted"] is False

    def test_asset_duplicate_dest_exists_no_force(self):
        from cli_anything.unreal.core.assets import asset_duplicate

        api = self._mock_api()
        api.does_asset_exist.return_value = True

        result = asset_duplicate(api, "/Game/M_Src", "/Game/M_Dst")
        assert "error" in result
        assert "already exists" in result["error"]
        assert "hint" in result

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_duplicate_dest_not_exists(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_duplicate

        api = self._mock_api()
        api.does_asset_exist.return_value = False
        mock_exec.return_value = {
            "status": "ok", "source": "/Game/M_Src",
            "destination": "/Game/M_Dst", "duplicated": True,
        }

        result = asset_duplicate(api, "/Game/M_Src", "/Game/M_Dst")
        assert result["status"] == "ok"
        assert result["duplicated"] is True

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_duplicate_force(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_duplicate

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        mock_exec.return_value = {
            "status": "ok", "source": "/Game/M_Src",
            "destination": "/Game/M_Dst", "duplicated": True,
        }

        result = asset_duplicate(api, "/Game/M_Src", "/Game/M_Dst", force=True)
        assert result["status"] == "ok"

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_rename(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_rename

        api = self._mock_api()
        mock_exec.return_value = {
            "status": "ok", "source": "/Game/M_Old",
            "destination": "/Game/M_New", "renamed": True,
        }

        result = asset_rename(api, "/Game/M_Old", "/Game/M_New")
        assert result["status"] == "ok"
        assert result["renamed"] is True

        from cli_anything.unreal.core.assets import get_asset_property

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.exec_python_ex.return_value = {
            "LogOutput": [{"Output": "LOADED_OBJECT:/Game/M_Test.M_Test"}]
        }
        api.get_property.return_value = {"BlendMode": "Opaque"}

        result = get_asset_property(api, "/Game/M_Test", "BlendMode")
        assert result["BlendMode"] == "Opaque"

    def test_asset_property_set(self):
        from cli_anything.unreal.core.assets import set_asset_property

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.exec_python_ex.return_value = {
            "LogOutput": [{"Output": "LOADED_OBJECT:/Game/M_Test.M_Test"}]
        }
        api.set_property.return_value = {"status": "ok"}

        result = set_asset_property(api, "/Game/M_Test", "BlendMode", "Masked")
        assert result["status"] == "ok"
        # Should have called exec_python_ex twice (once to load, once to save)
        assert api.exec_python_ex.call_count == 2


# ═══════════════════════════════════════════════════════════════════════
#  Test ue_http_api.py — asset & GC methods (mocked)
# ═══════════════════════════════════════════════════════════════════════

class TestHTTPAPIAssets:
    """Tests for the asset-related methods on UEEditorAPI."""

    @patch("requests.put")
    def test_does_asset_exist_true(self, mock_put):
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ReturnValue": True}
        mock_resp.raise_for_status.return_value = None
        mock_put.return_value = mock_resp

        api = UEEditorAPI()
        assert api.does_asset_exist("/Game/M_Test") is True

    @patch("requests.put")
    def test_does_asset_exist_false(self, mock_put):
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ReturnValue": False}
        mock_resp.raise_for_status.return_value = None
        mock_put.return_value = mock_resp

        api = UEEditorAPI()
        assert api.does_asset_exist("/Game/Missing") is False

    @patch("requests.put")
    def test_delete_asset_success(self, mock_put):
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ReturnValue": True}
        mock_resp.raise_for_status.return_value = None
        mock_put.return_value = mock_resp

        api = UEEditorAPI()
        assert api.delete_asset("/Game/M_Old") is True

    @patch("requests.put")
    def test_delete_asset_failure(self, mock_put):
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ReturnValue": False}
        mock_resp.raise_for_status.return_value = None
        mock_put.return_value = mock_resp

        api = UEEditorAPI()
        assert api.delete_asset("/Game/Missing") is False

    @patch("requests.put")
    def test_find_asset_referencers(self, mock_put):
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ReturnValue": ["/Game/MI_Child", "/Game/Maps/L1"]}
        mock_resp.raise_for_status.return_value = None
        mock_put.return_value = mock_resp

        api = UEEditorAPI()
        refs = api.find_asset_referencers("/Game/M_Test")
        assert len(refs) == 2
        assert "/Game/MI_Child" in refs

    @patch("requests.put")
    def test_find_asset_referencers_empty(self, mock_put):
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ReturnValue": []}
        mock_resp.raise_for_status.return_value = None
        mock_put.return_value = mock_resp

        api = UEEditorAPI()
        refs = api.find_asset_referencers("/Game/M_Unused")
        assert refs == []

    @patch("requests.put")
    def test_collect_garbage(self, mock_put):
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status.return_value = None
        mock_put.return_value = mock_resp

        api = UEEditorAPI()
        result = api.collect_garbage()
        assert isinstance(result, dict)


# ═══════════════════════════════════════════════════════════════════════
#  Test scene CLI commands
# ═══════════════════════════════════════════════════════════════════════

class TestSceneCLI:
    """Tests for scene CLI commands — mocked editor."""

    def test_scene_actors_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.scene.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_api = MagicMock()
            mock_editor.return_value = mock_api
            mock_run.return_value = {
                "actors": [
                    {"path": "/Game/Map:PersistentLevel.Cube_0",
                     "name": "Cube_0", "class": "StaticMeshActor"},
                    {"path": "/Game/Map:PersistentLevel.Light_0",
                     "name": "Light_0", "class": "Light"},
                ],
                "count": 2,
            }

            result = runner.invoke(cli, ["--json", "scene", "list"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["count"] == 2

    def test_scene_actors_with_class_filter(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.scene.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_api = MagicMock()
            mock_editor.return_value = mock_api
            mock_run.return_value = {
                "actors": [
                    {"path": "/Game/Map:PersistentLevel.PointLight_0",
                     "name": "PointLight_0", "class": "PointLight"},
                ],
                "count": 1,
            }

            result = runner.invoke(cli, [
                "--json", "scene", "list", "--class", "PointLight",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["count"] == 1

    def test_scene_find_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.scene.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_api = MagicMock()
            mock_editor.return_value = mock_api
            mock_run.return_value = {
                "actors": [
                    {"path": "/Game/Map:PersistentLevel.MyCube_0",
                     "name": "MyCube_0", "class": "StaticMeshActor"},
                ],
                "count": 1,
                "query": "Cube",
            }

            result = runner.invoke(cli, ["--json", "scene", "list", "-q", "Cube"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["count"] == 1
            assert data["query"] == "Cube"

    def test_scene_property_get_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.scene.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.get_property.return_value = {"bHidden": False}
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--json", "scene", "property",
                "/Game/Map:Actor_0", "bHidden",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["bHidden"] is False

    def test_scene_components_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.scene.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.describe_object.return_value = {
                "Properties": [
                    {"Name": "StaticMeshComponent0", "Type": "UStaticMeshComponent*"},
                    {"Name": "bHidden", "Type": "bool"},
                ],
            }
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--json", "scene", "list-components", "/Game/Map:Actor_0",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data["components"]) == 1

    def test_scene_transform_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.scene.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.exec_python_ex.return_value = {
                "LogOutput": [{"Output": "TRANSFORM_DATA:0.0,0.0,0.0|0.0,90.0,0.0|1.0,1.0,1.0"}]
            }
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--json", "scene", "get-transform", "/Game/Map:Actor_0",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["rotation"]["Yaw"] == 90


# ═══════════════════════════════════════════════════════════════════════
#  Test asset CLI commands
# ═══════════════════════════════════════════════════════════════════════

class TestAssetCLI:
    """Tests for project asset-* CLI commands — mocked editor."""

    def test_asset_exists_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.does_asset_exist.return_value = True
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--json", "asset", "exists", "/Game/M_Test",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["exists"] is True

    def test_asset_exists_not_found_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.does_asset_exist.return_value = False
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--json", "asset", "exists", "/Game/Missing",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["exists"] is False

    def test_asset_delete_cli_no_refs(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.assets._exec") as mock_exec:
            mock_api = MagicMock()
            mock_api.does_asset_exist.return_value = True
            mock_api.find_asset_referencers.return_value = []
            mock_editor.return_value = mock_api
            mock_exec.return_value = {"deleted": True}

            result = runner.invoke(cli, [
                "--json", "asset", "delete", "/Game/M_Old",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"
            assert data["deleted"] is True

    def test_asset_delete_cli_has_refs_blocked(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.does_asset_exist.return_value = True
            mock_api.find_asset_referencers.return_value = ["/Game/MI_Child"]
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--json", "asset", "delete", "/Game/M_Old",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "has_references"

    def test_asset_delete_cli_force(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.assets._exec") as mock_exec:
            mock_api = MagicMock()
            mock_api.does_asset_exist.return_value = True
            mock_api.find_asset_referencers.return_value = ["/Game/MI_Child"]
            mock_editor.return_value = mock_api
            mock_exec.return_value = {"deleted": True}

            result = runner.invoke(cli, [
                "--json", "asset", "delete", "/Game/M_Old", "--force",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"
            assert data["had_references"] is True

    def test_asset_refs_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.does_asset_exist.return_value = True
            mock_api.find_asset_referencers.return_value = ["/Game/Maps/L1"]
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--json", "asset", "refs", "/Game/M_Test",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["count"] == 1

    def test_asset_duplicate_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.assets._exec") as mock_exec:
            mock_api = MagicMock()
            mock_api.does_asset_exist.return_value = False
            mock_editor.return_value = mock_api
            mock_exec.return_value = {
                "status": "ok", "source": "/Game/M_Src",
                "destination": "/Game/M_Dst", "duplicated": True,
            }

            result = runner.invoke(cli, [
                "--json", "asset", "duplicate",
                "/Game/M_Src", "/Game/M_Dst",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"

    def test_asset_rename_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.assets._exec") as mock_exec:
            mock_editor.return_value = MagicMock()
            mock_exec.return_value = {
                "status": "ok", "source": "/Game/M_Old",
                "destination": "/Game/M_New", "renamed": True,
            }

            result = runner.invoke(cli, [
                "--json", "asset", "rename",
                "/Game/M_Old", "/Game/M_New",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════
#  Test plugin_bridge.py
# ═══════════════════════════════════════════════════════════════════════

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

class TestMaterialErrorsPlugin:
    """Tests for get_material_errors — plugin-based path."""

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    @patch("cli_anything.unreal.core.materials.ensure_plugin_deployed")
    def test_plugin_returns_errors(self, mock_deploy, mock_exec):
        """Plugin path returns compile errors."""
        from cli_anything.unreal.core.materials import get_material_errors

        mock_deploy.return_value = {"deployed": True, "action": "already_up_to_date"}
        mock_exec.return_value = {
            "errors": ["Type mismatch on BaseColor input"],
            "warnings": [],
            "material": "/Game/M_Test",
            "has_errors": True,
            "source": "plugin",
        }

        result = get_material_errors(MagicMock(), "/Game/M_Test", project_dir="/tmp/proj")
        assert result["has_errors"] is True
        assert len(result["errors"]) == 1
        assert result["source"] == "plugin"

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    @patch("cli_anything.unreal.core.materials.ensure_plugin_deployed")
    def test_plugin_no_errors(self, mock_deploy, mock_exec):
        """Plugin path returns empty errors for clean material."""
        from cli_anything.unreal.core.materials import get_material_errors

        mock_deploy.return_value = {"deployed": True, "action": "already_up_to_date"}
        mock_exec.return_value = {
            "errors": [],
            "warnings": [],
            "material": "/Game/M_Clean",
            "has_errors": False,
            "source": "plugin",
        }

        result = get_material_errors(MagicMock(), "/Game/M_Clean", project_dir="/tmp/proj")
        assert result["has_errors"] is False
        assert result["errors"] == []

    @patch("cli_anything.unreal.core.materials._exec_material_script")
    @patch("cli_anything.unreal.core.materials.ensure_plugin_deployed")
    def test_plugin_not_loaded_returns_error(self, mock_deploy, mock_exec):
        """Returns error message when plugin is deployed but not loaded."""
        from cli_anything.unreal.core.materials import get_material_errors

        mock_deploy.return_value = {"deployed": True, "action": "already_up_to_date"}
        mock_exec.return_value = {
            "error": "AttributeError: module 'unreal' has no attribute 'CliAnythingBridgeLibrary'"
        }

        result = get_material_errors(MagicMock(), "/Game/M_Test", project_dir="/tmp/proj")
        assert "error" in result
        assert "not loaded" in result["error"]
        assert "recompile" in result["error"]

    @patch("cli_anything.unreal.core.materials.ensure_plugin_deployed")
    def test_deploy_failure_returns_error(self, mock_deploy):
        """Returns error when plugin deployment fails."""
        from cli_anything.unreal.core.materials import get_material_errors

        mock_deploy.return_value = {"deployed": False, "error": "Source not found"}

        result = get_material_errors(MagicMock(), "/Game/M_Test", project_dir="/tmp/proj")
        assert "error" in result
        assert "Source not found" in result["error"]


class TestInstallSkills:
    """Tests for commands/skills.py — install-skills CLI."""

    def test_install_to_custom_target(self, tmp_path):
        """--target writes the full skill tree to the given dir.

        tmp_path is a pytest fixture that creates a fresh dir per test and
        removes it after teardown — so nothing to clean up manually.
        """
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        target = tmp_path / "my_skill"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--json", "install-skills", "--target", str(target)]
        )
        assert result.exit_code == 0, result.output

        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert data["installed_count"] == 1

        # Verify every source file made it to the target.
        source_dir = Path(__file__).parent.parent / "skills"
        expected = [p for p in source_dir.rglob("*") if p.is_file()]
        assert target.exists()
        for src in expected:
            rel = src.relative_to(source_dir)
            assert (target / rel).is_file(), f"missing: {rel}"

    def test_install_multiple_targets(self, tmp_path):
        """--target is repeatable; each dir gets an independent copy."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        t1, t2 = tmp_path / "t1", tmp_path / "t2"
        result = CliRunner().invoke(cli, [
            "--json", "install-skills",
            "--target", str(t1),
            "--target", str(t2),
        ])
        assert result.exit_code == 0, result.output

        data = json.loads(result.output)
        assert data["installed_count"] == 2
        assert (t1 / "SKILL.md").is_file()
        assert (t2 / "SKILL.md").is_file()

    def test_install_overwrites_existing_target(self, tmp_path):
        """If the target already exists it is replaced, not merged."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        target = tmp_path / "existing"
        target.mkdir()
        # Leave a stray file that should NOT survive the reinstall.
        (target / "stray.txt").write_text("should be gone")

        result = CliRunner().invoke(
            cli, ["--json", "install-skills", "--target", str(target)]
        )
        assert result.exit_code == 0, result.output

        assert not (target / "stray.txt").exists()
        assert (target / "SKILL.md").is_file()


# ═══════════════════════════════════════════════════════════════════════
#  Build success-path tests (mocked run_uat)
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
            assert "build stop" in result["error"].lower()

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

    def test_build_compile_no_timeout_option(self, temp_project):
        """build compile should not have --timeout option."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["build", "compile", "--help"])
        assert result.exit_code == 0
        assert "--timeout" not in result.output

    def test_build_cook_no_timeout_option(self, temp_project):
        """build cook should not have --timeout option."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["build", "cook", "--help"])
        assert result.exit_code == 0
        assert "--timeout" not in result.output

    def test_build_package_no_timeout_option(self, temp_project):
        """build package should not have --timeout option."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["build", "package", "--help"])
        assert result.exit_code == 0
        assert "--timeout" not in result.output

    def test_build_stop_cli(self, temp_project):
        """build stop command works and calls stop_build."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        with patch("cli_anything.unreal.core.build.kill_build_processes", return_value={
            "killed": [1234], "remaining": [], "status": "ok",
        }):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "--json", "--project", temp_project["uproject"],
                "build", "stop",
            ])
            assert result.exit_code == 0
            data = self._parse_json_output(result.output)
            assert data["status"] == "ok"
            assert 1234 in data["killed"]

    def test_build_is_building_cli_false(self, temp_project):
        """build is-building returns building=false when no processes."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        with patch("cli_anything.unreal.core.build.find_running_build_processes", return_value=[]):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "--json", "--project", temp_project["uproject"],
                "build", "is-building",
            ])
            assert result.exit_code == 0
            data = self._parse_json_output(result.output)
            assert data["building"] is False

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
                "--json", "--project", temp_project["uproject"],
                "build", "is-building",
            ])
            assert result.exit_code == 0
            data = self._parse_json_output(result.output)
            assert data["building"] is True

    def test_build_stop_none_running(self, temp_project):
        """build stop when nothing is running returns status=none."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        with patch("cli_anything.unreal.core.build.kill_build_processes", return_value={
            "killed": [], "remaining": [], "status": "none",
        }):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "--json", "--project", temp_project["uproject"],
                "build", "stop",
            ])
            assert result.exit_code == 0
            data = self._parse_json_output(result.output)
            assert data["status"] == "none"


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
            "--json", "--project", TEST574_UPROJECT,
            "build", "is-building",
        ])
        assert result.exit_code == 0
        data = self._parse_json_output(result.output)
        assert "building" in data

    def test_build_status_cli_real(self):
        """build status CLI against real project."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, [
            "--json", "--project", TEST574_UPROJECT,
            "build", "status",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["project"] == "Test574"

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
            "--json", "--project", TEST574_UPROJECT,
            "build", "stop",
        ])
        assert result.exit_code == 0
        data = self._parse_json_output(result.output)
        assert data["status"] in ("none", "ok", "partial")
