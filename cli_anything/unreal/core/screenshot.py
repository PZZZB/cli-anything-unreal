"""core/screenshot.py — Screenshot capture and comparison.

Requires a running UE editor with Remote Control API. Capture uses **one**
implementation: on **Windows**, the CLI process grabs the main Unreal Editor
window with GDI (``PrintWindow`` + ``GetDIBits``) and writes PNG via Pillow —
no C++ plugin. Output path:
  {ProjectDir}/Saved/Screenshots/WindowsEditor/{filename}.png

Also provides CVar A/B testing, atlas layout, Pillow compare/compress — these
are orchestration around the same capture primitive.
"""

import math
import os
import sys
import time
from pathlib import Path
from typing import Optional

from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

# Default screenshot delay to allow viewport to render
_DEFAULT_RENDER_DELAY = 1.0

def _build_ensure_viewport_realtime_py() -> str:
    """Editor Python: clear Remote-Desktop realtime lock + subsystem override.

    RDP / remote sessions register ``RealtimeOverride`` "Remote Desktop" when
    ``UEditorPerformanceSettings.b_disable_realtime_viewports_in_remote_sessions``
    is True (``SLevelViewport::OnPerformanceSettingsChanged``). Calling only
    ``editor_set_viewport_realtime(True)`` removes a *different* override
    ("Level Editor Subsystem Realtime Override") and does not clear "Remote Desktop".

    We toggle the performance setting with ``PropertyAccessChangeNotifyMode.ALWAYS`` so
    ``OnSettingChanged`` fires and viewports remove the RDP override, then force realtime
    on **every** viewport config key (``get_viewport_config_keys``) plus the default
    ``editor_set_viewport_realtime(True)`` call. The single-parameter API alone only hits
    one target viewport; others can stay off while the RDP tooltip is already gone.
    """
    # Use only double-quoted Python string literals inside ``inner`` so ``repr(inner)`` prefers
    # single-quote wrapping: ``exec('...')``. ``exec_python`` wraps in ``py "..."`` and escapes
    # every ``"``; if ``repr`` had emitted ``exec("...")``, those delimiters break after escaping.
    inner = r"""try:
    _p = unreal.load_object(None, "/Script/UnrealEd.Default__EditorPerformanceSettings")
    if _p is None:
        _cls = getattr(unreal, "EditorPerformanceSettings", None)
        if _cls is not None:
            _p = unreal.get_default_object(_cls)
    if _p is not None:
        _cn = getattr(unreal, "PropertyAccessChangeNotifyMode", None)
        _prop = "bDisableRealtimeViewportsInRemoteSessions"
        try:
            if _cn is not None:
                _p.set_editor_property(_prop, False, _cn.ALWAYS)
            else:
                _p.set_editor_property(_prop, False)
        except Exception:
            pass
except Exception:
    pass
try:
    _le = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    _keys_fn = getattr(_le, "get_viewport_config_keys", None)
    if _keys_fn is not None:
        for _k in _keys_fn():
            try:
                _le.editor_set_viewport_realtime(True, _k)
            except Exception:
                pass
    try:
        _le.editor_set_viewport_realtime(True)
    except Exception:
        pass
except Exception:
    pass"""
    return f"import unreal; exec({inner!r})"


def _ensure_editor_viewport_realtime(api: UEEditorAPI, timeout: float = 3.0) -> bool:
    """Ensure level viewport ticks: clear Remote Desktop realtime override when possible, then subsystem toggle."""
    try:
        py_result = api.exec_python(_build_ensure_viewport_realtime_py(), timeout=timeout)
        return "error" not in py_result
    except Exception:
        return False


