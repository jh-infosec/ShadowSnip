"""Removing a snip from a lab, and the snip list shown while a lab runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import lab


def _start(cfg, name="htb-lame"):
    folder = lab.start(cfg, name)
    cfg["active_lab"] = name
    return folder


def _state(folder: Path) -> dict:
    return json.loads((folder / lab.STATE_NAME).read_text(encoding="utf-8"))


# -- remove_snip ------------------------------------------------------------
def test_a_removed_snip_is_moved_not_deleted(cfg):
    folder = _start(cfg)
    first = lab.save(b"one", "png", cfg)
    second = lab.save(b"two", "png", cfg)

    removed = lab.remove_snip(cfg, second.name)

    assert removed == {"file": second.name, "number": 2, "notes": []}
    assert not second.exists()
    kept = folder / lab.REMOVED_DIR / second.name
    assert kept.read_bytes() == b"two"
    assert first.exists()
    assert lab.count(cfg) == 1


def test_a_removed_snip_leaves_the_record_and_the_index(cfg):
    folder = _start(cfg)
    lab.save(b"one", "png", cfg)
    wrong = lab.save(b"two", "png", cfg)

    lab.remove_snip(cfg, wrong.name)

    state = _state(folder)
    assert [e["file"] for e in state["entries"]] != [wrong.name]
    assert wrong.name not in [e.get("file") for e in state["entries"]]
    assert state["removed"][0]["file"] == wrong.name
    assert state["removed"][0]["removed"]
    assert wrong.name not in (folder / lab.INDEX_NAME).read_text(encoding="utf-8")


def test_a_note_attached_only_to_the_removed_snip_goes_with_it(cfg):
    folder = _start(cfg)
    wrong = lab.save(b"x", "png", cfg)
    note = lab.add_note(cfg, "this is the wrong box", attach=[wrong.name])

    removed = lab.remove_snip(cfg, wrong.name)

    assert removed["notes"] == [note["id"]]
    state = _state(folder)
    assert all(e.get("id") != note["id"] for e in state["entries"])
    assert any(e.get("id") == note["id"] for e in state["removed"])
    assert "wrong box" not in (folder / lab.INDEX_NAME).read_text(encoding="utf-8")


def test_a_note_shared_with_another_snip_stays_and_loses_the_reference(cfg):
    folder = _start(cfg)
    good = lab.save(b"a", "png", cfg)
    wrong = lab.save(b"b", "png", cfg)
    note = lab.add_note(cfg, "both show the share", attach=[good.name, wrong.name])

    removed = lab.remove_snip(cfg, wrong.name)

    assert removed["notes"] == []
    kept = [e for e in _state(folder)["entries"] if e.get("id") == note["id"]]
    assert kept and kept[0]["attach"] == [good.name]


def test_unattached_notes_are_untouched(cfg):
    folder = _start(cfg)
    wrong = lab.save(b"b", "png", cfg)
    lab.add_note(cfg, "loose thought")

    lab.remove_snip(cfg, wrong.name)

    assert [e["text"] for e in _state(folder)["entries"]] == ["loose thought"]


def test_numbering_reuses_the_removed_number(cfg):
    """The wrong last snip removed, the next one takes its place in the sequence."""
    _start(cfg)
    lab.save(b"a", "png", cfg)
    wrong = lab.save(b"b", "png", cfg)
    lab.remove_snip(cfg, wrong.name)

    replacement = lab.save(b"c", "png", cfg)

    assert replacement.name.startswith("002_")


def test_removing_the_same_name_twice_keeps_both_copies(cfg):
    folder = _start(cfg)
    snip = lab.save(b"first", "png", cfg)
    lab.remove_snip(cfg, snip.name)
    snip.write_bytes(b"second")

    lab.remove_snip(cfg, snip.name)

    held = sorted(p.read_bytes() for p in (folder / lab.REMOVED_DIR).iterdir())
    assert held == [b"first", b"second"]


def test_remove_works_with_the_record_switched_off(cfg):
    cfg["lab_index"] = False
    folder = _start(cfg)
    snip = lab.save(b"x", "png", cfg)

    assert lab.remove_snip(cfg, snip.name) is not None
    assert (folder / lab.REMOVED_DIR / snip.name).exists()


@pytest.mark.parametrize(
    "name", ["", "missing.png", "lab.json", "lab.md", "../outside.png", "sub\\x.png"]
)
def test_only_a_snip_in_the_lab_folder_can_be_removed(cfg, name, tmp_path):
    folder = _start(cfg)
    (folder.parent / "outside.png").write_bytes(b"not ours")

    assert lab.remove_snip(cfg, name) is None
    assert (folder.parent / "outside.png").exists()
    assert (folder / lab.STATE_NAME).exists()


def test_remove_needs_an_active_lab(cfg):
    folder = _start(cfg)
    snip = lab.save(b"x", "png", cfg)
    lab.stop(cfg)

    assert lab.remove_snip(cfg, snip.name) is None
    assert snip.exists()


def test_a_failed_move_is_reported(cfg, monkeypatch):
    _start(cfg)
    snip = lab.save(b"x", "png", cfg)

    def refuse(self, target):
        raise PermissionError("in use")

    monkeypatch.setattr(Path, "replace", refuse)
    with pytest.raises(lab.LabError, match="in use"):
        lab.remove_snip(cfg, snip.name)


def test_the_removed_folder_is_not_counted_or_listed(cfg):
    _start(cfg)
    snip = lab.save(b"x", "png", cfg)
    lab.remove_snip(cfg, snip.name)

    assert lab.count(cfg) == 0
    assert lab.snip_rows(cfg) == []


# -- snip_rows --------------------------------------------------------------
def test_rows_carry_section_caption_and_attached_notes(cfg):
    _start(cfg)
    lab.set_section(cfg, "10.10.10.3 / SMB")
    snip = lab.save(b"x", "png", cfg)
    lab.set_caption(cfg, snip.name, "anonymous login")
    lab.add_note(cfg, "guest allowed", attach=[snip.name])
    lab.add_note(cfg, "not attached")

    (row,) = lab.snip_rows(cfg)

    assert row["file"] == snip.name
    assert row["number"] == 1
    assert row["section"] == "10.10.10.3/SMB"
    assert row["caption"] == "anonymous login"
    assert row["notes"] == ["guest allowed"]
    assert row["time"]


def test_rows_are_in_capture_order(cfg):
    _start(cfg)
    names = [lab.save(bytes([i]), "png", cfg).name for i in range(3)]

    assert [row["file"] for row in lab.snip_rows(cfg)] == names


def test_rows_come_from_the_folder_when_there_is_no_record(cfg):
    cfg["lab_index"] = False
    _start(cfg)
    snip = lab.save(b"x", "png", cfg)

    (row,) = lab.snip_rows(cfg)

    assert row["file"] == snip.name
    assert row["number"] == 1
    assert row["section"] == "" and row["caption"] == "" and row["notes"] == []


def test_a_hand_copied_image_shows_up(cfg):
    folder = _start(cfg)
    (folder / "010_manual.png").write_bytes(b"x")

    assert [row["number"] for row in lab.snip_rows(cfg)] == [10]


def test_no_rows_without_a_lab(cfg):
    assert lab.snip_rows(cfg) == []


# -- 0.7.6: a failed record save puts the image back ------------------------------------
def _fail_writes_to(monkeypatch, name):
    import storage

    real = storage.write_atomic

    def write(path, data):
        if Path(path).name == name:
            raise OSError("disk full")
        return real(path, data)

    monkeypatch.setattr(storage, "write_atomic", write)


def test_a_failed_record_save_puts_the_image_back(cfg, monkeypatch):
    folder = _start(cfg)
    snip = lab.save(b"evidence", "png", cfg)
    _fail_writes_to(monkeypatch, lab.STATE_NAME)

    with pytest.raises(lab.LabError, match="Nothing was removed"):
        lab.remove_snip(cfg, snip.name)

    assert snip.read_bytes() == b"evidence"
    assert not (folder / lab.REMOVED_DIR / snip.name).exists()
    assert [e["file"] for e in _state(folder)["entries"]] == [snip.name]


def test_a_failed_index_render_keeps_the_removal(cfg, monkeypatch):
    """The record is the truth; lab.md is re-rendered on the next change."""
    folder = _start(cfg)
    snip = lab.save(b"evidence", "png", cfg)
    _fail_writes_to(monkeypatch, lab.INDEX_NAME)

    with pytest.raises(lab.LabError):
        lab.remove_snip(cfg, snip.name)

    assert not snip.exists()
    assert (folder / lab.REMOVED_DIR / snip.name).exists()
    assert _state(folder)["entries"] == []


def test_if_the_image_cannot_go_back_the_error_says_where_it_is(cfg, monkeypatch):
    folder = _start(cfg)
    snip = lab.save(b"evidence", "png", cfg)
    _fail_writes_to(monkeypatch, lab.STATE_NAME)
    real_replace = Path.replace

    def replace(self, target):
        if Path(self).parent.name == lab.REMOVED_DIR:
            raise OSError("locked")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(lab.LabError, match=f"{lab.REMOVED_DIR}/{snip.name}"):
        lab.remove_snip(cfg, snip.name)
