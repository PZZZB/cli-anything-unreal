"""core/screenshot.py — Screenshot capture and comparison.

Provides viewport screenshot, high-res capture, CVar A/B testing,
and image compression for AI Agent vision analysis.
Requires a running UE editor with Remote Control API.

Screenshot method:
  Uses AutomationBlueprintFunctionLibrary.TakeHighResScreenshot via
  /Script/FunctionalTesting module. Screenshots saved to:
  {ProjectDir}/Saved/Screenshots/WindowsEditor/{filename}.png
"""

import math
import os
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


def _ensure_editor_viewport_realtime(api: UEEditorAPI) -> bool:
    """Ensure level viewport ticks: clear Remote Desktop realtime override when possible, then subsystem toggle."""
    try:
        py_result = api.exec_python(_build_ensure_viewport_realtime_py())
        return "error" not in py_result
    except Exception:
        return False


def _refresh_editor_viewports(api: UEEditorAPI) -> dict:
    """Best-effort viewport refresh before screenshot capture."""
    steps = {"realtime": False, "invalidate": False, "redraw_console": False}

    steps["realtime"] = _ensure_editor_viewport_realtime(api)

    # 1) Python API invalidate (editor-side viewport refresh hint)
    try:
        py_result = api.exec_python(
            "import unreal; "
            "unreal.EditorLevelLibrary.editor_invalidate_viewports()"
        )
        steps["invalidate"] = "error" not in py_result
    except Exception:
        steps["invalidate"] = False

    # 2) Console redraw (forces redraw request)
    try:
        redraw_result = api.exec_console("RedrawAllViewports")
        steps["redraw_console"] = "error" not in redraw_result
    except Exception:
        steps["redraw_console"] = False

    return steps


_NOISY_SCREENSHOT_CVARS = {
    "r.TemporalAA.Upsampling": "0",
    "r.MotionBlurQuality": "0",
    "r.DepthOfFieldQuality": "0",
    "r.LensFlareQuality": "0",
    "r.BloomQuality": "0",
}


def _noisy_scrub_begin(api: UEEditorAPI) -> dict[str, str]:
    """Temporarily disable bloom/TAA/etc. for crisp captures. Returns values to restore."""
    saved: dict[str, str] = {}
    for cvar, value in _NOISY_SCREENSHOT_CVARS.items():
        try:
            old_val = api.get_cvar(cvar)
            saved[cvar] = old_val
            api.set_cvar(cvar, value)
        except Exception:
            pass
    time.sleep(0.3)
    return saved


def _noisy_scrub_end(api: UEEditorAPI, saved_cvars: dict[str, str]) -> None:
    for cvar, value in saved_cvars.items():
        try:
            api.set_cvar(cvar, str(value))
        except Exception:
            pass


def _capture_viewport_png_raw(
    api: UEEditorAPI,
    filename: str,
    project_dir: str | None,
    wait_timeout: float,
    res_x: int,
    res_y: int,
    delay: float,
) -> dict:
    """Run TakeHighResScreenshot and wait for PNG on disk. No CVar scrub, no JPEG."""
    foreground_ok = api.bring_to_foreground()
    refresh_result = _refresh_editor_viewports(api)

    api_result = api.take_screenshot(
        filename=filename,
        res_x=res_x,
        res_y=res_y,
        delay=delay,
    )
    if "error" in api_result:
        return api_result

    time.sleep(delay + 0.3)
    screenshot_path = _find_screenshot(
        filename,
        project_dir,
        max(2.0, wait_timeout / 2.0),
    )

    if screenshot_path and Path(screenshot_path).exists():
        size = Path(screenshot_path).stat().st_size
        return {
            "status": "ok",
            "path_raw": screenshot_path,
            "size_raw": size,
            "capture_mode": "foreground_then_refresh",
            "foreground_ok": foreground_ok,
            "refresh": refresh_result,
        }

    screenshot_path = None
    attempts = 2

    for attempt_idx in range(attempts):
        foreground_ok = api.bring_to_foreground() or foreground_ok
        if attempt_idx == 0:
            _refresh_editor_viewports(api)
        time.sleep(0.5)

        api_result = api.take_screenshot(
            filename=filename,
            res_x=res_x,
            res_y=res_y,
            delay=delay + (0.3 * attempt_idx),
        )

        if "error" in api_result:
            return api_result

        time.sleep(delay + 0.5 + (0.3 * attempt_idx))

        screenshot_path = _find_screenshot(
            filename,
            project_dir,
            max(2.0, wait_timeout / attempts),
        )
        if screenshot_path and Path(screenshot_path).exists():
            break

    if screenshot_path and Path(screenshot_path).exists():
        size = Path(screenshot_path).stat().st_size
        return {
            "status": "ok",
            "path_raw": screenshot_path,
            "size_raw": size,
            "capture_mode": "focus_fallback",
            "foreground_ok": foreground_ok,
            "refresh": refresh_result,
        }

    return {
        "status": "requested",
        "message": "Screenshot requested but file not found yet. "
        "It may appear shortly in Saved/Screenshots/WindowsEditor/",
        "foreground_ok": foreground_ok,
        "attempts": attempts,
        "hint": (
            "The editor window may not have had focus. "
            "Screenshots require the viewport to be rendering (window visible and focused)."
            if not foreground_ok
            else None
        ),
        "refresh": refresh_result,
        "api_result": api_result,
    }


