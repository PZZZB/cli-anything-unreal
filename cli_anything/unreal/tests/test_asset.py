"""Tests for test_asset.py — Uses synthetic data only, no UE editor required."""

import json
from unittest.mock import MagicMock, patch



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
        assert "def _cli_asset_class_name" in script
        assert "asset_class_path.asset_name" in script
        assert "asset_data.asset_class" in script
        assert "_class_filter = 'Blueprint'" in script
        assert "return _cls == _filter or _cls.endswith('Blueprint')" in script

    def test_search_assets_uses_all_assets_fallback(self):
        from cli_anything.unreal.core.assets import search_assets

        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {"assets": [], "count": 0}
            search_assets(self._mock_api(), query="SDF", class_name="Texture2D", package_path="/Game/UI/SDF")

        script = mock_run.call_args.args[1]
        assert "list(_ar.get_assets_by_path" in script
        assert "get_all_assets" in script
        assert "startswith(_pkg_prefix + '/')" in script

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

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_refs_found(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_refs

        api = self._mock_api()
        mock_exec.return_value = {
            "asset": "/Game/M_Test",
            "resolved_asset": "/Game/M_Test.M_Test",
            "referencers": ["/Game/MI_Child", "/Game/Maps/Level1"],
            "count": 2,
        }

        result = asset_refs(api, "/Game/M_Test", project_dir="F:/Project")
        assert result["count"] == 2
        assert "/Game/MI_Child" in result["referencers"]
        mock_exec.assert_called_once()
        assert mock_exec.call_args.args[0] is api
        assert mock_exec.call_args.args[2] == "F:/Project"

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_refs_resolves_package_and_object_paths_in_editor(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_refs

        mock_exec.return_value = {
            "asset": "/Game/Drone/MI_Drone",
            "resolved_asset": "/Game/Drone/MI_Drone.MI_Drone",
            "referencers": ["/Game/Maps/L_Drone"],
            "count": 1,
        }

        result = asset_refs(self._mock_api(), "/Game/Drone/MI_Drone")

        assert result["asset"] == "/Game/Drone/MI_Drone"
        assert result["resolved_asset"] == "/Game/Drone/MI_Drone.MI_Drone"
        assert result["count"] == 1
        script = mock_exec.call_args.args[1]
        assert "unreal.EditorAssetLibrary.load_asset" in script
        assert "unreal.load_asset" in script
        assert "unreal.load_object" in script
        assert "get_assets_by_package_name" in script
        assert "find_package_referencers_for_asset" in script

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_refs_not_found(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_refs

        mock_exec.return_value = {
            "error": "Asset not found: /Game/Missing",
            "asset": "/Game/Missing",
            "tried": ["/Game/Missing", "/Game/Missing.Missing"],
        }

        result = asset_refs(self._mock_api(), "/Game/Missing")
        assert "error" in result

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_refs_no_refs(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_refs

        mock_exec.return_value = {
            "asset": "/Game/M_Unused",
            "resolved_asset": "/Game/M_Unused.M_Unused",
            "referencers": [],
            "count": 0,
        }

        result = asset_refs(self._mock_api(), "/Game/M_Unused")
        assert result["count"] == 0
        assert result["referencers"] == []

    @patch("cli_anything.unreal.core.script_runner.run_python_code")
    def test_texture_source_info_uses_bridge(self, mock_run):
        from cli_anything.unreal.core.assets import texture_source_info

        mock_run.return_value = {
            "status": "ok",
            "asset": "/Game/T_SDF",
            "source_size": {"x": 128, "y": 64},
            "source_format": "TSF_BGRA8",
            "alpha_stats": {"available": True, "min": 0, "max": 255},
        }

        result = texture_source_info(self._mock_api(), "/Game/T_SDF")

        assert result["status"] == "ok"
        script = mock_run.call_args.args[1]
        assert "CliAnythingBridgeLibrary" in script
        assert "get_texture_source_info" in script
        assert "Texture2D" in script

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

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_delete_normalizes_package_path_to_object_path(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_delete

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.find_asset_referencers.return_value = []
        mock_exec.return_value = {"deleted": True, "deleted_asset": "/Game/WBP_Test.WBP_Test"}

        result = asset_delete(api, "/Game/WBP_Test", force=True)

        script = mock_exec.call_args.args[1]
        assert 'delete_path = "/Game/WBP_Test.WBP_Test"' in script
        assert 'requested_path = "/Game/WBP_Test"' in script
        assert result["status"] == "ok"
        assert result["asset"] == "/Game/WBP_Test"
        assert result["deleted_asset"] == "/Game/WBP_Test.WBP_Test"

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_delete_keeps_object_path(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_delete

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.find_asset_referencers.return_value = []
        mock_exec.return_value = {"deleted": True, "deleted_asset": "/Game/WBP_Test.WBP_Test"}

        asset_delete(api, "/Game/WBP_Test.WBP_Test", force=True)

        script = mock_exec.call_args.args[1]
        assert 'delete_path = "/Game/WBP_Test.WBP_Test"' in script
        assert 'requested_path = "/Game/WBP_Test.WBP_Test"' in script

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
        assert result["code"] == "ASSET_DELETE_FAILED"
        assert result["error"] == "Failed to delete asset: /Game/M_Old"
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
        assert mock_exec.call_args.kwargs["timeout"] == 120.0

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_rename_timeout_confirmed_by_postcondition(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_rename

        api = self._mock_api()
        api.does_asset_exist.side_effect = [False, True]
        mock_exec.return_value = {
            "error": "HTTPConnectionPool: Read timed out. (read timeout=15)",
        }

        result = asset_rename(api, "/Game/M_Old", "/Game/M_New", timeout=15)

        assert result["status"] == "ok"
        assert result["renamed"] is True
        assert result["completion_state"] == "confirmed"
        assert result["confirmed_by"] == "post_timeout_asset_exists"
        assert result["response_timed_out"] is True
        assert result["verification"]["outcome"] == "confirmed_success"
        assert api.does_asset_exist.call_args_list[0].args == ("/Game/M_Old",)
        assert api.does_asset_exist.call_args_list[1].args == ("/Game/M_New",)

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_rename_timeout_stays_unknown_when_postcheck_fails(self, mock_exec):
        from cli_anything.unreal.core.assets import asset_rename

        api = self._mock_api()
        api.does_asset_exist.side_effect = RuntimeError("editor still busy")
        mock_exec.return_value = {
            "error": "HTTPConnectionPool: Read timed out. (read timeout=2)",
        }

        result = asset_rename(api, "/Game/M_Old", "/Game/M_New", timeout=2)

        assert result["code"] == "ASSET_RENAME_TIMEOUT"
        assert result["completion_state"] == "unknown"
        assert result["retry_safe"] is False
        assert result["verification"]["outcome"] == "inconclusive"
        assert result["verification"]["source"]["exists"] is None
        assert result["verification"]["destination"]["exists"] is None

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_property_get_uses_loaded_asset(self, mock_exec):
        from cli_anything.unreal.core.assets import get_asset_property

        api = self._mock_api()
        mock_exec.return_value = {
            "asset": "/Game/M_Test",
            "loaded_asset": "/Game/M_Test.M_Test",
            "loaded_path": "/Game/M_Test",
            "targets": [
                {"kind": "asset", "object_path": "/Game/M_Test.M_Test"},
            ],
        }
        api.get_property.return_value = {"BlendMode": "Opaque"}

        result = get_asset_property(api, "/Game/M_Test", "BlendMode")

        assert result["BlendMode"] == "Opaque"
        api.get_property.assert_called_once_with("/Game/M_Test.M_Test", "BlendMode")
        assert "does_asset_exist" not in mock_exec.call_args.args[1]

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_property_get_normalizes_ue4_enum_repr(self, mock_exec):
        from cli_anything.unreal.core.assets import get_asset_property

        api = self._mock_api()
        mock_exec.return_value = {
            "targets": [
                {"kind": "asset", "object_path": "/Game/M_Test.M_Test"},
            ],
        }
        api.get_property.return_value = {
            "BlendMode": "<BlendMode.BLEND_OPAQUE: 0>",
        }

        result = get_asset_property(api, "/Game/M_Test", "BlendMode")

        assert result["BlendMode"] == "Opaque"

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_property_get_reads_blueprint_class_default_object(self, mock_exec):
        from cli_anything.unreal.core.assets import get_asset_property

        api = self._mock_api()
        mock_exec.side_effect = [
            {
                "asset": "/Game/BP_Test",
                "loaded_asset": "/Game/BP_Test.BP_Test",
                "loaded_path": "/Game/BP_Test",
                "targets": [
                    {"kind": "asset", "object_path": "/Game/BP_Test.BP_Test"},
                    {
                        "kind": "class_default_object",
                        "object_path": "/Game/BP_Test.Default__BP_Test_C",
                    },
                ],
            },
            {
                "InitialLifeSpan": 37.5,
                "asset": "/Game/BP_Test",
                "object_path": "/Game/BP_Test.Default__BP_Test_C",
                "target": "class_default_object",
                "read_via": "unreal_python",
            },
        ]
        api.get_property.return_value = {
            "error": "Property is not accessible via Remote Control"
        }

        result = get_asset_property(api, "/Game/BP_Test", "InitialLifeSpan")

        assert result["InitialLifeSpan"] == 37.5
        assert result["target"] == "class_default_object"
        assert api.get_property.call_count == 2
        resolve_script = mock_exec.call_args_list[0].args[1]
        assert '_asset.get_path_name() + "_C"' in resolve_script
        fallback_script = mock_exec.call_args_list[1].args[1]
        assert "get_editor_property" in fallback_script

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_property_get_normalizes_ue4_enum_repr_from_python(self, mock_exec):
        from cli_anything.unreal.core.assets import get_asset_property

        api = self._mock_api()
        mock_exec.side_effect = [
            {
                "targets": [
                    {"kind": "asset", "object_path": "/Game/M_Test.M_Test"},
                ],
            },
            {
                "BlendMode": "<BlendMode.BLEND_OPAQUE: 0>",
                "read_via": "unreal_python",
            },
        ]
        api.get_property.return_value = {
            "error": "Property is not accessible via Remote Control"
        }

        result = get_asset_property(api, "/Game/M_Test", "BlendMode")

        assert result["BlendMode"] == "Opaque"

    @patch("cli_anything.unreal.core.assets._exec")
    def test_asset_property_get_reports_load_failure(self, mock_exec):
        from cli_anything.unreal.core.assets import get_asset_property

        api = self._mock_api()
        mock_exec.return_value = {
            "error": "Asset not found: /Game/Missing",
            "asset": "/Game/Missing",
            "tried": ["/Game/Missing", "/Game/Missing.Missing"],
        }

        result = get_asset_property(api, "/Game/Missing", "BlendMode")

        assert result["error"] == "Asset not found: /Game/Missing"
        api.get_property.assert_not_called()

    def test_asset_property_set(self):
        from cli_anything.unreal.core.assets import set_asset_property

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.exec_python_ex.return_value = {
            "LogOutput": [{"Output": "LOADED_OBJECT:/Game/M_Test.M_Test"}]
        }
        api.set_property.return_value = {"status": "ok"}

        with patch(
            "cli_anything.unreal.core.script_runner.run_python_code",
            return_value={
                "status": "ok",
                "saved": True,
                "saved_packages": ["/Game/M_Test"],
            },
        ) as mock_save:
            result = set_asset_property(api, "/Game/M_Test", "BlendMode", "Masked")
        assert result["status"] == "ok"
        assert result["saved"] is True
        assert api.exec_python_ex.call_count == 1
        assert mock_save.call_args.kwargs["target_packages"] == ["/Game/M_Test"]

    def test_asset_property_set_loads_when_exists_probe_is_stale(self):
        from cli_anything.unreal.core.assets import set_asset_property

        api = self._mock_api()
        api.does_asset_exist.return_value = False
        api.exec_python_ex.return_value = {
            "LogOutput": [{"Output": "LOADED_OBJECT:/Game/M_Test.M_Test"}]
        }
        api.set_property.return_value = {"status": "ok"}

        with patch(
            "cli_anything.unreal.core.script_runner.run_python_code",
            return_value={"status": "ok", "saved": True},
        ):
            result = set_asset_property(api, "/Game/M_Test", "BlendMode", "Masked")
        assert result["status"] == "ok"
        assert api.set_property.call_args.args == (
            "/Game/M_Test.M_Test",
            "BlendMode",
            "Masked",
        )

    def test_asset_property_set_rejects_unconfirmed_write(self):
        from cli_anything.unreal.core.assets import set_asset_property

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.exec_python_ex.return_value = {
            "LogOutput": [{"Output": "LOADED_OBJECT:/Game/M_Test.M_Test"}]
        }
        api.set_property.return_value = {"error": "write rejected"}

        with patch(
            "cli_anything.unreal.core.script_runner.run_python_code"
        ) as mock_save:
            result = set_asset_property(api, "/Game/M_Test", "BlendMode", "Masked")

        assert result["code"] == "ASSET_PROPERTY_WRITE_FAILED"
        mock_save.assert_not_called()

    def test_asset_property_set_reports_target_save_failure(self):
        from cli_anything.unreal.core.assets import set_asset_property

        api = self._mock_api()
        api.does_asset_exist.return_value = True
        api.exec_python_ex.return_value = {
            "LogOutput": [{"Output": "LOADED_OBJECT:/Game/M_Test.M_Test"}]
        }
        api.set_property.return_value = {"status": "ok"}

        with patch(
            "cli_anything.unreal.core.script_runner.run_python_code",
            return_value={
                "error": "PACKAGE_SAVE_FAILED: /Game/M_Test: save_asset returned false",
                "code": "PACKAGE_SAVE_FAILED",
            },
        ):
            result = set_asset_property(api, "/Game/M_Test", "BlendMode", "Masked")

        assert result["code"] == "PACKAGE_SAVE_FAILED"
        assert result["asset"] == "/Game/M_Test"


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

    def test_asset_property_get_cli_surfaces_read_failure(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.assets.get_asset_property") as mock_get:
            mock_editor.return_value = MagicMock()
            mock_get.return_value = {"error": "Asset not found: /Game/Missing"}

            result = runner.invoke(cli, [
                "--output", "json", "asset", "property",
                "/Game/Missing", "BlendMode",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "ASSET_PROPERTY_READ_FAILED"
        assert data["message"] == "Asset not found: /Game/Missing"

    def test_asset_property_set_cli_surfaces_write_failure(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.assets.set_asset_property") as mock_set:
            mock_editor.return_value = MagicMock()
            mock_set.return_value = {"error": "Property cannot be written"}

            result = runner.invoke(cli, [
                "--output", "json", "asset", "property",
                "/Game/M_Test", "BlendMode=Masked",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "ASSET_PROPERTY_WRITE_FAILED"
        assert data["message"] == "Property cannot be written"

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
            mock_editor.return_value = mock_api
            with patch("cli_anything.unreal.core.assets._exec") as mock_exec:
                mock_exec.return_value = {
                    "asset": "/Game/M_Test",
                    "resolved_asset": "/Game/M_Test.M_Test",
                    "referencers": ["/Game/Maps/L1"],
                    "count": 1,
                }
                result = runner.invoke(cli, [
                    "--output", "json", "asset", "refs", "/Game/M_Test",
                ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["count"] == 1

    def test_asset_refs_cli_surfaces_resolution_failure(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.assets.asset_refs") as mock_refs:
            mock_editor.return_value = MagicMock()
            mock_refs.return_value = {
                "error": "Asset not found: /Game/Missing",
                "asset": "/Game/Missing",
                "tried": ["/Game/Missing", "/Game/Missing.Missing"],
            }

            result = runner.invoke(cli, [
                "--output", "json", "asset", "refs", "/Game/Missing",
            ])

        assert result.exit_code == 3
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "ASSET_REFS_FAILED"
        assert data["message"] == "Asset not found: /Game/Missing"
        assert data["details"]["tried"] == [
            "/Game/Missing", "/Game/Missing.Missing",
        ]

    def test_asset_texture_source_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.asset.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.assets.texture_source_info") as mock_info:
            mock_editor.return_value = MagicMock()
            mock_info.return_value = {
                "status": "ok",
                "asset": "/Game/T_SDF",
                "source_format": "TSF_BGRA8",
            }

            result = runner.invoke(cli, [
                "--output", "json", "asset", "texture-source", "/Game/T_SDF",
            ])

            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["source_format"] == "TSF_BGRA8"

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

    def test_asset_rename_cli_timeout_is_unknown_with_safe_verification_commands(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        api = MagicMock()
        api.does_asset_exist.side_effect = RuntimeError("editor still busy")
        with patch("cli_anything.unreal.commands.asset.require_editor", return_value=api), \
             patch("cli_anything.unreal.core.assets._exec") as mock_exec:
            mock_exec.return_value = {
                "error": "HTTPConnectionPool: Read timed out. (read timeout=2)",
            }

            result = runner.invoke(cli, [
                "--output", "json", "--port", "30021",
                "asset", "rename", "--timeout", "2",
                "/Game/M_Old", "/Game/M_New",
            ])

        assert result.exit_code == 4
        data = json.loads(result.output)
        assert data["code"] == "ASSET_RENAME_TIMEOUT"
        details = data["details"]
        assert details["completion_state"] == "unknown"
        assert details["retry_safe"] is False
        assert details["verification_commands"] == {
            "source": "ue-cli --output json --port 30021 asset exists /Game/M_Old",
            "destination": "ue-cli --output json --port 30021 asset exists /Game/M_New",
        }
        assert "Do not retry" in data["suggestion"]


# ═══════════════════════════════════════════════════════════════════════
#  Test plugin_bridge.py
# ═══════════════════════════════════════════════════════════════════════


