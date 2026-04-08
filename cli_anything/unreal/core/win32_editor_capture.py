"""Windows-only: capture a native HWND to PNG using GDI (PrintWindow + GetDIBits) + Pillow.

Used for editor screenshots from the CLI process so Unreal Python does not need a C++ plugin.
"""

from __future__ import annotations

import sys
import ctypes
from ctypes import wintypes
from pathlib import Path


def capture_hwnd_to_png(hwnd: int, output_path: Path, crop_rect: tuple[int, int, int, int] | None = None) -> bool:
    """Capture a top-level window to a PNG file. Requires Pillow.

    Uses ``PrintWindow`` with ``PW_RENDERFULLCONTENT``, then ``BitBlt`` fallback.
    If ``crop_rect`` is provided (left, top, right, bottom) in absolute screen coords,
    the image will be cropped before saving.

    Args:
        hwnd: Native window handle.
        output_path: Destination ``.png`` path.
        crop_rect: Optional absolute (x1, y1, x2, y2) bounds.

    Returns:
        True if the file was written.
    """
    if sys.platform != "win32":
        return False

    try:
        from PIL import Image
    except ImportError:
        return False

    output_path = Path(output_path)
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    rc = RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc)):
        return False

    width = int(rc.right - rc.left)
    height = int(rc.bottom - rc.top)
    if width <= 0 or height <= 0:
        return False

    PW_RENDERFULLCONTENT = 0x00000002
    SRCCOPY = 0x00CC0020

    hdc_win = user32.GetWindowDC(wintypes.HWND(hwnd))
    if not hdc_win:
        return False

    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    if not hdc_mem:
        user32.ReleaseDC(wintypes.HWND(hwnd), hdc_win)
        return False

    hbmp = gdi32.CreateCompatibleBitmap(hdc_win, width, height)
    if not hbmp:
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(wintypes.HWND(hwnd), hdc_win)
        return False

    old = gdi32.SelectObject(hdc_mem, hbmp)
    ok_pw = user32.PrintWindow(wintypes.HWND(hwnd), hdc_mem, PW_RENDERFULLCONTENT)
    if not ok_pw:
        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_win, 0, 0, SRCCOPY)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER)]

    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = width
    bi.bmiHeader.biHeight = -height  # top-down DIB
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0  # BI_RGB

    row_size = ((width * 32 + 31) // 32) * 4
    image_size = row_size * height
    buf = ctypes.create_string_buffer(image_size)

    DIB_RGB_COLORS = 0
    lines = gdi32.GetDIBits(
        hdc_mem,
        hbmp,
        0,
        height,
        buf,
        ctypes.byref(bi),
        DIB_RGB_COLORS,
    )

    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(wintypes.HWND(hwnd), hdc_win)

    if not lines:
        return False

    img = Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", row_size, 1)

    if crop_rect:
        cx1, cy1, cx2, cy2 = crop_rect
        # Convert absolute screen coords to local window coordinates
        lx1 = cx1 - rc.left
        ly1 = cy1 - rc.top
        lx2 = cx2 - rc.left
        ly2 = cy2 - rc.top
        
        # Clamp to bounds
        lx1 = max(0, min(lx1, width))
        ly1 = max(0, min(ly1, height))
        lx2 = max(0, min(lx2, width))
        ly2 = max(0, min(ly2, height))
        
        if lx2 > lx1 and ly2 > ly1:
            img = img.crop((lx1, ly1, lx2, ly2))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG", optimize=True)
    return True
