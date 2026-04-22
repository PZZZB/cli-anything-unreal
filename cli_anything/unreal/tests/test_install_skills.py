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


