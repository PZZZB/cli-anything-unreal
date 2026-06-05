"""conftest.py - Shared pytest configuration for ue-cli tests."""

import json
import uuid
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption("--e2e", action="store_true", default=False, help="Run end-to-end tests (requires running UE editor)")
    parser.addoption("--e2e-auto-launch", action="store_true", default=False, help="Auto-launch the UE editor for E2E tests when it is not already running")
    parser.addoption("--e2e-launch-timeout", type=int, default=180, help="Seconds to wait for editor auto-launch in E2E tests")
    parser.addoption("--e2e-smoke", action="store_true", default=False, help="Run only the bounded E2E smoke subset")


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end test requiring UE editor")
    config.addinivalue_line("markers", "e2e_smoke: bounded smoke test suitable for quick validation")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--e2e"):
        skip_e2e = pytest.mark.skip(reason="Need --e2e option to run")
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip_e2e)

    if config.getoption("--e2e-smoke"):
        skip_non_smoke = pytest.mark.skip(reason="Need e2e_smoke marker when --e2e-smoke is enabled")
        for item in items:
            if "e2e" in item.keywords and "e2e_smoke" not in item.keywords:
                item.add_marker(skip_non_smoke)


@pytest.fixture
def tmp_path(request):
    base = Path(__file__).resolve().parents[3] / ".tmp_pytest"
    base.mkdir(parents=True, exist_ok=True)
    safe_name = request.node.name.replace("/", "_").replace("\\", "_").replace(":", "_")
    path = base / f"{safe_name}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


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
