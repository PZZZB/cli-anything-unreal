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
        try:
            shutil.rmtree(target_dir)
        except PermissionError as exc:
            return {
                "deployed": True,
                "action": "update_pending_locked",
                "version": target_version,
                "bundled_version": bundled_version,
                "plugin_dir": str(target_dir),
                "error": str(exc),
                "warning": "Bridge plugin is in use and could not be updated while the editor is running.",
                "suggestion": "Close the editor, then run editor plugin-upgrade to deploy and compile the bundled bridge.",
                "retry_suggested": True,
            }

    shutil.copytree(str(_BUNDLED_PLUGIN_DIR), str(target_dir))

    return {
        "deployed": True,
        "action": action,
        "version": bundled_version,
        "plugin_dir": str(target_dir),
    }


def _read_modules_build_id(modules_path: Path) -> str | None:
    try:
        data = json.loads(modules_path.read_text(encoding="utf-8-sig"))
        return data.get("BuildId")
    except (OSError, json.JSONDecodeError):
        return None


def _newest_plugin_source_mtime(plugin_dir: Path) -> float:
    newest = 0.0
    source_dir = plugin_dir / "Source"

    for path in plugin_dir.glob("*.uplugin"):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            pass
    if not source_dir.is_dir():
        return newest
    for pattern in ("*.cpp", "*.h", "*.cs"):
        for path in source_dir.rglob(pattern):
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                pass
    return newest


def get_plugin_binary_status(project_dir: str, engine_root: str | None = None) -> dict:
    """Check whether the deployed bridge has a loadable editor binary.

    Launching UE with an enabled project plugin but no compiled module creates
    a modal "module could not be found" startup failure. This check lets the
    CLI compile before launch instead of learning that from a failed editor.
    """
    plugin_dir = Path(project_dir) / "Plugins" / _PLUGIN_NAME
    bin_dir = plugin_dir / "Binaries" / "Win64"
    dll_path = bin_dir / f"UnrealEditor-{_PLUGIN_NAME}.dll"
    modules_path = bin_dir / "UnrealEditor.modules"

    base = {
        "plugin_dir": str(plugin_dir),
        "dll_path": str(dll_path),
        "modules_path": str(modules_path),
    }

    if not plugin_dir.is_dir():
        return {
            **base,
            "ready": False,
            "reason": "not_deployed",
            "message": "Bridge plugin source is not deployed.",
        }

    if not dll_path.is_file():
        return {
            **base,
            "ready": False,
            "reason": "missing_binary",
            "message": "Bridge plugin binary is missing.",
        }

    if not modules_path.is_file():
        return {
            **base,
            "ready": False,
            "reason": "missing_modules_file",
            "message": "Bridge plugin UnrealEditor.modules file is missing.",
        }

    try:
        modules = json.loads(modules_path.read_text(encoding="utf-8-sig")).get("Modules", {})
    except (OSError, json.JSONDecodeError):
        modules = {}
    if _PLUGIN_NAME not in modules:
        return {
            **base,
            "ready": False,
            "reason": "missing_module_entry",
            "message": "Bridge plugin modules file does not list CliAnythingBridge.",
        }

    newest_source = _newest_plugin_source_mtime(plugin_dir)
    try:
        dll_mtime = dll_path.stat().st_mtime
    except OSError:
        dll_mtime = 0.0
    if newest_source > dll_mtime:
        return {
            **base,
            "ready": False,
            "reason": "stale_binary",
            "message": "Bridge plugin source is newer than its compiled binary.",
        }

    if engine_root:
        engine_modules = Path(engine_root) / "Engine" / "Binaries" / "Win64" / "UnrealEditor.modules"
        engine_build_id = _read_modules_build_id(engine_modules)
        plugin_build_id = _read_modules_build_id(modules_path)
        if engine_build_id and plugin_build_id and engine_build_id != plugin_build_id:
            return {
                **base,
                "ready": False,
                "reason": "build_id_mismatch",
                "message": "Bridge plugin binary was built against a different engine BuildId.",
                "engine_build_id": engine_build_id,
                "plugin_build_id": plugin_build_id,
            }

    return {
        **base,
        "ready": True,
        "reason": "ok",
        "message": "Bridge plugin binary is ready.",
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
