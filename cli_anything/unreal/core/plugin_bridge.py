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
import uuid
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


def _ensure_disabled_by_default(uplugin_path: Path) -> bool:
    try:
        data = json.loads(uplugin_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("EnabledByDefault") is False:
        return False
    data["EnabledByDefault"] = False
    uplugin_path.write_text(json.dumps(data, indent="\t") + "\n", encoding="utf-8")
    return True


def ensure_project_bridge_disabled_by_default(project_dir: str) -> dict:
    """Disable descriptor-level autoload for an already deployed bridge plugin."""
    target_uplugin = Path(project_dir) / "Plugins" / _PLUGIN_NAME / f"{_PLUGIN_NAME}.uplugin"
    if not target_uplugin.exists():
        return {
            "status": "missing",
            "changed": False,
            "plugin_dir": str(target_uplugin.parent),
        }
    changed = _ensure_disabled_by_default(target_uplugin)
    return {
        "status": "ok",
        "changed": changed,
        "plugin_dir": str(target_uplugin.parent),
    }


def _bridge_upgrade_transaction_root(project_dir: str, transaction_id: str) -> Path:
    return (
        Path(project_dir)
        / "Saved"
        / "ue-cli"
        / "bridge-upgrades"
        / transaction_id
    )


def rollback_plugin_deployment(deploy_result: dict) -> dict:
    """Restore the bridge saved by a transactional deployment."""
    transaction = deploy_result.get("upgrade_transaction")
    if not isinstance(transaction, dict):
        return {"status": "not_needed", "restored": False}

    transaction_root_value = transaction.get("transaction_root")
    backup_dir_value = transaction.get("backup_dir")
    plugin_dir_value = transaction.get("plugin_dir")
    if not all(
        isinstance(value, str) and value
        for value in (transaction_root_value, backup_dir_value, plugin_dir_value)
    ):
        return {
            "status": "error",
            "code": "BRIDGE_ROLLBACK_STATE_INVALID",
            "restored": False,
            "error": "Bridge upgrade rollback state is incomplete.",
        }

    transaction_root = Path(transaction_root_value)
    backup_dir = Path(backup_dir_value)
    plugin_dir = Path(plugin_dir_value)
    if (
        transaction_root.name != transaction.get("transaction_id")
        or backup_dir.parent != transaction_root
        or backup_dir.name != _PLUGIN_NAME
        or plugin_dir.name != _PLUGIN_NAME
    ):
        return {
            "status": "error",
            "code": "BRIDGE_ROLLBACK_STATE_INVALID",
            "restored": False,
            "error": "Bridge upgrade rollback paths failed validation.",
        }

    if not backup_dir.is_dir():
        return {
            "status": "error",
            "code": "BRIDGE_ROLLBACK_BACKUP_MISSING",
            "restored": False,
            "error": f"Bridge upgrade backup is missing: {backup_dir}",
            "backup_dir": str(backup_dir),
            "plugin_dir": str(plugin_dir),
        }

    try:
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)
        backup_dir.replace(plugin_dir)
    except OSError as exc:
        return {
            "status": "error",
            "code": "BRIDGE_ROLLBACK_FAILED",
            "restored": False,
            "error": f"Could not restore the previous bridge plugin: {exc}",
            "backup_dir": str(backup_dir),
            "plugin_dir": str(plugin_dir),
            "previous_version": transaction.get("previous_version"),
            "failed_version": transaction.get("new_version"),
        }

    cleanup_error = None
    try:
        transaction_root.rmdir()
    except OSError as exc:
        cleanup_error = str(exc)

    result = {
        "status": "restored",
        "restored": True,
        "previous_version": transaction.get("previous_version"),
        "failed_version": transaction.get("new_version"),
        "plugin_dir": str(plugin_dir),
    }
    if cleanup_error:
        result["cleanup_error"] = cleanup_error
    return result


