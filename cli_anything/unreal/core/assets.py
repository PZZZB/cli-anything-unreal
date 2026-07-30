"""assets.py — Asset management commands (exists, delete, rename, duplicate).

Uses EditorAssetLibrary via Remote Control HTTP API for read-only queries
(exists, refs) — single HTTP call per operation.

Mutations (delete, duplicate, rename) go through Python script execution
inside the editor, because Remote Control's call_function on CDO does
not reliably perform write operations like DeleteAsset.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING


_UNREAL_ENUM_RE = re.compile(
    r"^<[^.<>]+\.([A-Z][A-Z0-9_]*):\s*-?\d+>$"
)


def _normalize_unreal_property_value(value):
    """Normalize UE4 Python enum reprs to the stable UE property text form."""
    if not isinstance(value, str):
        return value
    match = _UNREAL_ENUM_RE.fullmatch(value.strip())
    if not match:
        return value
    tokens = match.group(1).split("_")
    if len(tokens) > 1:
        tokens = tokens[1:]
    return "".join(token.title() for token in tokens)


def _asset_class_matches(asset_class: str, class_filter: str | None) -> bool:
    """Return whether an Asset Registry class satisfies the CLI class filter."""
    if not class_filter:
        return True
    if class_filter == "Blueprint":
        return asset_class == class_filter or asset_class.endswith("Blueprint")
    return asset_class == class_filter


if TYPE_CHECKING:
    from cli_anything.unreal.utils.ue_http_api import UEEditorAPI


# ── Script templates ─────────────────────────────────────────────────

_SCRIPT_DELETE_ASSET = r'''
import unreal
requested_path = "{requested_path}"
delete_path = "{delete_path}"
EAL = unreal.EditorAssetLibrary

# Single attempt at deletion. Do NOT retry — repeated ForceDelete calls
# can mark the package as "potentially corrupt" in UE, making all future
# deletions impossible until editor restart.
deleted = EAL.delete_asset(delete_path)
if deleted:
    unreal.SystemLibrary.collect_garbage()
    result = {{"deleted": True, "deleted_asset": delete_path, "requested_asset": requested_path}}
else:
    result = {{"deleted": False, "deleted_asset": delete_path, "requested_asset": requested_path, "hint": "ForceDelete failed. The package may be locked by an open asset editor, Content Browser, or undo buffer. Try: 1) Close any material/asset editors for this asset, 2) Use 'editor close' then restart the editor, 3) Delete after restart."}}
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


_SCRIPT_TEXTURE_SOURCE_INFO = r'''
import json
import unreal

asset_path = {asset_path!r}

def _cli_object_path_candidates(path):
    base = str(path).strip().split(":", 1)[0]
    if not base:
        return [base]
    leaf = base.rsplit("/", 1)[-1]
    if "." in leaf:
        return [base]
    return [base, base + "." + leaf]

def _cli_load_texture(path):
    tried = []
    for candidate in _cli_object_path_candidates(path):
        if not candidate or candidate in tried:
            continue
        tried.append(candidate)
        obj = None
        try:
            obj = unreal.EditorAssetLibrary.load_asset(candidate)
        except Exception:
            obj = None
        if obj is None:
            try:
                obj = unreal.load_object(None, candidate)
            except Exception:
                obj = None
        if obj is not None:
            return obj, candidate, tried
    return None, None, tried

tex, loaded_path, tried_paths = _cli_load_texture(asset_path)
if tex is None:
    result = {"error": "Texture asset not found: " + asset_path, "tried": tried_paths}
elif not isinstance(tex, unreal.Texture2D):
    result = {"error": "Asset is not a Texture2D: " + loaded_path, "class": tex.get_class().get_name()}
elif not hasattr(unreal, "CliAnythingBridgeLibrary") or not hasattr(unreal.CliAnythingBridgeLibrary, "get_texture_source_info"):
    result = {"error": "CliAnythingBridgeLibrary is missing GetTextureSourceInfo. TextureSource inspection requires bridge plugin 1.16+.", "suggestion": "Run editor plugin-upgrade, then relaunch the editor."}
else:
    raw = unreal.CliAnythingBridgeLibrary.get_texture_source_info(tex)
    result = json.loads(raw or "{}")
    if "error" not in result:
        result["asset"] = loaded_path
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
import re as _re
import unreal as _u

_ar = _u.AssetRegistryHelpers.get_asset_registry()
_assets = list(_ar.get_assets_by_path({repr(package_path)}, recursive=True))
_pkg_prefix = str({repr(package_path)}).rstrip("/")
if not _assets:
    try:
        _all_assets = list(_ar.get_all_assets())
        _assets = [
            _ad for _ad in _all_assets
            if str(_ad.package_name) == _pkg_prefix or str(_ad.package_name).startswith(_pkg_prefix + '/')
        ]
    except Exception:
        _assets = []

_class_filter = {class_repr}
_name_query = {query_repr}
_limit = {limit_val}

def _cli_asset_class_matches(_cls, _filter):
    if not _filter:
        return True
    if _filter == "Blueprint":
        return _cls == _filter or _cls.endswith('Blueprint')
    return _cls == _filter

def _cli_asset_class_name(_asset_data):
    try:
        return str(_asset_data.asset_class_path.asset_name)
    except Exception:
        return str(_asset_data.asset_class)

# Case-insensitive regex for name query (re.search — partial match OK).
_name_pat = None
if _name_query:
    try:
        _name_pat = _re.compile(_name_query, _re.IGNORECASE)
    except _re.error as _e:
        result = {{"error": "Invalid regex for --query: " + str(_e),
                   "query": _name_query}}
        _name_pat = False  # sentinel

if _name_pat is False:
    pass
else:
    _results = []
    for _ad in _assets:
        _cls = _cli_asset_class_name(_ad)
        _name = str(_ad.asset_name)

        if not _cli_asset_class_matches(_cls, _class_filter):
            continue
        if _name_pat is not None and not _name_pat.search(_name):
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


def _asset_object_path(asset_path: str) -> str:
    """Return the full object path for package paths."""
    path = str(asset_path).strip()
    if not path:
        return path
    base, sep, suffix = path.partition(":")
    leaf = base.rsplit("/", 1)[-1]
    if "." not in leaf:
        base = base + "." + leaf
    return base + (sep + suffix if sep else "")


def _asset_reference_path_candidates(asset_path: str) -> list[str]:
    """Return likely reference-query paths for package/object path inputs."""
    candidates: list[str] = []
    for path in (str(asset_path).strip(), _asset_object_path(asset_path)):
        if path and path not in candidates:
            candidates.append(path)
    return candidates


def asset_refs(api: "UEEditorAPI", asset_path: str, **_kw) -> dict:
    """List all assets that reference the given asset."""
    tried = _asset_reference_path_candidates(asset_path)
    resolved_asset = None
    for candidate in tried:
        if api.does_asset_exist(candidate):
            resolved_asset = candidate
            break
    if resolved_asset is None:
        return {
            "error": f"Asset not found: {asset_path}",
            "asset": asset_path,
            "tried": tried,
            "suggestion": "Use a package path like /Game/A or a full object path like /Game/A.A.",
        }
    refs = api.find_asset_referencers(resolved_asset)
    result = {"asset": asset_path, "referencers": refs, "count": len(refs)}
    if resolved_asset != asset_path:
        result["resolved_asset"] = resolved_asset
    return result


def texture_source_info(
    api: "UEEditorAPI",
    asset_path: str,
    *,
    project_dir: str | None = None,
) -> dict:
    """Read Texture2D Source size/format and channel stats via the bridge plugin."""
    script = _SCRIPT_TEXTURE_SOURCE_INFO.replace("{asset_path!r}", repr(asset_path))
    return _exec(api, script, project_dir, timeout=30.0)


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

    delete_path = _asset_object_path(asset_path)
    script = _SCRIPT_DELETE_ASSET.format(requested_path=asset_path, delete_path=delete_path)
    script_result = _exec(api, script, project_dir)
    deleted = script_result.get("deleted", False)

    result = {
        "status": "ok" if deleted else "failed",
        "asset": asset_path,
        "deleted": deleted,
    }
    if script_result.get("deleted_asset"):
        result["deleted_asset"] = script_result["deleted_asset"]
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
    """Get a property value on a UAsset or Blueprint class default object."""
    resolve_script = f'''\
import unreal as _u

_requested_path = {asset_path!r}
_base_path = _requested_path.split(":", 1)[0]
_leaf = _base_path.rsplit("/", 1)[-1]
_path_candidates = [_base_path]
if "." not in _leaf:
    _path_candidates.append(_base_path + "." + _leaf)

_asset = None
_loaded_path = None
_tried = []
for _candidate in _path_candidates:
    if not _candidate or _candidate in _tried:
        continue
    _tried.append(_candidate)
    try:
        _asset = _u.EditorAssetLibrary.load_asset(_candidate)
    except Exception:
        _asset = None
    if _asset is None:
        try:
            _asset = _u.load_asset(_candidate)
        except Exception:
            _asset = None
    if _asset is None:
        try:
            _asset = _u.load_object(None, _candidate)
        except Exception:
            _asset = None
    if _asset is not None:
        _loaded_path = _candidate
        break

if _asset is None:
    result = {{
        "error": "Asset not found: " + _requested_path,
        "asset": _requested_path,
        "tried": _tried,
    }}
else:
    _targets = [{{
        "kind": "asset",
        "object_path": _asset.get_path_name(),
    }}]
    _generated_class = None
    try:
        _generated_class = _asset.generated_class()
    except Exception:
        try:
            _generated_class = _asset.get_editor_property("generated_class")
        except Exception:
            _generated_class = None
    if _generated_class is None:
        try:
            _generated_class = _u.load_object(
                None, _asset.get_path_name() + "_C"
            )
        except Exception:
            _generated_class = None
    if _generated_class is not None:
        try:
            _cdo = _u.get_default_object(_generated_class)
        except Exception:
            _cdo = None
        if _cdo is not None:
            _targets.append({{
                "kind": "class_default_object",
                "object_path": _cdo.get_path_name(),
            }})
    result = {{
        "asset": _requested_path,
        "loaded_asset": _asset.get_path_name(),
        "loaded_path": _loaded_path,
        "targets": _targets,
    }}
'''
    resolved = _exec(api, resolve_script, None)
    if resolved.get("error"):
        return resolved

    targets = resolved.get("targets", [])
    remote_errors = []
    for target in targets:
        object_path = target.get("object_path")
        if not object_path:
            continue
        remote_result = api.get_property(object_path, property_name)
        remote_error = remote_result.get("error") or remote_result.get("errorMessage")
        if not remote_error:
            normalized = dict(remote_result)
            if property_name in normalized:
                normalized[property_name] = _normalize_unreal_property_value(
                    normalized[property_name]
                )
            return normalized
        remote_errors.append({
            "target": target.get("kind"),
            "object_path": object_path,
            "error": str(remote_error),
        })

    fallback_script = f'''\
import re as _re
import unreal as _u

_asset_path = {asset_path!r}
_property_name = {property_name!r}
_targets = {targets!r}

def _cli_property_name(_name):
    return _re.sub(r"(?<!^)(?=[A-Z])", "_", _name).lower()

def _cli_serialize_property(_value):
    if _value is None or isinstance(_value, (bool, int, float, str)):
        return _value
    if isinstance(_value, _u.Object):
        return _value.get_path_name()
    if isinstance(_value, (list, tuple, set)):
        return [_cli_serialize_property(_item) for _item in _value]
    if isinstance(_value, dict):
        return {{
            str(_key): _cli_serialize_property(_item)
            for _key, _item in _value.items()
        }}
    return str(_value)

_property_candidates = [_property_name]
_snake_name = _cli_property_name(_property_name)
if _snake_name not in _property_candidates:
    _property_candidates.append(_snake_name)

_attempts = []
_property_read = False
for _target in _targets:
    _object_path = _target.get("object_path")
    try:
        _object = _u.load_object(None, _object_path)
    except Exception as _exc:
        _object = None
        _attempts.append({{
            "target": _target.get("kind"),
            "object_path": _object_path,
            "error": str(_exc),
        }})
    if _object is None:
        continue
    for _candidate in _property_candidates:
        try:
            _value = _object.get_editor_property(_candidate)
            result = {{
                _property_name: _cli_serialize_property(_value),
                "asset": _asset_path,
                "object_path": _object_path,
                "target": _target.get("kind"),
                "read_via": "unreal_python",
            }}
            _property_read = True
            break
        except Exception as _exc:
            _attempts.append({{
                "target": _target.get("kind"),
                "object_path": _object_path,
                "property": _candidate,
                "error": str(_exc),
            }})
    if _property_read:
        break

if not _property_read:
    result = {{
        "error": "Property '" + _property_name + "' is not readable on asset or class default object.",
        "asset": _asset_path,
        "property": _property_name,
        "targets": _targets,
        "attempts": _attempts,
    }}
'''
    fallback = _exec(api, fallback_script, None)
    if property_name in fallback:
        fallback[property_name] = _normalize_unreal_property_value(
            fallback[property_name]
        )
    if fallback.get("error") and remote_errors:
        fallback["remote_control_attempts"] = remote_errors
    return fallback

def set_asset_property(api: "UEEditorAPI", asset_path: str, property_name: str, value) -> dict:
    """Set a property value on a UAsset and mark it dirty."""
    exists_probe = api.does_asset_exist(asset_path)
        
    script = f'''
import unreal
asset_path = {asset_path!r}
asset = unreal.EditorAssetLibrary.load_asset(asset_path)
if asset is None and "." not in asset_path.rsplit("/", 1)[-1]:
    asset = unreal.EditorAssetLibrary.load_asset(asset_path + "." + asset_path.rsplit("/", 1)[-1])
if asset is None:
    try:
        asset = unreal.load_object(None, asset_path)
    except Exception:
        asset = None
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
        if exists_probe is False:
            return {"error": f"Asset not found: {asset_path}"}
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
