"""Where snips land on disk.

Every snip overwrites one file (`latest.png` by default) so the save folder
never fills up on its own. History (on by default since 0.8.0) keeps a
timestamped copy alongside, pruned to a fixed count; outside a lab those
copies are the Recent snips list in the window.
"""

from __future__ import annotations

import os
import re
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
    # Write first. If this fails, the previous latest file, whatever its
    # format, is still there; removing it beforehand would leave neither.
    path = write_atomic(target, data)
    # Only now drop stale siblings, so switching format does not leave two
    # 'latest' files.
    for other in folder.glob(f"{cfg['latest_name']}.*"):
        if other != target and other.suffix.lower() in _SUFFIXES:
            try:
                other.unlink()
            except OSError:
                pass
    return path


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
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _SUFFIXES),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in files[limit:]:
        try:
            stale.unlink()
        except OSError:
            pass


REMOVED_DIRNAME = "removed"
_STAMP_RE = re.compile(r"snip_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})")


def history_folder(cfg: dict) -> Path:
    return Path(cfg["save_dir"]) / HISTORY_DIRNAME


def history_rows(cfg: dict) -> list[dict]:
    """The history folder as rows for the snip list, oldest first.

    The same shape as lab.snip_rows(), with nothing filed: no section,
    caption or notes.
    """
    folder = history_folder(cfg)
    try:
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _SUFFIXES]
    except OSError:
        return []
    def stat_time(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0
    files.sort(key=lambda p: (stat_time(p), p.name))
    rows = []
    for number, path in enumerate(files, start=1):
        match = _STAMP_RE.match(path.name)
        if match:
            day, hh, mm, ss = match.groups()
            when = f"{day} {hh}:{mm}:{ss}"
        else:
            when = datetime.fromtimestamp(stat_time(path)).strftime("%Y-%m-%d %H:%M:%S")
        rows.append({
            "file": path.name, "number": number, "time": when, "section": "",
            "caption": "", "notes": [], "note_entries": [], "path": str(path),
            "recorded": False,
        })
    return rows


def remove_from_history(cfg: dict, name: str) -> Path | None:
    """Move a history snip into history/removed. Nothing is deleted."""
    folder = history_folder(cfg)
    source = folder / Path(name).name
    if not source.is_file():
        return None
    target_dir = folder / REMOVED_DIRNAME
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    n = 1
    while target.exists():
        target = target_dir / f"{source.stem}_{n}{source.suffix}"
        n += 1
    os.replace(source, target)
    return target


def suggested_name(ext: str) -> str:
    return f"snip_{datetime.now():%Y-%m-%d_%H-%M-%S}.{ext}"


def open_folder(path: Path) -> None:
    """Open a folder itself, rather than selecting it in its parent."""
    import sys

    path = Path(path)
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - opening the user's own folder
        return
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def open_file(path: Path) -> None:
    """Open a file in whatever the system has associated with it.

    The same call as open_folder underneath: Windows' startfile and Qt's
    openUrl both hand the path to the shell, which picks the viewer.
    """
    open_folder(path)


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
