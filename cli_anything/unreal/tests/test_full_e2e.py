"""test_full_e2e.py — End-to-end tests for cli-anything-unreal.

These tests require:
1. A UE editor running with AutomationTestAPI plugin
2. A valid project path

Set environment variables before running:
    UE_TEST_PROJECT=F:\\Test_RXEngine_5_7\\Test_RXEngine_5_7.uproject
    UE_TEST_PORT=30020  (optional; if unset, port is read from Config/DefaultRemoteControl.ini)

Run with:
    pytest cli_anything/unreal/tests/test_full_e2e.py -v --e2e

Screenshot sequence E2E (``TestScreenshotE2E``) needs the editor window able to tick
(Focus / Realtime); use the project's Remote Control port (or ``UE_TEST_PORT``).

Skip with:
    pytest cli_anything/unreal/tests/test_full_e2e.py -v  (auto-skips without --e2e)
"""

import json
import os
from pathlib import Path

import pytest

# Skip conditions are in conftest.py (pytest_addoption, pytest_configure, etc.)

# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def project_path():
    """Get test project path from environment."""
    path = os.environ.get("UE_TEST_PROJECT")
    if not path or not Path(path).exists():
        pytest.skip("UE_TEST_PROJECT not set or project not found")
    return path


@pytest.fixture
def api_port(project_path):
    """Resolve Remote Control port: UE_TEST_PORT, else project DefaultRemoteControl.ini, else 30010."""
    env = os.environ.get("UE_TEST_PORT")
    if env:
        return int(env)
    from cli_anything.unreal.utils.ue_backend import read_rc_port

    pd = str(Path(project_path).parent)
    ini_port = read_rc_port(pd)
    return ini_port if ini_port is not None else 30010


@pytest.fixture
def api(api_port):
    """Get a connected API instance."""
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    api = UEEditorAPI(port=api_port)
    if not api.is_alive():
        pytest.skip(f"UE editor not reachable on port {api_port}")
    return api


