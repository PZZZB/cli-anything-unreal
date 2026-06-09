"""Tests for test_scene.py — Uses synthetic data only, no UE editor required."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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

    def test_list_actors_query_checks_label_and_path(self):
        from cli_anything.unreal.core.scene import list_actors

        api = self._mock_api()
        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {"actors": [], "count": 0}
            list_actors(api, name_filter="FmlBush17")

        script = mock_run.call_args.args[1]
        assert "get_actor_label" in script
        assert "get_path_name" in script
        assert '"label": _label' in script
        assert "_query_field = 'all'" in script

    def test_list_actors_class_filter_query_checks_label_and_path(self):
        from cli_anything.unreal.core.scene import list_actors

        api = self._mock_api()
        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {"actors": [], "count": 0}
            list_actors(api, actor_class="StaticMeshActor", name_filter="FmlBush17")

        script = mock_run.call_args.args[1]
        assert "_u.GameplayStatics.get_all_actors_of_class" in script
        assert "get_actor_label" in script
        assert "_matches_actor(_a)" in script

    def test_list_actors_exact_field_options(self):
        from cli_anything.unreal.core.scene import list_actors

        api = self._mock_api()
        with patch("cli_anything.unreal.core.script_runner.run_python_code") as mock_run:
            mock_run.return_value = {"actors": [], "count": 0}
            list_actors(
                api,
                name_filter="StaticMeshActor_27",
                query_field="name",
                exact=True,
            )

        script = mock_run.call_args.args[1]
        assert "_query_field = 'name'" in script
        assert "_exact = True" in script
        assert "str(_value).lower() == _needle" in script

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

            result = runner.invoke(cli, ["--output", "json", "scene", "list"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["count"] == 2

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
                "--output", "json", "scene", "list", "--class", "PointLight",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["count"] == 1

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

            result = runner.invoke(cli, ["--output", "json", "scene", "list", "-q", "Cube"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["count"] == 1
            assert data["result"]["query"] == "Cube"

    def test_scene_find_cli_exact_label_field(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.scene.require_editor") as mock_editor, \
             patch("cli_anything.unreal.core.scene.list_actors") as mock_list:
            mock_api = MagicMock()
            mock_editor.return_value = mock_api
            mock_list.return_value = {"actors": [], "count": 0}

            result = runner.invoke(cli, [
                "--output", "json",
                "scene", "list",
                "-q", "SM_Env_FmlBush17",
                "--field", "label",
                "--exact",
            ])

        assert result.exit_code == 0
        mock_list.assert_called_once_with(
            mock_api,
            actor_class=None,
            name_filter="SM_Env_FmlBush17",
            query_field="label",
            exact=True,
        )

    def test_scene_property_get_cli(self):
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.commands.scene.require_editor") as mock_editor:
            mock_api = MagicMock()
            mock_api.get_property.return_value = {"bHidden": False}
            mock_editor.return_value = mock_api

            result = runner.invoke(cli, [
                "--output", "json", "scene", "property",
                "/Game/Map:Actor_0", "bHidden",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["bHidden"] is False

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
                "--output", "json", "scene", "list-components", "/Game/Map:Actor_0",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert len(data["result"]["components"]) == 1

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
                "--output", "json", "scene", "get-transform", "/Game/Map:Actor_0",
            ])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["rotation"]["Yaw"] == 90


# ═══════════════════════════════════════════════════════════════════════
#  Test asset CLI commands
# ═══════════════════════════════════════════════════════════════════════


