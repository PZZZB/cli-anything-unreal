"""Architecture dependency guards."""

import ast
from pathlib import Path


def test_typed_error_preserves_exception_message():
    from cli_anything.unreal.errors import UeCliError

    error = UeCliError(code="TEST_FAILURE", message="boom")

    assert str(error) == "boom"
    assert error.args == ("boom",)


def test_core_and_utils_do_not_import_command_modules():
    package_root = Path(__file__).parents[1]
    violations = []

    for layer in ("core", "utils"):
        for source_path in (package_root / layer).rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8-sig"), filename=str(source_path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported = [node.module or ""]
                else:
                    continue
                for module_name in imported:
                    if (
                        module_name == "cli_anything.unreal.commands"
                        or module_name.startswith("cli_anything.unreal.commands.")
                    ):
                        violations.append(
                            f"{source_path.relative_to(package_root)}:{node.lineno}: {module_name}"
                        )

    assert violations == [], "Lower layers import Click commands:\n" + "\n".join(violations)


def test_editor_command_uses_canonical_lifecycle_helpers():
    from cli_anything.unreal.commands import editor
    from cli_anything.unreal.core import editor_lifecycle

    shared_helpers = {
        "_active_launch_task_for_project",
        "_build_launch_cmd",
        "_check_already_running",
        "_check_log_errors",
        "_remote_control_launch_error",
        "_same_project_path",
    }

    for name in shared_helpers:
        assert getattr(editor, name) is getattr(editor_lifecycle, name), name
