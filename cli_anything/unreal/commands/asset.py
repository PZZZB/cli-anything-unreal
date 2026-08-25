"""commands/asset.py — Asset operations commands."""

import shlex
import subprocess as sp
import sys

import click

from cli_anything.unreal.commands import (
    AppError,
    AppState,
    handle_error,
    output,
    require_editor,
)
from cli_anything.unreal.commands._parse_value import parse_property_value
from cli_anything.unreal.errors import raise_for_legacy_error


@click.group("asset")
def asset_group():
    """Asset operations (list, exists, delete, duplicate, rename, properties)."""
    pass


@asset_group.command("list")
@click.option("--query", "-q", default="",
              help="Case-insensitive regex for asset names (via re.search). "
                   "Plain strings behave as substrings; anchors/alternation also work.")
@click.option(
    "--class",
    "class_name",
    default=None,
    help="Filter by class (e.g., Material, Texture2D, Blueprint; Blueprint includes WidgetBlueprint/AnimBlueprint)",
)
@click.option("--path", "package_path", default="/Game", help="Content path to search (default: /Game)")
@click.option("--limit", default=0, type=int, help="Max results (0 = unlimited)")
@handle_error
@click.pass_obj
def asset_list(state: AppState, query, class_name, package_path, limit):
    """Search and list assets via the Asset Registry (same as Content Browser).

    \b
    Examples:
        asset list                              # all assets under /Game
        asset list -q BlackHole                 # search by name
        asset list --class Material             # filter by class
        asset list --class Material -q Water    # combine filters
        asset list --path /Game/Blueprints      # search specific folder
    """
    from cli_anything.unreal.core.assets import search_assets

    api = require_editor(state)
    result = search_assets(api, query=query, class_name=class_name,
                           package_path=package_path, limit=limit)
    raise_for_legacy_error(result, default_code="ASSET_LIST_FAILED")
    output(result, state)


@asset_group.command("exists")
@click.argument("asset_path")
@handle_error
@click.pass_obj
def asset_exists_cmd(state: AppState, asset_path):
    """Check if an asset exists at the given content path.

    Example: asset exists /Game/Materials/M_Water
    """
    from cli_anything.unreal.core.assets import asset_exists

    api = require_editor(state)
    result = asset_exists(api, asset_path, project_dir=state.session.project_dir)
    output(result, state)


@asset_group.command("texture-source")
@click.argument("asset_path")
@handle_error
@click.pass_obj
def asset_texture_source_cmd(state: AppState, asset_path):
    """Read Texture2D Source size/format and alpha/value stats via bridge.

    Example: asset texture-source /Game/UI/T_SDF
    """
    from cli_anything.unreal.core.assets import texture_source_info

    api = require_editor(state)
    result = texture_source_info(api, asset_path, project_dir=state.session.project_dir)
    raise_for_legacy_error(result, default_code="ASSET_TEXTURE_SOURCE_FAILED")
    output(result, state)


@asset_group.command("delete")
@click.argument("asset_path")
@click.option("--force", is_flag=True, default=False,
              help="Delete even if other assets reference it (they will have broken references).")
@handle_error
@click.pass_obj
def asset_delete_cmd(state: AppState, asset_path, force):
    """Safely delete an asset with reference detection.

    Without --force: if other assets reference it, returns the list of
    referencers instead of deleting (avoids triggering modal dialogs).

    With --force: deletes regardless of references.

    Example: asset delete /Game/Materials/M_Old --force
    """
    from cli_anything.unreal.core.assets import asset_delete

    api = require_editor(state)
    result = asset_delete(api, asset_path, force=force, project_dir=state.session.project_dir)
    raise_for_legacy_error(result, default_code="ASSET_DELETE_FAILED")
    output(result, state)


