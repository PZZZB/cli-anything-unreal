"""test_full_e2e.py — End-to-end tests for ue-cli.

These tests require:
1. A UE editor running with AutomationTestAPI plugin
2. A valid project path

Set environment variables before running:
    UE_TEST_PROJECT=F:\\Test_RXEngine_5_7\\Test_RXEngine_5_7.uproject
    UE_TEST_PORT=30020  (optional; if unset, port is read from Config/DefaultRemoteControl.ini)

Run with:
    pytest cli_anything/unreal/tests/test_full_e2e.py -v --e2e --e2e-auto-launch

Or auto-launch the editor if not running:
    pytest cli_anything/unreal/tests/test_full_e2e.py -v --e2e --e2e-auto-launch --e2e-launch-timeout 300

Screenshot E2E covers **user-facing CLIs** (``screenshot static`` / ``screenshot dynamic``)
plus optional paths (Python API, ``--no-compress``) to guard different entry points.
Needs editor focus/realtime and the project's Remote Control port (or ``UE_TEST_PORT``).

Skip with:
    pytest cli_anything/unreal/tests/test_full_e2e.py -v  (auto-skips without --e2e)
"""

import json
import os
import subprocess
import sys
import time
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
def api(api_port, project_path, request):
    """Get a connected API instance. Auto-launch editor if --e2e-auto-launch is set."""
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

    api = UEEditorAPI(port=api_port)
    if not api.is_alive():
        if request.config.getoption("--e2e-auto-launch"):
            # Launch editor via CLI
            launch_timeout = request.config.getoption("--e2e-launch-timeout")
            result = subprocess.run(
                [
                    "python", "-m", "cli_anything.unreal",
                    "--output", "json",
                    "--project", project_path,
                    "editor", "launch",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                pytest.skip(f"Editor launch failed: {result.stderr}")
            # Wait for editor to come online
            deadline = time.time() + launch_timeout
            while time.time() < deadline:
                if api.is_alive():
                    break
                time.sleep(2)
            else:
                pytest.skip(f"Editor did not come online within {launch_timeout}s")
        else:
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
            "--output", "json", "--port", str(api_port),
            "editor", "status",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        online = [item for item in data["result"] if item["port"] == api_port and item["status"] == "online"]
        assert online, data["result"]


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Project Info
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestConfirmationBrokerE2E:
    """Exercise the out-of-band dialog round trip against a real editor."""

    def test_active_confirmation_round_trip(self, api, project_path, api_port):
        title = f"ue-cli confirmation E2E {os.getpid()}"
        base = [
            sys.executable,
            "-m", "cli_anything.unreal",
            "--output", "json",
            "--project", project_path,
            "--port", str(api_port),
        ]
        enabled = False
        pending_id = None

        def run_cli(*args, timeout=45):
            completed = subprocess.run(
                [*base, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return completed, json.loads(completed.stdout)

        def completed_output(completed):
            return completed.stdout or completed.stderr

        def find_test_confirmation():
            nonlocal pending_id
            listed, payload = run_cli("confirmation", "list")
            assert listed.returncode == 0, completed_output(listed)
            matches = [
                item for item in payload["result"]["confirmations"]
                if item.get("title") == title
            ]
            if matches:
                pending_id = matches[0]["id"]
            return matches

        try:
            armed, armed_payload = run_cli(
                "confirmation", "enable", "--ttl", "120",
            )
            assert armed.returncode == 0, completed_output(armed)
            assert armed_payload["result"]["status"] == "enabled"
            enabled = True

            code = (
                "import unreal; "
                f"result = unreal.EditorDialog.show_message({title!r}, "
                "'Choose No for the ue-cli E2E.', unreal.AppMsgType.YES_NO)"
            )
            blocked, blocked_payload = run_cli(
                "editor", "run-script", "-c", code,
                "--timeout", "30", "--no-save",
            )
            assert blocked.returncode == 4, completed_output(blocked)
            assert blocked_payload["code"] == "EDITOR_BLOCKED_BY_CONFIRMATION"
            assert blocked_payload["details"]["delivery_state"] == "waiting_confirmation"

            matches = find_test_confirmation()
            assert len(matches) == 1
            item = matches[0]
            assert item["source"] == "bridge"
            assert item["answerable"] is True
            assert item["choices"] == ["yes", "no"]

            answered, answered_payload = run_cli(
                "confirmation", "answer", pending_id,
                "--choice", "no", "--wait", "5",
            )
            assert answered.returncode == 0, completed_output(answered)
            assert answered_payload["result"]["resolved"] is True
            pending_id = None

            responsive, responsive_payload = run_cli(
                "editor", "cvar", "get", "t.MaxFPS",
            )
            assert responsive.returncode == 0, completed_output(responsive)
            assert responsive_payload["status"] == "success"
            assert find_test_confirmation() == []
        finally:
            if enabled and pending_id is None:
                try:
                    find_test_confirmation()
                except Exception:
                    pass
            if pending_id:
                # Keep a failed E2E from parking the editor behind its own dialog.
                try:
                    run_cli(
                        "confirmation", "answer", pending_id,
                        "--choice", "no", "--wait", "5",
                    )
                except Exception:
                    pass
            if enabled:
                try:
                    run_cli("confirmation", "disable")
                except Exception:
                    pass


@pytest.mark.e2e
class TestProjectE2E:
    """Test project info queries."""

    def test_project_info(self, cli_runner, project_path):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "project", "info",
            "--project", project_path,
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert "name" in data["result"]
        assert "modules" in data["result"]

    def test_project_config_list(self, cli_runner, project_path):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path,
            "project", "config", "list",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert len(data["result"]) > 0

    def test_project_content(self, cli_runner, project_path, api_port):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "--project", project_path,
            "asset", "list",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert "count" in data["result"]


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Materials
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestMaterialsE2E:
    """Test material queries against running editor."""

    READ_ONLY_MATERIAL = "/Engine/EngineMaterials/DefaultMaterial"

    def test_material_reads_preserve_unrelated_dirty_package(
        self, api, cli_runner, project_path, api_port,
    ):
        """Issue #81: reads never save unrelated dirty packages."""
        import hashlib

        from cli_anything.unreal.core.script_runner import run_python_code
        from cli_anything.unreal.unreal_cli import cli

        query_path = "/Game/__UeCliE2E/M_Issue81_Query"
        dirty_path = "/Game/__UeCliE2E/BP_Issue81_Dirty"

        setup = '''
import unreal
tools = unreal.AssetToolsHelpers.get_asset_tools()
query = unreal.EditorAssetLibrary.load_asset(
    "/Game/__UeCliE2E/M_Issue81_Query"
)
if query is None:
    query = tools.create_asset(
        "M_Issue81_Query", "/Game/__UeCliE2E",
        unreal.Material, unreal.MaterialFactoryNew()
    )
dirty = unreal.EditorAssetLibrary.load_asset(
    "/Game/__UeCliE2E/BP_Issue81_Dirty"
)
if dirty is None:
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.Actor)
    dirty = tools.create_asset(
        "BP_Issue81_Dirty", "/Game/__UeCliE2E",
        unreal.Blueprint, factory
    )
assets = [query, dirty]
if any(asset is None for asset in assets):
    result = {
        "error": "Failed to create issue #81 E2E assets",
    }
else:
    saved = [unreal.EditorAssetLibrary.save_loaded_asset(asset) for asset in assets]
    result = {
        "status": "ok",
        "saved": saved,
    }
'''
        setup_result = run_python_code(api, setup, timeout=60.0, save=False)
        assert setup_result.get("status") == "ok", setup_result
        assert all(setup_result.get("saved", [])), setup_result

        dirty_file = (
            Path(project_path).parent
            / "Content" / "__UeCliE2E" / "BP_Issue81_Dirty.uasset"
        )
        assert dirty_file.is_file()
        before_hash = hashlib.sha256(dirty_file.read_bytes()).hexdigest()
        before_mtime = dirty_file.stat().st_mtime_ns

        make_dirty = f'''
import unreal
path = {dirty_path!r}
asset = unreal.EditorAssetLibrary.load_asset(path)
if asset is None:
    result = {{"error": "Dirty test asset did not load"}}
else:
    asset.modify()
    dirty_packages = [
        package.get_path_name().split(".")[0]
        for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
    ]
    result = {{"status": "ok", "dirty_packages": dirty_packages}}
'''

        try:
            dirty_result = run_python_code(api, make_dirty, timeout=30.0, save=False)
            assert dirty_result.get("status") == "ok", dirty_result
            assert dirty_path in dirty_result.get("dirty_packages", []), dirty_result

            common = [
                "--output", "json", "--project", project_path,
                "--port", str(api_port), "material",
            ]
            supported = cli_runner.invoke(cli, [*common, "info", query_path])

            assert supported.exit_code == 0, supported.output

            dirty_after = run_python_code(api, '''
import unreal
result = {
    "dirty_packages": [
        package.get_path_name().split(".")[0]
        for package in unreal.EditorLoadingAndSavingUtils.get_dirty_content_packages()
    ]
}
''', timeout=30.0, save=False)
            assert dirty_path in dirty_after.get("dirty_packages", []), dirty_after
            assert dirty_file.stat().st_mtime_ns == before_mtime
            assert hashlib.sha256(dirty_file.read_bytes()).hexdigest() == before_hash
        finally:
            restore = run_python_code(api, f'''
import unreal
path = {dirty_path!r}
asset = unreal.EditorAssetLibrary.load_asset(path)
if asset is None:
    result = {{"error": "Issue #81 dirty fixture did not load for restore"}}
else:
    saved = unreal.EditorAssetLibrary.save_loaded_asset(asset)
    result = {{"status": "ok", "saved": saved}}
''', timeout=30.0, save=False)
            assert restore.get("status") == "ok", restore
            assert restore.get("saved") is True, restore

    def test_material_function_info_and_graph(
        self, api, cli_runner, project_path, api_port,
    ):
        """Issue #88: MaterialFunction reads expose nodes and internal edges."""
        from cli_anything.unreal.unreal_cli import cli

        function_path = "/Engine/Functions/Engine_MaterialFunctions03/Blends/Blend_Overlay"
        common = [
            "--output", "json", "--project", project_path,
            "--port", str(api_port), "material",
        ]

        function_info = cli_runner.invoke(cli, [*common, "info", function_path])
        function_graph = cli_runner.invoke(cli, [*common, "get-graph", function_path])

        assert function_info.exit_code == 0, function_info.output
        info_data = json.loads(function_info.output)["result"]
        assert info_data["class"] == "MaterialFunction", info_data
        assert info_data["node_count"] > 1, info_data
        assert info_data["edges"], info_data
        assert info_data["function_inputs"], info_data
        assert info_data["function_outputs"], info_data

        assert function_graph.exit_code == 0, function_graph.output
        graph_data = json.loads(function_graph.output)["result"]
        assert graph_data["node_count"] == info_data["node_count"], graph_data
        assert graph_data["connected_nodes"], graph_data
        assert set(info_data["function_outputs"]).issubset(graph_data["connected_nodes"]), graph_data
        assert api.is_alive()

    def test_material_list(self, api, project_path):
        from cli_anything.unreal.core.materials import list_materials

        project_dir = str(Path(project_path).parent)
        result = list_materials(api, "/Game/", project_dir)
        assert "materials" in result
        assert isinstance(result["materials"], list)

    def test_material_info(self, api, project_path):
        """Test material info against a deterministic engine asset."""
        from cli_anything.unreal.core.materials import get_material_info

        project_dir = str(Path(project_path).parent)
        info = get_material_info(api, self.READ_ONLY_MATERIAL, project_dir)
        assert "name" in info

    def test_material_analyze_cli(self, cli_runner, project_path, api_port):
        """Test material analyze via CLI."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "material", "analyze", self.READ_ONLY_MATERIAL,
        ])
        assert result.exit_code == 0
        analysis = json.loads(result.output)
        assert analysis["status"] == "success"
        result_data = analysis.get("result", analysis)
        assert "issues" in result_data
        assert "warnings" in result_data

    def test_material_attributes_output_graph_cli(
        self, api, cli_runner, project_path, api_port,
    ):
        """Material Attributes output is visible to info, graph, and analysis."""
        from cli_anything.unreal.core.materials import (
            add_material_node,
            connect_material_nodes,
            delete_material_node,
            get_material_info,
        )
        from cli_anything.unreal.core.script_runner import run_python_code
        from cli_anything.unreal.unreal_cli import cli

        material_path = "/Game/__UeCliE2E/M_MaterialAttributes"
        setup_script = r'''
import unreal

path = "/Game/__UeCliE2E/M_MaterialAttributes"
mat = unreal.EditorAssetLibrary.load_asset(path)
created = mat is None
if created:
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        "M_MaterialAttributes", "/Game/__UeCliE2E",
        unreal.Material, unreal.MaterialFactoryNew()
    )
if mat is None:
    result = {"error": "Failed to create issue #68 E2E material"}
else:
    mat.modify()
    mat.set_editor_property("use_material_attributes", True)
    saved = unreal.EditorAssetLibrary.save_loaded_asset(mat)
    result = {
        "status": "ok",
        "created": created,
        "saved": saved,
    }
'''
        setup = run_python_code(api, setup_script, timeout=60.0, save=False)
        assert setup.get("status") == "ok", f"setup failed: {setup}"
        assert setup.get("saved") is True, f"setup save failed: {setup}"

        project_dir = str(Path(project_path).parent)
        existing = get_material_info(api, material_path, project_dir)
        assert existing.get("status") == "ok", existing
        for node in existing.get("nodes", []):
            deleted = delete_material_node(
                api, material_path, node["name"], project_dir=project_dir,
            )
            assert deleted.get("status") == "ok", deleted

        color = add_material_node(
            api,
            material_path,
            "MaterialExpressionConstant3Vector",
            pos_x=-600,
            project_dir=project_dir,
        )
        assert color.get("status") == "ok", color
        attributes = add_material_node(
            api,
            material_path,
            "MaterialExpressionMakeMaterialAttributes",
            pos_x=-300,
            project_dir=project_dir,
        )
        assert attributes.get("status") == "ok", attributes
        edge = connect_material_nodes(
            api,
            material_path,
            color["node"]["name"],
            "",
            attributes["node"]["name"],
            "BaseColor",
            project_dir=project_dir,
        )
        assert edge.get("status") == "ok", edge
        output = connect_material_nodes(
            api,
            material_path,
            attributes["node"]["name"],
            "",
            "__material_output__",
            "MaterialAttributes",
            project_dir=project_dir,
        )
        assert output.get("status") == "ok", output

        common = [
            "--output", "json", "--project", project_path,
            "--port", str(api_port), "material",
        ]
        info_result = cli_runner.invoke(cli, [*common, "info", material_path])
        graph_result = cli_runner.invoke(cli, [*common, "get-graph", material_path])
        analyze_result = cli_runner.invoke(cli, [*common, "analyze", material_path])

        assert info_result.exit_code == 0, info_result.output
        assert graph_result.exit_code == 0, graph_result.output
        assert analyze_result.exit_code == 0, analyze_result.output

        info = json.loads(info_result.output)["result"]
        graph = json.loads(graph_result.output)["result"]
        analysis = json.loads(analyze_result.output)["result"]

        assert info.get("use_material_attributes") is True
        output_node = info["material_outputs"]["MaterialAttributes"]["node"]
        assert output_node in graph["connected_nodes"]
        assert len(graph["connected_nodes"]) == 2
        assert graph["orphan_nodes"] == []
        assert analysis["stats"]["connected_outputs"] == ["MaterialAttributes"]
        assert not any(
            "No material output connections" in warning
            for warning in analysis["warnings"]
        )


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Screenshots
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestScreenshotE2E:
    """Screenshot E2E.

    **User-facing CLIs** (what you document for end users): ``screenshot static`` (static),
    ``screenshot dynamic`` (dynamic). Additional tests below cover the same behavior
    through Python APIs or CLI flags so regressions do not slip in via one entry only.
    """

    def test_take_screenshot(self, api, project_path):
        """Python API: ``take_screenshot`` (same pipeline as ``screenshot static``)."""
        from cli_anything.unreal.core.screenshot import take_screenshot

        project_dir = str(Path(project_path).parent)
        result = take_screenshot(
            api, "e2e_test_screenshot",
            project_dir=project_dir,
        )
        assert "error" not in result or result.get("status") == "ok"

    def test_screenshot_static_cli(self, cli_runner, project_path, api_port):
        """CLI: ``screenshot static`` — static capture for users/agents."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "screenshot", "capture", "--filename", "e2e_cli_test",
        ])

        data = json.loads(result.output)
        result_data = data.get("result", data)
        if result_data.get("status") != "ok":
            pytest.fail(f"screenshot static failed; detail: {result_data.get('error', result_data)}")

        assert result.exit_code == 0

    def test_screenshot_dynamic_cli(self, cli_runner, project_path, api_port):
        """CLI: ``screenshot dynamic`` — dynamic atlas (default JPEG for LLM when Pillow works)."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "screenshot", "capture-sequence", "-n", "2", "-i", "0.35",
        ])
        data = json.loads(result.output)
        result_data = data.get("result", data)
        if result_data.get("status") != "ok":
            pytest.fail(
                "sequence capture incomplete (viewport focus or UE automation queue); "
                f"detail: {result_data.get('error', result_data)}"
            )

        assert result.exit_code == 0

        atlas = Path(result_data["atlas_path"])
        assert atlas.exists()
        assert atlas.stat().st_size > 1000
        assert result_data.get("frame_count") == 2
        assert len(result_data.get("frame_paths") or []) == 2
        for fp in result_data["frame_paths"]:
            assert Path(fp).exists()

        grid = result_data.get("grid") or {}
        assert grid.get("cols", 0) >= 1
        assert grid.get("rows", 0) >= 1

        prep = result_data.get("viewport_prep") or {}
        assert prep.get("realtime") is True

        assert result_data.get("cli_command", "").startswith("screenshot dynamic")
        assert "llm_context" in result_data

        dp = result_data.get("default_path") or ""
        assert dp
        assert Path(dp).exists()
        if result_data.get("compressed"):
            assert Path(result_data["compressed"]).exists()
            assert dp.lower().endswith(".jpg")
        else:
            assert dp.lower().endswith(".png")

    def test_screenshot_dynamic_cli_no_compress(self, cli_runner, project_path, api_port):
        """CLI: ``screenshot dynamic --no-compress`` — PNG atlas only."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "screenshot", "capture-sequence", "-n", "2", "-i", "0.35", "--no-compress",
        ])
        data = json.loads(result.output)
        result_data = data.get("result", data)
        if result_data.get("status") != "ok":
            pytest.fail(
                "sequence capture incomplete; "
                f"detail: {result_data.get('error', result_data)}"
            )

        assert result.exit_code == 0

        assert Path(result_data["atlas_path"]).exists()
        assert result_data.get("default_path") == result_data.get("atlas_path")
        assert str(result_data["default_path"]).lower().endswith(".png")
        assert "compressed" not in result_data

    def test_capture_screenshot_atlas_core(self, api, project_path):
        """Python API: ``capture_screenshot_atlas`` (same core as ``screenshot dynamic``)."""
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
            pytest.fail(
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
            "--output", "json", "--port", str(api_port),
            "editor", "exec", "stat fps",
        ])
        assert result.exit_code == 0

    def test_cvar_get_missing_cli_errors(self, cli_runner, api_port):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "editor", "cvar", "get", "r.__ue_cli_missing_cvar_probe__",
        ])
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] in {"CVAR_NOT_FOUND", "CVAR_GET_AMBIGUOUS_EMPTY"}


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Material Node Editing (MaterialEditingLibrary)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestMaterialEditingE2E:
    """Test material editing via MaterialEditingLibrary against running editor.

    Reuses one dedicated material and never forces expression GC between tests.
    UE 5.7 can crash when Python requests garbage collection for expressions
    that MaterialEditingLibrary just marked as garbage.
    """

    TEST_MATERIAL = "/Game/E2E_TestMaterial"
    _material_ready = False

    @pytest.fixture(autouse=True)
    def _ensure_test_material(self, api):
        """Create or load a stable test material without deleting its graph."""
        from cli_anything.unreal.core.script_runner import run_python_code

        if not TestMaterialEditingE2E._material_ready:
            setup_script = '''
import unreal
EAL = unreal.EditorAssetLibrary
ATH = unreal.AssetToolsHelpers.get_asset_tools()
path = "/Game/E2E_TestMaterial"
if EAL.does_asset_exist(path):
    mat = EAL.load_asset(path)
else:
    mat = ATH.create_asset(
        "E2E_TestMaterial", "/Game", unreal.Material, unreal.MaterialFactoryNew()
    )
if mat is None or not isinstance(mat, unreal.Material):
    result = {"error": "Could not load or create shared E2E material"}
else:
    result = {"status": "ok", "saved": EAL.save_loaded_asset(mat)}
'''
            setup = run_python_code(api, setup_script, timeout=60.0, save=False)
            if setup.get("status") != "ok" or not setup.get("saved"):
                pytest.skip(f"Could not prepare shared E2E material: {setup}")
            TestMaterialEditingE2E._material_ready = True
        yield

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

    def test_connect_set_material_attributes_creates_safe_input(self, api, project_path):
        """Connecting an attribute creates its matching native input without raw array writes."""
        from cli_anything.unreal.core.materials import (
            add_material_node,
            connect_material_nodes,
            delete_material_node,
            disconnect_material_nodes,
            get_material_info,
        )

        project_dir = str(Path(project_path).parent)
        created_nodes = []
        try:
            source = add_material_node(
                api,
                self.TEST_MATERIAL,
                "MaterialExpressionConstant3Vector",
                pos_x=-300,
                pos_y=200,
                project_dir=project_dir,
            )
            assert source.get("status") == "ok", f"source add failed: {source}"
            source_name = source["node"]["name"]
            created_nodes.append(source_name)

            target = add_material_node(
                api,
                self.TEST_MATERIAL,
                "MaterialExpressionSetMaterialAttributes",
                pos_x=0,
                pos_y=200,
                project_dir=project_dir,
            )
            assert target.get("status") == "ok", f"target add failed: {target}"
            target_name = target["node"]["name"]
            created_nodes.append(target_name)

            connected = connect_material_nodes(
                api,
                self.TEST_MATERIAL,
                source_name,
                "",
                target_name,
                "WorldPositionOffset",
                project_dir=project_dir,
            )
            assert connected.get("status") == "ok", f"connect failed: {connected}"
            assert connected.get("set_material_attribute_input") is True
            assert connected.get("input_created") is True

            info = get_material_info(api, self.TEST_MATERIAL, project_dir)
            edge = next(
                edge
                for edge in info.get("edges", [])
                if edge["from_node"] == source_name and edge["to_node"] == target_name
            )
            assert edge["to_input_index"] == connected["input_index"]
            assert edge["to_input"]

            disconnected = disconnect_material_nodes(
                api,
                self.TEST_MATERIAL,
                source_name,
                "",
                target_name,
                "WorldPositionOffset",
                project_dir=project_dir,
            )
            assert disconnected.get("status") == "ok", f"disconnect failed: {disconnected}"
            assert disconnected.get("had_connection") is True
        finally:
            for node_name in reversed(created_nodes):
                delete_material_node(api, self.TEST_MATERIAL, node_name, project_dir=project_dir)

    def test_add_set_material_attributes_rejects_raw_parallel_array_props(self, api, project_path):
        """Raw AttributeSetTypes writes are rejected before creating a node."""
        from cli_anything.unreal.core.materials import add_material_node, get_material_info

        project_dir = str(Path(project_path).parent)
        before = get_material_info(api, self.TEST_MATERIAL, project_dir)
        result = add_material_node(
            api,
            self.TEST_MATERIAL,
            "MaterialExpressionSetMaterialAttributes",
            set_props=[("AttributeSetTypes", "(A=0,B=0,C=0,D=0)")],
            project_dir=project_dir,
        )

        assert result.get("code") == "MATERIAL_SET_ATTRIBUTES_UNSAFE_PROPERTY", result
        after = get_material_info(api, self.TEST_MATERIAL, project_dir)
        assert after.get("node_count") == before.get("node_count")

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

    def test_disconnect_between_expressions(self, api, project_path):
        """Test disconnecting a material expression input pin."""
        from cli_anything.unreal.core.materials import (
            add_material_node, connect_material_nodes, disconnect_material_nodes, get_material_info,
        )

        project_dir = str(Path(project_path).parent)

        const_result = add_material_node(
            api, self.TEST_MATERIAL,
            "MaterialExpressionConstant",
            project_dir=project_dir,
        )
        assert const_result.get("status") == "ok"
        const_name = const_result["node"]["name"]

        multiply_result = add_material_node(
            api, self.TEST_MATERIAL,
            "MaterialExpressionMultiply",
            project_dir=project_dir,
        )
        assert multiply_result.get("status") == "ok"
        multiply_name = multiply_result["node"]["name"]

        conn = connect_material_nodes(
            api, self.TEST_MATERIAL,
            const_name, "", multiply_name, "A",
            project_dir=project_dir,
        )
        assert conn.get("status") == "ok"

        before = get_material_info(api, self.TEST_MATERIAL, project_dir)
        assert any(
            edge["from_node"] == const_name and edge["to_node"] == multiply_name
            for edge in before.get("edges", [])
        )

        disc = disconnect_material_nodes(
            api, self.TEST_MATERIAL,
            const_name, "", multiply_name, "A",
            project_dir=project_dir,
        )
        assert disc.get("status") == "ok", f"disconnect failed: {disc}"
        assert disc.get("to") == multiply_name
        assert disc.get("to_input") == "A"

        after = get_material_info(api, self.TEST_MATERIAL, project_dir)
        assert not any(
            edge["from_node"] == const_name and edge["to_node"] == multiply_name
            for edge in after.get("edges", [])
        )

    def test_recompile(self, api, project_path):
        """Test recompiling a material."""
        from cli_anything.unreal.core.materials import recompile_material

        project_dir = str(Path(project_path).parent)
        result = recompile_material(api, self.TEST_MATERIAL, project_dir=project_dir)
        assert result.get("status") == "ok"

    def test_material_instance_param_reads_and_empty_material_function_info(
        self, api, cli_runner, project_path, api_port,
    ):
        """Effective parameters and empty MaterialFunction inspection stay truthful."""
        from cli_anything.unreal.core.materials import (
            add_material_node,
            connect_material_nodes,
            get_material_info,
            get_material_param,
            set_material_param,
        )
        from cli_anything.unreal.core.script_runner import run_python_code
        from cli_anything.unreal.unreal_cli import cli

        project_dir = str(Path(project_path).parent)
        setup = r'''
import unreal

EAL = unreal.EditorAssetLibrary
ATH = unreal.AssetToolsHelpers.get_asset_tools()
mat_path = "/Game/E2E_MIParamMat"
mi_path = "/Game/E2E_MIParamInst"
leaf_path = "/Game/E2E_MIParamLeaf"
function_path = "/Game/E2E_MaterialFunction"

mat = EAL.load_asset(mat_path)
if mat is None:
    mat = ATH.create_asset("E2E_MIParamMat", "/Game", unreal.Material, unreal.MaterialFactoryNew())
if mat is None:
    result = {"error": "Failed to create parent material"}
else:
    factory = unreal.MaterialInstanceConstantFactoryNew()
    mi = EAL.load_asset(mi_path)
    if mi is None:
        mi = ATH.create_asset("E2E_MIParamInst", "/Game", unreal.MaterialInstanceConstant, factory)
    if mi is None:
        result = {"error": "Failed to create material instance"}
    else:
        mi.modify()
        mi.set_editor_property("parent", mat)
        leaf = EAL.load_asset(leaf_path)
        if leaf is None:
            leaf = ATH.create_asset("E2E_MIParamLeaf", "/Game", unreal.MaterialInstanceConstant, factory)
        if leaf is None:
            result = {"error": "Failed to create leaf material instance"}
        else:
            leaf.modify()
            leaf.set_editor_property("parent", mi)
            function = EAL.load_asset(function_path)
            if function is None:
                function = ATH.create_asset(
                    "E2E_MaterialFunction", "/Game",
                    unreal.MaterialFunction, unreal.MaterialFunctionFactoryNew()
                )
            if function is None:
                result = {"error": "Failed to create material function"}
            else:
                save_results = [
                    EAL.save_loaded_asset(asset) for asset in [mat, mi, leaf, function]
                ]
                result = {
                    "status": "ok",
                    "saved": all(save_results),
                    "leaf_local_scalar_count": len(leaf.get_editor_property("scalar_parameter_values")),
                    "static_switch_supported": hasattr(
                        unreal.MaterialEditingLibrary,
                        "set_material_instance_static_switch_parameter_value",
                    ),
                }
'''
        setup_result = run_python_code(api, setup, timeout=60.0, save=False)
        assert setup_result.get("status") == "ok", setup_result
        assert setup_result.get("saved") is True, setup_result
        assert setup_result.get("leaf_local_scalar_count") == 0, setup_result

        parent_info = get_material_info(api, "/Game/E2E_MIParamMat", project_dir)
        assert parent_info.get("status") == "ok", parent_info
        scalar_node = next((
            node for node in parent_info.get("nodes", [])
            if node.get("type") == "MaterialExpressionScalarParameter"
        ), None)
        if scalar_node is None:
            scalar_result = add_material_node(
                api,
                "/Game/E2E_MIParamMat",
                "MaterialExpressionScalarParameter",
                pos_x=-300,
                set_props=[("ParameterName", "Roughness"), ("DefaultValue", "0.1")],
                project_dir=project_dir,
            )
            assert scalar_result.get("status") == "ok", scalar_result
            scalar_node = scalar_result["node"]
        scalar_connection = connect_material_nodes(
            api,
            "/Game/E2E_MIParamMat",
            scalar_node["name"],
            "",
            "__material_output__",
            "Roughness",
            project_dir=project_dir,
        )
        assert scalar_connection.get("status") == "ok", scalar_connection

        if setup_result.get("static_switch_supported"):
            parent_info = get_material_info(api, "/Game/E2E_MIParamMat", project_dir)
            static_node = next((
                node for node in parent_info.get("nodes", [])
                if node.get("type") == "MaterialExpressionStaticSwitchParameter"
            ), None)
            if static_node is None:
                static_result = add_material_node(
                    api,
                    "/Game/E2E_MIParamMat",
                    "MaterialExpressionStaticSwitchParameter",
                    pos_x=-300,
                    pos_y=200,
                    set_props=[("ParameterName", "UseDetail"), ("DefaultValue", "false")],
                    project_dir=project_dir,
                )
                assert static_result.get("status") == "ok", static_result

            switch_setup = run_python_code(api, r'''
import unreal
mi = unreal.EditorAssetLibrary.load_asset("/Game/E2E_MIParamInst")
if mi is None:
    result = {"error": "Failed to load material instance for static switch"}
else:
    changed = unreal.MaterialEditingLibrary.set_material_instance_static_switch_parameter_value(
        mi, "UseDetail", True
    )
    mi.modify()
    saved = unreal.EditorAssetLibrary.save_loaded_asset(mi)
    result = {"status": "ok", "changed": changed, "saved": saved}
''', timeout=60.0, save=False)
            assert switch_setup.get("status") == "ok", switch_setup
            assert switch_setup.get("saved") is True, switch_setup

        result = set_material_param(
            api,
            "/Game/E2E_MIParamInst",
            "Roughness",
            "0.77",
            "scalar",
            project_dir=project_dir,
        )
        assert result.get("status") == "ok", result
        assert result.get("saved") is True, result
        assert result.get("applied") is True, result
        assert result.get("readback_match") is True, result
        assert result.get("readback_value") == pytest.approx(0.77), result
        assert result.get("verification") == "effective_parameter_readback", result
        assert result.get("set_return_authoritative") is False, result

        cli_set = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "material", "set-param", "/Game/E2E_MIParamInst",
            "--name", "Roughness", "--value", "0.77", "--type", "scalar",
        ])
        assert cli_set.exit_code == 0, cli_set.output
        cli_set_data = json.loads(cli_set.output)
        cli_set_result = cli_set_data["result"]
        assert cli_set_result.get("status") == "ok", cli_set_result
        assert cli_set_result.get("applied") is True, cli_set_result
        assert cli_set_result.get("readback_match") is True, cli_set_result
        assert cli_set_result.get("readback_value") == pytest.approx(0.77), cli_set_result
        assert cli_set_result.get("set_return_authoritative") is False, cli_set_result

        value = get_material_param(api, "/Game/E2E_MIParamInst", "Roughness", project_dir=project_dir)
        assert value.get("status") == "ok", value
        assert abs(float(value.get("value")) - 0.77) < 0.001

        inherited = get_material_param(api, "/Game/E2E_MIParamLeaf", "Roughness", project_dir=project_dir)
        assert inherited.get("status") == "ok", inherited
        assert inherited.get("type") == "scalar", inherited
        assert abs(float(inherited.get("value")) - 0.77) < 0.001

        if setup_result.get("static_switch_supported"):
            static_switch = get_material_param(
                api, "/Game/E2E_MIParamLeaf", "UseDetail", project_dir=project_dir,
            )
            assert static_switch.get("status") == "ok", static_switch
            assert static_switch.get("type") == "static_switch", static_switch
            assert static_switch.get("value") is True, static_switch

            cli_switch = cli_runner.invoke(cli, [
                "--output", "json", "--project", project_path, "--port", str(api_port),
                "material", "get-param", "/Game/E2E_MIParamLeaf", "--name", "UseDetail",
            ])
            assert cli_switch.exit_code == 0, cli_switch.output
            cli_switch_data = json.loads(cli_switch.output)
            assert cli_switch_data["result"]["type"] == "static_switch", cli_switch_data
            assert cli_switch_data["result"]["value"] is True, cli_switch_data

        cli_function = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "material", "info", "/Game/E2E_MaterialFunction",
        ])
        assert cli_function.exit_code == 0, cli_function.output
        cli_function_data = json.loads(cli_function.output)
        assert cli_function_data["result"]["node_count"] == 0, cli_function_data
        assert cli_function_data["result"]["edges"] == [], cli_function_data

    def test_add_node_cli(self, cli_runner, project_path, api_port):
        """Test add-node via CLI."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "material", "add-node", self.TEST_MATERIAL,
            "--type", "MaterialExpressionConstant",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"].get("status") == "ok"

    def test_add_node_cli_applies_python_aliases_atomically(
        self, api, cli_runner, project_path, api_port
    ):
        """Scalar aliases apply; an unknown required property creates no node."""
        from cli_anything.unreal.core.script_runner import run_python_code
        from cli_anything.unreal.unreal_cli import cli

        parameter_name = "CodexIssue142DepthBias"
        add_result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "material", "add-node", self.TEST_MATERIAL,
            "--type", "MaterialExpressionScalarParameter",
            "--set", f"parameter_name={parameter_name}",
            "--set", "default_value=1.0",
        ])
        assert add_result.exit_code == 0, add_result.output
        add_data = json.loads(add_result.output)
        edit = add_data["result"]
        assert edit.get("status") == "ok", edit
        assert "property_warnings" not in edit
        assert edit["applied_properties"] == {
            "parameter_name": "ParameterName",
            "default_value": "DefaultValue",
        }

        node_name = edit["node"]["name"]
        inspect_script = f'''
import unreal
mat = unreal.EditorAssetLibrary.load_asset({self.TEST_MATERIAL!r})
nodes = [node for node in unreal.ObjectIterator(unreal.MaterialExpression) if node.get_outer() == mat]
node = next((node for node in nodes if node.get_name() == {node_name!r}), None)
result = {{
    "found": node is not None,
    "parameter_name": str(node.get_editor_property("parameter_name")) if node else None,
    "default_value": float(node.get_editor_property("default_value")) if node else None,
    "node_count": len(nodes),
}}
'''
        inspected = run_python_code(api, inspect_script, timeout=60.0, save=False)
        assert inspected.get("found") is True, inspected
        assert inspected.get("parameter_name") == parameter_name, inspected
        assert inspected.get("default_value") == pytest.approx(1.0), inspected
        before_count = inspected["node_count"]

        rejected = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "material", "add-node", self.TEST_MATERIAL,
            "--type", "MaterialExpressionScalarParameter",
            "--set", "definitely_missing_property=1",
        ])
        assert rejected.exit_code == 3, rejected.output
        rejected_data = json.loads(rejected.output)
        assert rejected_data["code"] == "MATERIAL_NODE_PROPERTIES_UNAPPLIED"
        assert rejected_data["details"]["node_created"] is False
        assert rejected_data["details"]["saved"] is False

        counted = run_python_code(api, inspect_script, timeout=60.0, save=False)
        assert counted.get("node_count") == before_count, counted

    def test_rename_custom_input_cli(self, api, cli_runner, project_path, api_port):
        """Custom input rename changes the real HLSL variable name."""
        from cli_anything.unreal.core.materials import add_material_node, get_material_info
        from cli_anything.unreal.unreal_cli import cli

        project_dir = str(Path(project_path).parent)
        add_result = add_material_node(
            api,
            self.TEST_MATERIAL,
            "MaterialExpressionCustom",
            set_props=[("code", "return OutlineWidth + Softness;")],
            add_input_names=["OutlineWidth", "Softness"],
            project_dir=project_dir,
        )
        assert add_result.get("status") == "ok", f"add custom node failed: {add_result}"
        node_name = add_result["node"]["name"]

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "material", "rename-custom-input", self.TEST_MATERIAL,
            "--node", node_name,
            "--from", "OutlineWidth",
            "--to", "OutlineWidthPx",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"].get("status") == "ok"
        assert data["result"].get("inputs_after") == ["OutlineWidthPx", "Softness"]
        assert data["result"].get("code_updated") is True

        info = get_material_info(api, self.TEST_MATERIAL, project_dir)
        custom = next(n for n in info["nodes"] if n["name"] == node_name)
        assert custom.get("inputs") == ["OutlineWidthPx", "Softness"]
        assert "OutlineWidthPx + Softness" in custom.get("code_preview", "")
        assert "OutlineWidth + Softness" not in custom.get("code_preview", "")

    def test_recompile_cli(self, cli_runner, project_path, api_port):
        """Test recompile via CLI."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "material", "recompile", self.TEST_MATERIAL,
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"].get("status") == "ok"


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

    def test_clean_material_function_no_errors(self, api, project_path):
        """Engine MaterialFunction errors use the bridge preview-material path."""
        from cli_anything.unreal.core.materials import get_material_errors

        project_dir = str(Path(project_path).parent)
        function_path = "/Engine/Functions/Engine_MaterialFunctions01/Shading/PowerToRoughness"
        result = get_material_errors(api, function_path, project_dir=project_dir)

        if "error" in result and "not loaded" in result.get("error", ""):
            pytest.skip("Bridge plugin not loaded in editor")

        assert result.get("source") == "plugin"
        assert result.get("asset_class") == "MaterialFunction"
        assert result.get("has_errors") is False
        assert result.get("errors") == []

    def test_broken_material_has_errors(self, api, project_path):
        """Material with invalid Custom HLSL should report compile errors."""
        from cli_anything.unreal.core.materials import (
            add_material_node,
            connect_material_nodes,
            delete_material_node,
            get_material_errors,
            get_material_info,
        )
        from cli_anything.unreal.core.script_runner import run_python_code

        project_dir = str(Path(project_path).parent)

        setup_script = r'''
import unreal

EAL = unreal.EditorAssetLibrary
ATH = unreal.AssetToolsHelpers.get_asset_tools()
mat_path = "/Game/E2E_ErrorMaterial"
mat = EAL.load_asset(mat_path)
if mat is None:
    mat = ATH.create_asset("E2E_ErrorMaterial", "/Game", unreal.Material, unreal.MaterialFactoryNew())
if mat is None:
    result = {"error": "Failed to create or load E2E_ErrorMaterial"}
else:
    result = {"status": "ok", "saved": EAL.save_loaded_asset(mat)}
'''
        setup = run_python_code(api, setup_script, timeout=60.0, save=False)
        assert setup.get("status") == "ok", f"Setup failed: {setup}"
        assert setup.get("saved") is True, setup

        material_path = "/Game/E2E_ErrorMaterial"
        existing = get_material_info(api, material_path, project_dir)
        assert existing.get("status") == "ok", existing
        for node in existing.get("nodes", []):
            deleted = delete_material_node(
                api, material_path, node["name"], project_dir=project_dir,
            )
            assert deleted.get("status") == "ok", deleted

        custom = add_material_node(
            api,
            material_path,
            "MaterialExpressionCustom",
            pos_x=-300,
            set_props=[("Code", "return invalid_var;")],
            project_dir=project_dir,
        )
        assert custom.get("status") == "ok", custom
        node_name = custom["node"]["name"]

        try:
            connection = connect_material_nodes(
                api,
                material_path,
                node_name,
                "",
                "__material_output__",
                "BaseColor",
                project_dir=project_dir,
            )
            assert connection.get("status") == "ok", connection

            result = get_material_errors(api, material_path, project_dir=project_dir)

            if "error" in result and "not loaded" in result.get("error", ""):
                pytest.skip("Bridge plugin not loaded in editor")

            assert result.get("source") == "plugin"
            assert result.get("has_errors") is True
            assert len(result.get("errors", [])) > 0
            all_errors = " ".join(result["errors"])
            assert "invalid_var" in all_errors
        finally:
            cleanup = delete_material_node(
                api, material_path, node_name, project_dir=project_dir,
            )
            assert cleanup.get("status") == "ok", cleanup

    def test_material_errors_cli(self, cli_runner, project_path, api_port):
        """Test material errors CLI command returns plugin-sourced results."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "material", "get-errors", "/Game/E2E_TestMaterial",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        result_data = data.get("result", data)

        if "error" in result_data and "not loaded" in result_data.get("error", ""):
            pytest.skip("Bridge plugin not loaded")

        assert result_data.get("source") == "plugin"
        assert result_data.get("has_errors") is False


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Material HLSL/Shader Source via Bridge Plugin
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestMaterialHlslShaderSourceE2E:
    """Test get_material_hlsl_code and get_material_shader_source via Bridge plugin.

    Uses the E2E_TestMaterial created by TestMaterialEditingE2E, or falls back
    to any available material in the project.
    """

    def _get_test_material(self, api, project_path):
        """Find a usable material for testing."""
        from cli_anything.unreal.core.materials import list_materials

        project_dir = str(Path(project_path).parent)

        # Try E2E_TestMaterial first
        result = list_materials(api, "/Game/", project_dir)
        for mat in result.get("materials", []):
            if "E2E_TestMaterial" in mat.get("path", ""):
                return mat["path"]

        # Fallback to any material
        if result.get("materials"):
            return result["materials"][0]["path"]

        pytest.skip("No materials in project")

    def test_hlsl_code(self, api, project_path):
        """Test get_material_hlsl_code returns valid HLSL expression source."""
        from cli_anything.unreal.core.materials import get_material_hlsl_code

        project_dir = str(Path(project_path).parent)
        mat_path = self._get_test_material(api, project_path)

        result = get_material_hlsl_code(api, mat_path, project_dir=project_dir)

        if "error" in result and "not loaded" in result.get("error", ""):
            pytest.skip("Bridge plugin not loaded in editor")

        assert result.get("source") == "plugin"
        assert result.get("lines", 0) > 0, "HLSL code should have content"
        assert result.get("file"), "Should have output file path"

    def test_hlsl_code_contains_material_structs(self, api, project_path):
        """Verify HLSL code contains FMaterialPixelParameters."""
        from cli_anything.unreal.core.materials import get_material_hlsl_code

        project_dir = str(Path(project_path).parent)
        mat_path = self._get_test_material(api, project_path)

        result = get_material_hlsl_code(api, mat_path, project_dir=project_dir)
        if "error" in result:
            pytest.skip(f"Bridge not available: {result.get('error')}")

        file_path = result.get("file", "")
        if file_path and Path(file_path).exists():
            content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
            assert "FMaterialPixelParameters" in content, \
                "HLSL code should contain FMaterialPixelParameters struct"

    def test_shader_source(self, api, project_path):
        """Test get_material_shader_source returns compiled .usf files."""
        from cli_anything.unreal.core.materials import get_material_shader_source

        project_dir = str(Path(project_path).parent)
        mat_path = self._get_test_material(api, project_path)

        result = get_material_shader_source(api, mat_path, project_dir=project_dir)

        if "error" in result and "not loaded" in result.get("error", ""):
            pytest.skip("Bridge plugin not loaded in editor")

        assert result.get("source") == "plugin"
        assert result.get("shader_cache_refresh") == "changed"
        assert result.get("shader_count", 0) > 0, "Should have at least one compiled shader"
        assert len(result.get("shaders", [])) > 0, "Shaders list should not be empty"

    def test_shader_source_contains_cbuffers(self, api, project_path):
        """Verify shader source files contain cbuffer View and struct definitions."""
        from cli_anything.unreal.core.materials import get_material_shader_source

        project_dir = str(Path(project_path).parent)
        mat_path = self._get_test_material(api, project_path)

        result = get_material_shader_source(api, mat_path, project_dir=project_dir)
        if "error" in result:
            pytest.skip(f"Bridge not available: {result.get('error')}")

        shaders = result.get("shaders", [])
        # Check that at least one shader file has cbuffer View and FMaterialPixelParameters
        found_view = False
        found_pixel_params = False

        for shader in shaders:
            file_path = shader.get("file", "")
            if file_path and Path(file_path).exists():
                content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
                if "cbuffer View" in content:
                    found_view = True
                if "FMaterialPixelParameters" in content:
                    found_pixel_params = True

        assert found_view, "At least one shader should contain 'cbuffer View'"
        assert found_pixel_params, "At least one shader should contain 'FMaterialPixelParameters'"

    def test_hlsl_code_cli(self, cli_runner, project_path, api_port):
        """Test material hlsl-code CLI command."""
        from cli_anything.unreal.unreal_cli import cli
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        mat_path = self._get_test_material(UEEditorAPI(port=api_port), project_path)

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "material", "hlsl-code", mat_path,
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        result_data = data.get("result", data)

        if "error" in result_data and "not loaded" in result_data.get("error", ""):
            pytest.skip("Bridge plugin not loaded")

        assert result_data.get("source") == "plugin"
        assert result_data.get("lines", 0) > 0

    def test_shader_source_cli(self, cli_runner, project_path, api_port):
        """Test material shader-source CLI command."""
        from cli_anything.unreal.unreal_cli import cli
        from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

        mat_path = self._get_test_material(UEEditorAPI(port=api_port), project_path)

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "material", "shader-source", mat_path,
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        result_data = data.get("result", data)

        if "error" in result_data and "not loaded" in result_data.get("error", ""):
            pytest.skip("Bridge plugin not loaded")

        assert result_data.get("source") == "plugin"
        assert result_data.get("shader_cache_refresh") == "changed"
        assert result_data.get("shader_count", 0) > 0
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
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "blueprint", "list",
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert "blueprints" in data["result"]

    def test_blueprint_info_cli(self, cli_runner, project_path, api_port):
        """Test blueprint info via CLI."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "blueprint", "info", self.TEST_BLUEPRINT,
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"].get("name") == "E2E_TestBlueprint"

    def test_blueprint_compile_cli(self, cli_runner, project_path, api_port):
        """Test blueprint compile via CLI."""
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--project", project_path, "--port", str(api_port),
            "blueprint", "compile", self.TEST_BLUEPRINT,
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"].get("status") == "ok"


