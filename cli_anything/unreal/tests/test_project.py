"""Tests for test_project.py — Uses synthetic data only, no UE editor required."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


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


