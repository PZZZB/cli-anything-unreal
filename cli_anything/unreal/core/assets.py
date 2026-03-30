"""assets.py — Asset management commands (exists, delete, rename, duplicate).

Uses EditorAssetLibrary via Remote Control HTTP API for read-only queries
(exists, refs) — single HTTP call per operation.

Mutations (delete, duplicate, rename) go through Python script execution
inside the editor, because Remote Control's call_function on CDO does
not reliably perform write operations like DeleteAsset.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI


# ── Script templates ─────────────────────────────────────────────────

_SCRIPT_DELETE_ASSET = r'''
import unreal
path = "{asset_path}"
EAL = unreal.EditorAssetLibrary
deleted = EAL.delete_asset(path)
if deleted:
    unreal.SystemLibrary.collect_garbage()
result = {{"deleted": deleted}}
'''

_SCRIPT_DUPLICATE_ASSET = r'''
import unreal
source = "{source_path}"
dest = "{dest_path}"

EAL = unreal.EditorAssetLibrary

_proceed = True
if not EAL.does_asset_exist(source):
    result = {{"error": "Source asset not found: " + source}}
    _proceed = False
elif EAL.does_asset_exist(dest):
    if EAL.delete_asset(dest):
        unreal.SystemLibrary.collect_garbage()
    else:
        result = {{"error": "Could not delete existing destination: " + dest}}
        _proceed = False

if _proceed:
    success = EAL.duplicate_asset(source, dest)
    result = {{
        "status": "ok" if success else "failed",
        "source": source,
        "destination": dest,
        "duplicated": success,
    }}
'''

_SCRIPT_RENAME_ASSET = r'''
import unreal
source = "{source_path}"
dest = "{dest_path}"

EAL = unreal.EditorAssetLibrary

if not EAL.does_asset_exist(source):
    result = {{"error": "Source asset not found: " + source}}
elif EAL.does_asset_exist(dest):
    result = {{"error": "Destination already exists: " + dest}}
else:
    success = EAL.rename_asset(source, dest)
    result = {{
        "status": "ok" if success else "failed",
        "source": source,
        "destination": dest,
        "renamed": success,
    }}
'''


def _exec(api: "UEEditorAPI", script: str, project_dir: str | None, timeout: float = 15.0) -> dict:
    from cli_anything.unreal.core.script_runner import run_python_code
    return run_python_code(api, script, project_dir=project_dir, timeout=timeout, save=False)


# ── Public API ───────────────────────────────────────────────────────

def asset_exists(api: "UEEditorAPI", asset_path: str, **_kw) -> dict:
    """Check whether an asset exists. Single HTTP call."""
    exists = api.does_asset_exist(asset_path)
    return {"exists": exists, "asset": asset_path}


def asset_refs(api: "UEEditorAPI", asset_path: str, **_kw) -> dict:
    """List all assets that reference the given asset."""
    if not api.does_asset_exist(asset_path):
        return {"error": f"Asset not found: {asset_path}"}
    refs = api.find_asset_referencers(asset_path)
    return {"asset": asset_path, "referencers": refs, "count": len(refs)}


def asset_delete(
    api: "UEEditorAPI",
    asset_path: str,
    *,
    force: bool = False,
    project_dir: str | None = None,
    **_kw,
) -> dict:
    """Delete an asset with reference detection.

    DeleteAsset is a force-delete that does not show dialogs (verified
    on RXEngine 5.7). The --force flag controls whether to warn about
    referencers before deleting.

    Without --force: if other assets reference it, returns the list
    instead of deleting.

    With --force: deletes regardless (referencers will have broken refs).

    Deletion + GC runs via Python script inside the editor because
    Remote Control call_function on CDO is unreliable for mutations.
    """
    if not api.does_asset_exist(asset_path):
        return {"status": "not_found", "asset": asset_path, "deleted": False}

    refs = api.find_asset_referencers(asset_path)
    if refs and not force:
        return {
            "status": "has_references",
            "asset": asset_path,
            "deleted": False,
            "referencers": refs,
            "hint": "Use --force to delete anyway (referencers will have broken references)",
        }

    script = _SCRIPT_DELETE_ASSET.format(asset_path=asset_path)
    script_result = _exec(api, script, project_dir)
    deleted = script_result.get("deleted", False)

    result = {
        "status": "ok" if deleted else "failed",
        "asset": asset_path,
        "deleted": deleted,
    }
    if refs:
        result["had_references"] = True
        result["referencers"] = refs
    return result


def asset_duplicate(
    api: "UEEditorAPI",
    source_path: str,
    dest_path: str,
    *,
    force: bool = False,
    project_dir: str | None = None,
) -> dict:
    """Duplicate an asset. With --force, overwrites existing destination.

    Pre-deletes destination + GC to avoid the "overwrite?" dialog that
    duplicate_asset shows when the destination already exists.
    """
    if not force and api.does_asset_exist(dest_path):
        return {
            "error": f"Destination already exists: {dest_path}",
            "hint": "Use --force to overwrite (deletes existing asset first)",
        }

    script = _SCRIPT_DUPLICATE_ASSET.format(
        source_path=source_path, dest_path=dest_path,
    )
    return _exec(api, script, project_dir)


def asset_rename(
    api: "UEEditorAPI",
    source_path: str,
    dest_path: str,
    *,
    project_dir: str | None = None,
) -> dict:
    """Rename/move an asset."""
    script = _SCRIPT_RENAME_ASSET.format(source_path=source_path, dest_path=dest_path)
    return _exec(api, script, project_dir)
