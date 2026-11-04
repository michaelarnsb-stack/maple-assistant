"""Screen capture of the game window.

We capture through the OS (GDI BitBlt via `mss`), never by touching the game
process, so the anti-cheat sees an ordinary screenshot tool.
"""

from __future__ import annotations

import base64
import ctypes
import io
import sys

from PIL import Image

# Long-edge cap. Claude's current models accept up to 2576px, but 1600px keeps
# game UI text readable at roughly half the image-token cost.
MAX_LONG_EDGE = 1600
JPEG_QUALITY = 85


def foreground_window() -> int | None:
    if sys.platform != "win32":
        return None
    return ctypes.windll.user32.GetForegroundWindow() or None


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """(left, top, width, height) of a window, or None if unusable."""
    if sys.platform != "win32" or not hwnd:
        return None

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = RECT()
    # DWMWA_EXTENDED_FRAME_BOUNDS = 9 gives the visible bounds without the
    # invisible resize border Windows 10/11 adds around windows.
    ok = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        ctypes.c_void_p(hwnd), 9, ctypes.byref(rect), ctypes.sizeof(rect)
    ) == 0
    if not ok and not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width < 200 or height < 150:
        return None
    return rect.left, rect.top, width, height


def grab(hwnd: int | None = None) -> Image.Image:
    """Screenshot of `hwnd` if given and valid, else of the primary monitor."""
    import mss

    with mss.mss() as sct:
        rect = window_rect(hwnd) if hwnd else None
        if rect:
            left, top, width, height = rect
            region = {"left": left, "top": top, "width": width, "height": height}
        else:
            region = sct.monitors[1]
        shot = sct.grab(region)
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def downscale(img: Image.Image, max_edge: int = MAX_LONG_EDGE) -> Image.Image:
    long_edge = max(img.size)
    if long_edge <= max_edge:
        return img
    scale = max_edge / long_edge
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)


def to_image_block(img: Image.Image) -> dict:
    """Encode as a Messages API base64 image content block."""
    buf = io.BytesIO()
    downscale(img).convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(buf.getvalue()).decode("ascii"),
        },
    }
