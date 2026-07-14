"""Static checks for the repository's GitHub Issue repair path."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[3]
ISSUE_TEMPLATE_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"
BUG_REPORT = ISSUE_TEMPLATE_DIR / "bug-report.yml"
TEMPLATE_CONFIG = ISSUE_TEMPLATE_DIR / "config.yml"

REQUIRED_REPORT_FIELDS = {
    "tool_version",
    "environment",
    "command",
    "expected",
    "actual",
    "reproduction",
}


def _form_items(document: str) -> dict[str, str]:
    """Return form item text keyed by each item's ``id``."""
    items = {}
    for block in re.split(r"(?m)(?=^  - type:)", document):
        match = re.search(r"(?m)^    id:\s*([a-zA-Z0-9_-]+)\s*$", block)
        if match:
            items[match.group(1)] = block
    return items


def test_bug_report_collects_required_agent_evidence_without_labels():
    document = BUG_REPORT.read_text(encoding="utf-8")
    items = _form_items(document)

    assert not re.search(r"(?m)^\s*labels\s*:", document)
    assert REQUIRED_REPORT_FIELDS <= items.keys()
    for field_id in REQUIRED_REPORT_FIELDS:
        assert re.search(
            r"(?m)^      required:\s*true\s*$", items[field_id]
        ), f"{field_id} must be required"

    assert "logs" in items
    assert not re.search(r"(?m)^      required:\s*true\s*$", items["logs"])


def test_blank_issues_remain_enabled():
    document = TEMPLATE_CONFIG.read_text(encoding="utf-8")

    assert re.search(r"(?m)^blank_issues_enabled:\s*true\s*$", document)