def _refresh_editor_viewports(api: UEEditorAPI, timeout: float = 3.0) -> dict:
    """Best-effort viewport refresh before screenshot capture."""
    steps = {"realtime": False, "invalidate": False, "redraw_console": False}

    steps["realtime"] = _ensure_editor_viewport_realtime(api, timeout=timeout)

    # 1) Python API invalidate (editor-side viewport refresh hint)
    try:
        py_result = api.exec_python(
            "import unreal; "
            "unreal.EditorLevelLibrary.editor_invalidate_viewports()",
            timeout=timeout,
        )
        steps["invalidate"] = "error" not in py_result
    except Exception:
        steps["invalidate"] = False

    # 2) Console redraw (forces redraw request)
    try:
        redraw_result = api.exec_console("RedrawAllViewports", timeout=timeout)
        steps["redraw_console"] = "error" not in redraw_result
    except Exception:
        steps["redraw_console"] = False

    return steps


def _get_active_viewport_rect(api: UEEditorAPI, timeout: float | None) -> tuple[int, int, int, int] | None:
    bounds_script = (
        "import unreal\n"
        "try:\n"
        "    bounds = unreal.CliAnythingBridgeLibrary.get_active_viewport_screen_bounds()\n"
        "    unreal.log(f'VIEWPORT_BOUNDS:{bounds.x},{bounds.y},{bounds.z},{bounds.w}')\n"
        "except Exception:\n"
        "    pass"
    )
    bounds_res = api.exec_python_ex(bounds_script, timeout=timeout)
    for log_item in bounds_res.get("LogOutput", []):
        line = log_item.get("Output", "")
        if line.startswith("VIEWPORT_BOUNDS:"):
            parts = line.split(":", 1)[1].split(",")
            try:
                x, y, w, h = map(int, parts)
                if w > 0 and h > 0:
                    return (x, y, x + w, y + h)
            except ValueError:
                pass
    return None


def _capture_viewport_png_raw(
    api: UEEditorAPI,
    filename: str,
    project_dir: str | None,
    wait_timeout: float,
    res_x: int,
    res_y: int,
    delay: float,
    refresh: bool = True,
    foreground: bool = True,
    rc_timeout: float | None = None,
    viewport_rect: tuple[int, int, int, int] | None = None,
    use_viewport_bounds: bool = True,
) -> dict:
    """Capture the main editor window to PNG from the CLI host (Windows GDI + Pillow).

    ``res_x`` / ``res_y`` are reserved for API compatibility; capture uses the
    current editor window size.
    """
    if sys.platform != "win32":
        return {
            "status": "error",
            "message": "Editor window capture is only implemented on Windows (CLI host).",
            "foreground_ok": False,
            "refresh": {},
        }

    foreground_ok = api.bring_to_foreground() if foreground else False
    refresh_result = _refresh_editor_viewports(api, timeout=rc_timeout or 3.0) if refresh else {}

    time.sleep(delay)

    save_dir = (
        Path(project_dir) / "Saved" / "Screenshots" / "WindowsEditor"
        if project_dir
        else Path.cwd()
    )
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"{filename}.png"

    hwnd = api.find_editor_window_hwnd()
    if not hwnd:
        return {
            "status": "error",
            "message": "Could not find Unreal Editor window handle (is the editor running?).",
            "foreground_ok": foreground_ok,
            "refresh": refresh_result,
        }

    if use_viewport_bounds and viewport_rect is None:
        viewport_rect = _get_active_viewport_rect(api, timeout=rc_timeout)

    from cli_anything.unreal.core.win32_editor_capture import capture_hwnd_to_png

    if not capture_hwnd_to_png(hwnd, save_path, crop_rect=viewport_rect):
        return {
            "status": "error",
            "message": (
                "GDI capture failed (install Pillow if missing: pip install Pillow)."
            ),
            "foreground_ok": foreground_ok,
            "refresh": refresh_result,
        }

    size = save_path.stat().st_size
    return {
        "status": "ok",
        "path_raw": str(save_path),
        "size_raw": size,
        "capture_mode": "win32_gdi_cli",
        "foreground_ok": foreground_ok,
        "refresh": refresh_result,
    }


