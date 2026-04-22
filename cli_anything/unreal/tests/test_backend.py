"""Tests for test_backend.py — Uses synthetic data only, no UE editor required."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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


