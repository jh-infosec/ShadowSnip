"""Where snips land on disk.

Every snip overwrites one file (`latest.png` by default) so the save folder
never fills up on its own. History is off by default; when it is on, a
timestamped copy is kept alongside and the folder is pruned to a fixed count.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

HISTORY_DIRNAME = "history"
_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg")


def save_dir(cfg: dict) -> Path:
    path = Path(cfg["save_dir"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_atomic(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def save_latest(data: bytes, ext: str, cfg: dict) -> Path:
    """Replace the standing snip file and return its path."""
    folder = save_dir(cfg)
    target = folder / f"{cfg['latest_name']}.{ext}"
    # Drop stale siblings so switching format does not leave two 'latest' files.
    for other in folder.glob(f"{cfg['latest_name']}.*"):
        if other != target and other.suffix.lower() in _SUFFIXES:
            try:
                other.unlink()
            except OSError:
                pass
    return write_atomic(target, data)


def save_history(data: bytes, ext: str, cfg: dict) -> Path | None:
    if not cfg.get("keep_history"):
        return None
    folder = save_dir(cfg) / HISTORY_DIRNAME
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")[:-3]
    path = write_atomic(folder / f"snip_{stamp}.{ext}", data)
    prune_history(cfg)
    return path


def prune_history(cfg: dict) -> None:
    folder = Path(cfg["save_dir"]) / HISTORY_DIRNAME
    if not folder.is_dir():
        return
    limit = int(cfg.get("history_limit", 50))
    files = sorted(
        (p for p in folder.iterdir() if p.suffix.lower() in _SUFFIXES),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in files[limit:]:
        try:
            stale.unlink()
        except OSError:
            pass


def suggested_name(ext: str) -> str:
    return f"snip_{datetime.now():%Y-%m-%d_%H-%M-%S}.{ext}"


def reveal(path: Path) -> None:
    """Open the containing folder, selecting the file where possible."""
    import subprocess
    import sys

    path = Path(path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