def take_screenshot(
    api: UEEditorAPI,
    filename: str = "screenshot",
    project_dir: str | None = None,
    wait_timeout: float = 15.0,
    res_x: int = 1920,
    res_y: int = 1080,
    delay: float = _DEFAULT_RENDER_DELAY,
) -> dict:
    """Capture the main Unreal Editor window to PNG (then optional JPEG for agents).

    Args:
        api: Connected UEEditorAPI instance.
        filename: Output filename (without extension).
        project_dir: Project directory (for finding saved screenshots).
        wait_timeout: Unused (capture is synchronous); kept for API compatibility.
        res_x: Unused; capture uses the live editor window size.
        res_y: Unused; capture uses the live editor window size.
        delay: Seconds for viewport to render before capture.

    Returns:
        {"path": str, "size": int} or {"error": str}
    """
    raw = _capture_viewport_png_raw(
        api, filename, project_dir, wait_timeout, res_x, res_y, delay
    )
    if raw.get("status") == "ok":
        screenshot_path = raw["path_raw"]
        size = raw["size_raw"]
        compressed = compress_for_agent(screenshot_path)
        response = {
            "status": "ok",
            "read_this": compressed or screenshot_path,
            "path_raw": screenshot_path,
            "size_raw": size,
            "capture_mode": raw["capture_mode"],
            "refresh": raw["refresh"],
        }
        if compressed:
            response["compressed"] = compressed
            response["size_compressed"] = Path(compressed).stat().st_size
        else:
            response["compress_hint"] = (
                "Auto-compress unavailable (Pillow not installed). "
                "Returning raw PNG. Install with: pip install Pillow"
            )
        return response
    return raw



