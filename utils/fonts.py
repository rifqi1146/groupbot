import os
import logging
from PIL import ImageFont
from utils.config import FONT_DIR

log = logging.getLogger(__name__)

def get_font(font_names, size):
    """
    Robustly load a font from various locations.

    Args:
        font_names (str or list): Name(s) of the font to load (e.g. "DejaVuSans.ttf").
        size (int): Font size.

    Returns:
        ImageFont: A PIL ImageFont object.
    """
    if isinstance(font_names, str):
        font_names = [font_names]

    custom_dir = FONT_DIR

    common_paths = [
        "/usr/share/fonts/truetype/dejavu/",
        "/usr/share/fonts/truetype/liberation/",
        "/usr/share/fonts/truetype/freefont/",
        "/usr/share/fonts/",
        "C:\\Windows\\Fonts\\",
        "/Library/Fonts/",
        "/System/Library/Fonts/",
        "./",
    ]

    for name in font_names:
        # 1. Try environment variable
        if custom_dir:
            path = os.path.join(custom_dir, name)
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass

        # 2. Try loading by name (PIL searches system paths)
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass

        # 3. Try common system paths
        for base in common_paths:
            path = os.path.join(base, name)
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    pass

        # 4. Try if name is already an absolute path (keep compatibility but discouragement)
        if os.path.isabs(name) and os.path.exists(name):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                pass

    # 5. Final fallback to default
    log.warning(f"Could not find any of fonts {font_names}, falling back to default.")
    try:
        return ImageFont.load_default()
    except Exception:
        return None
