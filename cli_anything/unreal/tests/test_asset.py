"""Tests for test_asset.py — Uses synthetic data only, no UE editor required."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestAssets:
    """Tests for core/assets.py — mocked API calls."""

    def _mock_api(self):
        api = MagicMock()
        return api

    def test_asset_class_matches_blueprint_family(self):
        from cli_anything.unreal.core.assets import _asset_class_matches

        assert _asset_class_matches("Blueprint", "Blueprint") is True
        assert _asset_class_matches("WidgetBlueprint", "Blueprint") is True
        assert _asset_class_matches("AnimBlueprint", "Blueprint") is True
        assert _asset_class_matches("Material", "Blueprint") is False

    def test_search_assets_blueprint_filter_uses_family_matcher(self):
        from cli_anything.unreal.core.assets import search_assets

        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {"assets": [], "count": 0}
            search_assets(self._mock_api(), class_name="Blueprint")

        script = mock_run.call_args.args[1]
        assert "def _cli_asset_class_matches" in script
        assert "_class_filter = 'Blueprint'" in script
        assert "return _cls == _filter or _cls.endswith('Blueprint')" in script

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
                "--output", "json", "asset", "exists", "/Game/M_Test",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["exists"] is True

    def test_asset_exists_not_found_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.does_asset_exist.return_value = False
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--output", "json", "asset", "exists", "/Game/Missing",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["exists"] is False

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
                "--output", "json", "asset", "delete", "/Game/M_Old",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["status"] == "ok"
            assert data["result"]["deleted"] is True

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
                "--output", "json", "asset", "delete", "/Game/M_Old",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["status"] == "has_references"

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
                "--output", "json", "asset", "delete", "/Game/M_Old", "--force",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["status"] == "ok"
            assert data["result"]["had_references"] is True

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
                "--output", "json", "asset", "refs", "/Game/M_Test",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["count"] == 1

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
                "--output", "json", "asset", "duplicate",
                "/Game/M_Src", "/Game/M_Dst",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["status"] == "ok"

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
                "--output", "json", "asset", "rename",
                "/Game/M_Old", "/Game/M_New",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════
#  Test plugin_bridge.py
# ═══════════════════════════════════════════════════════════════════════


