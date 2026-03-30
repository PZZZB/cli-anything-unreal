"""plugin_bridge.py — Auto-deploy and detect the CliAnythingBridge UE plugin.

The bridge plugin exposes internal C++ APIs (e.g. FMaterialResource::GetCompileErrors)
that are not available through Python. Plugin source ships with the CLI package and is
automatically copied to the project's Plugins/ directory when needed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from cli_anything.unreal.core.script_runner import run_python_code

_PLUGIN_NAME = "CliAnythingBridge"

_BUNDLED_PLUGIN_DIR = Path(__file__).resolve().parent.parent / "bridge_plugin" / _PLUGIN_NAME


def _read_uplugin_version(uplugin_path: Path) -> str | None:
    """Read VersionName from a .uplugin file."""
    try:
        data = json.loads(uplugin_path.read_text(encoding="utf-8"))
        return data.get("VersionName")
    except (OSError, json.JSONDecodeError):
        return None


def ensure_plugin_deployed(project_dir: str) -> dict:
    """Ensure the bridge plugin source is deployed to the project.

    Copies or updates plugin source from the CLI package to
    {project_dir}/Plugins/CliAnythingBridge/. Skips if already up-to-date.

    Returns:
        {"deployed": bool, "action": str, "plugin_dir": str}
    """
    target_dir = Path(project_dir) / "Plugins" / _PLUGIN_NAME
    target_uplugin = target_dir / f"{_PLUGIN_NAME}.uplugin"
    bundled_uplugin = _BUNDLED_PLUGIN_DIR / f"{_PLUGIN_NAME}.uplugin"

    if not _BUNDLED_PLUGIN_DIR.exists():
        return {
            "deployed": False,
            "action": "error",
            "error": f"Bundled plugin source not found at {_BUNDLED_PLUGIN_DIR}",
        }

    bundled_version = _read_uplugin_version(bundled_uplugin)

    if target_uplugin.exists():
        target_version = _read_uplugin_version(target_uplugin)
        if target_version == bundled_version:
            return {
                "deployed": True,
                "action": "already_up_to_date",
                "version": target_version,
                "plugin_dir": str(target_dir),
            }
        action = f"updated_{target_version}_to_{bundled_version}"
    else:
        action = "fresh_install"

    if target_dir.exists():
        shutil.rmtree(target_dir)

    shutil.copytree(str(_BUNDLED_PLUGIN_DIR), str(target_dir))

    return {
        "deployed": True,
        "action": action,
        "version": bundled_version,
        "plugin_dir": str(target_dir),
    }


def is_plugin_loaded(api) -> bool:
    """Check if the bridge plugin is loaded in the running editor.

    Attempts to reference UCliAnythingBridgeLibrary via a trivial Python snippet.
    Returns True if the class exists, False otherwise.
    """
    probe_script = (
        "import unreal\n"
        "try:\n"
        "    cls = unreal.CliAnythingBridgeLibrary\n"
        "    result = {'loaded': True}\n"
        "except AttributeError:\n"
        "    result = {'loaded': False}\n"
    )

    try:
        result = run_python_code(api, probe_script, timeout=10.0, save=False)
        return result.get("loaded", False)
    except Exception:
        return False