@asset_group.command("refs")
@click.argument("asset_path")
@handle_error
@click.pass_obj
def asset_refs_cmd(state: AppState, asset_path):
    """List all assets that reference the given asset.

    Useful before deleting — shows what would break.

    Example: asset refs /Game/Materials/M_Water
    """
    from cli_anything.unreal.core.assets import asset_refs

    api = require_editor(state)
    result = asset_refs(api, asset_path, project_dir=state.session.project_dir)
    if isinstance(result, dict) and result.get("error"):
        raise AppError(
            "ASSET_REFS_FAILED",
            str(result["error"]),
            exit_code=3,
            details=result,
        )
    output(result, state)


@asset_group.command("duplicate")
@click.argument("source_path")
@click.argument("dest_path")
@click.option("--force", is_flag=True, default=False,
              help="Overwrite destination if it already exists.")
@handle_error
@click.pass_obj
def asset_duplicate_cmd(state: AppState, source_path, dest_path, force):
    """Duplicate an asset to a new path.

    With --force: if destination exists, deletes it first then duplicates.
    Without --force: fails if destination already exists.

    Example: asset duplicate /Game/M_Water /Game/M_Water_v2
    """
    from cli_anything.unreal.core.assets import asset_duplicate

    api = require_editor(state)
    result = asset_duplicate(api, source_path, dest_path, force=force,
                             project_dir=state.session.project_dir)
    raise_for_legacy_error(result, default_code="ASSET_DUPLICATE_FAILED")
    output(result, state)


@asset_group.command("rename")
@click.argument("source_path")
@click.argument("dest_path")
@click.option(
    "--timeout",
    type=click.IntRange(min=1),
    default=120,
    show_default=True,
    help="Maximum seconds to wait before verifying an ambiguous rename outcome.",
)
@handle_error
@click.pass_obj
def asset_rename_cmd(state: AppState, source_path, dest_path, timeout):
    """Rename/move an asset to a new path.

    Fails if destination already exists.

    Example: asset rename /Game/M_Old /Game/M_New
    """
    from cli_anything.unreal.core.assets import asset_rename

    api = require_editor(state)
    result = asset_rename(api, source_path, dest_path,
                          project_dir=state.session.project_dir,
                          timeout=timeout)
    if result.get("code") == "ASSET_RENAME_TIMEOUT":
        result["verification_commands"] = {
            "source": _asset_exists_command(state, source_path),
            "destination": _asset_exists_command(state, dest_path),
        }
        raise AppError(
            result["code"],
            result["error"],
            exit_code=4,
            suggestion=result.get("suggestion"),
            details=result,
        )
    raise_for_legacy_error(result, default_code="ASSET_RENAME_FAILED")
    output(result, state)


def _asset_exists_command(state: AppState, asset_path: str) -> str:
    """Build a verification command pinned to the selected editor."""
    parts = ["ue-cli", "--output", state.output_mode]
    if state.session.project_path:
        parts.extend(["--project", state.session.project_path])
    parts.extend(["--port", str(state.session.port), "asset", "exists", asset_path])
    return sp.list2cmdline(parts) if sys.platform == "win32" else shlex.join(parts)


@asset_group.command("property")
@click.argument("asset_path")
@click.argument("expression")
@handle_error
@click.pass_obj
def asset_property(state: AppState, asset_path, expression):
    """Get or set a property on a UAsset.

    Read:  asset property <path> PropertyName
    Write: asset property <path> PropertyName=NewValue

    \b
    Examples:
        asset property /Game/M_Water BlendMode           # read
        asset property /Game/M_Water BlendMode=Translucent  # write
    """
    from cli_anything.unreal.core.assets import get_asset_property, set_asset_property

    api = require_editor(state)

    if "=" in expression:
        prop_name, raw_value = expression.split("=", 1)
        result = set_asset_property(api, asset_path, prop_name, parse_property_value(raw_value))
        error_code = "ASSET_PROPERTY_WRITE_FAILED"
    else:
        result = get_asset_property(api, asset_path, expression)
        error_code = "ASSET_PROPERTY_READ_FAILED"

    if isinstance(result, dict) and result.get("error"):
        raise AppError(
            error_code,
            str(result["error"]),
            exit_code=3,
            details=result,
        )

    output(result, state)
