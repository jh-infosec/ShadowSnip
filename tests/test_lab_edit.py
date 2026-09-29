"""Editing notes after the fact, and the extra fields the snip list reads."""

from __future__ import annotations

import json

import lab


def _start(cfg, name="box"):
    folder = lab.start(cfg, name)
    cfg["active_lab"] = name
    return folder


def _state(folder):
    return json.loads((folder / lab.STATE_NAME).read_text(encoding="utf-8"))


def test_a_note_can_be_rewritten(cfg):
    folder = _start(cfg)
    snip = lab.save(b"x", "png", cfg)
    note = lab.add_note(cfg, "frist draft", attach=[snip.name])

    assert lab.update_note(cfg, note["id"], "first draft") == "updated"

    (entry,) = [e for e in _state(folder)["entries"] if e.get("id") == note["id"]]
    assert entry["text"] == "first draft"
    assert entry["edited"]
    assert "first draft" in (folder / lab.INDEX_NAME).read_text(encoding="utf-8")


def test_an_emptied_note_is_removed_not_left_blank(cfg):
    folder = _start(cfg)
    snip = lab.save(b"x", "png", cfg)
    note = lab.add_note(cfg, "wrong", attach=[snip.name])

    assert lab.update_note(cfg, note["id"], "   ") == "removed"

    state = _state(folder)
    assert all(e.get("id") != note["id"] for e in state["entries"])
    assert state["removed"][0]["id"] == note["id"]


def test_the_same_text_writes_nothing(cfg, monkeypatch):
    _start(cfg)
    note = lab.add_note(cfg, "same")
    writes = []
    monkeypatch.setattr(lab, "_save_state", lambda *a: writes.append(a))

    assert lab.update_note(cfg, note["id"], " same ") == "unchanged"
    assert writes == []


def test_an_unknown_note_or_no_lab_is_none(cfg):
    _start(cfg)
    assert lab.update_note(cfg, "n999", "x") is None
    lab.stop(cfg)
    assert lab.update_note(cfg, "n001", "x") is None


def test_caption_of(cfg):
    _start(cfg)
    snip = lab.save(b"x", "png", cfg)
    assert lab.caption_of(cfg, snip.name) == ""
    lab.set_caption(cfg, snip.name, "smb shares")
    assert lab.caption_of(cfg, snip.name) == "smb shares"
    assert lab.caption_of(cfg, "999_nope.png") is None


def test_rows_carry_the_path_note_ids_and_record_state(cfg):
    folder = _start(cfg)
    snip = lab.save(b"x", "png", cfg)
    note = lab.add_note(cfg, "hi", attach=[snip.name])
    (folder / "050_by-hand.png").write_bytes(b"y")

    first, by_hand = lab.snip_rows(cfg)

    assert first["path"] == str(snip)
    assert first["note_entries"] == [{"id": note["id"], "text": "hi"}]
    assert first["recorded"] is True
    assert by_hand["recorded"] is False
