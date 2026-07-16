"""Tests for test_install_skills.py — Uses synthetic data only, no UE editor required."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestInstallSkills:
    """Tests for commands/skills.py — install-skills CLI."""

    def test_bundled_skill_metadata_uses_ue_cli_name(self):
        """Skill name matches the new package/CLI name."""
        source_dir = Path(__file__).parent.parent / "skills"
        skill_md = (source_dir / "SKILL.md").read_text(encoding="utf-8")
        evals = json.loads((source_dir / "evals" / "evals.json").read_text(encoding="utf-8"))

        assert "name: ue-cli" in skill_md
        assert evals["skill_name"] == "ue-cli"

    def test_viewport_realtime_guidance_is_reflection_aware(self):
        """Bundled editor workflows query the engine before choosing a fallback."""
        references_dir = Path(__file__).parent.parent / "skills" / "references"

        for filename in ("workflows-editor.md", "workflows-editor.original.md"):
            workflow = (references_dir / filename).read_text(encoding="utf-8")
            assert "editor api-discover LevelEditorSubsystem -q realtime" in workflow
            assert "EditorSetViewportRealtime" in workflow
            assert "editor_set_viewport_realtime(True)" in workflow
            assert "viewport realtime -> not exposed to Python" not in workflow
            assert "viewport realtime → not exposed to Python" not in workflow

    def test_install_to_custom_target(self, tmp_path):
        """--target writes the full skill tree to the given dir.

        tmp_path is a pytest fixture that creates a fresh dir per test and
        removes it after teardown — so nothing to clean up manually.
        """
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        target = tmp_path / "my_skill"
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--output", "json", "install-skills", "--target", str(target)]
        )
        assert result.exit_code == 0, result.output

        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["installed_count"] == 1

        # Verify every source file made it to the target.
        source_dir = Path(__file__).parent.parent / "skills"
        expected = [p for p in source_dir.rglob("*") if p.is_file()]
        assert target.exists()
        for src in expected:
            rel = src.relative_to(source_dir)
            assert (target / rel).is_file(), f"missing: {rel}"

    def test_install_multiple_targets(self, tmp_path):
        """--target is repeatable; each dir gets an independent copy."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        t1, t2 = tmp_path / "t1", tmp_path / "t2"
        result = CliRunner().invoke(cli, [
            "--output", "json", "install-skills",
            "--target", str(t1),
            "--target", str(t2),
        ])
        assert result.exit_code == 0, result.output

        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["installed_count"] == 2
        assert (t1 / "SKILL.md").is_file()
        assert (t2 / "SKILL.md").is_file()

    def test_default_targets_use_ue_cli_directory(self, tmp_path):
        """Default skill installs use the package/CLI name as their leaf dir."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = CliRunner().invoke(cli, ["--output", "json", "install-skills"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["installed_count"] == 3
        paths = {
            name: Path(info["path"])
            for name, info in data["result"]["targets"].items()
        }
        assert paths["claude_global"] == tmp_path / ".claude" / "skills" / "ue-cli"
        assert paths["codebuddy_global"] == tmp_path / ".codebuddy" / "agents" / "ue-cli"
        assert paths["gemini_global"] == tmp_path / ".gemini" / "skills" / "ue-cli"
        assert all((path / "SKILL.md").is_file() for path in paths.values())

    def test_install_overwrites_existing_target(self, tmp_path):
        """If the target already exists it is replaced, not merged."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        target = tmp_path / "existing"
        target.mkdir()
        # Leave a stray file that should NOT survive the reinstall.
        (target / "stray.txt").write_text("should be gone")

        result = CliRunner().invoke(
            cli, ["--output", "json", "install-skills", "--target", str(target)]
        )
        assert result.exit_code == 0, result.output

        assert not (target / "stray.txt").exists()
        assert (target / "SKILL.md").is_file()


# ═══════════════════════════════════════════════════════════════════════
#  Build success-path tests (mocked run_uat)
# ═══════════════════════════════════════════════════════════════════════


