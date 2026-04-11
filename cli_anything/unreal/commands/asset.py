"""commands/asset.py — Asset operations commands."""

import click

from cli_anything.unreal.commands import AppState, handle_error, output, require_editor, require_project


@click.group("asset")
def asset_group():
    """Asset operations (exists, delete, duplicate, info, etc.)."""
    pass


@asset_group.command("list")
@click.option("--ext", default="", help="Filter by extension (e.g., .uasset)")
@click.option("--filter", "path_filter", default="", help="Filter by path substring")
@click.option("--depth", default=5, help="Max directory depth")
@handle_error
@click.pass_obj
def asset_list(state: AppState, ext, path_filter, depth):
    """List content assets in the project."""
    from cli_anything.unreal.core.project import list_content

    require_project(state)
    assets = list_content(state.session.project_dir, filter_ext=ext, filter_path=path_filter, max_depth=depth)

    if state.json_output:
        output({"assets": assets, "count": len(assets)}, state)
    else:
        state.skin.info(f"Found {len(assets)} assets")
        if assets:
            headers = ["Name", "Extension", "Content Path"]
            rows = [[a["name"], a["ext"], a.get("content_path", "")] for a in assets]
            state.skin.table(headers, rows)


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
    output(result, state)


@asset_group.command("rename")
@click.argument("source_path")
@click.argument("dest_path")
@handle_error
@click.pass_obj
def asset_rename_cmd(state: AppState, source_path, dest_path):
    """Rename/move an asset to a new path.

    Fails if destination already exists.

    Example: asset rename /Game/M_Old /Game/M_New
    """
    from cli_anything.unreal.core.assets import asset_rename

    api = require_editor(state)
    result = asset_rename(api, source_path, dest_path,
                          project_dir=state.session.project_dir)
    output(result, state)


@asset_group.command("info")
@click.argument("asset_path")
@click.option("--filter", "prop_filter", default=None,
              help="Case-insensitive substring filter for property names.")
@click.option("--property", "prop_name", default=None,
              help="Get full metadata for a specific property (legacy C++ mode).")
@handle_error
@click.pass_obj
def asset_info_cmd(state: AppState, asset_path, prop_filter, prop_name):
    """Describe a UAsset with Python-safe property names.

    Returns snake_case property names and current values that can be used
    directly in Python scripts. Use --filter to search for specific properties.
    Use --property for legacy C++ reflection metadata (PascalCase names).
    """
    if prop_name:
        # Legacy mode: use C++ describe API for full metadata on a single property
        from cli_anything.unreal.core.assets import describe_asset
        api = require_editor(state)
        result = describe_asset(api, asset_path, prop_name)
    else:
        # New mode: Python runtime inspection with snake_case names
        from cli_anything.unreal.core.script_runner import inspect_instance
        api = require_editor(state)
        result = inspect_instance(api, asset_path, mode="asset",
                                  prop_filter=prop_filter)
    output(result, state)


@asset_group.command("get-property")
@click.argument("asset_path")
@click.argument("property_name")
@handle_error
@click.pass_obj
def asset_get_property(state: AppState, asset_path, property_name):
    """Get a property on a UAsset in the Content Browser."""
    from cli_anything.unreal.core.assets import get_asset_property

    api = require_editor(state)
    result = get_asset_property(api, asset_path, property_name)
    output(result, state)


@asset_group.command("set-property")
@click.argument("asset_path")
@click.argument("property_name")
@click.argument("new_value")
@handle_error
@click.pass_obj
def asset_set_property(state: AppState, asset_path, property_name, new_value):
    """Set a property on a UAsset in the Content Browser."""
    from cli_anything.unreal.core.assets import set_asset_property

    api = require_editor(state)
    result = set_asset_property(api, asset_path, property_name, new_value)
    output(result, state)
