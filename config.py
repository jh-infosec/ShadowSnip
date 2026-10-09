"""Settings storage for ShadowSnip.

Config lives in %APPDATA%\\ShadowSnip\\config.json on Windows and in
~/.config/shadowsnip/config.json on Linux. Missing keys fall back to
DEFAULTS, so a config written by an older version keeps working.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

APP_NAME = "ShadowSnip"
APP_VERSION = "0.7.6"


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    # Linux: the XDG config folder, where every other desktop app keeps its
    # settings, rather than a dot-folder in home.
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return (Path(xdg) if xdg else Path.home() / ".config") / APP_NAME.lower()


def default_save_dir() -> Path:
    base = os.environ.get("USERPROFILE")
    root = Path(base) if base else Path.home()
    return root / "Pictures" / APP_NAME


CONFIG_PATH = config_dir() / "config.json"

DEFAULTS = {
    # Global hotkey that starts a snip. Modifiers: ctrl, alt, shift, win.
    "hotkey": "ctrl+shift+s",
    # Global hotkey that files a one-line note into the engaged lab.
    "note_hotkey": "ctrl+shift+n",
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
    # Consoles, Explorer, the desktop, and VM/RDP/SSH client windows: every
    # place a synthetic Ctrl+C means something other than "copy". The key name
    # predates the VM and remote-session entries and is kept as it is so that
    # existing config files keep their setting.
    "auto_copy_skip_consoles": True,
    # Also treat a double-click (word) and a triple-click (line) as a
    # selection, not only a drag.
    "auto_copy_double_click": True,
    # Ignore a clip identical to the one before it. Re-selecting the same word
    # is the commonest gesture there is.
    "auto_copy_dedupe": True,
    # Show a short confirmation near the cursor when a clip is captured.
    "auto_copy_toast": True,
    # Extra executable names never copied from, on top of the built-in list of
    # password managers in autocopy.BLOCKED_PROCESSES. Lowercase, with the
    # extension: "myvault.exe".
    "auto_copy_extra_blocked": [],
    # Show the preview window after a snip.
    "show_preview": True,
    # 0-255 dimming of the frozen screen behind the selection.
    "dim_opacity": 110,
    # Lab sessions. Empty active_lab means no lab is engaged; empty lab_root
    # means <save_dir>/labs.
    "active_lab": "",
    "lab_root": "",
    "lab_index": True,
    # Offer a caption box under the image after each snip filed in a lab.
    "lab_caption": True,
    # The list of the running lab's snips beside the image in the preview
    # window. Toggled with the Snip list button; remembered between runs.
    "lab_snip_list": True,
    # Mark-up tools: pen and highlighter colour and width, the redact mode.
    # Checked and clamped by annotate.sanitise_prefs when the window reads it.
    "annotation": {},
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


def without_exe(name: str) -> str:
    """`lightroom.exe` -> `lightroom`, and anything else unchanged.

    Only `.exe` is stripped: `setup.msi` keeps its extension, so a list entry
    of `setup` does not silently cover it.
    """
    stem, _, extension = name.rpartition(".")
    return stem if stem and extension == "exe" else name


def add_name(text: str, name: str) -> str:
    """The exclusion field's text with `name` added, unless it is already in it.

    Either spelling counts as present -- adding `lightroom.exe` to a list that
    already says `lightroom` changes nothing -- because the block check treats
    the two the same. Returns the field's whole new text, so the caller can
    set it and be done.
    """
    names = normalise_names(text)
    stems = {without_exe(item) for item in names}
    for item in normalise_names(name):
        if without_exe(item) in stems:
            continue
        names.append(item)
        stems.add(without_exe(item))
    return ", ".join(names)


def normalise_names(value) -> list[str]:
    """A list of lowercase executable names, from a list or a typed-in string.

    The settings window offers one text field, and a hand-edited config.json
    may hold either shape, so both are accepted and both come back as a list
    with the blanks and duplicates gone.
    """
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    if not isinstance(value, (list, tuple, set)):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, (dict, list, tuple, set)):
            continue
        name = str(item or "").strip().lower()
        if name and name not in names:
            names.append(name)
    return names


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
        "lab_snip_list",
        "auto_copy",
        "auto_copy_skip_consoles",
        "auto_copy_double_click",
        "auto_copy_dedupe",
        "auto_copy_toast",
    ):
        cfg[flag] = bool(cfg.get(flag))
    cfg["auto_copy_extra_blocked"] = normalise_names(cfg.get("auto_copy_extra_blocked"))
    # `or ""` rather than a bare str(): a JSON null would otherwise sanitise to
    # the string "None" and sail through as a real value. A null save_dir in
    # particular reaches Path() as None and raises TypeError on the first snip,
    # which is not an OSError and so is not caught where the writes happen.
    for key in ("hotkey", "note_hotkey"):
        if not str(cfg.get(key) or "").strip():
            cfg[key] = DEFAULTS[key]
    if not str(cfg.get("save_dir") or "").strip():
        cfg["save_dir"] = DEFAULTS["save_dir"]
    name = str(cfg.get("latest_name") or "").strip() or DEFAULTS["latest_name"]
    cfg["latest_name"] = Path(name).stem or DEFAULTS["latest_name"]
    # Lab names are kept as typed; only surrounding whitespace is trimmed.
    cfg["active_lab"] = str(cfg.get("active_lab", "") or "").strip()
    cfg["lab_root"] = str(cfg.get("lab_root", "") or "").strip()
    if not isinstance(cfg.get("annotation"), dict):
        cfg["annotation"] = {}
    return cfg