def take_screenshot(
    api: UEEditorAPI,
    filename: str = "screenshot",
    disable_noisy: bool = True,
    project_dir: str | None = None,
    wait_timeout: float = 15.0,
    res_x: int = 1920,
    res_y: int = 1080,
    delay: float = _DEFAULT_RENDER_DELAY,
) -> dict:
    """Take a screenshot of the editor viewport.

    Args:
        api: Connected UEEditorAPI instance.
        filename: Output filename (without extension).
        disable_noisy: If True, temporarily disable noisy effects.
        project_dir: Project directory (for finding saved screenshots).
        wait_timeout: Max seconds to wait for file to appear on disk.
        res_x: Screenshot width.
        res_y: Screenshot height.
        delay: Seconds for viewport to render before capture.

    Returns:
        {"path": str, "size": int} or {"error": str}
    """
    saved_cvars: dict[str, str] = {}
    if disable_noisy:
        saved_cvars = _noisy_scrub_begin(api)

    try:
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
    finally:
        if disable_noisy and saved_cvars:
            _noisy_scrub_end(api, saved_cvars)



def compare_screenshots(
    api: UEEditorAPI,
    image_a: str,
    image_b: str,
    tolerance: str = "Low",
) -> dict:
    """Compare two screenshots for differences.

    Uses pixel-level comparison via Pillow if available,
    otherwise reports basic file size comparison.

    Args:
        api: UEEditorAPI (unused currently, kept for API compat).
        image_a: Path to first image.
        image_b: Path to second image.
        tolerance: Comparison tolerance (Zero, Low, Medium, High).

    Returns:
        {"similar": bool, "difference": float, ...}
    """
    try:
        from PIL import Image, ImageChops
        import math

        img_a = Image.open(image_a).convert("RGB")
        img_b = Image.open(image_b).convert("RGB")

        # Resize if different dimensions
        if img_a.size != img_b.size:
            img_b = img_b.resize(img_a.size, Image.LANCZOS)

        diff = ImageChops.difference(img_a, img_b)
        pixels = list(diff.getdata())
        total_diff = sum(sum(p) for p in pixels)
        max_diff = len(pixels) * 255 * 3
        difference_pct = (total_diff / max_diff) * 100 if max_diff > 0 else 0

        thresholds = {"Zero": 0, "Low": 1.0, "Medium": 5.0, "High": 15.0}
        threshold = thresholds.get(tolerance, 1.0)

        return {
            "similar": difference_pct <= threshold,
            "difference_percent": round(difference_pct, 4),
            "tolerance": tolerance,
            "threshold_percent": threshold,
            "image_a": image_a,
            "image_b": image_b,
        }
    except ImportError:
        # Fallback: compare file sizes
        size_a = Path(image_a).stat().st_size
        size_b = Path(image_b).stat().st_size
        size_diff = abs(size_a - size_b) / max(size_a, size_b) * 100

        return {
            "similar": size_diff < 5,
            "size_difference_percent": round(size_diff, 2),
            "note": "Pillow not installed; comparison is file-size only",
            "image_a": image_a,
            "image_b": image_b,
        }


