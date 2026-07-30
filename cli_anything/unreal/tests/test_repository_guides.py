"""Static checks for repository-level agent guidance."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
CANONICAL_GUIDE = ROOT / "AGENTS.md"
COMPATIBILITY_GUIDES = (ROOT / "CLAUDE.md", ROOT / "CODEBUDDY.md")


def test_agent_guides_use_one_canonical_source():
    """Claude Code and CodeBuddy entrypoints import the canonical guide."""
    assert CANONICAL_GUIDE.is_file()
    assert CANONICAL_GUIDE.read_text(encoding="utf-8").startswith("# AGENTS.md\n")

    for guide in COMPATIBILITY_GUIDES:
        import_line = guide.read_text(encoding="utf-8").strip()
        assert import_line == "@AGENTS.md", guide
        assert (guide.parent / import_line[1:]).resolve() == CANONICAL_GUIDE.resolve()


def test_canonical_guide_avoids_volatile_test_counts():
    """Persistent guidance names test commands, not fast-stale collection totals."""
    document = CANONICAL_GUIDE.read_text(encoding="utf-8")

    assert "python -m pytest cli_anything/unreal/tests/ -v" in document
    assert "~358 tests" not in document
    assert "Current collection:" not in document
