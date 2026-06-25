"""Tests for UMG authoring commands."""

import json
from unittest.mock import MagicMock, patch


class TestUMGCore:
    def test_widget_asset_path_candidates_normalizes_generated_class_and_subobject(self):
        from cli_anything.unreal.core.umg import _widget_asset_path_candidates

        assert _widget_asset_path_candidates("/Game/UI/WBP_Hud") == [
            "/Game/UI/WBP_Hud",
            "/Game/UI/WBP_Hud.WBP_Hud",
        ]
        assert _widget_asset_path_candidates("/Game/UI/WBP_Hud.WBP_Hud") == [
            "/Game/UI/WBP_Hud.WBP_Hud",
            "/Game/UI/WBP_Hud",
        ]
        assert _widget_asset_path_candidates("/Game/UI/WBP_Hud.WBP_Hud_C") == [
            "/Game/UI/WBP_Hud.WBP_Hud",
            "/Game/UI/WBP_Hud",
        ]
        assert _widget_asset_path_candidates("/Game/UI/WBP_Hud.WBP_Hud:WidgetTree.TitleText") == [
            "/Game/UI/WBP_Hud.WBP_Hud",
            "/Game/UI/WBP_Hud",
        ]

    @patch("cli_anything.unreal.core.umg._exec_umg_script")
    def test_create_widget_blueprint(self, mock_exec):
        from cli_anything.unreal.core.umg import create_widget_blueprint

        mock_exec.return_value = {
            "status": "ok",
            "action": "create",
            "widget": "/Game/UI/WBP_Hud",
            "root": {"name": "RootCanvas", "class": "CanvasPanel"},
        }

        result = create_widget_blueprint(MagicMock(), "/Game/UI/WBP_Hud", force=True)

        assert result["status"] == "ok"
        assert result["root"]["class"] == "CanvasPanel"
        script = mock_exec.call_args.args[1]
        assert "set_widget_blueprint_root" in script

    @patch("cli_anything.unreal.core.umg._exec_umg_script")
    def test_add_widget_to_canvas(self, mock_exec):
        from cli_anything.unreal.core.umg import add_widget_to_canvas

        mock_exec.return_value = {
            "status": "ok",
            "action": "add_widget",
            "widget": {"name": "TitleText", "class": "TextBlock"},
            "slot": {"position": [10.0, 20.0], "size": [320.0, 48.0], "z_order": 3},
        }

        result = add_widget_to_canvas(
            MagicMock(),
            "/Game/UI/WBP_Hud",
            widget_type="TextBlock",
            widget_name="TitleText",
            text="Ready",
            x=10.0,
            y=20.0,
            width=320.0,
            height=48.0,
            z_order=3,
            variable=True,
        )

        assert result["status"] == "ok"
        assert result["widget"]["name"] == "TitleText"
        script = mock_exec.call_args.args[1]
        assert "add_widget_to_canvas" in script
        assert '"Ready"' in script

    @patch("cli_anything.unreal.core.umg._exec_umg_script")
    def test_get_widget_tree(self, mock_exec):
        from cli_anything.unreal.core.umg import get_widget_tree

        mock_exec.return_value = {
            "status": "ok",
            "widget": "/Game/UI/WBP_Hud",
            "root": {"name": "RootCanvas", "class": "CanvasPanel"},
            "widgets": [
                {"name": "RootCanvas", "class": "CanvasPanel"},
                {"name": "TitleText", "class": "TextBlock"},
            ],
        }

        result = get_widget_tree(MagicMock(), "/Game/UI/WBP_Hud")

        assert result["status"] == "ok"
        assert result["root"]["name"] == "RootCanvas"
        assert len(result["widgets"]) == 2

    @patch("cli_anything.unreal.core.umg._exec_umg_script")
    def test_get_widget_tree_uses_asset_registry_fallback(self, mock_exec):
        from cli_anything.unreal.core.umg import get_widget_tree

        mock_exec.return_value = {"status": "ok", "widgets": []}

        get_widget_tree(MagicMock(), "/Game/UI/WBP_Hud")

        script = mock_exec.call_args.args[1]
        assert "def _cli_load_widget_blueprint" in script
        assert "get_assets_by_package_name" in script
        assert "data.get_asset()" in script


class TestUMGCLI:
    @patch("cli_anything.unreal.core.umg.create_widget_blueprint")
    def test_umg_create_cli(self, mock_create):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_create.return_value = {
            "status": "ok",
            "action": "create",
            "widget": "/Game/UI/WBP_Hud",
            "root": {"name": "RootCanvas", "class": "CanvasPanel"},
        }

        with patch("cli_anything.unreal.commands.umg.require_editor", return_value=MagicMock()):
            result = CliRunner().invoke(cli, [
                "--output", "json",
                "umg", "create", "/Game/UI/WBP_Hud",
                "--force",
            ])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["widget"] == "/Game/UI/WBP_Hud"

    @patch("cli_anything.unreal.core.umg.add_widget_to_canvas")
    def test_umg_add_widget_cli(self, mock_add):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_add.return_value = {
            "status": "ok",
            "action": "add_widget",
            "widget": {"name": "TitleText", "class": "TextBlock"},
        }

        with patch("cli_anything.unreal.commands.umg.require_editor", return_value=MagicMock()):
            result = CliRunner().invoke(cli, [
                "--output", "json",
                "umg", "add-widget", "/Game/UI/WBP_Hud",
                "--type", "TextBlock",
                "--name", "TitleText",
                "--text", "Ready",
                "--x", "10",
                "--y", "20",
                "--w", "320",
                "--h", "48",
                "--z", "3",
                "--variable",
            ])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["widget"]["name"] == "TitleText"

    @patch("cli_anything.unreal.core.umg.get_widget_tree")
    def test_umg_tree_cli(self, mock_tree):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_tree.return_value = {
            "status": "ok",
            "widget": "/Game/UI/WBP_Hud",
            "root": {"name": "RootCanvas", "class": "CanvasPanel"},
            "widgets": [],
        }

        with patch("cli_anything.unreal.commands.umg.require_editor", return_value=MagicMock()):
            result = CliRunner().invoke(cli, [
                "--output", "json",
                "umg", "tree", "/Game/UI/WBP_Hud",
            ])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["root"]["class"] == "CanvasPanel"