def screenshot_with_cvar(
    api: UEEditorAPI,
    cvar_name: str,
    values: list[str],
    labels: list[str] | None = None,
    filename_prefix: str = "cvar_test",
    settle_time: float = 1.0,
    project_dir: str | None = None,
) -> dict:
    """Take screenshots with different CVar values for A/B comparison.

    Args:
        api: Connected UEEditorAPI instance.
        cvar_name: CVar name to toggle.
        values: List of values to test.
        labels: Optional labels for each value.
        filename_prefix: Filename prefix for screenshots.
        settle_time: Seconds to wait after CVar change before screenshot.
        project_dir: Project directory.

    Returns:
        {"screenshots": [{"label": str, "path": str, "cvar_value": str}, ...]}
    """
    if labels is None:
        labels = [f"value_{v}" for v in values]

    if len(labels) != len(values):
        return {"error": "labels and values must have the same length"}

    # Save original CVar value
    original_value = api.get_cvar(cvar_name)

    screenshots = []
    try:
        for i, (value, label) in enumerate(zip(values, labels)):
            # Set CVar
            api.set_cvar(cvar_name, value)

            # Wait for rendering to settle
            time.sleep(settle_time)

            # Take screenshot with extra delay for rendering
            fname = f"{filename_prefix}_{label}"
            result = take_screenshot(
                api,
                filename=fname,
                disable_noisy=True,
                project_dir=project_dir,
                delay=settle_time + 0.5,
            )

            screenshots.append({
                "label": label,
                "cvar_value": value,
                **result,
            })

    finally:
        # Restore original CVar
        if original_value:
            api.set_cvar(cvar_name, str(original_value))

    # Compare consecutive screenshots
    comparisons = []
    for i in range(len(screenshots) - 1):
        a = screenshots[i].get("path", "")
        b = screenshots[i + 1].get("path", "")
        if a and b and Path(a).exists() and Path(b).exists():
            comp = compare_screenshots(api, a, b)
            comparisons.append({
                "a": screenshots[i]["label"],
                "b": screenshots[i + 1]["label"],
                **comp,
            })

    return {
        "cvar": cvar_name,
        "screenshots": screenshots,
        "comparisons": comparisons,
    }


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
    disable_noisy: bool = True,
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
    """Capture several viewport frames spaced in time, then merge into one PNG atlas.

    Args:
        api: Connected editor API.
        frame_count: Number of sequential screenshots.
        interval: Sleep seconds *between* completed captures (lets animation advance).
        cols: Atlas columns; ``None`` → auto grid.
        filename_prefix: Stem for per-frame files ( …_000, …_001 ).
        output_atlas: Output .png path; default under project's Screenshots/WindowsEditor.
        project_dir: UE project directory (for finding/writing screenshots).
        disable_noisy: If True, scrub bloom/TAA/etc. once for the whole capture run.
        res_x, res_y: Capture resolution.
        delay: UE high-res shot delay.
        wait_timeout: Per-frame file wait.
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

    saved_cvars: dict[str, str] = {}
    if disable_noisy:
        saved_cvars = _noisy_scrub_begin(api)

    frame_results: list[dict] = []
    frame_paths: list[str] = []
    prep_refresh: dict = {}

    try:
        # Dynamic / multi-frame: Realtime must stay on so time advances between captures.
        prep_refresh = _refresh_editor_viewports(api)

        for i in range(frame_count):
            # Second+ TakeHighResScreenshot can race the previous automation task; settle + focus helps.
            if i > 0:
                try:
                    api.bring_to_foreground()
                except Exception:
                    pass
                time.sleep(1.25)

            fname = f"{filename_prefix}_{i:03d}"
            shot = _capture_viewport_png_raw(
                api,
                fname,
                project_dir,
                wait_timeout,
                res_x,
                res_y,
                delay,
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
                _ensure_editor_viewport_realtime(api)
                time.sleep(interval)

    finally:
        if disable_noisy and saved_cvars:
            _noisy_scrub_end(api, saved_cvars)

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
    out["cli_command"] = "screenshot sequence [-n FRAMES] [-i INTERVAL]"

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


def _find_screenshot(
    filename: str,
    project_dir: str | None,
    timeout: float = 15.0,
) -> str | None:
    """Find a screenshot file in the Saved/Screenshots directory.

    TakeHighResScreenshot saves to:
    {ProjectDir}/Saved/Screenshots/WindowsEditor/{filename}.png

    Args:
        filename: Expected filename stem.
        project_dir: Project directory.
        timeout: Max seconds to wait.

    Returns:
        Full path to screenshot, or None.
    """
    if not project_dir:
        return None

    # Primary location for editor screenshots
    search_dirs = [
        Path(project_dir) / "Saved" / "Screenshots" / "WindowsEditor",
        Path(project_dir) / "Saved" / "Screenshots",
        Path(project_dir) / "Saved",
    ]

    deadline = time.time() + timeout
    while time.time() < deadline:
        candidates: list[Path] = []
        for search_dir in search_dirs:
            if search_dir.is_dir():
                for f in search_dir.iterdir():
                    if (f.stem == filename or f.stem.startswith(filename)) and f.suffix.lower() in (
                        ".png",
                        ".jpg",
                        ".bmp",
                    ):
                        candidates.append(f)
        if candidates:
            exact = [p for p in candidates if p.stem == filename]
            pool = exact if exact else candidates
            best = max(
                pool,
                key=lambda p: (
                    p.suffix.lower() == ".png",
                    p.stat().st_mtime,
                ),
            )
            return str(best)
        time.sleep(0.3)

    return None