# ═══════════════════════════════════════════════════════════════════════
#  E2E: Scene Queries
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.e2e
class TestUMGE2E:
    """Test UMG Widget Blueprint authoring against a running editor."""

    TEST_WIDGET = "/Game/__UeCliE2E/WBP_CliUMG"

    def _cleanup(self, api):
        from cli_anything.unreal.core.script_runner import run_python_code

        script = f"""
import unreal
path = {json.dumps(self.TEST_WIDGET)}
EAL = unreal.EditorAssetLibrary
deleted = False
if EAL.does_asset_exist(path):
    deleted = EAL.delete_asset(path)
    unreal.SystemLibrary.collect_garbage()
result = {{"status": "ok", "deleted": deleted}}
"""
        run_python_code(api, script, timeout=60, save=False)

    def test_umg_create_add_tree_cli(self, cli_runner, project_path, api_port, api):
        from cli_anything.unreal.unreal_cli import cli

        self._cleanup(api)
        try:
            create = cli_runner.invoke(cli, [
                "--output", "json", "--project", project_path, "--port", str(api_port),
                "umg", "create", self.TEST_WIDGET,
                "--force",
            ])
            assert create.exit_code == 0, create.output
            create_data = json.loads(create.output)
            assert create_data["status"] == "success"
            assert create_data["result"]["status"] == "ok"
            assert create_data["result"]["root"]["class"] == "CanvasPanel"

            add = cli_runner.invoke(cli, [
                "--output", "json", "--project", project_path, "--port", str(api_port),
                "umg", "add-widget", self.TEST_WIDGET,
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
            assert add.exit_code == 0, add.output
            add_data = json.loads(add.output)
            assert add_data["status"] == "success"
            assert add_data["result"]["status"] == "ok"
            assert add_data["result"]["widget"]["name"] == "TitleText"
            assert add_data["result"]["widget"]["text"] == "Ready"

            tree = cli_runner.invoke(cli, [
                "--output", "json", "--project", project_path, "--port", str(api_port),
                "umg", "tree", self.TEST_WIDGET,
            ])
            assert tree.exit_code == 0, tree.output
            tree_data = json.loads(tree.output)
            assert tree_data["status"] == "success"
            assert tree_data["result"]["status"] == "ok"
            names = {widget["name"] for widget in tree_data["result"]["widgets"]}
            assert {"RootCanvas", "TitleText"}.issubset(names)
        finally:
            self._cleanup(api)

@pytest.fixture
def scene_fixture_actors(api):
    """Create deterministic scene actors and remove only those actors afterward."""
    from cli_anything.unreal.core.script_runner import run_python_code

    setup = run_python_code(api, '''
import unreal

subsystem_class = getattr(unreal, "EditorActorSubsystem", None)
if subsystem_class is not None:
    actor_subsystem = unreal.get_editor_subsystem(subsystem_class)
else:
    actor_subsystem = None

created = []

def spawn(actor_class, location):
    if actor_subsystem is not None:
        actor = actor_subsystem.spawn_actor_from_class(actor_class, location)
    else:
        actor = unreal.EditorLevelLibrary.spawn_actor_from_class(actor_class, location)
    if actor is None:
        raise RuntimeError("Could not spawn " + actor_class.get_name())
    created.append(actor)
    return actor

def spawn_from_object(asset, location):
    if actor_subsystem is not None:
        actor = actor_subsystem.spawn_actor_from_object(asset, location)
    else:
        actor = unreal.EditorLevelLibrary.spawn_actor_from_object(asset, location)
    if actor is None:
        raise RuntimeError("Could not spawn actor from " + asset.get_path_name())
    created.append(actor)
    return actor

def destroy(actor):
    if actor_subsystem is not None:
        actor_subsystem.destroy_actor(actor)
    else:
        unreal.EditorLevelLibrary.destroy_actor(actor)

try:
    actor = spawn(unreal.Actor, unreal.Vector(0, 0, 0))
    actor.set_actor_label("UE CLI E2E LabelOnly Search")

    light = spawn(unreal.DirectionalLight, unreal.Vector(200, 0, 0))
    light.set_actor_label("UE CLI E2E Directional Light")

    cube = unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube.Cube")
    if cube is None:
        raise RuntimeError("Could not load /Engine/BasicShapes/Cube.Cube")
    static_mesh_actor = spawn_from_object(cube, unreal.Vector(400, 0, 0))
    static_mesh_actor.set_actor_label("UE CLI E2E Static Mesh")

    result = {
        "status": "ok",
        "actor_path": actor.get_path_name(),
        "actor_name": actor.get_name(),
        "actor_label": actor.get_actor_label(),
        "light_path": light.get_path_name(),
        "mesh_path": static_mesh_actor.get_path_name(),
        "paths": [item.get_path_name() for item in created],
    }
except Exception as exc:
    paths = [item.get_path_name() for item in created]
    for item in reversed(created):
        destroy(item)
    result = {"status": "error", "error": str(exc), "cleaned_paths": paths}
''', save=False)
    assert setup.get("status") == "ok", setup
    paths = setup.get("paths") or []
    assert len(paths) == 3, setup

    try:
        yield setup
    finally:
        cleanup = run_python_code(api, f'''
import unreal

targets = set({paths!r})
subsystem_class = getattr(unreal, "EditorActorSubsystem", None)
if subsystem_class is not None:
    actor_subsystem = unreal.get_editor_subsystem(subsystem_class)
    actors = actor_subsystem.get_all_level_actors()
else:
    actor_subsystem = None
    actors = unreal.EditorLevelLibrary.get_all_level_actors()

destroyed = []
for actor in actors:
    path = actor.get_path_name()
    if path not in targets:
        continue
    if actor_subsystem is not None:
        actor_subsystem.destroy_actor(actor)
    else:
        unreal.EditorLevelLibrary.destroy_actor(actor)
    destroyed.append(path)

result = {{"status": "ok", "destroyed": destroyed}}
''', save=False)
        assert cleanup.get("status") == "ok", cleanup
        assert set(cleanup.get("destroyed") or []) == set(paths), cleanup


@pytest.mark.e2e
class TestSceneE2E:
    """Test scene/level actor queries against running editor."""

    @pytest.fixture(autouse=True)
    def _prepare_scene(self, scene_fixture_actors):
        self.scene = scene_fixture_actors

    def test_list_actors(self, api):
        from cli_anything.unreal.core.scene import list_actors

        result = list_actors(api)
        assert "actors" in result
        assert isinstance(result["actors"], list)
        assert any(
            actor["path"] == self.scene["actor_path"]
            for actor in result["actors"]
        )

    def test_list_actors_cli(self, cli_runner, api_port):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "scene", "list",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert "actors" in data["result"]
        assert "count" in data["result"]
        assert any(
            actor["path"] == self.scene["actor_path"]
            for actor in data["result"]["actors"]
        )

    def test_find_actor_by_name(self, api):
        from cli_anything.unreal.core.scene import find_actor_by_name

        result = find_actor_by_name(api, self.scene["actor_name"])
        assert any(
            actor["path"] == self.scene["actor_path"]
            for actor in result["actors"]
        )

    def test_find_actor_cli(self, cli_runner, api_port):
        from cli_anything.unreal.unreal_cli import cli

        result = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "scene", "list", "-q", "Light",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert "actors" in data["result"]
        assert any(
            actor["path"] == self.scene["light_path"]
            for actor in data["result"]["actors"]
        )


    def test_find_actor_cli_matches_outliner_label(self, cli_runner, api_port):
        from cli_anything.unreal.unreal_cli import cli

        label = self.scene["actor_label"]
        result = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "scene", "list", "-q", "LabelOnly Search",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        actors = data["result"].get("actors") or []
        matches = [actor for actor in actors if actor.get("label") == label]
        assert matches, data["result"]
        assert matches[0]["name"] != label

        exact = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "scene", "list", "-q", label, "--field", "label", "--exact",
        ])
        assert exact.exit_code == 0
        exact_data = json.loads(exact.output)
        exact_actors = exact_data["result"].get("actors") or []
        assert any(actor.get("label") == label for actor in exact_actors)


    def test_get_actor_transform(self, api):
        from cli_anything.unreal.core.scene import get_actor_transform

        result = get_actor_transform(api, self.scene["actor_path"])
        assert "location" in result
        assert "rotation" in result
        assert "scale" in result

    def test_listed_actor_path_works_across_scene_read_commands(
        self, cli_runner, api_port, api
    ):
        from cli_anything.unreal.unreal_cli import cli

        listed = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "scene", "list",
        ])
        assert listed.exit_code == 0
        listed_data = json.loads(listed.output)
        actors = listed_data["result"].get("actors") or []
        actor_path = self.scene["actor_path"]
        assert any(actor["path"] == actor_path for actor in actors)
        transform = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "scene", "get-transform", actor_path,
        ])
        assert transform.exit_code == 0
        transform_data = json.loads(transform.output)
        assert transform_data["status"] == "success"
        assert "location" in transform_data["result"]

        components = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "scene", "list-components", actor_path,
        ])
        assert components.exit_code == 0
        components_data = json.loads(components.output)
        assert components_data["status"] == "success"
        assert "components" in components_data["result"]

        actor_outer = actor_path.rsplit(".", 1)[0]
        missing_path = actor_outer + ".CodexMissingActor_36"
        for command, error_code in (
            (["scene", "get-transform", missing_path], "SCENE_TRANSFORM_READ_FAILED"),
            (["scene", "list-components", missing_path], "SCENE_COMPONENT_LIST_FAILED"),
        ):
            missing = cli_runner.invoke(cli, [
                "--output", "json", "--port", str(api_port), *command,
            ])
            assert missing.exit_code == 3
            missing_data = json.loads(missing.output)
            assert missing_data["status"] == "error"
            assert missing_data["code"] == error_code

    # ─── api-discover: the actor → component → property workflow ─────────
    # These protect the "human's Details-panel path" contract added in plugin v1.9:
    #   1) api-discover <actor>      → returns `components` tree (matches Details)
    #   2) api-discover <component>  → returns component's own props/functions
    #   3) scene property <component> Prop=Value → writes the subobject

    def test_api_discover_actor_returns_components(self, cli_runner, api_port):
        """api-discover <actor> must return a `components` tree."""
        from cli_anything.unreal.unreal_cli import cli

        actor_path = self.scene["light_path"]

        result = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "editor", "api-discover", actor_path,
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        data = json.loads(result.output)

        assert data["status"] == "success"
        result_data = data.get("result", data)
        assert result_data.get("class") == "DirectionalLight"
        assert "components" in result_data, "actor api-discover must include components tree"
        comps = result_data["components"]
        assert isinstance(comps, list) and len(comps) >= 1
        # Every component entry should carry a usable path + class
        for c in comps:
            assert c.get("path")
            assert c.get("class")
            assert "is_root" in c and "is_native" in c

    def test_api_discover_component_drills_in(self, cli_runner, api_port):
        """api-discover <component.path> must resolve to the component class."""
        from cli_anything.unreal.unreal_cli import cli

        actor_path = self.scene["light_path"]

        # Step 1: discover the light component path
        r1 = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "editor", "api-discover", actor_path,
        ])
        assert r1.exit_code == 0
        d1 = json.loads(r1.output)
        d1_result = d1.get("result", d1)
        light_comp = next(
            (c for c in d1_result["components"] if "Light" in c["class"]),
            None,
        )
        assert light_comp is not None, d1_result

        # Step 2: api-discover that component
        r2 = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "editor", "api-discover", light_comp["path"], "-q", "intensity",
        ])
        assert r2.exit_code == 0, f"CLI failed: {r2.output}"
        d2 = json.loads(r2.output)
        d2_result = d2.get("result", d2)

        assert d2_result.get("component") == light_comp["path"]
        assert d2_result.get("owning_actor") == actor_path
        # LightComponent should have Intensity in the filter result
        assert "Intensity" in d2_result.get("properties", [])

    def test_scene_property_accepts_component_path(self, cli_runner, api_port):
        """scene property get/set works on a component subobject path, not just actor."""
        from cli_anything.unreal.unreal_cli import cli

        actor_path = self.scene["light_path"]

        r1 = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "editor", "api-discover", actor_path,
        ])
        d1 = json.loads(r1.output)
        d1_result = d1.get("result", d1)
        light_comp = next(
            (c for c in d1_result["components"] if "Light" in c["class"]),
            None,
        )
        assert light_comp is not None, d1_result

        comp_path = light_comp["path"]

        # Read current intensity
        rg = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "scene", "property", comp_path, "Intensity",
        ])
        assert rg.exit_code == 0, f"Read failed: {rg.output}"
        rg_data = json.loads(rg.output)
        rg_result = rg_data.get("result", rg_data)
        original = rg_result.get("Intensity")
        assert original is not None

        # Write a new value, then restore
        probe_value = float(original) + 1.0
        try:
            rs = cli_runner.invoke(cli, [
                "--output", "json", "--port", str(api_port),
                "scene", "property", comp_path, f"Intensity={probe_value}",
            ])
            assert rs.exit_code == 0, f"Write failed: {rs.output}"

            rv = cli_runner.invoke(cli, [
                "--output", "json", "--port", str(api_port),
                "scene", "property", comp_path, "Intensity",
            ])
            assert rv.exit_code == 0
            rv_data = json.loads(rv.output)
            rv_result = rv_data.get("result", rv_data)
            assert abs(float(rv_result["Intensity"]) - probe_value) < 1e-3
        finally:
            # Always restore the pre-test value
            cli_runner.invoke(cli, [
                "--output", "json", "--port", str(api_port),
                "scene", "property", comp_path, f"Intensity={original}",
            ])

    def test_scene_property_reads_static_mesh_asset_reference(self, cli_runner, api_port, api):
        """StaticMesh references are readable through RC or Python fallback."""
        from cli_anything.unreal.core.scene import get_actor_components
        from cli_anything.unreal.unreal_cli import cli

        components = get_actor_components(api, self.scene["mesh_path"]).get("components", [])
        mesh_component = next(
            (component for component in components if component["class"] == "StaticMeshComponent"),
            None,
        )
        assert mesh_component is not None, components

        read_result = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port),
            "scene", "property", mesh_component["path"], "StaticMesh",
        ])

        assert read_result.exit_code == 0, read_result.output
        payload = json.loads(read_result.output)
        assert payload["status"] == "success"
        assert payload["result"]["StaticMesh"].startswith("/")
        if "read_via" in payload["result"]:
            assert payload["result"]["read_via"] == "unreal_python"

    def test_scene_property_reads_static_mesh_lod_vertex_paint_fields(self, cli_runner, api_port, api):
        """Native bridge reads non-reflected LODData vertex-paint fields."""
        from cli_anything.unreal.core.scene import get_actor_components, list_actors
        from cli_anything.unreal.unreal_cli import cli

        mesh_component = None
        inspected_components = []
        actors = list_actors(api, actor_class="StaticMeshActor").get("actors", [])
        for actor in actors:
            components = get_actor_components(api, actor["path"]).get("components", [])
            for component in components:
                if component["class"] != "StaticMeshComponent":
                    continue
                inspected_components.append(component["path"])
                lod_data = api.get_property(component["path"], "LODData").get("LODData")
                if isinstance(lod_data, list) and lod_data:
                    mesh_component = component
                    break
            if mesh_component is not None:
                break
        if mesh_component is None:
            pytest.skip(
                "No StaticMeshComponent with LODData[0] is available; "
                f"inspected {inspected_components}"
            )

        for expression, expected_type in (
            ("LODData[0].PaintedVertices", list),
            ("LODData[0].OverrideVertexColors", (dict, type(None))),
        ):
            read_result = cli_runner.invoke(cli, [
                "--output", "json", "--port", str(api_port),
                "scene", "property", mesh_component["path"], expression,
            ])
            assert read_result.exit_code == 0, read_result.output
            payload = json.loads(read_result.output)
            assert payload["status"] == "success"
            assert isinstance(payload["result"][expression], expected_type)
            assert payload["result"]["read_via"] == "native_bridge"

    def test_scene_property_reads_post_process_weighted_blendables(self, cli_runner, api_port, api):
        """Nested PostProcessSettings blendables return structured entries."""
        from cli_anything.unreal.core.script_runner import run_python_code
        from cli_anything.unreal.unreal_cli import cli

        setup = run_python_code(api, '''
import unreal

subsystem_class = getattr(unreal, "EditorActorSubsystem", None)
if subsystem_class is not None:
    actor_subsystem = unreal.get_editor_subsystem(subsystem_class)
    actor = actor_subsystem.spawn_actor_from_class(
        unreal.PostProcessVolume,
        unreal.Vector(600, 0, 0),
    )
else:
    actor_subsystem = None
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.PostProcessVolume,
        unreal.Vector(600, 0, 0),
    )

material = unreal.load_asset(
    "/Engine/EngineMaterials/DefaultPostProcessMaterial.DefaultPostProcessMaterial"
)
if actor is None or material is None:
    result = {"error": "Could not create weighted-blendable fixture."}
else:
    actor.set_actor_label("UE CLI E2E Post Process")
    settings = actor.get_editor_property("settings")
    weighted = settings.get_editor_property("weighted_blendables")
    entry = unreal.WeightedBlendable()
    entry.set_editor_property("weight", 0.625)
    entry.set_editor_property("object", material)
    weighted.set_editor_property("array", [entry])
    settings.set_editor_property("weighted_blendables", weighted)
    actor.set_editor_property("settings", settings)
    result = {
        "actor_path": actor.get_path_name(),
        "material_path": material.get_path_name(),
    }
''', save=False)
        assert not setup.get("error"), setup
        actor_path = setup["actor_path"]

        try:
            expression = "Settings.WeightedBlendables.Array"
            read_result = cli_runner.invoke(cli, [
                "--output", "json", "--port", str(api_port),
                "scene", "property", actor_path, expression,
            ])

            assert read_result.exit_code == 0, read_result.output
            payload = json.loads(read_result.output)
            entries = payload["result"][expression]
            assert payload["result"]["read_via"] == "unreal_python"
            assert len(entries) == 1
            assert entries[0]["weight"] == pytest.approx(0.625)
            assert entries[0]["object"] == setup["material_path"]
        finally:
            cleanup = run_python_code(api, f'''
import unreal

actor = unreal.load_object(None, {actor_path!r})
if actor is None:
    result = {{"destroyed": False, "already_absent": True}}
else:
    subsystem_class = getattr(unreal, "EditorActorSubsystem", None)
    if subsystem_class is not None:
        destroyed = unreal.get_editor_subsystem(subsystem_class).destroy_actor(actor)
    else:
        destroyed = unreal.EditorLevelLibrary.destroy_actor(actor)
    result = {{"destroyed": bool(destroyed), "already_absent": False}}
''', save=False)
            assert cleanup.get("destroyed") or cleanup.get("already_absent"), cleanup


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
            "--output", "json", "--port", str(api_port), "--project", project_path,
            "asset", "exists", "/Game/E2E_NonExistent",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["exists"] is False

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

        for asset_path in (self.TEST_ASSET, self.TEST_ASSET + ".E2E_AssetTest"):
            result = cli_runner.invoke(cli, [
                "--output", "json", "--port", str(api_port), "--project", project_path,
                "asset", "refs", asset_path,
            ])
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["status"] == "success"
            assert data["result"]["resolved_asset"] == (
                "/Game/E2E_AssetTest.E2E_AssetTest"
            )
            assert "count" in data["result"]

        missing_result = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port), "--project", project_path,
            "asset", "refs", "/Game/E2E_AssetRefsMissing",
        ])
        assert missing_result.exit_code == 3
        missing_data = json.loads(missing_result.output)
        assert missing_data["status"] == "error"
        assert missing_data["code"] == "ASSET_REFS_FAILED"

    def test_asset_describe_and_property_cli(self, cli_runner, api_port, api, project_path):
        from cli_anything.unreal.unreal_cli import cli
        from cli_anything.unreal.core.script_runner import run_python_code

        project_dir = str(Path(project_path).parent)

        # Ensure clean state via script (HTTP API delete unreliable)
        cleanup_code = (
            "import unreal\n"
            "EAL = unreal.EditorAssetLibrary\n"
            "can_create = True\n"
            "if EAL.does_asset_exist('/Game/E2E_AssetPropTest'):\n"
            "    if EAL.delete_asset('/Game/E2E_AssetPropTest'):\n"
            "        unreal.SystemLibrary.collect_garbage()\n"
            "    else:\n"
            "        can_create = False\n"
            "if can_create:\n"
            "    ATH = unreal.AssetToolsHelpers.get_asset_tools()\n"
            "    mat = ATH.create_asset('E2E_AssetPropTest', '/Game', "
            "unreal.Material, unreal.MaterialFactoryNew())\n"
            "    result = {'created': mat is not None}\n"
            "else:\n"
            "    result = {'created': False, 'error': 'delete failed'}\n"
        )
        run_python_code(api, cleanup_code, project_dir=project_dir, timeout=15, save=False)

        # 1. List with filter to find the asset
        result = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port), "--project", project_path,
            "asset", "list", "-q", "E2E_AssetPropTest",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert "assets" in data["result"]
        assert any(a["name"] == "E2E_AssetPropTest" for a in data["result"]["assets"])

        # 2. Get Property via asset property
        result = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port), "--project", project_path,
            "asset", "property", "/Game/E2E_AssetPropTest", "BlendMode",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert "BlendMode" in data["result"]
        assert data["result"]["BlendMode"] == "Opaque"

        # 3. Set Property
        result = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port), "--project", project_path,
            "asset", "property", "/Game/E2E_AssetPropTest", "BlendMode=BLEND_Masked",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"].get("status") == "ok"

        # 4. Get Property again to verify
        result = cli_runner.invoke(cli, [
            "--output", "json", "--port", str(api_port), "--project", project_path,
            "asset", "property", "/Game/E2E_AssetPropTest", "BlendMode",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["BlendMode"] == "Masked"

        # Cleanup via script
        run_python_code(api, (
            "import unreal\n"
            "unreal.EditorAssetLibrary.delete_asset('/Game/E2E_AssetPropTest')\n"
            "unreal.SystemLibrary.collect_garbage()\n"
            "result = {'cleaned': True}\n"
        ), project_dir=project_dir, timeout=10, save=False)

    def test_asset_property_reads_blueprint_class_default_object(
        self, cli_runner, api_port, api, project_path
    ):
        from cli_anything.unreal.unreal_cli import cli
        from cli_anything.unreal.core.script_runner import run_python_code

        project_dir = str(Path(project_path).parent)
        asset_path = "/Game/E2E_AssetProperty/BP_E2E_ClassDefaults"
        cleanup_code = (
            "import unreal\n"
            f"path = {asset_path!r}\n"
            "if unreal.EditorAssetLibrary.does_asset_exist(path):\n"
            "    unreal.EditorAssetLibrary.delete_asset(path)\n"
            "    unreal.SystemLibrary.collect_garbage()\n"
            "result = {'cleaned': True}\n"
        )
        create_code = (
            "import unreal\n"
            f"path = {asset_path!r}\n"
            "factory = unreal.BlueprintFactory()\n"
            "factory.set_editor_property('parent_class', unreal.Actor)\n"
            "tools = unreal.AssetToolsHelpers.get_asset_tools()\n"
            "bp = tools.create_asset('BP_E2E_ClassDefaults', "
            "'/Game/E2E_AssetProperty', unreal.Blueprint, factory)\n"
            "if bp is None:\n"
            "    result = {'error': 'Blueprint creation failed'}\n"
            "else:\n"
            "    try:\n"
            "        generated_class = bp.generated_class()\n"
            "    except Exception:\n"
            "        generated_class = None\n"
            "    if generated_class is None:\n"
            "        try:\n"
            "            generated_class = bp.get_editor_property('generated_class')\n"
            "        except Exception:\n"
            "            generated_class = unreal.load_object(\n"
            "                None, bp.get_path_name() + '_C')\n"
            "    cdo = unreal.get_default_object(generated_class)\n"
            "    cdo.set_editor_property('initial_life_span', 37.5)\n"
            "    saved = unreal.EditorAssetLibrary.save_asset("
            "path, only_if_is_dirty=False)\n"
            "    result = {'created': True, 'saved': saved}\n"
        )

        run_python_code(
            api, cleanup_code, project_dir=project_dir, timeout=15, save=False
        )
        try:
            created = run_python_code(
                api, create_code, project_dir=project_dir, timeout=15, save=False
            )
            assert created.get("created") is True
            assert created.get("saved") is True

            listed = cli_runner.invoke(cli, [
                "--output", "json", "--port", str(api_port),
                "--project", project_path,
                "asset", "list", "--path", "/Game/E2E_AssetProperty",
                "-q", "BP_E2E_ClassDefaults", "--limit", "10",
            ])
            assert listed.exit_code == 0
            listed_data = json.loads(listed.output)
            assert listed_data["status"] == "success"
            assert any(
                item["path"] == asset_path
                for item in listed_data["result"]["assets"]
            )

            read = cli_runner.invoke(cli, [
                "--output", "json", "--port", str(api_port),
                "--project", project_path,
                "asset", "property", asset_path, "InitialLifeSpan",
            ])
            assert read.exit_code == 0
            read_data = json.loads(read.output)
            assert read_data["status"] == "success"
            assert read_data["result"]["InitialLifeSpan"] == 37.5

            missing = cli_runner.invoke(cli, [
                "--output", "json", "--port", str(api_port),
                "--project", project_path,
                "asset", "property", asset_path, "DefinitelyMissingProperty",
            ])
            assert missing.exit_code == 3
            missing_data = json.loads(missing.output)
            assert missing_data["status"] == "error"
            assert missing_data["code"] == "ASSET_PROPERTY_READ_FAILED"
        finally:
            run_python_code(
                api, cleanup_code, project_dir=project_dir, timeout=15, save=False
            )