def finalize_plugin_deployment(deploy_result: dict) -> dict:
    """Discard a transactional deployment backup after validation succeeds."""
    transaction = deploy_result.get("upgrade_transaction")
    if not isinstance(transaction, dict):
        return {"status": "not_needed", "committed": False}

    transaction_root_value = transaction.get("transaction_root")
    backup_dir_value = transaction.get("backup_dir")
    transaction_id = transaction.get("transaction_id")
    if not all(
        isinstance(value, str) and value
        for value in (transaction_root_value, backup_dir_value, transaction_id)
    ):
        return {
            "status": "cleanup_failed",
            "committed": True,
            "error": "Bridge upgrade cleanup state is incomplete.",
        }

    transaction_root = Path(transaction_root_value)
    backup_dir = Path(backup_dir_value)
    if (
        transaction_root.name != transaction_id
        or backup_dir.parent != transaction_root
        or backup_dir.name != _PLUGIN_NAME
    ):
        return {
            "status": "cleanup_failed",
            "committed": True,
            "error": "Bridge upgrade cleanup paths failed validation.",
        }
    try:
        if transaction_root.exists():
            shutil.rmtree(transaction_root)
    except OSError as exc:
        return {
            "status": "cleanup_failed",
            "committed": True,
            "error": f"New bridge is valid, but its upgrade backup could not be removed: {exc}",
            "transaction_root": str(transaction_root),
            "previous_version": transaction.get("previous_version"),
            "version": transaction.get("new_version"),
        }
    return {
        "status": "committed",
        "committed": True,
        "previous_version": transaction.get("previous_version"),
        "version": transaction.get("new_version"),
    }


def ensure_plugin_deployed(
    project_dir: str,
    *,
    preserve_existing: bool = False,
    force_redeploy: bool = False,
) -> dict:
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
    target_version = None

    if target_uplugin.exists():
        target_version = _read_uplugin_version(target_uplugin)
        if target_version == bundled_version and not force_redeploy:
            normalized = _ensure_disabled_by_default(target_uplugin)
            return {
                "deployed": True,
                "action": "already_up_to_date",
                "version": target_version,
                "plugin_dir": str(target_dir),
                "descriptor_normalized": normalized,
            }
        if target_version == bundled_version:
            action = f"reinstalled_{bundled_version}"
        else:
            action = f"updated_{target_version}_to_{bundled_version}"
    else:
        action = "fresh_install"

    upgrade_transaction = None
    if target_dir.exists():
        if preserve_existing:
            transaction_id = uuid.uuid4().hex
            transaction_root = _bridge_upgrade_transaction_root(project_dir, transaction_id)
            backup_dir = transaction_root / _PLUGIN_NAME
            try:
                transaction_root.mkdir(parents=True, exist_ok=False)
                target_dir.replace(backup_dir)
            except OSError as exc:
                try:
                    if transaction_root.exists():
                        shutil.rmtree(transaction_root)
                except OSError:
                    pass
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
            upgrade_transaction = {
                "transaction_id": transaction_id,
                "transaction_root": str(transaction_root),
                "backup_dir": str(backup_dir),
                "plugin_dir": str(target_dir),
                "previous_version": target_version,
                "new_version": bundled_version,
                "status": "pending",
            }
        else:
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

    try:
        # copytree defaults to copy2(), which preserves packaged source mtimes.
        # Fresh mtimes force UBT to rebuild rules after a bridge source upgrade.
        shutil.copytree(
            str(_BUNDLED_PLUGIN_DIR),
            str(target_dir),
            copy_function=shutil.copy,
        )
    except OSError as exc:
        failed = {
            "deployed": False,
            "action": "error",
            "version": bundled_version,
            "plugin_dir": str(target_dir),
            "error": f"Could not deploy bundled bridge source: {exc}",
        }
        if upgrade_transaction:
            failed["upgrade_transaction"] = upgrade_transaction
            failed["rollback"] = rollback_plugin_deployment(failed)
        else:
            try:
                if target_dir.exists():
                    shutil.rmtree(target_dir)
            except OSError:
                pass
        return failed
    normalized = _ensure_disabled_by_default(target_uplugin)

    result = {
        "deployed": True,
        "action": action,
        "version": bundled_version,
        "plugin_dir": str(target_dir),
        "descriptor_normalized": normalized,
    }
    if upgrade_transaction:
        result["upgrade_transaction"] = upgrade_transaction
        result["rollback_available"] = True
    return result


def _read_modules_build_id(modules_path: Path) -> str | None:
    try:
        data = json.loads(modules_path.read_text(encoding="utf-8-sig"))
        return data.get("BuildId")
    except (OSError, json.JSONDecodeError):
        return None


def _clean_bridge_build_outputs(project_dir: str) -> dict:
    plugin_dir = Path(project_dir) / "Plugins" / _PLUGIN_NAME
    removed = []
    for subdir in ("Intermediate", "Binaries"):
        path = plugin_dir / subdir
        if not path.exists():
            continue
        try:
            shutil.rmtree(path)
        except OSError as exc:
            return {
                "status": "error",
                "code": "BRIDGE_OUTPUT_CLEAN_FAILED",
                "error": f"Could not remove stale bridge build output {path}: {exc}",
                "path": str(path),
            }
        removed.append(str(path))
    return {"status": "ok", "removed": removed}


