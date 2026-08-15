"""Settings storage for ShadowSnip.

Config lives in %APPDATA%\\ShadowSnip\\config.json. Missing keys fall back to
DEFAULTS, so a config written by an older version keeps working.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

APP_NAME = "ShadowSnip"
APP_VERSION = "0.3.1"


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def default_save_dir() -> Path:
    base = os.environ.get("USERPROFILE")
    root = Path(base) if base else Path.home()
    return root / "Pictures" / APP_NAME


CONFIG_PATH = config_dir() / "config.json"

DEFAULTS = {
    # Global hotkey that starts a snip. Modifiers: ctrl, alt, shift, win.
    "hotkey": "ctrl+shift+s",
    # Where the always-overwritten snip and any history land.
    "save_dir": str(default_save_dir()),
    # Base name of the file that gets replaced on every snip.
    "latest_name": "latest",
    # Keep timestamped copies alongside the latest file.
    "keep_history": False,
    "history_limit": 50,
    # Compression. max_dimension 0 means "do not downscale".
    "max_dimension": 0,
    "quantize": True,
    "quantize_colors": 256,
    # Skip quantising when the grab holds more distinct colours than this;
    # text and photographs lose visible detail to a 256-entry palette.
    # 0 disables the check.
    "quantize_max_source_colors": 4096,
    # And only keep the palette version when it is at least this much smaller.
    "quantize_min_saving": 25,
    "png_compress_level": 9,
    # Disk format: png, webp or jpeg. Clipboard always gets PNG.
    "disk_format": "png",
    "webp_quality": 90,
    "jpeg_quality": 90,
    # Also put an uncompressed CF_DIB on the clipboard for older apps.
    "clipboard_dib_fallback": True,
    # Copy on select: a finished drag copies the highlighted text. Off by
    # default; it needs a system-wide mouse hook to work at all.
    "auto_copy": False,
    "auto_copy_min_drag": 8,
    "auto_copy_skip_consoles": True,
    # Show the preview window after a snip.
    "show_preview": True,
    # 0-255 dimming of the frozen screen behind the selection.
    "dim_opacity": 110,
    # Lab sessions. Empty active_lab means no lab is engaged; empty lab_root
    # means <save_dir>/labs.
    "active_lab": "",
    "lab_root": "",
    "lab_index": True,
    "lab_caption": True,
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULTS:
                    cfg[key] = value
    except (OSError, ValueError):
        pass
    return _sanitise(cfg)


def save(cfg: dict) -> None:
    """Write the config atomically so a crash mid-write cannot corrupt it."""
    cfg = _sanitise(dict(cfg))
    target = CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, sort_keys=True)
        os.replace(tmp, target)
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _clamp(value, low, high, fallback):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, value))


def _sanitise(cfg: dict) -> dict:
    cfg["max_dimension"] = _clamp(cfg.get("max_dimension"), 0, 30000, 0)
    cfg["quantize_colors"] = _clamp(cfg.get("quantize_colors"), 2, 256, 256)
    cfg["quantize_max_source_colors"] = _clamp(
        cfg.get("quantize_max_source_colors"), 0, 16_777_216, 4096
    )
    cfg["quantize_min_saving"] = _clamp(cfg.get("quantize_min_saving"), 0, 90, 25)
    cfg["png_compress_level"] = _clamp(cfg.get("png_compress_level"), 0, 9, 9)
    cfg["webp_quality"] = _clamp(cfg.get("webp_quality"), 1, 100, 90)
    cfg["jpeg_quality"] = _clamp(cfg.get("jpeg_quality"), 1, 100, 90)
    cfg["history_limit"] = _clamp(cfg.get("history_limit"), 1, 5000, 50)
    cfg["dim_opacity"] = _clamp(cfg.get("dim_opacity"), 0, 255, 110)
    cfg["auto_copy_min_drag"] = _clamp(cfg.get("auto_copy_min_drag"), 1, 200, 8)
    if cfg.get("disk_format") not in ("png", "webp", "jpeg"):
        cfg["disk_format"] = "png"
    for flag in (
        "keep_history",
        "quantize",
        "clipboard_dib_fallback",
        "show_preview",
        "lab_index",
        "lab_caption",
        "auto_copy",
        "auto_copy_skip_consoles",
    ):
        cfg[flag] = bool(cfg.get(flag))
    if not str(cfg.get("hotkey", "")).strip():
        cfg["hotkey"] = DEFAULTS["hotkey"]
    if not str(cfg.get("save_dir", "")).strip():
        cfg["save_dir"] = DEFAULTS["save_dir"]
    name = str(cfg.get("latest_name", "")).strip() or DEFAULTS["latest_name"]
    cfg["latest_name"] = Path(name).stem or DEFAULTS["latest_name"]
    # Lab names are kept as typed; only surrounding whitespace is trimmed.
    cfg["active_lab"] = str(cfg.get("active_lab", "") or "").strip()
    cfg["lab_root"] = str(cfg.get("lab_root", "") or "").strip()
    return cfg
