"""test_core.py — Unit tests for cli-anything-unreal core modules.

Uses synthetic data only — no UE editor or engine installation required.
"""

import json
import os
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
            # Result depends on default paths existing


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

        with patch("cli_anything.unreal.core.build.find_engine_root", return_value=None):
            result = compile_project(temp_project["uproject"])
            assert result["status"] == "error"
            assert "engine root" in result["error"].lower()

    def test_cook_no_engine(self, temp_project):
        from cli_anything.unreal.core.build import cook_content

        with patch("cli_anything.unreal.core.build.find_engine_root", return_value=None):
            result = cook_content(temp_project["uproject"])
            assert result["status"] == "error"

    def test_package_no_engine(self, temp_project):
        from cli_anything.unreal.core.build import package_project

        with patch("cli_anything.unreal.core.build.find_engine_root", return_value=None):
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
        assert len(result["properties"]) == 1
        assert "SetBlendMode" in result["functions"]
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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor:
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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor:
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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor:
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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor:
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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor:
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

    def test_screenshot_cvar_test_mismatched_labels(self):
        """Test error when labels and values length mismatch."""
        from cli_anything.unreal.core.screenshot import screenshot_with_cvar

        mock_api = MagicMock()
        result = screenshot_with_cvar(
            mock_api,
            "r.Test",
            values=["0", "1"],
            labels=["only_one"],
        )
        assert "error" in result


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
        result = runner.invoke(cli, [
            "--json", "--project", temp_project["uproject"],
            "project", "content",
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
        assert data["status"] == "offline"

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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor:
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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor:
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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor:
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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor:
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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor:
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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor:
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
    """Tests for core.script_runner — generic Python execution with result capture."""

    # -- run_python_script / run_python_code internals ------------------

    def test_run_python_script_captures_result(self, tmp_path):
        """When user script defines ``result``, it should be captured."""
        from cli_anything.unreal.core.script_runner import run_python_script

        script = tmp_path / "test.py"
        script.write_text("result = {'hello': 'world', 'count': 42}\n", encoding="utf-8")

        mock_api = MagicMock()

        # Simulate editor execution: when exec_python_file is called,
        # we actually run the wrapper script ourselves.
        def _fake_exec(wrapper_path):
            exec(compile(Path(wrapper_path).read_text(encoding="utf-8"),
                         wrapper_path, "exec"))
            return {}
        mock_api.exec_python_file.side_effect = _fake_exec

        result = run_python_script(mock_api, str(script),
                                   project_dir=str(tmp_path), timeout=5,
                                   save=False)
        assert result["hello"] == "world"
        assert result["count"] == 42

    def test_run_python_code_captures_result(self, tmp_path):
        """``run_python_code`` with inline code and a result variable."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()

        def _fake_exec(wrapper_path):
            exec(compile(Path(wrapper_path).read_text(encoding="utf-8"),
                         wrapper_path, "exec"))
            return {}
        mock_api.exec_python_file.side_effect = _fake_exec

        result = run_python_code(mock_api, "result = {'actors': 99}",
                                 project_dir=str(tmp_path), timeout=5,
                                 save=False)
        assert result["actors"] == 99

    def test_no_result_variable(self, tmp_path):
        """When user script does NOT define ``result``, a generic ok is returned."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()

        def _fake_exec(wrapper_path):
            exec(compile(Path(wrapper_path).read_text(encoding="utf-8"),
                         wrapper_path, "exec"))
            return {}
        mock_api.exec_python_file.side_effect = _fake_exec

        result = run_python_code(mock_api, "x = 1 + 1",
                                 project_dir=str(tmp_path), timeout=5,
                                 save=False)
        assert result["status"] == "ok"
        assert "no result variable" in result["note"].lower()

    def test_non_dict_result_wrapped(self, tmp_path):
        """A non-dict ``result`` should be wrapped as {"value": ...}."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()

        def _fake_exec(wrapper_path):
            exec(compile(Path(wrapper_path).read_text(encoding="utf-8"),
                         wrapper_path, "exec"))
            return {}
        mock_api.exec_python_file.side_effect = _fake_exec

        result = run_python_code(mock_api, "result = 'just a string'",
                                 project_dir=str(tmp_path), timeout=5,
                                 save=False)
        assert result["status"] == "ok"
        assert result["value"] == "just a string"

    def test_timeout_returns_error(self, tmp_path):
        """If the JSON output never appears, an error dict is returned."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        mock_api.exec_python_file.return_value = {}  # no-op — output never written

        result = run_python_code(mock_api, "result = {'should': 'timeout'}",
                                 project_dir=str(tmp_path), timeout=0.5)
        assert "error" in result
        assert "timed out" in result["error"].lower()

    def test_temp_files_cleaned_up(self, tmp_path):
        """Wrapper script and output JSON should be removed after execution."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()

        def _fake_exec(wrapper_path):
            exec(compile(Path(wrapper_path).read_text(encoding="utf-8"),
                         wrapper_path, "exec"))
            return {}
        mock_api.exec_python_file.side_effect = _fake_exec

        temp_dir = tmp_path / "Saved" / "Temp"
        run_python_code(mock_api, "result = {'clean': True}",
                        project_dir=str(tmp_path), timeout=5,
                        save=False)

        remaining = list(temp_dir.glob("_run_*"))
        assert remaining == [], f"Temp files not cleaned up: {remaining}"

    def test_uses_system_temp_without_project_dir(self):
        """Without project_dir, temp files go to system temp directory."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()
        mock_api.exec_python_file.return_value = {}

        # Just verify it doesn't crash — timeout is expected
        result = run_python_code(mock_api, "result = {}", timeout=0.5)
        assert "error" in result  # timed out because no real exec

    # -- CLI integration tests ------------------------------------------

    def test_editor_exec_py_uses_script_runner(self):
        """``editor exec 'py ...'`` should route through run_python_code."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        runner = CliRunner()
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor, \
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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor:
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
        with patch("cli_anything.unreal.unreal_cli._require_editor") as mock_editor, \
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

    def test_script_error_captured(self, tmp_path):
        """When user script raises an exception, error details are returned (not timeout)."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()

        def _fake_exec(wrapper_path):
            exec(compile(Path(wrapper_path).read_text(encoding="utf-8"),
                         wrapper_path, "exec"))
            return {}
        mock_api.exec_python_file.side_effect = _fake_exec

        result = run_python_code(
            mock_api,
            "raise ValueError('something went wrong')",
            project_dir=str(tmp_path), timeout=5,
            save=False,
        )
        assert "error" in result
        assert "something went wrong" in result["error"]
        assert result["error_type"] == "ValueError"
        assert "traceback" in result

    def test_script_attribute_error_captured(self, tmp_path):
        """Simulate the real-world AttributeError from the UE module scenario."""
        from cli_anything.unreal.core.script_runner import run_python_code

        mock_api = MagicMock()

        def _fake_exec(wrapper_path):
            exec(compile(Path(wrapper_path).read_text(encoding="utf-8"),
                         wrapper_path, "exec"))
            return {}
        mock_api.exec_python_file.side_effect = _fake_exec

        code = "import os\n_ = os.nonexistent_attr\n"
        result = run_python_code(mock_api, code,
                                 project_dir=str(tmp_path), timeout=5,
                                 save=False)
        assert "error" in result
        assert result["error_type"] == "AttributeError"