def combine_images_to_atlas(
    image_paths: list[str],
    output_path: str,
    *,
    cols: int | None = None,
    padding: int = 6,
    background: tuple[int, int, int] = (28, 28, 32),
    label_frames: bool = True,
) -> dict:
    """Lay out multiple same-project screenshots into one PNG grid (sprite sheet).

    Intended for feeding a single image to an LLM to infer motion across time.

    Args:
        image_paths: Ordered paths to PNG/JPG frames.
        output_path: Destination .png path.
        cols: Number of columns; ``None`` → ceil(sqrt(n)).
        padding: Gap in pixels between cells and around the border.
        background: RGB fill behind cells.
        label_frames: Draw small ``i/n`` index on each cell.

    Returns:
        ``{"status": "ok", "path": str, "size": int, "cols": int, "rows": int}``
        or ``{"error": str}``.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return {
            "error": "Pillow is required for atlas layout. Install: pip install Pillow",
        }

    paths = [p for p in image_paths if p and Path(p).exists()]
    n = len(paths)
    if n == 0:
        return {"error": "No valid image paths to combine"}

    images: list[Image.Image] = []
    for p in paths:
        try:
            img = Image.open(p)
            if img.mode in ("RGBA", "P"):
                rgba = img.convert("RGBA")
                bg = Image.new("RGB", rgba.size, background)
                bg.paste(rgba, mask=rgba.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            images.append(img)
        except Exception as exc:
            return {"error": f"Failed to load {p}: {exc}"}

    cell_w = max(im.width for im in images)
    cell_h = max(im.height for im in images)

    if cols is None or cols < 1:
        cols = max(min(n, int(math.ceil(math.sqrt(n)))), 1)
    cols = min(cols, n)
    rows = (n + cols - 1) // cols

    atlas_w = cols * cell_w + (cols + 1) * padding
    atlas_h = rows * cell_h + (rows + 1) * padding
    atlas = Image.new("RGB", (atlas_w, atlas_h), background)
    draw = ImageDraw.Draw(atlas)
    try:
        font = ImageFont.truetype("arial.ttf", max(14, cell_h // 28))
    except Exception:
        font = ImageFont.load_default()

    for idx, im in enumerate(images):
        r, c = divmod(idx, cols)
        x0 = padding + c * (cell_w + padding)
        y0 = padding + r * (cell_h + padding)
        px = x0 + (cell_w - im.width) // 2
        py = y0 + (cell_h - im.height) // 2
        atlas.paste(im, (px, py))
        if label_frames:
            tag = f"{idx + 1}/{n}"
            try:
                bbox = draw.textbbox((0, 0), tag, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except AttributeError:
                tw, th = draw.textsize(tag, font=font)
            draw.rectangle(
                (x0 + 2, y0 + 2, x0 + tw + 8, y0 + th + 8),
                fill=(0, 0, 0),
                outline=(200, 200, 80),
            )
            draw.text((x0 + 5, y0 + 4), tag, fill=(255, 220, 120), font=font)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(str(out), "PNG", optimize=True)
    size = out.stat().st_size
    return {
        "status": "ok",
        "path": str(out.resolve()),
        "size": size,
        "cols": cols,
        "rows": rows,
        "cell": [cell_w, cell_h],
    }


def capture_screenshot_atlas(
    api: UEEditorAPI,
    frame_count: int,
    *,
    interval: float = 0.5,
    cols: int | None = None,
    filename_prefix: str = "motion_seq",
    output_atlas: str | None = None,
    project_dir: str | None = None,
        res_x: int = 1920,
        res_y: int = 1080,
        delay: float = _DEFAULT_RENDER_DELAY,
        wait_timeout: float = 15.0,
        padding: int = 6,
        label_frames: bool = True,
        jpeg_for_llm: bool = True,
        max_atlas_edge: int = 4096,
        jpeg_quality: int = 85,
    ) -> dict:
    """Capture several editor-window frames spaced in time, then merge into one PNG atlas.

    Args:
        api: Connected editor API.
        frame_count: Number of sequential screenshots.
        interval: Sleep seconds *between* completed captures (lets animation advance).
        cols: Atlas columns; ``None`` → auto grid.
        filename_prefix: Stem for per-frame files ( …_000, …_001 ).
        output_atlas: Output .png path; default under project's Screenshots/WindowsEditor.
        project_dir: UE project directory (for finding/writing screenshots).
        res_x, res_y: Unused (compatibility); native capture uses editor window size.
        delay: Seconds to wait for rendering before each capture.
        wait_timeout: Unused (synchronous capture); kept for API compatibility.
        padding, label_frames: Passed to ``combine_images_to_atlas``.
        jpeg_for_llm: Also write a downscaled JPEG next to the atlas.
        max_atlas_edge: Max dimension for JPEG downsampling.
        jpeg_quality: JPEG quality.

    Returns:
        Dict with ``atlas_path``, ``frames``, ``grid``, optional ``atlas_jpg``.
    """
    if frame_count < 1:
        return {"error": "frame_count must be >= 1"}

    if output_atlas:
        atlas_path = str(Path(output_atlas).resolve())
    elif project_dir:
        atlas_path = str(
            Path(project_dir)
            / "Saved"
            / "Screenshots"
            / "WindowsEditor"
            / f"{filename_prefix}_motion_sheet.png"
        )
    else:
        atlas_path = str(Path.cwd() / f"{filename_prefix}_motion_sheet.png")

    frame_results: list[dict] = []
    frame_paths: list[str] = []
    prep_refresh: dict = {}

    try:
        # Dynamic / multi-frame: keep realtime on but avoid repeated refresh calls
        # and repeated viewport-bound queries, which can each wait on Remote Control.
        prep_refresh = {"realtime": _ensure_editor_viewport_realtime(api, timeout=min(wait_timeout, 1.0))}
        viewport_rect = _get_active_viewport_rect(api, timeout=min(wait_timeout, 1.0))

        for i in range(frame_count):
            fname = f"{filename_prefix}_{i:03d}"
            shot = _capture_viewport_png_raw(
                api,
                fname,
                project_dir,
                wait_timeout,
                res_x,
                res_y,
                delay,
                refresh=False,
                foreground=False,
                rc_timeout=wait_timeout,
                viewport_rect=viewport_rect,
                use_viewport_bounds=False,
            )
            frame_results.append({"index": i, **shot})
            pr = shot.get("path_raw")
            if pr and Path(pr).exists():
                frame_paths.append(pr)
            else:
                err = shot.get("error") or shot.get("message") or shot.get("hint") or str(shot)
                return {
                    "error": f"Frame {i} capture failed: {err}",
                    "partial_frames": frame_paths,
                    "frame_results": frame_results,
                }
            if i < frame_count - 1 and interval > 0:
                _ensure_editor_viewport_realtime(api, timeout=wait_timeout)
                time.sleep(interval)

    except Exception as e:
        return {
            "error": f"Exception during sequence capture: {e}",
            "partial_frames": frame_paths,
            "frame_results": frame_results,
        }

    if len(frame_paths) != frame_count:
        return {
            "error": f"Expected {frame_count} files, found {len(frame_paths)}",
            "frame_results": frame_results,
            "frame_paths": frame_paths,
        }

    merged = combine_images_to_atlas(
        frame_paths,
        atlas_path,
        cols=cols,
        padding=padding,
        label_frames=label_frames,
    )
    if merged.get("error"):
        return {**merged, "frame_paths": frame_paths, "frame_results": frame_results}

    out: dict = {
        "status": "ok",
        "atlas_path": merged["path"],
        "atlas_size": merged["size"],
        "grid": {"cols": merged["cols"], "rows": merged["rows"], "cell": merged["cell"]},
        "frame_paths": frame_paths,
        "frame_count": frame_count,
        "viewport_prep": prep_refresh,
    }

    if jpeg_for_llm:
        jpg = compress_for_agent(
            merged["path"],
            max_edge=max_atlas_edge,
            quality=jpeg_quality,
            output_path=str(Path(merged["path"]).with_suffix(".jpg")),
        )
        if jpg:
            out["atlas_jpg"] = jpg
            out["atlas_jpg_size"] = Path(jpg).stat().st_size
            out["compressed"] = jpg
            out["size_compressed"] = Path(jpg).stat().st_size
            out["read_this"] = jpg
        else:
            out["read_this"] = merged["path"]
            out["compress_hint"] = "Motion-sheet JPEG skipped (Pillow missing or compress failed)"
    else:
        out["read_this"] = merged["path"]

    out["llm_context"] = (
        "This is a time-ordered dynamic preview: each cell is the viewport at a later time, "
        "arranged left-to-right then top-to-bottom (see i/N labels). "
        "Compare neighboring cells to infer motion, waves, particles, or other temporal effects."
    )
    out["cli_command"] = "screenshot dynamic [-n FRAMES] [-i INTERVAL]"

    return out


def compress_for_agent(
    png_path: str,
    max_edge: int = 1920,
    quality: int = 85,
    output_path: str | None = None,
) -> str | None:
    """Compress a screenshot to JPEG for AI Agent vision analysis.

    Args:
        png_path: Path to source PNG file.
        max_edge: Maximum dimension (width or height).
        quality: JPEG quality (1-100).
        output_path: Output path (defaults to same name with .jpg).

    Returns:
        Path to compressed file, or None if compression failed.
    """
    try:
        from PIL import Image
    except ImportError:
        return None

    try:
        img = Image.open(png_path)

        # Resize if needed
        w, h = img.size
        if w > max_edge or h > max_edge:
            ratio = min(max_edge / w, max_edge / h)
            new_size = (int(w * ratio), int(h * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        # Convert to RGB (JPEG doesn't support alpha)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Save as JPEG
        if output_path is None:
            output_path = str(Path(png_path).with_suffix(".jpg"))

        img.save(output_path, "JPEG", quality=quality, optimize=True)
        return output_path

    except Exception:
        return None