def repair_bridge_modules_manifest(project_dir: str, engine_root: str) -> dict:
    """Create the plugin module manifest omitted by module-targeted UBT builds."""
    from cli_anything.unreal.utils.ue_backend import get_editor_binary_prefix

    editor_binary_prefix = get_editor_binary_prefix(engine_root)
    engine_modules_path = (
        Path(engine_root)
        / "Engine"
        / "Binaries"
        / "Win64"
        / f"{editor_binary_prefix}.modules"
    )
    try:
        engine_modules = json.loads(
            engine_modules_path.read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "error",
            "code": "BRIDGE_ENGINE_BUILD_ID_UNAVAILABLE",
            "error": f"Could not read engine module metadata {engine_modules_path}: {exc}",
            "engine_modules_path": str(engine_modules_path),
        }

    build_id = engine_modules.get("BuildId")
    if not isinstance(build_id, str) or not build_id:
        return {
            "status": "error",
            "code": "BRIDGE_ENGINE_BUILD_ID_UNAVAILABLE",
            "error": f"Engine module metadata has no BuildId: {engine_modules_path}",
            "engine_modules_path": str(engine_modules_path),
        }

    bin_dir = Path(project_dir) / "Plugins" / _PLUGIN_NAME / "Binaries" / "Win64"
    try:
        binaries = sorted(
            bin_dir.glob(f"{editor_binary_prefix}-{_PLUGIN_NAME}*.dll"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
    except OSError as exc:
        return {
            "status": "error",
            "code": "BRIDGE_BINARY_PROBE_FAILED",
            "error": f"Could not inspect bridge binaries in {bin_dir}: {exc}",
            "binary_directory": str(bin_dir),
        }
    if not binaries:
        return {
            "status": "error",
            "code": "BRIDGE_BINARY_MISSING_AFTER_COMPILE",
            "error": "Bridge module compile exited 0, but no bridge DLL was produced.",
            "binary_directory": str(bin_dir),
        }

    binary_path = binaries[0]
    modules_path = bin_dir / f"{editor_binary_prefix}.modules"
    expected = {
        "BuildId": build_id,
        "Modules": {_PLUGIN_NAME: binary_path.name},
    }
    current = None
    try:
        current = json.loads(modules_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        pass
    if current == expected:
        return {
            "status": "ok",
            "action": "already_valid",
            "modules_path": str(modules_path),
            "binary_path": str(binary_path),
            "build_id": build_id,
        }

    action = "repaired" if modules_path.exists() else "created"
    temp_path = modules_path.with_name(modules_path.name + ".tmp")
    try:
        bin_dir.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(json.dumps(expected, indent="\t") + "\n", encoding="utf-8")
        temp_path.replace(modules_path)
    except OSError as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return {
            "status": "error",
            "code": "BRIDGE_MODULES_WRITE_FAILED",
            "error": f"Could not write bridge module metadata {modules_path}: {exc}",
            "modules_path": str(modules_path),
        }
    return {
        "status": "ok",
        "action": action,
        "modules_path": str(modules_path),
        "binary_path": str(binary_path),
        "build_id": build_id,
    }


def compile_bridge_plugin(
    uproject_path: str,
    *,
    engine_root: str | None = None,
    config: str = "Development",
    log_file: str | None = None,
    on_start=None,
) -> dict:
    """Build only CliAnythingBridge, repair metadata, then prove launchability."""
    from cli_anything.unreal.core.build import (
        _validate_win64_editor_build_products,
        compile_project,
    )
    from cli_anything.unreal.utils.ue_backend import find_engine_root

    resolved_engine_root = engine_root or find_engine_root(uproject_path)
    recovery_command = (
        f'ue-cli --project "{uproject_path}" build compile '
        f"--platform Win64 --config {config}"
    )
    base = {
        "build_scope": "bridge_module",
        "module": _PLUGIN_NAME,
        "full_editor_build_started": False,
    }
    if not resolved_engine_root:
        return {
            **base,
            "status": "error",
            "code": "ENGINE_NOT_FOUND",
            "error": "Could not find engine root for bridge module compile.",
        }

    project_dir = str(Path(uproject_path).parent)
    clean_result = _clean_bridge_build_outputs(project_dir)
    if clean_result.get("status") != "ok":
        return {**base, **clean_result}

    compile_result = compile_project(
        uproject_path,
        config=config,
        platform="Win64",
        engine_root=resolved_engine_root,
        log_file=log_file,
        on_start=on_start,
        modules=[_PLUGIN_NAME],
    )
    result = {
        **base,
        "cleanup": clean_result,
        "compile_result": compile_result,
    }
    for key in ("command", "log_file", "returncode", "duration_seconds"):
        if key in compile_result:
            result[key] = compile_result[key]

    ubt_succeeded = compile_result.get("status") == "ok" or (
        compile_result.get("code") == "INVALID_BUILD_OUTPUT"
    )
    if not ubt_succeeded:
        return {
            **result,
            "status": "error",
            "code": compile_result.get("code", "BRIDGE_MODULE_COMPILE_FAILED"),
            "error": compile_result.get("error", "Bridge module compile failed."),
        }

    metadata_repair = repair_bridge_modules_manifest(project_dir, resolved_engine_root)
    result["metadata_repair"] = metadata_repair
    if metadata_repair.get("status") != "ok":
        return {
            **result,
            "status": "error",
            "code": "BRIDGE_METADATA_REPAIR_FAILED",
            "error": metadata_repair.get(
                "error",
                "Bridge module metadata could not be repaired after compilation.",
            ),
            "full_editor_build_required": True,
            "fallback_reason": metadata_repair.get("code", "metadata_repair_failed"),
            "recovery_command": recovery_command,
        }

    output_validation = _validate_win64_editor_build_products(
        uproject_path,
        resolved_engine_root,
        config,
        [_PLUGIN_NAME],
    )
    result["output_validation"] = output_validation or {"status": "ok"}
    if output_validation.get("status") == "error":
        return {
            **result,
            "status": "error",
            "code": "BRIDGE_TARGETED_BUILD_INCOMPLETE",
            "error": (
                "Bridge module compiled and its metadata was repaired, but the "
                "Editor target still has invalid build output."
            ),
            "full_editor_build_required": True,
            "fallback_reason": output_validation.get(
                "failure_kind",
                "editor_output_validation_failed",
            ),
            "recovery_command": recovery_command,
        }

    binary_status = get_plugin_binary_status(
        project_dir,
        engine_root=resolved_engine_root,
    )
    result["bridge_binary_status"] = binary_status
    if not binary_status.get("ready", False):
        return {
            **result,
            "status": "error",
            "code": "BRIDGE_BINARY_NOT_READY",
            "error": binary_status.get(
                "message",
                "Bridge binary is not ready after targeted compilation.",
            ),
            "full_editor_build_required": True,
            "fallback_reason": binary_status.get("reason", "bridge_binary_not_ready"),
            "recovery_command": recovery_command,
        }

    return {
        **result,
        "status": "ok",
        "full_editor_build_required": False,
    }


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
    editor_binary_prefix = "UnrealEditor"
    if engine_root:
        try:
            from cli_anything.unreal.utils.ue_backend import get_editor_binary_prefix
            editor_binary_prefix = get_editor_binary_prefix(engine_root)
        except Exception:
            editor_binary_prefix = "UnrealEditor"
    dll_path = bin_dir / f"{editor_binary_prefix}-{_PLUGIN_NAME}.dll"
    modules_path = bin_dir / f"{editor_binary_prefix}.modules"

    base = {
        "plugin_dir": str(plugin_dir),
        "editor_binary_prefix": editor_binary_prefix,
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

    if not dll_path.is_file() and not modules_path.is_file():
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
            "message": f"Bridge plugin {editor_binary_prefix}.modules file is missing.",
        }

    try:
        modules = json.loads(modules_path.read_text(encoding="utf-8-sig")).get("Modules", {})
    except (OSError, json.JSONDecodeError):
        modules = {}
    module_binary = modules.get(_PLUGIN_NAME)
    if not isinstance(module_binary, str) or not module_binary:
        return {
            **base,
            "ready": False,
            "reason": "missing_module_entry",
            "message": "Bridge plugin modules file does not list CliAnythingBridge.",
        }

    if Path(module_binary).name != module_binary or Path(module_binary).suffix.casefold() != ".dll":
        return {
            **base,
            "ready": False,
            "reason": "invalid_module_entry",
            "message": "Bridge plugin modules file contains an invalid CliAnythingBridge binary path.",
        }
    dll_path = bin_dir / module_binary
    base["dll_path"] = str(dll_path)
    if not dll_path.is_file():
        return {
            **base,
            "ready": False,
            "reason": "missing_binary",
            "message": "Bridge plugin binary is missing.",
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
        engine_modules = Path(engine_root) / "Engine" / "Binaries" / "Win64" / f"{editor_binary_prefix}.modules"
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
