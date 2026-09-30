"""Lab sessions.

A lab is a named folder that collects everything captured while it is engaged.
Normal behaviour does not change: the clipboard copy and the standing
`latest.png` still happen exactly as before. The lab folder is simply a second
destination, and the snips land in it numbered in the order they were taken.

Two files live alongside the images:

    lab.json   the source of truth: name, start time, current section, and one
               record per snip and per note, in capture order
    lab.md     rendered from lab.json, ready to paste into a writeup

lab.md is regenerated from lab.json on every change rather than appended to,
so a caption or a note added after the fact just re-renders instead of needing
the markdown to be edited in place.

The active lab name is stored in the config, so a restart or a crash resumes
the same lab instead of quietly dropping back to normal mode.

## Sections

A lab carries a **current section**: a breadcrumb like

    10.10.10.3 / SMB / anonymous share

Everything captured while it is set -- snips and notes alike -- is filed under
it, and `lab.md` renders those paths as nested headings. The structure is
therefore recorded while the work is happening, rather than reconstructed from
a pile of screenshots afterwards, because setting the breadcrumb is how you say
"I am on SMB now". The section lives in lab.json rather than the config, so it
belongs to the lab and resuming one restores where you were.

Section parts are never used as folder names, so unlike lab names they have no
filesystem restrictions to respect. Only whitespace is collapsed, and the depth
and part length are capped so a runaway paste cannot produce a heading level
markdown has no room for.

## Notes

A note is an entry with text instead of an image. It records the section it was
taken in, and optionally the filenames of snips it belongs to: a note typed
while looking at a snip attaches to that snip and renders directly beneath its
image, which is the layout a report wants. Everything else renders in capture
order within its section.

Notes are ordinary text in an ordinary file. A lab already holds screenshots of
hashes and tokens, and now it holds them as text as well -- see the warning in
README.md. The `.gitignore` written into the labs root stops the obvious
accident and nothing else.

## Compatibility

Records written by 0.3.x have entries with no `kind` and no `section`. They
read as snips at the root of the tree, so an old lab opens and renders without
being migrated.
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
# Where a removed snip goes. Inside the lab, so it travels with it and is
# covered by the same .gitignore.
REMOVED_DIR = "removed"

# Labs are full of hashes, tokens and internal hostnames by design. The
# ignore file goes in the labs root on creation so none of it reaches a repo
# by accident.
GITIGNORE_BODY = "# Lab captures. Nothing in here belongs in a repository.\n*\n"

SECTION_SEPARATOR = "/"
# Six levels is one more than markdown has heading levels below the lab title,
# and far more than any real engagement needs.
MAX_SECTION_DEPTH = 6
MAX_SECTION_PART = 80
# Deeper than markdown can express; anything past this shares level six.
MAX_HEADING_LEVEL = 6

_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg")
_NUMBER_RE = re.compile(r"^(\d+)_")
_NOTE_ID_RE = re.compile(r"^n(\d+)$")


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
        state = _blank_state(name)
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


def note_count(cfg: dict, name: str | None = None) -> int:
    """How many notes a lab holds."""
    name = name or active_name(cfg)
    if not name:
        return 0
    state = _load_state(folder(cfg, name))
    return sum(1 for entry in state.get("entries", []) if entry_kind(entry) == "note")


# -- sections --------------------------------------------------------------
def normalise_section(path) -> str:
    """Tidy a breadcrumb: collapse whitespace, drop empty parts, cap the depth.

    Section parts are headings, not folder names, so nothing is stripped for
    the filesystem's benefit. The caps exist so a stray paste cannot produce a
    part longer than a heading should be or a tree deeper than markdown can
    render.
    """
    parts = []
    for raw in str(path or "").split(SECTION_SEPARATOR):
        part = " ".join(str(raw).split())
        if part:
            parts.append(part[:MAX_SECTION_PART])
        if len(parts) == MAX_SECTION_DEPTH:
            break
    return SECTION_SEPARATOR.join(parts)


def section(cfg: dict) -> str:
    """The current section of the active lab, or "" for the root."""
    target = active_folder(cfg)
    if target is None:
        return ""
    return normalise_section(_load_state(target).get("section", ""))


def sections(cfg: dict) -> list[str]:
    """Every breadcrumb used in the active lab, parents before children.

    This is what the section picker offers. Retyping `10.0.0.3/SMB` from memory
    an hour later is how you end up with `SCAN` and `SCANvv2` as two separate
    branches of the same tree, and the near-miss is invisible until the writeup.

    Ancestors are included even when nothing was filed directly under them,
    because they are headings in `lab.md` and going back up a level is a normal
    move.
    """
    target = active_folder(cfg)
    if target is None:
        return []
    state = _load_state(target)

    used: list[str] = []
    for entry in state.get("entries", []) if isinstance(state.get("entries"), list) else []:
        if not isinstance(entry, dict):
            continue
        path = entry_section(entry)
        if path and path not in used:
            used.append(path)
    current = normalise_section(state.get("section", ""))
    if current and current not in used:
        used.append(current)

    out: list[str] = []
    for path in used:
        node = ""
        for part in path.split(SECTION_SEPARATOR):
            node = f"{node}{SECTION_SEPARATOR}{part}" if node else part
            if node not in out:
                out.append(node)
    return out


def move_snip(cfg: dict, filename: str, path) -> str | None:
    """Re-file an already-saved snip under a section.

    The common repair: a snip taken before the breadcrumb was set is filed at
    the root, which separates it from the notes written about it a minute
    later. Snipping first and labelling after is the natural rhythm, so this
    has to be fixable — explicitly, by asking, rather than by the application
    guessing which section a snip "really" belonged to.

    Returns the new section, or None when there is no lab, no record, or no
    such snip in it.
    """
    target = active_folder(cfg)
    if target is None or not cfg.get("lab_index", True):
        return None
    state = _load_state(target)
    if not state:
        return None

    cleaned = normalise_section(path)
    for entry in reversed(state.get("entries", [])):
        if not isinstance(entry, dict) or entry.get("file") != filename:
            continue
        if entry_section(entry) != cleaned:
            entry["section"] = cleaned
            _save_state(target, state, cfg)
        return cleaned
    return None


def set_section(cfg: dict, path) -> str:
    """Point the active lab at a section. Returns the normalised breadcrumb."""
    target = active_folder(cfg)
    if target is None or not cfg.get("lab_index", True):
        return ""
    cleaned = normalise_section(path)
    state = _load_state(target) or _blank_state(target.name)
    if normalise_section(state.get("section", "")) == cleaned:
        # Nothing changed, so nothing is rewritten. Editing the box and
        # tabbing away should not churn the file on disk.
        return cleaned
    state["section"] = cleaned
    _save_state(target, state, cfg)
    return cleaned


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
        state = _load_state(target) or _blank_state(target.name)
        state.setdefault("entries", []).append(
            {
                "kind": "snip",
                "file": filename,
                "number": number,
                "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "caption": "",
                "section": normalise_section(state.get("section", "")),
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


def add_note(cfg: dict, text: str, attach=None) -> dict | None:
    """Record a note in the active lab's current section.

    `attach` is an iterable of snip filenames the note belongs to. An attached
    note renders directly beneath that snip's image rather than on its own,
    which is the arrangement a report wants: evidence, then the sentence about
    the evidence.

    Returns the stored entry, or None when there is no lab, no record being
    kept, or nothing worth storing.
    """
    target = active_folder(cfg)
    if target is None or not cfg.get("lab_index", True):
        return None
    text = str(text or "").strip()
    if not text:
        return None

    state = _load_state(target) or _blank_state(target.name)
    entry = {
        "kind": "note",
        "id": _next_note_id(state),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "text": text,
        "section": normalise_section(state.get("section", "")),
        "attach": [str(name) for name in (attach or ()) if str(name).strip()],
    }
    state.setdefault("entries", []).append(entry)
    _save_state(target, state, cfg)
    return entry


# -- removing --------------------------------------------------------------
def remove_snip(cfg: dict, filename: str) -> dict | None:
    """Take a snip out of the active lab, keeping it recoverable.

    For the wrong window, the wrong tab, the snip that caught a password
    prompt. The image is moved into `removed/` inside the lab rather than
    deleted, and its record, together with any note that was attached to it
    and nothing else, is moved into the `removed` list in lab.json. lab.md is
    re-rendered without it. Putting it back is a matter of moving the file up
    a level and the record back into `entries`, by hand.

    A note attached to several snips stays, minus the reference to this one:
    it is still about the others.

    The folder is `removed`, not `.removed`: a hidden folder is one you forget
    is holding a screenshot of a hash.

    Returns what was removed, as {"file", "number", "notes"}, or None when
    there is no lab or no such snip in it.
    """
    target = active_folder(cfg)
    filename = str(filename or "").strip()
    if target is None or not filename or Path(filename).name != filename:
        # A bare filename only. Anything with a separator in it is not one of
        # ours, and must not be able to move files out of some other folder.
        return None

    source = target / filename
    if not source.is_file() or source.suffix.lower() not in _SUFFIXES:
        return None

    bin_dir = target / REMOVED_DIR
    try:
        bin_dir.mkdir(exist_ok=True)
        destination = bin_dir / filename
        if destination.exists():
            destination = bin_dir / f"{source.stem}_{_now_iso().replace(':', '-')}{source.suffix}"
        source.replace(destination)
    except OSError as exc:
        raise LabError(f"could not move {filename} out of the lab: {exc}") from exc

    match = _NUMBER_RE.match(filename)
    removed = {
        "file": filename,
        "number": int(match.group(1)) if match else 0,
        "notes": [],
    }

    state = _load_state(target)
    if not state:
        return removed

    kept: list = []
    moved: list[dict] = []
    for entry in state.get("entries", []):
        if not isinstance(entry, dict):
            kept.append(entry)
            continue
        if entry_kind(entry) == "snip" and entry.get("file") == filename:
            moved.append(entry)
            continue
        if entry_kind(entry) == "note" and filename in entry.get("attach", ()):
            others = [name for name in entry.get("attach", ()) if name != filename]
            if not others:
                moved.append(entry)
                removed["notes"].append(str(entry.get("id", "")))
                continue
            entry["attach"] = others
        kept.append(entry)

    if moved:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for entry in moved:
            entry["removed"] = stamp
        state["entries"] = kept
        state.setdefault("removed", []).extend(moved)
        _save_state(target, state, cfg)
    return removed


def snip_rows(cfg: dict) -> list[dict]:
    """Every snip in the active lab, oldest first, for the list in the window.

    Built from the images in the folder and enriched from the record, so the
    list is right even with the lab record switched off, and a snip copied in
    by hand still shows up. Each row carries:

        file, number, time, section, caption, notes (texts attached to it),
        note_entries ({"id", "text"} for each of those notes, for editing),
        path (the image), recorded (whether lab.json has an entry for it)
    """
    target = active_folder(cfg)
    if target is None:
        return []

    state = _load_state(target)
    recorded = state.get("entries", []) if isinstance(state.get("entries"), list) else []
    by_file: dict[str, dict] = {}
    attached: dict[str, list[dict]] = {}
    for entry in recorded:
        if not isinstance(entry, dict):
            continue
        if entry_kind(entry) == "snip" and entry.get("file"):
            by_file[str(entry["file"])] = entry
        elif entry_kind(entry) == "note":
            note = {
                "id": str(entry.get("id", "")),
                "text": str(entry.get("text", "")).strip(),
            }
            for name in entry.get("attach", ()):
                attached.setdefault(str(name), []).append(note)

    rows = []
    for path in _images(target):
        entry = by_file.get(path.name, {})
        match = _NUMBER_RE.match(path.name)
        number = entry.get("number")
        if not isinstance(number, int):
            number = int(match.group(1)) if match else 0
        rows.append(
            {
                "file": path.name,
                "number": number,
                "time": str(entry.get("time", "")),
                "section": entry_section(entry) if entry else "",
                "caption": str(entry.get("caption", "")).strip(),
                "notes": [note["text"] for note in attached.get(path.name, [])],
                "note_entries": [dict(note) for note in attached.get(path.name, [])],
                "path": str(path),
                "recorded": bool(entry),
            }
        )
    rows.sort(key=lambda row: (row["number"], row["file"]))
    return rows


def update_note(cfg: dict, note_id: str, text: str) -> str | None:
    """Rewrite a note's text, or remove the note when the text is emptied.

    Clearing a note and saving is how a note is deleted from the snip editor,
    so an empty text moves the note to the `removed` list in lab.json, the same
    place a removed snip's notes go, rather than leaving an empty quote in
    lab.md.

    Returns "updated", "removed", "unchanged", or None when there is no lab,
    no record, or no such note.
    """
    target = active_folder(cfg)
    if target is None or not cfg.get("lab_index", True):
        return None
    state = _load_state(target)
    if not state:
        return None
    text = str(text or "").strip()
    recorded = state.get("entries", [])
    for index, entry in enumerate(recorded):
        if not isinstance(entry, dict) or entry_kind(entry) != "note":
            continue
        if str(entry.get("id", "")) != str(note_id):
            continue
        if not text:
            entry["removed"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            state.setdefault("removed", []).append(recorded.pop(index))
            _save_state(target, state, cfg)
            return "removed"
        if str(entry.get("text", "")).strip() == text:
            return "unchanged"
        entry["text"] = text
        entry["edited"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _save_state(target, state, cfg)
        return "updated"
    return None


def caption_of(cfg: dict, filename: str) -> str | None:
    """The recorded caption of a snip, or None when it has no record."""
    for entry in reversed(entries(cfg)):
        if isinstance(entry, dict) and entry_kind(entry) == "snip" and entry.get("file") == filename:
            return str(entry.get("caption", "")).strip()
    return None


# -- reading the record ----------------------------------------------------
def entry_kind(entry: dict) -> str:
    """"snip" or "note", including for records written before notes existed."""
    kind = str(entry.get("kind", "")).strip().lower()
    if kind in ("snip", "note"):
        return kind
    return "note" if "text" in entry else "snip"


def entry_section(entry: dict) -> str:
    return normalise_section(entry.get("section", ""))


def entries(cfg: dict) -> list[dict]:
    target = active_folder(cfg)
    if target is None:
        return []
    recorded = _load_state(target).get("entries", [])
    return recorded if isinstance(recorded, list) else []


# -- index -----------------------------------------------------------------
def render_index(state: dict) -> str:
    """Build lab.md: the section tree, with the entries in capture order.

    Sections appear in the order they were first used rather than
    alphabetically, because that is the order the work happened in and the
    order a reader of the writeup will want to follow.
    """
    lines = [f"# {state.get('name', 'lab')}", ""]
    started = str(state.get("started", ""))
    if started:
        lines.append(f"Started {started.replace('T', ' ')[:19]}")
        lines.append("")

    recorded = state.get("entries", [])
    if not isinstance(recorded, list):
        recorded = []

    grouped = _ordered_groups(state)

    # Notes attached to a snip in the same section render under that snip, so
    # they must not also render on their own.
    consumed = _attached_note_ids(grouped)

    lines.extend(_render_entries(grouped.get("", []), consumed))
    for path, depth in _walk_sections(grouped):
        level = min(depth + 2, MAX_HEADING_LEVEL)
        lines.append(f"{'#' * level} {path.rsplit(SECTION_SEPARATOR, 1)[-1]}")
        lines.append("")
        lines.extend(_render_entries(grouped.get(path, []), consumed))

    return "\n".join(lines).rstrip() + "\n"


def _ordered_groups(state: dict, include=()) -> dict[str, list[dict]]:
    """Entries grouped by section, sections in report order.

    Report order is first use, unless the outline has been rearranged: moving
    an entry by hand records `section_order` in lab.json, so emptying the
    first section of its first snip does not quietly reshuffle the report.
    Sections in `include` are added even when empty, so the outline can offer
    them as places to drop things.
    """
    recorded = state.get("entries", [])
    if not isinstance(recorded, list):
        recorded = []
    grouped: dict[str, list[dict]] = {}
    for entry in recorded:
        if isinstance(entry, dict):
            grouped.setdefault(entry_section(entry), []).append(entry)
    for path in include:
        if path:
            grouped.setdefault(normalise_section(path), [])

    order = state.get("section_order")
    if not isinstance(order, list) or not order:
        return grouped
    rank = {normalise_section(p): i for i, p in enumerate(order)}
    keys = list(grouped)
    known = sorted((k for k in keys if k in rank), key=rank.get)
    rest = [k for k in keys if k and k not in rank]
    ordered: dict[str, list[dict]] = {}
    if "" in grouped:
        ordered[""] = grouped[""]
    for key in known + rest:
        if key:
            ordered[key] = grouped[key]
    return ordered


# -- the outline -----------------------------------------------------------
def outline(cfg: dict) -> dict:
    """The shape of lab.md, for the outline tree in the window.

    Returns {"name", "record", "sections": [...]}, where each section is
    {"path", "name", "depth", "entries"} in report order, the top of the report
    first with path "". Entries are what lab.md shows there, in order:

        {"kind": "snip", "key", "file", "label", "caption", "notes": [note...]}
        {"kind": "note", "key", "id", "text", "evidence": [files]}

    A snip's `notes` are those rendered beneath it. The current section is
    included even when nothing is filed in it yet, so it can be dropped onto.
    """
    target = active_folder(cfg)
    if target is None:
        return {"name": "", "record": False, "sections": []}
    record = bool(cfg.get("lab_index", True))
    state = _load_state(target) if record else {}
    current = normalise_section(state.get("section", ""))
    grouped = _ordered_groups(state, include=[current])
    consumed = _attached_note_ids(grouped)

    def nodes(here):
        out = []
        for entry in here:
            if entry_kind(entry) == "note":
                note_id = str(entry.get("id", ""))
                if note_id in consumed:
                    continue
                out.append(
                    {
                        "kind": "note",
                        "key": f"note:{note_id}",
                        "id": note_id,
                        "text": str(entry.get("text", "")).strip(),
                        "evidence": [str(n) for n in entry.get("attach", ()) if str(n).strip()],
                    }
                )
                continue
            filename = str(entry.get("file", ""))
            number = entry.get("number", 0)
            beneath = [
                {
                    "kind": "note",
                    "key": f"note:{note.get('id', '')}",
                    "id": str(note.get("id", "")),
                    "text": str(note.get("text", "")).strip(),
                    "evidence": [filename],
                }
                for note in here
                if entry_kind(note) == "note" and filename in note.get("attach", ())
            ]
            out.append(
                {
                    "kind": "snip",
                    "key": f"snip:{filename}",
                    "file": filename,
                    "label": f"{number:03d}" if isinstance(number, int) else str(number),
                    "caption": str(entry.get("caption", "")).strip(),
                    "notes": beneath,
                }
            )
        return out

    sections = [{"path": "", "name": "", "depth": -1, "entries": nodes(grouped.get("", []))}]
    for path, depth in _walk_sections(grouped):
        sections.append(
            {
                "path": path,
                "name": path.rsplit(SECTION_SEPARATOR, 1)[-1],
                "depth": depth,
                "entries": nodes(grouped.get(path, [])),
            }
        )
    return {"name": state.get("name", target.name), "record": record, "sections": sections}


def move_entry(cfg: dict, key: str, section, before_key: str | None = None) -> bool:
    """Move a snip or note to a section, optionally just before another entry.

    `key` is "snip:<file>" or "note:<id>", as outline() hands out. A snip takes
    the notes rendered beneath it along, so evidence and the sentence about it
    are never separated by a drag. Without `before_key`, or when that entry is
    not in the target section, the entry goes to the end of the section.

    Returns False when there is no lab, no record, or no such entry.
    """
    target = active_folder(cfg)
    if target is None or not cfg.get("lab_index", True):
        return False
    state = _load_state(target)
    recorded = state.get("entries") if state else None
    if not isinstance(recorded, list):
        return False

    moving = _find_entry(recorded, key)
    if moving is None:
        return False
    old_section = entry_section(moving)
    group = [moving]
    if entry_kind(moving) == "snip":
        filename = moving.get("file")
        group += [
            e for e in recorded
            if isinstance(e, dict) and e is not moving
            and entry_kind(e) == "note"
            and entry_section(e) == old_section
            and filename in e.get("attach", ())
        ]

    # Pin the order the sections are in now, before this move can change
    # which section is used first.
    if not isinstance(state.get("section_order"), list):
        state["section_order"] = [p for p in _ordered_groups(state) if p]

    cleaned = normalise_section(section)
    remaining = [e for e in recorded if not any(e is g for g in group)]
    for entry in group:
        entry["section"] = cleaned

    anchor = _find_entry(remaining, before_key) if before_key else None
    if anchor is not None and entry_section(anchor) == cleaned:
        index = next(i for i, e in enumerate(remaining) if e is anchor)
    else:
        index = len(remaining)
        for i in range(len(remaining) - 1, -1, -1):
            entry = remaining[i]
            if isinstance(entry, dict) and entry_section(entry) == cleaned:
                index = i + 1
                break
    state["entries"] = remaining[:index] + group + remaining[index:]
    if cleaned and cleaned not in state["section_order"]:
        state["section_order"].append(cleaned)
    _save_state(target, state, cfg)
    return True


def _find_entry(recorded, key) -> dict | None:
    kind, _, ident = str(key or "").partition(":")
    for entry in recorded:
        if not isinstance(entry, dict):
            continue
        if kind == "snip" and entry_kind(entry) == "snip" and entry.get("file") == ident:
            return entry
        if kind == "note" and entry_kind(entry) == "note" and str(entry.get("id", "")) == ident:
            return entry
    return None


def _attached_note_ids(grouped: dict[str, list[dict]]) -> set[str]:
    """Ids of notes that will be rendered under a snip rather than on their own.

    Only within a section: a note attached to a snip filed somewhere else stays
    where it was written and carries a reference to the evidence instead, so a
    note never silently moves out of the section it was taken in.
    """
    consumed: set[str] = set()
    for here in grouped.values():
        files = {
            entry.get("file") for entry in here if entry_kind(entry) == "snip"
        }
        for entry in here:
            if entry_kind(entry) != "note":
                continue
            if any(name in files for name in entry.get("attach", ())):
                consumed.add(str(entry.get("id", "")))
    return consumed


def _render_entries(here, consumed) -> list[str]:
    lines: list[str] = []
    for entry in here:
        if entry_kind(entry) == "note":
            if str(entry.get("id", "")) in consumed:
                continue  # rendered beneath its snip
            lines.extend(_render_note(entry))
        else:
            lines.extend(_render_snip(entry, here))
    return lines


def _render_snip(entry: dict, section_entries) -> list[str]:
    number = entry.get("number", 0)
    label = f"{number:03d}" if isinstance(number, int) else str(number)
    filename = str(entry.get("file", ""))

    header = f"**{label}**"
    when = str(entry.get("time", "")).strip()
    if when:
        header += f" - {when}"
    caption = str(entry.get("caption", "")).strip()
    if caption:
        header += f" - {caption}"

    lines = [header, "", f"![{label}]({filename})", ""]
    for note in section_entries:
        if entry_kind(note) != "note":
            continue
        if filename and filename in note.get("attach", ()):
            for chunk in str(note.get("text", "")).strip().splitlines():
                lines.append(f"> {chunk}" if chunk.strip() else ">")
            lines.append("")
    return lines


def _render_note(entry: dict) -> list[str]:
    lines = [str(entry.get("text", "")).strip(), ""]
    attached = [str(name) for name in entry.get("attach", ()) if str(name).strip()]
    if attached:
        # Reaching here means the snip is filed in another section, so the note
        # points at the evidence rather than being dragged away from where it
        # was written.
        lines.append(f"_Evidence: {', '.join(attached)}_")
        lines.append("")
    return lines


def _walk_sections(grouped) -> list[tuple[str, int]]:
    """Every section path, parents before children, in first-use order.

    A path like `10.0.0.3/SMB` implies a `10.0.0.3` node even when nothing was
    ever filed directly under it, so the intermediate headings are created here
    rather than being left as gaps in the tree.
    """
    tree: dict = {}
    for path in grouped:
        if not path:
            continue
        node = tree
        for part in path.split(SECTION_SEPARATOR):
            node = node.setdefault(part, {})

    out: list[tuple[str, int]] = []

    def walk(node: dict, prefix: str, depth: int) -> None:
        for part, child in node.items():
            full = f"{prefix}{SECTION_SEPARATOR}{part}" if prefix else part
            out.append((full, depth))
            walk(child, full, depth + 1)

    walk(tree, "", 0)
    return out


# -- internals -------------------------------------------------------------
def _blank_state(name: str) -> dict:
    return {"name": name, "started": _now_iso(), "section": "", "entries": []}


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


def _next_note_id(state: dict) -> str:
    """One past the highest note id in the record.

    Derived rather than counted for the same reason as the snip numbers: a
    hand-edited record with entries removed still produces an id that collides
    with nothing.
    """
    highest = 0
    for entry in state.get("entries", []):
        if not isinstance(entry, dict):
            continue
        match = _NOTE_ID_RE.match(str(entry.get("id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"n{highest + 1:03d}"


def _load_state(target: Path) -> dict:
    try:
        with open(target / STATE_NAME, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save_state(target: Path, state: dict, cfg: dict) -> None:
    """Persist the record and its rendered index, or report the exact failure."""
    try:
        storage.write_atomic(
            target / STATE_NAME, json.dumps(state, indent=2).encode("utf-8")
        )
    except OSError as exc:
        raise LabError(f"could not update {STATE_NAME}: {exc}") from exc
    try:
        storage.write_atomic(
            target / INDEX_NAME, render_index(state).encode("utf-8")
        )
    except OSError as exc:
        raise LabError(
            f"the lab record was saved but {INDEX_NAME} could not be rendered: {exc}"
        ) from exc


def _ensure_gitignore(base: Path) -> None:
    path = base / GITIGNORE_NAME
    if path.exists():
        return
    try:
        storage.write_atomic(path, GITIGNORE_BODY.encode("utf-8"))
    except OSError as exc:
        raise LabError(f"could not write the protective {GITIGNORE_NAME}: {exc}") from exc


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
