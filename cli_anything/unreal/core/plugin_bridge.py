"""plugin_bridge.py — Auto-deploy, detect, and upgrade the CliAnythingBridge UE plugin.

The bridge exposes C++ APIs that Unreal Python/Blueprint cannot call directly
(e.g. ``FMaterialResource::GetCompileErrors()``). Screenshots are handled in
Python on the CLI host (Windows GDI), not in this plugin. Plugin source ships
with the CLI package and is copied to the project's ``Plugins/`` directory
when needed.
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


def get_bundled_version() -> str | None:
    """Get the version of the plugin bundled with this CLI package."""
    bundled_uplugin = _BUNDLED_PLUGIN_DIR / f"{_PLUGIN_NAME}.uplugin"
    return _read_uplugin_version(bundled_uplugin)


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


def get_loaded_plugin_version(api, timeout: float = 10.0, raise_on_error: bool = False) -> str | None:
    """Get the version of the plugin currently loaded in the running editor.

    Queries UCliAnythingBridgeLibrary::GetPluginVersion() via Python.
    Returns the version string (e.g. "1.5") or None if the plugin is not loaded.
    """
    script = (
        "import unreal\n"
        "try:\n"
        "    ver = unreal.CliAnythingBridgeLibrary.get_plugin_version()\n"
        "    result = {'version': ver}\n"
        "except AttributeError:\n"
        "    result = {'version': None}\n"
    )

    try:
        result = run_python_code(api, script, timeout=timeout, save=False)
        return result.get("version")
    except Exception:
        if raise_on_error:
            raise
        return None


def check_plugin_version(api, project_dir: str) -> dict:
    """Check whether the running plugin matches the bundled version.

    Returns:
        {
            "match": bool,
            "bundled_version": str,
            "loaded_version": str | None,
            "plugin_loaded": bool,
            "action_needed": "none" | "deploy_and_recompile" | "recompile",
        }
    """
    bundled_ver = get_bundled_version()
    loaded_ver = get_loaded_plugin_version(api)
    plugin_loaded = loaded_ver is not None

    if not plugin_loaded:
        # Plugin not loaded — check if source is deployed
        deploy = ensure_plugin_deployed(project_dir)
        if deploy.get("action") == "already_up_to_date":
            # Source is deployed but DLL not compiled/loaded
            action = "recompile"
        else:
            # Source was just deployed or needs deployment
            action = "deploy_and_recompile"
        return {
            "match": False,
            "bundled_version": bundled_ver,
            "loaded_version": None,
            "plugin_loaded": False,
            "action_needed": action,
        }

    if loaded_ver == bundled_ver:
        return {
            "match": True,
            "bundled_version": bundled_ver,
            "loaded_version": loaded_ver,
            "plugin_loaded": True,
            "action_needed": "none",
        }

    # Version mismatch: loaded is older than bundled
    # Need to deploy new source, recompile, and restart
    ensure_plugin_deployed(project_dir)
    return {
        "match": False,
        "bundled_version": bundled_ver,
        "loaded_version": loaded_ver,
        "plugin_loaded": True,
        "action_needed": "recompile",
    }
