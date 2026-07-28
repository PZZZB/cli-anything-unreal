"""commands/screenshot.py — Screenshot capture commands."""

import click

from cli_anything.unreal.commands import AppError, AppState, handle_error, output, require_editor


@click.group("screenshot")
def screenshot_group():
    """Screenshot capture and comparison (requires running editor)."""
    pass


def _raise_capture_error(result: dict) -> None:
    if not isinstance(result, dict) or not (
        result.get("status") == "error" or result.get("error")
    ):
        return
    timed_out = bool(result.get("timed_out"))
    raise AppError(
        "SCREENSHOT_CAPTURE_TIMEOUT" if timed_out else "SCREENSHOT_CAPTURE_FAILED",
        result.get("message") or result.get("error") or "Screenshot capture failed.",
        exit_code=3,
        details=result,
    )


@screenshot_group.command("capture")
@click.option("--path", "output_path", default=None,
              help="Output file path, or an existing directory combined with --filename.")
@click.option("--filename", default="screenshot",
              help="Output filename or stem when --path is a directory, or legacy project screenshot name.")
@click.option("--no-compress", is_flag=True, help="Return raw PNG instead of compressed JPG")
@click.option(
    "--include-ui",
    is_flag=True,
    help="Include composed viewport UI such as stat HUD and Slate/Canvas overlays.",
)
@handle_error
@click.pass_obj
def screenshot_static(state: AppState, output_path, filename, no_compress, include_ui):
    """Take a single static screenshot. Returns compressed JPG by default.

    Use --path for a full file path (e.g., F:/Test574/round7_result.png),
    or an existing directory together with --filename.
    Use --filename for a name prefix only (legacy mode).
    """
    from cli_anything.unreal.core.screenshot import take_screenshot

    if output_path:
        import os
        ext = os.path.splitext(output_path)[1].lower()
        if ext == ".png":
            no_compress = True

    api = require_editor(state)
    result = take_screenshot(
        api, filename,
        project_dir=state.session.project_dir,
        output_path=output_path,
        jpeg_for_llm=not no_compress,
        include_ui=include_ui,
    )
    _raise_capture_error(result)

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
        delay=0.1,
        wait_timeout=3.0,
        padding=6,
        label_frames=True,
        jpeg_for_llm=not no_compress,
        max_atlas_edge=1920,
        jpeg_quality=85,
    )
    _raise_capture_error(result)
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