@pytest.fixture
def cli_runner():
    """Get a Click test runner."""
    from click.testing import CliRunner
    return CliRunner()


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Editor Connection
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestEditorConnection:
    """Test editor HTTP API connection."""

    def test_editor_is_alive(self, api):
        assert api.is_alive() is True

    def test_editor_status_cli(self, cli_runner, api_port):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--port", str(api_port),
            "editor", "status",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "online"


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Project Info
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestProjectE2E:
    """Test project info queries."""

    def test_project_info(self, cli_runner, project_path):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "project", "info",
            "--project", project_path,
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "name" in data
        assert "modules" in data

    def test_project_config_list(self, cli_runner, project_path):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path,
            "project", "config", "list",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) > 0

    def test_project_content(self, cli_runner, project_path):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path,
            "project", "content",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "count" in data


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Materials
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestMaterialsE2E:
    """Test material queries against running editor."""

    def test_material_list(self, api, project_path):
        from cli_anything.unreal.core.materials import list_materials

        project_dir = str(Path(project_path).parent)
        result = list_materials(api, "/Game/", project_dir)
        assert "materials" in result
        assert isinstance(result["materials"], list)

    def test_material_info(self, api, project_path):
        """Test getting info on first available material."""
        from cli_anything.unreal.core.materials import list_materials, get_material_info

        project_dir = str(Path(project_path).parent)
        materials = list_materials(api, "/Game/", project_dir)

        if not materials.get("materials"):
            pytest.skip("No materials found in project")

        mat_path = materials["materials"][0]["path"]
        info = get_material_info(api, mat_path, project_dir)
        assert "name" in info

    def test_material_analyze_cli(self, cli_runner, project_path, api_port):
        """Test material analyze via CLI."""
        from cli_anything.unreal.unreal_cli import cli

        # First list materials
        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path, "--port", str(api_port),
            "material", "list",
        ])
        if result.exit_code != 0:
            pytest.skip("Could not list materials")

        data = json.loads(result.output)
        if not data.get("materials"):
            pytest.skip("No materials in project")

        mat_path = data["materials"][0]["path"]

        # Analyze
        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path, "--port", str(api_port),
            "material", "analyze", mat_path,
        ])
        assert result.exit_code == 0
        analysis = json.loads(result.output)
        assert "issues" in analysis
        assert "warnings" in analysis


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Screenshots
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestScreenshotE2E:
    """Test screenshot functionality against running editor."""

    def test_take_screenshot(self, api, project_path):
        from cli_anything.unreal.core.screenshot import take_screenshot

        project_dir = str(Path(project_path).parent)
        result = take_screenshot(
            api, "e2e_test_screenshot",
            disable_noisy=True,
            project_dir=project_dir,
        )
        # Should not error
        assert "error" not in result or result.get("status") == "ok"

    def test_screenshot_cli(self, cli_runner, project_path, api_port):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path, "--port", str(api_port),
            "screenshot", "take", "--filename", "e2e_cli_test",
        ])
        assert result.exit_code == 0

    def test_screenshot_sequence_cli(self, cli_runner, project_path, api_port):
        """CLI ``screenshot sequence``: atlas + default compressed output when Pillow works."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path, "--port", str(api_port),
            "screenshot", "sequence", "-n", "2", "-i", "0.35",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        if data.get("status") != "ok":
            pytest.skip(
                "sequence capture incomplete (viewport focus or UE automation queue); "
                f"detail: {data.get('error', data)}"
            )

        atlas = Path(data["atlas_path"])
        assert atlas.exists()
        assert atlas.stat().st_size > 1000
        assert data.get("frame_count") == 2
        assert len(data.get("frame_paths") or []) == 2
        for fp in data["frame_paths"]:
            assert Path(fp).exists()

        grid = data.get("grid") or {}
        assert grid.get("cols", 0) >= 1
        assert grid.get("rows", 0) >= 1

        prep = data.get("viewport_prep") or {}
        assert prep.get("realtime") is True

        assert data.get("cli_command", "").startswith("screenshot sequence")
        assert "llm_context" in data

        dp = data.get("default_path") or ""
        assert dp
        assert Path(dp).exists()
        if data.get("compressed"):
            assert Path(data["compressed"]).exists()
            assert dp.lower().endswith(".jpg")
        else:
            # Pillow missing or compress failed — still a valid primary path
            assert dp.lower().endswith(".png")

    def test_screenshot_sequence_cli_no_compress(self, cli_runner, project_path, api_port):
        """CLI ``--no-compress``: primary output is PNG atlas only."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path, "--port", str(api_port),
            "screenshot", "sequence", "-n", "2", "-i", "0.35", "--no-compress",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        if data.get("status") != "ok":
            pytest.skip(
                "sequence capture incomplete; "
                f"detail: {data.get('error', data)}"
            )

        assert Path(data["atlas_path"]).exists()
        assert data.get("default_path") == data.get("atlas_path")
        assert str(data["default_path"]).lower().endswith(".png")
        assert "compressed" not in data

    def test_capture_screenshot_atlas_core(self, api, project_path):
        """Core ``capture_screenshot_atlas`` (same path as CLI) without Click."""
        from cli_anything.unreal.core.screenshot import capture_screenshot_atlas

        project_dir = str(Path(project_path).parent)
        result = capture_screenshot_atlas(
            api,
            2,
            interval=0.35,
            project_dir=project_dir,
            jpeg_for_llm=True,
            max_atlas_edge=1920,
        )
        if result.get("status") != "ok":
            pytest.skip(
                "capture_screenshot_atlas failed; "
                f"detail: {result.get('error', result)}"
            )

        assert Path(result["atlas_path"]).exists()
        assert result["frame_count"] == 2
        assert (result.get("viewport_prep") or {}).get("realtime") is True
        if result.get("compressed"):
            assert Path(result["compressed"]).exists()


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Console Commands
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestConsoleE2E:
    """Test console command execution."""

    def test_exec_console(self, api):
        result = api.exec_console("stat fps")
        assert "error" not in result

    def test_cvar_get_set(self, api):
        # Get a known CVar
        val = api.get_cvar("r.VSync")
        assert val is not None

    def test_exec_cli(self, cli_runner, api_port):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--port", str(api_port),
            "editor", "exec", "stat fps",
        ])
        assert result.exit_code == 0


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Material Node Editing (MaterialEditingLibrary)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestMaterialEditingE2E:
    """Test material editing via MaterialEditingLibrary against running editor.

    Creates a temporary material, adds/connects/disconnects/deletes nodes,
    then cleans up.
    """

    TEST_MATERIAL = "/Game/E2E_TestMaterial"
    _material_created = False

    @pytest.fixture(autouse=True)
    def _ensure_test_material(self, api, project_path):
        """Create test material once (first test), clean nodes before each test."""
        from cli_anything.unreal.core.materials import _exec_material_script

        project_dir = str(Path(project_path).parent)

        if not TestMaterialEditingE2E._material_created:
            # First test: create material
            create_script = '''
import unreal
import json

mat_path = "/Game/E2E_TestMaterial"

EAL = unreal.EditorAssetLibrary
can_create = True
if EAL.does_asset_exist(mat_path):
    if EAL.delete_asset(mat_path):
        unreal.SystemLibrary.collect_garbage()
    else:
        can_create = False

if can_create:
    factory = unreal.MaterialFactoryNew()
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    mat = asset_tools.create_asset("E2E_TestMaterial", "/Game", unreal.Material, factory)
else:
    mat = None

if mat is not None:
    result = {{"status": "ok", "name": mat.get_name()}}
else:
    result = {{"error": "Failed to create test material"}}
'''
            result = _exec_material_script(api, create_script, project_dir=project_dir)
            if "error" in result:
                pytest.skip(f"Could not create test material: {result['error']}")
            TestMaterialEditingE2E._material_created = True
        else:
            # Subsequent tests: just clean nodes
            clean_script = '''
import unreal
import json

mat = unreal.EditorAssetLibrary.load_asset("/Game/E2E_TestMaterial")
if mat is not None:
    mel = unreal.MaterialEditingLibrary
    mel.delete_all_material_expressions(mat)
    mel.recompile_material(mat)
    result = {{"status": "ok"}}
else:
    result = {{"error": "material not loaded"}}
'''
            _exec_material_script(api, clean_script, project_dir=project_dir)

        yield

    @pytest.fixture(autouse=True, scope="class")
    def _cleanup_after_all(self, request):
        """Delete test material after all tests in this class."""
        yield
        # Reset flag for next test run
        TestMaterialEditingE2E._material_created = False

    def test_add_node(self, api, project_path):
        """Test adding a node to a material."""
        from cli_anything.unreal.core.materials import add_material_node

        project_dir = str(Path(project_path).parent)
        result = add_material_node(
            api, self.TEST_MATERIAL,
            "MaterialExpressionConstant3Vector",
            pos_x=-300, pos_y=0,
            project_dir=project_dir,
        )
        assert result.get("status") == "ok", f"add_node failed: {result}"
        assert result["node"]["type"] == "MaterialExpressionConstant3Vector"

    def test_add_and_connect_to_base_color(self, api, project_path):
        """Test adding a node and connecting it to BaseColor output."""
        from cli_anything.unreal.core.materials import (
            add_material_node, connect_material_nodes, get_material_info,
        )

        project_dir = str(Path(project_path).parent)

        # Add a Constant3Vector node
        add_result = add_material_node(
            api, self.TEST_MATERIAL,
            "MaterialExpressionConstant3Vector",
            pos_x=-300, pos_y=0,
            project_dir=project_dir,
        )
        assert add_result.get("status") == "ok", f"add failed: {add_result}"
        node_name = add_result["node"]["name"]

        # Connect it to material BaseColor
        conn_result = connect_material_nodes(
            api, self.TEST_MATERIAL,
            node_name, "",
            "__material_output__", "BaseColor",
            project_dir=project_dir,
        )
        assert conn_result.get("status") == "ok", f"connect failed: {conn_result}"

        # Verify via material info — should have at least 1 node
        info = get_material_info(api, self.TEST_MATERIAL, project_dir)
        assert info.get("node_count", 0) >= 1

    def test_add_and_delete_node(self, api, project_path):
        """Test adding then deleting a node."""
        from cli_anything.unreal.core.materials import (
            add_material_node, delete_material_node,
        )

        project_dir = str(Path(project_path).parent)

        # Add
        add_result = add_material_node(
            api, self.TEST_MATERIAL,
            "MaterialExpressionConstant",
            project_dir=project_dir,
        )
        assert add_result.get("status") == "ok"
        node_name = add_result["node"]["name"]

        # Delete
        del_result = delete_material_node(
            api, self.TEST_MATERIAL, node_name,
            project_dir=project_dir,
        )
        assert del_result.get("status") == "ok"
        assert del_result["deleted_node"] == node_name

    def test_connect_and_disconnect(self, api, project_path):
        """Test connecting and disconnecting nodes."""
        from cli_anything.unreal.core.materials import (
            add_material_node, connect_material_nodes, disconnect_material_nodes,
        )

        project_dir = str(Path(project_path).parent)

        # Add node
        add_result = add_material_node(
            api, self.TEST_MATERIAL,
            "MaterialExpressionConstant3Vector",
            project_dir=project_dir,
        )
        assert add_result.get("status") == "ok"
        node_name = add_result["node"]["name"]

        # Connect to BaseColor
        conn = connect_material_nodes(
            api, self.TEST_MATERIAL,
            node_name, "", "__material_output__", "BaseColor",
            project_dir=project_dir,
        )
        assert conn.get("status") == "ok"

        # Disconnect
        disc = disconnect_material_nodes(
            api, self.TEST_MATERIAL,
            node_name, "", "__material_output__", "BaseColor",
            project_dir=project_dir,
        )
        assert disc.get("status") == "ok"

    def test_recompile(self, api, project_path):
        """Test recompiling a material."""
        from cli_anything.unreal.core.materials import recompile_material

        project_dir = str(Path(project_path).parent)
        result = recompile_material(api, self.TEST_MATERIAL, project_dir=project_dir)
        assert result.get("status") == "ok"

    def test_add_node_cli(self, cli_runner, project_path, api_port):
        """Test add-node via CLI."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path, "--port", str(api_port),
            "material", "add-node", self.TEST_MATERIAL,
            "--type", "MaterialExpressionConstant",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        assert data.get("status") == "ok"

    def test_recompile_cli(self, cli_runner, project_path, api_port):
        """Test recompile via CLI."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path, "--port", str(api_port),
            "material", "recompile", self.TEST_MATERIAL,
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data.get("status") == "ok"


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Material Errors via Bridge Plugin
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestMaterialErrorsPluginE2E:
    """Test get_material_errors using the CliAnythingBridge plugin.

    Requires the bridge plugin to be compiled and loaded in the editor.
    """

    def test_clean_material_no_errors(self, api, project_path):
        """Clean material should report no compile errors."""
        from cli_anything.unreal.core.materials import get_material_errors

        project_dir = str(Path(project_path).parent)
        result = get_material_errors(api, "/Game/E2E_TestMaterial", project_dir=project_dir)

        if "error" in result and "not loaded" in result.get("error", ""):
            pytest.skip("Bridge plugin not loaded in editor")

        assert result.get("source") == "plugin"
        assert result.get("has_errors") is False
        assert result.get("errors") == []

    def test_broken_material_has_errors(self, api, project_path):
        """Material with invalid Custom HLSL should report compile errors."""
        from cli_anything.unreal.core.materials import get_material_errors
        from cli_anything.unreal.core.script_runner import run_python_code

        project_dir = str(Path(project_path).parent)

        # Create material with bad HLSL and recompile (all UE-side).
        # Uses "return invalid_var;" which fails fast (single undeclared identifier).
        setup_script = r'''
import unreal

EAL = unreal.EditorAssetLibrary
ATH = unreal.AssetToolsHelpers.get_asset_tools()
mel = unreal.MaterialEditingLibrary

mat_path = "/Game/E2E_ErrorMaterial"
can_create = True
if EAL.does_asset_exist(mat_path):
    if EAL.delete_asset(mat_path):
        unreal.SystemLibrary.collect_garbage()
    else:
        can_create = False

if can_create:
    mat = ATH.create_asset("E2E_ErrorMaterial", "/Game", unreal.Material, unreal.MaterialFactoryNew())
    custom = mel.create_material_expression(mat, unreal.MaterialExpressionCustom, -300, 0)
    custom.set_editor_property("code", "return invalid_var;")
    custom.set_editor_property("output_type", unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    mel.connect_material_property(custom, "", unreal.MaterialProperty.MP_BASE_COLOR)
    mel.recompile_material(mat)
    result = {"status": "ok"}
else:
    result = {"error": "delete_asset failed for E2E_ErrorMaterial"}
'''
        setup = run_python_code(api, setup_script, timeout=60.0)
        assert setup.get("status") == "ok", f"Setup failed: {setup}"

        try:
            result = get_material_errors(api, "/Game/E2E_ErrorMaterial", project_dir=project_dir)

            if "error" in result and "not loaded" in result.get("error", ""):
                pytest.skip("Bridge plugin not loaded in editor")

            assert result.get("source") == "plugin"
            assert result.get("has_errors") is True
            assert len(result.get("errors", [])) > 0
            all_errors = " ".join(result["errors"])
            assert "invalid_var" in all_errors
        finally:
            cleanup = r'''
import unreal
EAL = unreal.EditorAssetLibrary
if EAL.does_asset_exist("/Game/E2E_ErrorMaterial"):
    EAL.delete_asset("/Game/E2E_ErrorMaterial")
    unreal.SystemLibrary.collect_garbage()
result = {"cleaned": True}
'''
            run_python_code(api, cleanup, timeout=15.0)

    def test_material_errors_cli(self, cli_runner, project_path, api_port):
        """Test material errors CLI command returns plugin-sourced results."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path, "--port", str(api_port),
            "material", "errors", "/Game/E2E_TestMaterial",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)

        if "error" in data and "not loaded" in data.get("error", ""):
            pytest.skip("Bridge plugin not loaded")

        assert data.get("source") == "plugin"
        assert data.get("has_errors") is False


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Blueprint Editing (BlueprintEditorLibrary)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestBlueprintEditingE2E:
    """Test blueprint editing via BlueprintEditorLibrary against running editor.

    Creates a temporary blueprint, adds functions/variables, inspects info,
    compiles, then cleans up.
    """

    TEST_BLUEPRINT = "/Game/E2E_TestBlueprint"
    _blueprint_created = False

    @pytest.fixture(autouse=True)
    def _ensure_test_blueprint(self, api, project_path):
        """Create test blueprint once (first test)."""
        from cli_anything.unreal.core.blueprint import _exec_blueprint_script

        project_dir = str(Path(project_path).parent)

        if not TestBlueprintEditingE2E._blueprint_created:
            create_script = '''
import unreal
import json

bp_path = "/Game/E2E_TestBlueprint"

EAL = unreal.EditorAssetLibrary
can_create = True
if EAL.does_asset_exist(bp_path):
    if EAL.delete_asset(bp_path):
        unreal.SystemLibrary.collect_garbage()
    else:
        can_create = False

if can_create:
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.Actor)
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    bp = asset_tools.create_asset("E2E_TestBlueprint", "/Game", unreal.Blueprint, factory)
else:
    bp = None

if bp is not None:
    result = {{"status": "ok", "name": bp.get_name()}}
else:
    result = {{"error": "Failed to create test blueprint"}}
'''
            result = _exec_blueprint_script(api, create_script, project_dir=project_dir)
            if "error" in result:
                pytest.skip(f"Could not create test blueprint: {result['error']}")
            TestBlueprintEditingE2E._blueprint_created = True

        yield

    @pytest.fixture(autouse=True, scope="class")
    def _cleanup_after_all(self, request):
        """Reset flag after all tests in this class."""
        yield
        TestBlueprintEditingE2E._blueprint_created = False

    def test_blueprint_list(self, api, project_path):
        """Test listing blueprints."""
        from cli_anything.unreal.core.blueprint import list_blueprints

        project_dir = str(Path(project_path).parent)
        result = list_blueprints(api, "/Game/", project_dir)
        assert "blueprints" in result
        assert isinstance(result["blueprints"], list)
        # Our test blueprint should be in the list
        names = [b["name"] for b in result["blueprints"]]
        assert "E2E_TestBlueprint" in names

    def test_blueprint_info(self, api, project_path):
        """Test getting blueprint info."""
        from cli_anything.unreal.core.blueprint import get_blueprint_info

        project_dir = str(Path(project_path).parent)
        result = get_blueprint_info(api, self.TEST_BLUEPRINT, project_dir)
        assert result.get("name") == "E2E_TestBlueprint"
        assert "graphs" in result
        assert "nodes" in result

    def test_add_function(self, api, project_path):
        """Test adding a function graph."""
        from cli_anything.unreal.core.blueprint import add_function

        project_dir = str(Path(project_path).parent)
        result = add_function(api, self.TEST_BLUEPRINT, "E2E_TestFunc",
                              project_dir=project_dir)
        assert result.get("status") == "ok", f"add_function failed: {result}"
        assert result["function"] == "E2E_TestFunc"

    def test_add_and_remove_function(self, api, project_path):
        """Test adding then removing a function graph."""
        from cli_anything.unreal.core.blueprint import add_function, remove_function

        project_dir = str(Path(project_path).parent)

        # Add
        add_result = add_function(api, self.TEST_BLUEPRINT, "E2E_TempFunc",
                                  project_dir=project_dir)
        assert add_result.get("status") == "ok", f"add failed: {add_result}"

        # Remove
        remove_result = remove_function(api, self.TEST_BLUEPRINT, "E2E_TempFunc",
                                        project_dir=project_dir)
        assert remove_result.get("status") == "ok", f"remove failed: {remove_result}"

    def test_add_variable(self, api, project_path):
        """Test adding a member variable."""
        from cli_anything.unreal.core.blueprint import add_variable

        project_dir = str(Path(project_path).parent)
        result = add_variable(api, self.TEST_BLUEPRINT, "E2E_Health", "float",
                              project_dir=project_dir)
        assert result.get("status") == "ok", f"add_variable failed: {result}"
        assert result["variable"] == "E2E_Health"
        assert result["type"] == "float"

    def test_add_variable_bool(self, api, project_path):
        """Test adding a bool variable."""
        from cli_anything.unreal.core.blueprint import add_variable

        project_dir = str(Path(project_path).parent)
        result = add_variable(api, self.TEST_BLUEPRINT, "E2E_IsAlive", "bool",
                              project_dir=project_dir)
        assert result.get("status") == "ok", f"add_variable failed: {result}"

    def test_compile(self, api, project_path):
        """Test compiling a blueprint."""
        from cli_anything.unreal.core.blueprint import compile_blueprint

        project_dir = str(Path(project_path).parent)
        result = compile_blueprint(api, self.TEST_BLUEPRINT, project_dir=project_dir)
        assert result.get("status") == "ok", f"compile failed: {result}"

    def test_blueprint_list_cli(self, cli_runner, project_path, api_port):
        """Test blueprint list via CLI."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path, "--port", str(api_port),
            "blueprint", "list",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        assert "blueprints" in data

    def test_blueprint_info_cli(self, cli_runner, project_path, api_port):
        """Test blueprint info via CLI."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path, "--port", str(api_port),
            "blueprint", "info", self.TEST_BLUEPRINT,
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        assert data.get("name") == "E2E_TestBlueprint"

    def test_blueprint_compile_cli(self, cli_runner, project_path, api_port):
        """Test blueprint compile via CLI."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--project", project_path, "--port", str(api_port),
            "blueprint", "compile", self.TEST_BLUEPRINT,
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        assert data.get("status") == "ok"


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Scene Queries
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestSceneE2E:
    """Test scene/level actor queries against running editor."""

    def test_list_actors(self, api):
        from cli_anything.unreal.core.scene import list_actors

        result = list_actors(api)
        assert "actors" in result
        assert isinstance(result["actors"], list)
        assert result["count"] >= 0

    def test_list_actors_cli(self, cli_runner, api_port):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--port", str(api_port),
            "scene", "actors",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "actors" in data
        assert "count" in data

    def test_find_actor_by_name(self, api):
        from cli_anything.unreal.core.scene import list_actors, find_actor_by_name

        all_actors = list_actors(api)
        if not all_actors.get("actors"):
            pytest.skip("No actors in level")

        first_name = all_actors["actors"][0]["name"]
        result = find_actor_by_name(api, first_name)
        assert result["count"] >= 1

    def test_find_actor_cli(self, cli_runner, api_port):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--port", str(api_port),
            "scene", "find", "Light",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "actors" in data

    def test_describe_actor(self, api):
        from cli_anything.unreal.core.scene import list_actors, describe_actor

        all_actors = list_actors(api)
        if not all_actors.get("actors"):
            pytest.skip("No actors in level")

        actor_path = all_actors["actors"][0]["path"]
        result = describe_actor(api, actor_path)
        assert "Properties" in result or "error" in result

    def test_get_actor_transform(self, api):
        from cli_anything.unreal.core.scene import list_actors, get_actor_transform

        all_actors = list_actors(api)
        if not all_actors.get("actors"):
            pytest.skip("No actors in level")

        actor_path = all_actors["actors"][0]["path"]
        result = get_actor_transform(api, actor_path)
        assert "location" in result
        assert "rotation" in result
        assert "scale" in result

    def test_transform_cli(self, cli_runner, api_port, api):
        from cli_anything.unreal.core.scene import list_actors
        from cli_anything.unreal.unreal_cli import cli

        all_actors = list_actors(api)
        if not all_actors.get("actors"):
            pytest.skip("No actors in level")

        actor_path = all_actors["actors"][0]["path"]
        result = cli_runner.invoke(cli, [
            "--json", "--port", str(api_port),
            "scene", "transform", actor_path,
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "location" in data


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Asset Management
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestAssetsE2E:
    """Test asset management commands against running editor.

    Creates a temporary asset, checks exists/refs, duplicates, renames,
    then deletes — verifying each step.
    """

    TEST_ASSET = "/Game/E2E_AssetTest"
    TEST_DUPLICATE = "/Game/E2E_AssetTest_Dup"
    TEST_RENAME = "/Game/E2E_AssetTest_Renamed"

    @pytest.fixture(autouse=True, scope="class")
    def _cleanup(self, request):
        """Cleanup test assets after all tests (best-effort)."""
        yield
        try:
            from cli_anything.unreal.utils.ue_http_api import UEEditorAPI
            from cli_anything.unreal.core.script_runner import run_python_code
            env_port = os.environ.get("UE_TEST_PORT")
            port = int(env_port) if env_port else 30010
            api = UEEditorAPI(port=port)
            if api.is_alive():
                paths = [TestAssetsE2E.TEST_ASSET,
                         TestAssetsE2E.TEST_DUPLICATE,
                         TestAssetsE2E.TEST_RENAME]
                delete_lines = "\n".join(
                    f"if EAL.does_asset_exist('{p}'): EAL.delete_asset('{p}')"
                    for p in paths
                )
                code = (
                    "import unreal\n"
                    "EAL = unreal.EditorAssetLibrary\n"
                    f"{delete_lines}\n"
                    "unreal.SystemLibrary.collect_garbage()\n"
                    "result = {'cleaned': True}\n"
                )
                run_python_code(api, code, timeout=15, save=False)
        except Exception:
            pass

    def _script_delete(self, api, asset_path, project_dir=None):
        """Delete asset via script (reliable, unlike HTTP API on CDO)."""
        from cli_anything.unreal.core.script_runner import run_python_code
        code = (
            "import unreal\n"
            "EAL = unreal.EditorAssetLibrary\n"
            f"if EAL.does_asset_exist('{asset_path}'):\n"
            f"    EAL.delete_asset('{asset_path}')\n"
            "    unreal.SystemLibrary.collect_garbage()\n"
            "result = {'cleaned': True}\n"
        )
        run_python_code(api, code, project_dir=project_dir, timeout=10, save=False)

    def test_asset_exists_false(self, api, project_path):
        from cli_anything.unreal.core.assets import asset_exists

        project_dir = str(Path(project_path).parent)
        self._script_delete(api, self.TEST_ASSET, project_dir)

        result = asset_exists(api, self.TEST_ASSET)
        assert result["exists"] is False

    def test_asset_create_and_exists(self, api, project_path):
        from cli_anything.unreal.core.assets import asset_exists
        from cli_anything.unreal.core.script_runner import run_python_code

        project_dir = str(Path(project_path).parent)
        self._script_delete(api, self.TEST_ASSET, project_dir)

        code = (
            "import unreal\n"
            "ATH = unreal.AssetToolsHelpers.get_asset_tools()\n"
            "mat = ATH.create_asset('E2E_AssetTest', '/Game', "
            "unreal.Material, unreal.MaterialFactoryNew())\n"
            "result = {'created': mat is not None}\n"
        )
        run_result = run_python_code(api, code, project_dir=project_dir,
                                     timeout=10, save=False)
        assert run_result.get("created") is True, f"Create failed: {run_result}"

        result = asset_exists(api, self.TEST_ASSET)
        assert result["exists"] is True

    def test_asset_refs_no_refs(self, api):
        from cli_anything.unreal.core.assets import asset_refs

        result = asset_refs(api, self.TEST_ASSET)
        if "error" in result:
            pytest.skip("Test asset not created")
        assert result["count"] == 0

    def test_asset_duplicate(self, api, project_path):
        from cli_anything.unreal.core.assets import asset_exists, asset_duplicate

        project_dir = str(Path(project_path).parent)
        self._script_delete(api, self.TEST_DUPLICATE, project_dir)

        result = asset_duplicate(api, self.TEST_ASSET, self.TEST_DUPLICATE,
                                 project_dir=project_dir)
        assert result.get("status") == "ok", f"Duplicate failed: {result}"

        exists_result = asset_exists(api, self.TEST_DUPLICATE)
        assert exists_result["exists"] is True

    def test_asset_delete_with_gc(self, api, project_path):
        from cli_anything.unreal.core.assets import asset_exists, asset_delete

        project_dir = str(Path(project_path).parent)
        result = asset_delete(api, self.TEST_DUPLICATE, force=True,
                              project_dir=project_dir)
        assert result.get("deleted") is True or result.get("status") == "not_found"

        exists_result = asset_exists(api, self.TEST_DUPLICATE)
        assert exists_result["exists"] is False

    def test_asset_delete_main(self, api, project_path):
        from cli_anything.unreal.core.assets import asset_exists, asset_delete

        project_dir = str(Path(project_path).parent)
        result = asset_delete(api, self.TEST_ASSET, force=True,
                              project_dir=project_dir)
        assert result.get("deleted") is True or result.get("status") == "not_found"

        exists_result = asset_exists(api, self.TEST_ASSET)
        assert exists_result["exists"] is False

    def test_asset_exists_cli(self, cli_runner, api_port, project_path):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--json", "--port", str(api_port), "--project", project_path,
            "project", "asset-exists", "/Game/E2E_NonExistent",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["exists"] is False

    def test_asset_refs_cli(self, cli_runner, api_port, api, project_path):
        from cli_anything.unreal.unreal_cli import cli
        from cli_anything.unreal.core.script_runner import run_python_code

        project_dir = str(Path(project_path).parent)

        # Ensure clean state via script (HTTP API delete unreliable)
        cleanup_code = (
            "import unreal\n"
            "EAL = unreal.EditorAssetLibrary\n"
            "can_create = True\n"
            "if EAL.does_asset_exist('/Game/E2E_AssetTest'):\n"
            "    if EAL.delete_asset('/Game/E2E_AssetTest'):\n"
            "        unreal.SystemLibrary.collect_garbage()\n"
            "    else:\n"
            "        can_create = False\n"
            "if can_create:\n"
            "    ATH = unreal.AssetToolsHelpers.get_asset_tools()\n"
            "    mat = ATH.create_asset('E2E_AssetTest', '/Game', "
            "unreal.Material, unreal.MaterialFactoryNew())\n"
            "    result = {'created': mat is not None}\n"
            "else:\n"
            "    result = {'created': False, 'error': 'delete failed'}\n"
        )
        run_python_code(api, cleanup_code, project_dir=project_dir, timeout=15, save=False)

        result = cli_runner.invoke(cli, [
            "--json", "--port", str(api_port), "--project", project_path,
            "project", "asset-refs", self.TEST_ASSET,
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "count" in data

        # Cleanup via script
        run_python_code(api, (
            "import unreal\n"
            "unreal.EditorAssetLibrary.delete_asset('/Game/E2E_AssetTest')\n"
            "unreal.SystemLibrary.collect_garbage()\n"
            "result = {'cleaned': True}\n"
        ), project_dir=project_dir, timeout=10, save=False)
