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


    @patch("cli_anything.unreal.core.umg._exec_umg_script")
    def test_get_live_widget_tree_uses_object_iterator_and_runtime_geometry(self, mock_exec):
        from cli_anything.unreal.core.umg import get_live_widget_tree

        mock_exec.return_value = {
            "status": "ok",
            "target": "BP_RXCrosshairStyle_C",
            "count": 1,
            "instances": [
                {
                    "name": "BP_RXCrosshairStyle_C_4",
                    "class": "BP_RXCrosshairStyle_C",
                    "widgets": [
                        {
                            "name": "Image_Dot",
                            "class": "Image",
                            "slot": {"type": "CanvasPanelSlot", "position": [1.0, 2.0], "size": [32.0, 32.0]},
                            "cached_geometry": {"local_size": [32.0, 32.0], "absolute_size": [32.0, 32.0]},
                            "brush": {"resource": "/Game/UI/T_Dot.T_Dot"},
                        }
                    ],
                }
            ],
        }

        result = get_live_widget_tree(MagicMock(), "BP_RXCrosshairStyle_C", limit=3)

        assert result["status"] == "ok"
        assert result["instances"][0]["widgets"][0]["name"] == "Image_Dot"
        script = mock_exec.call_args.args[1]
        assert "unreal.ObjectIterator" in script
        assert "get_cached_geometry" in script
        assert "CanvasPanelSlot" in script
        assert "get_brush" in script
        assert "limit = int(3)" in script


    @patch("cli_anything.unreal.core.umg._exec_umg_script")
    def test_set_widget_image(self, mock_exec):
        from cli_anything.unreal.core.umg import set_widget_image

        mock_exec.return_value = {
            "status": "ok",
            "action": "set_image",
            "widget": {"name": "Icon", "class": "Image"},
        }

        result = set_widget_image(
            MagicMock(),
            "/Game/UI/WBP_Hud",
            widget_name="Icon",
            texture_path="/Game/UI/T_Icon",
            x=12.0,
            y=24.0,
            width=64.0,
            height=32.0,
            z_order=5,
        )

        assert result["status"] == "ok"
        script = mock_exec.call_args.args[1]
        assert "set_widget_image_properties" in script
        assert '"/Game/UI/T_Icon"' in script
        assert "set_position = True" in script
        assert "set_size = True" in script
        assert "set_z_order = True" in script

    @patch("cli_anything.unreal.core.umg._exec_umg_script")
    def test_set_widget_image_can_update_brush_image_size_without_resource(self, mock_exec):
        from cli_anything.unreal.core.umg import set_widget_image

        mock_exec.return_value = {
            "status": "ok",
            "action": "set_image",
            "widget": {"name": "Icon", "class": "Image", "brush": {"image_size": [18.0, 18.0]}},
        }

        result = set_widget_image(
            MagicMock(),
            "/Game/UI/WBP_Hud",
            widget_name="Icon",
            image_size=(18.0, 18.0),
        )

        assert result["status"] == "ok"
        script = mock_exec.call_args.args[1]
        assert "set_resource = False" in script
        assert "set_brush_image_size = True" in script
        assert "image_width = float(18.0)" in script
        assert "image_height = float(18.0)" in script


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

    @patch("cli_anything.unreal.core.umg.get_live_widget_tree")
    def test_umg_live_tree_cli(self, mock_tree):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_tree.return_value = {
            "status": "ok",
            "target": "BP_RXCrosshairStyle_C",
            "count": 1,
            "instances": [{"name": "BP_RXCrosshairStyle_C_4", "widgets": []}],
        }

        with patch("cli_anything.unreal.commands.umg.require_editor", return_value=MagicMock()):
            result = CliRunner().invoke(cli, [
                "--output", "json",
                "umg", "live-tree", "BP_RXCrosshairStyle_C",
                "--limit", "3",
            ])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["instances"][0]["name"] == "BP_RXCrosshairStyle_C_4"
        mock_tree.assert_called_once()
        assert mock_tree.call_args.kwargs["limit"] == 3

    @patch("cli_anything.unreal.core.umg.set_widget_image")
    def test_umg_set_image_cli(self, mock_set):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_set.return_value = {
            "status": "ok",
            "action": "set_image",
            "widget": {"name": "Icon", "class": "Image"},
        }

        with patch("cli_anything.unreal.commands.umg.require_editor", return_value=MagicMock()):
            result = CliRunner().invoke(cli, [
                "--output", "json",
                "umg", "set-image", "/Game/UI/WBP_Hud",
                "--name", "Icon",
                "--texture", "/Game/UI/T_Icon",
                "--x", "12",
                "--y", "24",
                "--w", "64",
                "--h", "32",
                "--z", "5",
            ])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["widget"]["name"] == "Icon"
        mock_set.assert_called_once()

    @patch("cli_anything.unreal.core.umg.set_widget_image")
    def test_umg_set_image_cli_accepts_image_size(self, mock_set):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        mock_set.return_value = {
            "status": "ok",
            "action": "set_image",
            "widget": {"name": "Icon", "class": "Image"},
        }

        with patch("cli_anything.unreal.commands.umg.require_editor", return_value=MagicMock()):
            result = CliRunner().invoke(cli, [
                "--output", "json",
                "umg", "set-image", "/Game/UI/WBP_Hud",
                "--name", "Icon",
                "--image-size", "18", "18",
            ])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "success"
        mock_set.assert_called_once()
        assert mock_set.call_args.kwargs["image_size"] == (18.0, 18.0)
