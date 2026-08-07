"""Tests for test_blueprint.py — Uses synthetic data only, no UE editor required."""

import json
from unittest.mock import MagicMock, patch



class TestBlueprint:
    """Tests for core/blueprint.py — mocked script execution."""

    def test_blueprint_asset_path_candidates_normalizes_generated_class(self):
        from cli_anything.unreal.core.blueprint import _blueprint_asset_path_candidates

        assert _blueprint_asset_path_candidates("/Game/UI/BP_Test") == [
            "/Game/UI/BP_Test",
            "/Game/UI/BP_Test.BP_Test",
        ]
        assert _blueprint_asset_path_candidates("/Game/UI/BP_Test.BP_Test") == [
            "/Game/UI/BP_Test.BP_Test",
            "/Game/UI/BP_Test",
        ]
        assert _blueprint_asset_path_candidates("/Game/UI/BP_Test.BP_Test_C") == [
            "/Game/UI/BP_Test.BP_Test",
            "/Game/UI/BP_Test",
        ]
        assert _blueprint_asset_path_candidates("/Game/UI/BP_Test.BP_Test_C:WidgetTree.Root") == [
            "/Game/UI/BP_Test.BP_Test",
            "/Game/UI/BP_Test",
        ]

    @patch("cli_anything.unreal.core.script_runner.run_python_code")
    def test_compile_blueprint_uses_normalized_asset_candidates(self, mock_run):
        from cli_anything.unreal.core.blueprint import compile_blueprint

        mock_run.return_value = {"status": "ok", "action": "compile"}

        compile_blueprint(MagicMock(), "/Game/UI/BP_Test.BP_Test_C")

        script = mock_run.call_args.args[1]
        assert 'asset_path = "/Game/UI/BP_Test.BP_Test_C"' in script
        assert 'asset_candidates = ["/Game/UI/BP_Test.BP_Test", "/Game/UI/BP_Test"]' in script
        assert "_cli_load_blueprint" in script
        from cli_anything.unreal.core.script_runner import SavePolicy

        assert mock_run.call_args.kwargs["save_policy"] is SavePolicy.TARGET_PACKAGES
        assert mock_run.call_args.kwargs["target_packages"] == [
            "/Game/UI/BP_Test.BP_Test_C"
        ]

    @patch("cli_anything.unreal.core.script_runner.run_python_code")
    def test_compile_blueprint_resolver_searches_registry_parent_path(self, mock_run):
        from cli_anything.unreal.core.blueprint import compile_blueprint

        mock_run.return_value = {"status": "ok", "action": "compile"}

        compile_blueprint(MagicMock(), "/Game/UI/BP_Test")

        script = mock_run.call_args.args[1]
        assert "registry.get_assets_by_path(parent_path, False, False)" in script
        assert "str(data.asset_name) in wanted_asset_names" in script

    @patch("cli_anything.unreal.core.script_runner.run_python_code")
    def test_blueprint_resolver_uses_unreal_load_asset_fallback(self, mock_run):
        from cli_anything.unreal.core.blueprint import get_blueprint_info

        mock_run.return_value = {"name": "BP_Drone", "path": "/Game/Drone/BP_Drone.BP_Drone"}

        get_blueprint_info(MagicMock(), "/Game/Drone/BP_Drone")

        script = mock_run.call_args.args[1]
        assert "unreal.load_asset(candidate)" in script
        assert 'asset_candidates = ["/Game/Drone/BP_Drone", "/Game/Drone/BP_Drone.BP_Drone"]' in script
        from cli_anything.unreal.core.script_runner import SavePolicy

        assert mock_run.call_args.kwargs["save_policy"] is SavePolicy.NEVER
        assert mock_run.call_args.kwargs["target_packages"] is None

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

            result = runner.invoke(cli, ["--output", "json", "blueprint", "list"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert "blueprints" in data["result"]
            assert len(data["result"]["blueprints"]) == 1

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
                "--output", "json", "blueprint", "info", "/Game/BP_Test",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["name"] == "BP_Test"

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
                "--output", "json", "blueprint", "add-function", "/Game/BP_Test",
                "--name", "MyFunc",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["status"] == "ok"
            assert data["result"]["function"] == "MyFunc"

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
                "--output", "json", "blueprint", "add-variable", "/Game/BP_Test",
                "--name", "Health", "--type", "float",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["status"] == "ok"
            assert data["result"]["variable"] == "Health"

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
                "--output", "json", "blueprint", "compile", "/Game/BP_Test",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["status"] == "ok"

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
                "--output", "json", "blueprint", "rename-graph", "/Game/BP_Test",
                "--old", "OldFunc", "--new", "NewFunc",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["status"] == "ok"
            assert data["result"]["new_name"] == "NewFunc"


# ═══════════════════════════════════════════════════════════════════════
#  Script Runner
# ═══════════════════════════════════════════════════════════════════════


