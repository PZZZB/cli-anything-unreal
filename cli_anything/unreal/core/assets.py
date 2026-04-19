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

# Single attempt at deletion. Do NOT retry — repeated ForceDelete calls
# can mark the package as "potentially corrupt" in UE, making all future
# deletions impossible until editor restart.
deleted = EAL.delete_asset(path)
if deleted:
    unreal.SystemLibrary.collect_garbage()
    result = {{"deleted": True}}
else:
    result = {{"deleted": False, "hint": "ForceDelete failed. The package may be locked by an open asset editor, Content Browser, or undo buffer. Try: 1) Close any material/asset editors for this asset, 2) Use 'editor close' then restart the editor, 3) Delete after restart."}}
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


def search_assets(
    api: "UEEditorAPI",
    query: str = "",
    class_name: str | None = None,
    package_path: str = "/Game",
    limit: int = 0,
) -> dict:
    """Search assets via the Asset Registry (same as Content Browser).

    Runs entirely engine-side in a single HTTP call via Python script.
    Uses ``AssetRegistry.get_assets_by_path()`` — the same system the
    Content Browser and Asset Picker use.

    Parameters
    ----------
    api:
        A connected :class:`UEEditorAPI` instance.
    query:
        Name substring filter (case-insensitive).
    class_name:
        Short class name (e.g., ``"Material"``, ``"Texture2D"``).
        Resolved engine-side — no mapping table needed.
    package_path:
        Content path to search (default ``"/Game"``).
    limit:
        Max results (0 = unlimited).

    Returns
    -------
    dict
        ``{"assets": [{"name", "class", "path"}], "count": int}``
    """
    from cli_anything.unreal.core.script_runner import run_python_code

    class_repr = repr(class_name) if class_name else "None"
    query_repr = repr(query) if query else "None"
    limit_val = limit or 0

    script = f'''\
import unreal as _u

_ar = _u.AssetRegistryHelpers.get_asset_registry()
_assets = _ar.get_assets_by_path({repr(package_path)}, recursive=True)

_class_filter = {class_repr}
_name_query = {query_repr}
_limit = {limit_val}

_results = []
for _ad in _assets:
    _cls = str(_ad.asset_class_path.asset_name)
    _name = str(_ad.asset_name)

    if _class_filter and _cls != _class_filter:
        continue
    if _name_query and _name_query.lower() not in _name.lower():
        continue

    _results.append({{
        "name": _name,
        "class": _cls,
        "path": str(_ad.package_name),
    }})
    if _limit and len(_results) >= _limit:
        break

result = {{"assets": _results, "count": len(_results)}}
'''
    return run_python_code(api, script, save=False)


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

def get_asset_property(api: "UEEditorAPI", asset_path: str, property_name: str) -> dict:
    """Get a property value on a UAsset."""
    if not api.does_asset_exist(asset_path):
        return {"error": f"Asset not found: {asset_path}"}
        
    script = f'''
import unreal
asset = unreal.EditorAssetLibrary.load_asset('{asset_path}')
if asset:
    unreal.log(f'LOADED_OBJECT:{{asset.get_path_name()}}')
'''
    res = api.exec_python_ex(script)
    object_path = None
    for item in res.get("LogOutput", []):
        line = item.get("Output", "")
        if line.startswith("LOADED_OBJECT:"):
            object_path = line.split(":", 1)[1].strip()
            
    if not object_path:
        return {"error": f"Failed to load asset into memory: {asset_path}"}
        
    return api.get_property(object_path, property_name)

def set_asset_property(api: "UEEditorAPI", asset_path: str, property_name: str, value) -> dict:
    """Set a property value on a UAsset and mark it dirty."""
    if not api.does_asset_exist(asset_path):
        return {"error": f"Asset not found: {asset_path}"}
        
    script = f'''
import unreal
asset = unreal.EditorAssetLibrary.load_asset('{asset_path}')
if asset:
    unreal.log(f'LOADED_OBJECT:{{asset.get_path_name()}}')
'''
    res = api.exec_python_ex(script)
    object_path = None
    for item in res.get("LogOutput", []):
        line = item.get("Output", "")
        if line.startswith("LOADED_OBJECT:"):
            object_path = line.split(":", 1)[1].strip()
            
    if not object_path:
        return {"error": f"Failed to load asset into memory: {asset_path}"}
        
    set_res = api.set_property(object_path, property_name, value)
    
    # Mark package dirty so it can be saved
    dirty_script = f'''
import unreal
asset = unreal.EditorAssetLibrary.load_asset('{asset_path}')
if asset:
    unreal.EditorAssetLibrary.save_asset('{asset_path}', only_if_is_dirty=False)
    unreal.log('SAVED')
'''
    api.exec_python_ex(dirty_script)
    
    return set_res
