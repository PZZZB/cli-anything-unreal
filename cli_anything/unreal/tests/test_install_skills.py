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

    def test_bundled_skill_encoding_preserves_chinese_triggers(self):
        """Windows PowerShell 5.1 can detect UTF-8 and render trigger text."""
        skill_path = Path(__file__).parent.parent / "skills" / "SKILL.md"
        skill_bytes = skill_path.read_bytes()

        assert skill_bytes.startswith(b"\xef\xbb\xbf")
        skill_md = skill_bytes.decode("utf-8-sig")
        assert "Chinese: 虚幻引擎, 材质, 蓝图, 关卡" in skill_md
        assert "铏氬够寮曟搸" not in skill_md
        assert "鏉愯川" not in skill_md

    def test_viewport_realtime_guidance_is_reflection_aware(self):
        """Bundled editor workflows query the engine before choosing a fallback."""
        references_dir = Path(__file__).parent.parent / "skills" / "references"

        workflow = (references_dir / "workflows-editor.md").read_text(encoding="utf-8")
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

        target = tmp_path / "custom-agent" / "skills" / "ue-cli"
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

        t1 = tmp_path / "agent-one" / "skills" / "ue-cli"
        t2 = tmp_path / "agent-two" / "skills" / "ue-cli"
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
        """Default installs cover native and cross-agent global directories."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        for marker in (".claude", ".codebuddy", ".codex", ".gemini"):
            (tmp_path / marker).mkdir()

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = CliRunner().invoke(cli, ["--output", "json", "install-skills"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["result"]["installed_count"] == 4
        paths = {
            name: Path(info["path"])
            for name, info in data["result"]["targets"].items()
        }
        assert paths["agents_global"] == tmp_path / ".agents" / "skills" / "ue-cli"
        assert paths["claude_global"] == tmp_path / ".claude" / "skills" / "ue-cli"
        assert paths["codebuddy_global"] == tmp_path / ".codebuddy" / "agents" / "ue-cli"
        assert paths["gemini_global"] == tmp_path / ".gemini" / "skills" / "ue-cli"
        assert all((path / "SKILL.md").is_file() for path in paths.values())

        clients = {
            client
            for info in data["result"]["targets"].values()
            for client in info["clients"]
        }
        assert clients == {
            "claude_code",
            "codebuddy",
            "codex",
            "cursor",
            "gemini",
            "github_copilot",
            "opencode",
            "windsurf",
        }
        assert data["result"]["detected_clients"] == [
            "claude_code",
            "codebuddy",
            "codex",
            "gemini",
        ]

    def test_default_targets_skip_clients_that_are_not_detected(self, tmp_path):
        """Default install does not create config dirs for absent clients."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        (tmp_path / ".cursor").mkdir()
        with patch("pathlib.Path.home", return_value=tmp_path):
            result = CliRunner().invoke(cli, ["--output", "json", "install-skills"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)["result"]
        assert data["installed_count"] == 1
        assert data["skipped_count"] == 3
        assert data["detected_clients"] == ["cursor"]
        assert data["targets"]["agents_global"]["installed"] is True
        for name in ("claude_global", "codebuddy_global", "gemini_global"):
            assert data["targets"][name]["skipped"] is True
        assert not (tmp_path / ".claude").exists()
        assert not (tmp_path / ".codebuddy").exists()
        assert not (tmp_path / ".gemini").exists()

    def test_all_targets_explicitly_installs_without_detected_clients(self, tmp_path):
        """--all-targets is the opt-in path for provisioning every client."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = CliRunner().invoke(
                cli,
                ["--output", "json", "install-skills", "--all-targets"],
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)["result"]
        assert data["installed_count"] == 4
        assert data["skipped_count"] == 0
        assert data["detected_clients"] == []
        assert data["forced_all_targets"] is True

    def test_no_detected_client_is_a_non_mutating_warning(self, tmp_path):
        """A plain install on a clean profile reports why nothing was written."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = CliRunner().invoke(cli, ["--output", "json", "install-skills"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)["result"]
        assert data["installed_count"] == 0
        assert data["skipped_count"] == 4
        assert "No supported client was detected" in data["warning"]
        for client_dir in (".agents", ".claude", ".codebuddy", ".gemini"):
            assert not (tmp_path / client_dir).exists()

    def test_copilot_vscode_extension_is_detected(self, tmp_path):
        """Copilot can be present as a VS Code extension without ~/.copilot."""
        from cli_anything.unreal.commands.skills import _detect_clients

        extension = tmp_path / ".vscode" / "extensions" / "github.copilot-1.2.3"
        extension.mkdir(parents=True)

        assert _detect_clients(tmp_path) == {"github_copilot"}

    def test_install_overwrites_existing_target(self, tmp_path):
        """If the target already exists it is replaced, not merged."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        skills_root = tmp_path / "existing" / "skills"
        target = skills_root / "ue-cli"
        sibling = skills_root / "other-skill"
        target.mkdir(parents=True)
        sibling.mkdir()
        # Leave a stray file that should NOT survive the reinstall.
        (target / "stray.txt").write_text("should be gone")
        (sibling / "SKILL.md").write_text("must survive")

        result = CliRunner().invoke(
            cli, ["--output", "json", "install-skills", "--target", str(target)]
        )
        assert result.exit_code == 0, result.output

        assert not (target / "stray.txt").exists()
        assert (target / "SKILL.md").is_file()
        assert (sibling / "SKILL.md").read_text() == "must survive"

    def test_custom_target_must_be_the_ue_cli_leaf(self, tmp_path):
        """A broad skill root is rejected before any directory is removed."""
        from click.testing import CliRunner
        from cli_anything.unreal.unreal_cli import cli

        broad_target = tmp_path / "skills"
        broad_target.mkdir()
        sentinel = broad_target / "other-skill.txt"
        sentinel.write_text("must survive")

        result = CliRunner().invoke(
            cli,
            ["--output", "json", "install-skills", "--target", str(broad_target)],
        )

        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["code"] == "INVALID_SKILL_TARGET"
        assert "must end with 'ue-cli'" in data["message"]
        assert sentinel.read_text() == "must survive"

    def test_custom_target_cannot_overlap_bundled_source(self, tmp_path):
        """Source, ancestors, and descendants cannot be replacement targets."""
        from cli_anything.unreal.commands import AppError
        from cli_anything.unreal.commands.skills import _validate_custom_target

        repo_root = tmp_path / "ue-cli"
        source_dir = repo_root / "package" / "skills"
        source_dir.mkdir(parents=True)

        for unsafe_target in (
            repo_root,
            source_dir,
            source_dir / "nested" / "ue-cli",
        ):
            with pytest.raises(AppError, match="overlaps the bundled skill source"):
                _validate_custom_target(source_dir, unsafe_target)


# ═══════════════════════════════════════════════════════════════════════
#  Build success-path tests (mocked run_uat)
# ═══════════════════════════════════════════════════════════════════════


