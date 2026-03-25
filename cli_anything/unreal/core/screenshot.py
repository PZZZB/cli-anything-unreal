"""core/screenshot.py — Screenshot capture and comparison.

Provides viewport screenshot, high-res capture, CVar A/B testing,
and image compression for AI Agent vision analysis.
Requires a running UE editor with Remote Control API.

Screenshot method:
  Uses AutomationBlueprintFunctionLibrary.TakeHighResScreenshot via
  /Script/FunctionalTesting module. Screenshots saved to:
  {ProjectDir}/Saved/Screenshots/WindowsEditor/{filename}.png
"""

import os
import time
from pathlib import Path
from typing import Optional

from cli_anything.unreal.utils.ue_http_api import UEEditorAPI

# Default screenshot delay to allow viewport to render
_DEFAULT_RENDER_DELAY = 1.0


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
    # Optionally disable noisy rendering features for clean capture
    saved_cvars = {}
    noisy_cvars = {
        "r.TemporalAA.Upsampling": "0",
        "r.MotionBlurQuality": "0",
        "r.DepthOfFieldQuality": "0",
        "r.LensFlareQuality": "0",
        "r.BloomQuality": "0",
    }

    if disable_noisy:
        for cvar, value in noisy_cvars.items():
            try:
                old_val = api.get_cvar(cvar)
                saved_cvars[cvar] = old_val
                api.set_cvar(cvar, value)
            except Exception:
                pass
        # Give a moment for settings to take effect
        time.sleep(0.3)

    try:
        # Bring editor to foreground — viewport only renders when visible
        foreground_ok = api.bring_to_foreground()
        time.sleep(1.0)  # Let viewport start rendering

        # Request screenshot via AutomationBlueprintFunctionLibrary
        result = api.take_screenshot(
            filename=filename,
            res_x=res_x,
            res_y=res_y,
            delay=delay,
        )

        if "error" in result:
            return result

        # The automation task runs asynchronously in UE.
        # Wait at least 'delay' seconds (the render delay) before polling for file.
        time.sleep(delay + 1.0)

        # Wait for the file to appear on disk
        # TakeHighResScreenshot saves to: Saved/Screenshots/WindowsEditor/{filename}.png
        screenshot_path = _find_screenshot(filename, project_dir, wait_timeout)

        if screenshot_path and Path(screenshot_path).exists():
            size = Path(screenshot_path).stat().st_size

            # Auto-compress for Agent (default: return compressed path)
            compressed = compress_for_agent(screenshot_path)

            response = {
                "status": "ok",
                "read_this": compressed or screenshot_path,
                "path_raw": screenshot_path,
                "size_raw": size,
            }

            if compressed:
                response["size_compressed"] = Path(compressed).stat().st_size
            else:
                response["compress_hint"] = (
                    "Auto-compress unavailable (Pillow not installed). "
                    "Returning raw PNG. Install with: pip install Pillow"
                )

            return response

        return {
            "status": "requested",
            "message": "Screenshot requested but file not found yet. "
                       "It may appear shortly in Saved/Screenshots/WindowsEditor/",
            "foreground_ok": foreground_ok,
            "hint": (
                "The editor window may not have had focus. "
                "Screenshots require the viewport to be rendering (window visible and focused)."
                if not foreground_ok else None
            ),
            "api_result": result,
        }

    finally:
        # Restore noisy CVars
        if disable_noisy:
            for cvar, value in saved_cvars.items():
                try:
                    api.set_cvar(cvar, str(value))
                except Exception:
                    pass


def take_viewport_screenshot(
    api: UEEditorAPI,
    filename: str = "highres",
    resolution_multiplier: int = 2,
) -> dict:
    """Take a high-resolution viewport screenshot.

    Args:
        api: Connected UEEditorAPI instance.
        filename: Output filename.
        resolution_multiplier: Resolution multiplier.

    Returns:
        API response dict.
    """
    return api.take_screenshot(
        filename=filename,
        res_x=1920 * resolution_multiplier,
        res_y=1080 * resolution_multiplier,
        delay=1.5,
    )


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
        for search_dir in search_dirs:
            if search_dir.is_dir():
                for f in search_dir.iterdir():
                    if (f.stem == filename or f.stem.startswith(filename)) and \
                       f.suffix.lower() in (".png", ".jpg", ".bmp"):
                        return str(f)
        time.sleep(1.0)

    return None
