"""commands/screenshot.py — Screenshot capture commands."""

import click

from cli_anything.unreal.commands import AppState, handle_error, output, require_editor


@click.group("screenshot")
def screenshot_group():
    """Screenshot capture and comparison (requires running editor)."""
    pass


@screenshot_group.command("capture")
@click.option("--filename", default="screenshot", help="Output filename (no extension)")
@click.option("--no-compress", is_flag=True, help="Return raw PNG instead of compressed JPG")
@handle_error
@click.pass_obj
def screenshot_static(state: AppState, filename, no_compress):
    """Take a single static screenshot. Returns compressed JPG by default."""
    from cli_anything.unreal.core.screenshot import take_screenshot

    api = require_editor(state)
    result = take_screenshot(
        api, filename,
        project_dir=state.session.project_dir,
    )

    # Default: same path agents read — JPG from compress_for_agent when not --no-compress
    if result.get("status") == "ok" or result.get("path_raw"):
        if no_compress:
            result["default_path"] = result.get("path_raw") or result.get("read_this")
        else:
            result["default_path"] = result.get("read_this") or result.get("path_raw")

    output(result, state)


def _exec_screenshot_dynamic(state: AppState, frames, interval, no_compress):
    """Implementation for ``screenshot capture-sequence``."""
    from cli_anything.unreal.core.screenshot import capture_screenshot_atlas

    api = require_editor(state)
    result = capture_screenshot_atlas(
        api,
        frames,
        interval=interval,
        cols=None,
        filename_prefix="motion_seq",
        output_atlas=None,
        project_dir=state.session.project_dir,
        res_x=1920,
        res_y=1080,
        delay=1.0,
        wait_timeout=15.0,
        padding=6,
        label_frames=True,
        jpeg_for_llm=not no_compress,
        max_atlas_edge=1920,
        jpeg_quality=85,
    )
    if result.get("status") == "ok":
        if no_compress:
            result["default_path"] = result.get("atlas_path") or result.get("read_this")
        else:
            result["default_path"] = result.get("read_this") or result.get("atlas_path")
    output(result, state)


@screenshot_group.command(
    "capture-sequence",
    help=(
        "Viewport frames over time merged into one atlas; "
        "default primary output is compressed JPG like static screenshot."
    ),
)
@click.option(
    "-n",
    "--frames",
    type=int,
    default=6,
    show_default=True,
    help="How many timed viewport captures to merge into one sheet",
)
@click.option(
    "-i",
    "--interval",
    type=float,
    default=0.5,
    show_default=True,
    help="Seconds to wait after each capture (scene time advances)",
)
@click.option(
    "--no-compress",
    is_flag=True,
    help="Return raw PNG atlas only (same as static screenshot --no-compress)",
)
@handle_error
@click.pass_obj
def screenshot_dynamic(state: AppState, frames, interval, no_compress):
    _exec_screenshot_dynamic(state, frames, interval, no_compress)
