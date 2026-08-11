"""Lab sessions.

A lab is a named folder that collects every snip taken while it is engaged.
Normal behaviour does not change: the clipboard copy and the standing
`latest.png` still happen exactly as before. The lab folder is simply a second
destination, and the snips land in it numbered in the order they were taken.

Two files live alongside the images:

    lab.json   the source of truth: name, start time, one record per snip
    lab.md     rendered from lab.json, ready to paste into a writeup

lab.md is regenerated from lab.json on every change rather than appended to,
so a caption added after the fact just re-renders instead of needing the
markdown to be edited in place.

The active lab name is stored in the config, so a restart or a crash resumes
the same lab instead of quietly dropping back to normal mode.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import storage

STATE_NAME = "lab.json"
INDEX_NAME = "lab.md"
GITIGNORE_NAME = ".gitignore"

# Labs are full of hashes, tokens and internal hostnames by design. The
# ignore file goes in the labs root on creation so none of it reaches a repo
# by accident.
GITIGNORE_BODY = "# Lab captures. Nothing in here belongs in a repository.\n*\n"

_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg")
_NUMBER_RE = re.compile(r"^(\d+)_")


class LabError(RuntimeError):
    """The lab folder could not be created or written."""


# -- locations -------------------------------------------------------------
def root(cfg: dict) -> Path:
    """The folder that holds every lab. Defaults to <save_dir>/labs."""
    configured = str(cfg.get("lab_root", "")).strip()
    if configured:
        return Path(configured)
    return Path(cfg["save_dir"]) / "labs"


def folder(cfg: dict, name: str) -> Path:
    return root(cfg) / name


def active_name(cfg: dict) -> str:
    return str(cfg.get("active_lab", "")).strip()


def is_active(cfg: dict) -> bool:
    return bool(active_name(cfg))


def active_folder(cfg: dict) -> Path | None:
    name = active_name(cfg)
    return folder(cfg, name) if name else None


# -- lifecycle -------------------------------------------------------------
def start(cfg: dict, name: str) -> Path:
    """Create or resume the lab called `name` and return its folder.

    The name is used as the folder name exactly as given. Windows rejects a
    few characters and a handful of reserved words, so creation is reported
    rather than left to fail silently.
    """
    name = str(name).strip()
    if not name:
        raise LabError("a lab needs a name")

    target = folder(cfg, name)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as exc:
        # ValueError covers a null byte in the name, which pathlib raises
        # before the OS ever sees it.
        raise LabError(f"'{name}' cannot be used as a folder name ({exc})") from exc

    _ensure_gitignore(root(cfg))

    state = _load_state(target)
    if not state:
        state = {"name": name, "started": _now_iso(), "entries": []}
        _save_state(target, state, cfg)
    return target


def stop(cfg: dict) -> str:
    """Disengage the current lab. Returns the name that was active."""
    name = active_name(cfg)
    cfg["active_lab"] = ""
    return name


def recent(cfg: dict, limit: int = 10) -> list[str]:
    """Lab names, most recently written first."""
    base = root(cfg)
    if not base.is_dir():
        return []
    try:
        folders = [p for p in base.iterdir() if p.is_dir()]
    except OSError:
        return []
    folders.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in folders[:limit]]


def count(cfg: dict, name: str | None = None) -> int:
    """How many snips a lab holds."""
    name = name or active_name(cfg)
    if not name:
        return 0
    return len(_images(folder(cfg, name)))


# -- saving ----------------------------------------------------------------
def save(data: bytes, ext: str, cfg: dict) -> Path | None:
    """Write one snip into the active lab. Returns None when none is active.

    Files are named `003_2026-08-11_14-31-07.png`: the sequence number first
    so the folder sorts in capture order, the timestamp after it so the name
    still says when it was taken.
    """
    target = active_folder(cfg)
    if target is None:
        return None

    now = datetime.now()
    number = _next_number(target)
    filename = f"{number:03d}_{now:%Y-%m-%d_%H-%M-%S}.{ext}"
    path = storage.write_atomic(target / filename, data)

    if cfg.get("lab_index", True):
        state = _load_state(target) or {
            "name": target.name,
            "started": _now_iso(),
            "entries": [],
        }
        state.setdefault("entries", []).append(
            {
                "file": filename,
                "number": number,
                "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "caption": "",
            }
        )
        _save_state(target, state, cfg)
    return path


def set_caption(cfg: dict, filename: str, caption: str) -> bool:
    """Attach a caption to an already-saved snip and re-render the index."""
    target = active_folder(cfg)
    if target is None or not cfg.get("lab_index", True):
        return False
    state = _load_state(target)
    if not state:
        return False
    for entry in reversed(state.get("entries", [])):
        if entry.get("file") == filename:
            entry["caption"] = str(caption).strip()
            _save_state(target, state, cfg)
            return True
    return False


# -- index -----------------------------------------------------------------
def render_index(state: dict) -> str:
    """Build lab.md from the recorded entries."""
    lines = [f"# {state.get('name', 'lab')}", ""]
    started = state.get("started", "")
    if started:
        lines.append(f"Started {started.replace('T', ' ')[:19]}")
        lines.append("")

    for entry in state.get("entries", []):
        number = entry.get("number", 0)
        lines.append(f"## {number:03d} at {entry.get('time', '')}")
        lines.append("")
        caption = entry.get("caption", "").strip()
        if caption:
            lines.append(caption)
            lines.append("")
        lines.append(f"![{number:03d}]({entry.get('file', '')})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# -- internals -------------------------------------------------------------
def _images(target: Path) -> list[Path]:
    if not target.is_dir():
        return []
    try:
        return [p for p in target.iterdir() if p.suffix.lower() in _SUFFIXES]
    except OSError:
        return []


def _next_number(target: Path) -> int:
    """One past the highest number already in the folder.

    Derived from the filenames rather than a counter in lab.json, so resuming
    a lab, deleting the state file, or copying images in by hand all still
    produce a sensible next number.
    """
    highest = 0
    for path in _images(target):
        match = _NUMBER_RE.match(path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _load_state(target: Path) -> dict:
    try:
        with open(target / STATE_NAME, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save_state(target: Path, state: dict, cfg: dict) -> None:
    payload = json.dumps(state, indent=2).encode("utf-8")
    try:
        storage.write_atomic(target / STATE_NAME, payload)
        storage.write_atomic(
            target / INDEX_NAME, render_index(state).encode("utf-8")
        )
    except OSError:
        # The image is already on disk and on the clipboard; a failed index
        # write is not worth losing the snip over.
        pass


def _ensure_gitignore(base: Path) -> None:
    path = base / GITIGNORE_NAME
    if path.exists():
        return
    try:
        storage.write_atomic(path, GITIGNORE_BODY.encode("utf-8"))
    except OSError:
        pass


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
