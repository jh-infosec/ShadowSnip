"""The outline of lab.md, and rearranging it by moving entries."""

from __future__ import annotations

import json

import lab


def _start(cfg, name="box"):
    folder = lab.start(cfg, name)
    cfg["active_lab"] = name
    return folder


def _snip(cfg, section, data=b"x"):
    lab.set_section(cfg, section)
    return lab.save(data, "png", cfg).name


def _layout(cfg):
    """[(section path, [entry keys])] as the outline reports them."""
    return [(s["path"], [e["key"] for e in s["entries"]]) for s in lab.outline(cfg)["sections"]]


def _md(folder):
    return (folder / lab.INDEX_NAME).read_text(encoding="utf-8")


def test_the_outline_follows_the_report(cfg):
    _start(cfg)
    a = _snip(cfg, "")
    b = _snip(cfg, "host/smb")
    note = lab.add_note(cfg, "anonymous allowed", attach=[b])
    loose = lab.add_note(cfg, "try null session next")

    out = lab.outline(cfg)

    assert out["name"] == "box" and out["record"] is True
    assert _layout(cfg) == [
        ("", [f"snip:{a}"]),
        ("host", []),
        ("host/smb", [f"snip:{b}", f"note:{loose['id']}"]),
    ]
    smb = out["sections"][2]
    assert smb["name"] == "smb" and smb["depth"] == 1
    assert smb["entries"][0]["notes"][0]["id"] == note["id"]
    assert smb["entries"][0]["label"] == "002"


def test_the_current_section_is_offered_even_when_empty(cfg):
    _start(cfg)
    lab.set_section(cfg, "host/web")
    assert ("host/web", []) in _layout(cfg)


def test_moving_a_snip_to_another_section(cfg):
    folder = _start(cfg)
    a = _snip(cfg, "")
    lab.set_section(cfg, "host/smb")

    assert lab.move_entry(cfg, f"snip:{a}", "host/smb")

    assert ("host/smb", [f"snip:{a}"]) in _layout(cfg)
    assert _md(folder).index("### smb") < _md(folder).index(a)


def test_a_snip_takes_its_notes_with_it(cfg):
    _start(cfg)
    a = _snip(cfg, "one")
    note = lab.add_note(cfg, "about a", attach=[a])
    _snip(cfg, "two")

    lab.move_entry(cfg, f"snip:{a}", "two")

    two = [s for s in lab.outline(cfg)["sections"] if s["path"] == "two"][0]
    moved = [e for e in two["entries"] if e["key"] == f"snip:{a}"][0]
    assert [n["id"] for n in moved["notes"]] == [note["id"]]


def test_reordering_within_a_section(cfg):
    _start(cfg)
    a = _snip(cfg, "s")
    b = _snip(cfg, "s")
    c = _snip(cfg, "s")

    lab.move_entry(cfg, f"snip:{c}", "s", before_key=f"snip:{a}")

    assert ("s", [f"snip:{c}", f"snip:{a}", f"snip:{b}"]) in _layout(cfg)


def test_before_an_entry_in_another_section_goes_to_the_end(cfg):
    _start(cfg)
    a = _snip(cfg, "s")
    b = _snip(cfg, "t")
    c = _snip(cfg, "s")

    lab.move_entry(cfg, f"snip:{b}", "s", before_key="snip:nope.png")

    assert ("s", [f"snip:{a}", f"snip:{c}", f"snip:{b}"]) in _layout(cfg)


def test_section_order_survives_emptying_the_first_section(cfg):
    folder = _start(cfg)
    first = _snip(cfg, "recon")
    _snip(cfg, "exploit")
    _snip(cfg, "recon")

    # Moving recon's first snip to the end of exploit would, by first use,
    # put exploit ahead of recon. The pinned order keeps recon first.
    lab.move_entry(cfg, f"snip:{first}", "exploit")

    paths = [s["path"] for s in lab.outline(cfg)["sections"]]
    assert paths.index("recon") < paths.index("exploit")
    assert _md(folder).index("## recon") < _md(folder).index("## exploit")
    assert json.loads((folder / lab.STATE_NAME).read_text())["section_order"][:2] == ["recon", "exploit"]


def test_a_loose_note_can_be_moved(cfg):
    _start(cfg)
    note = lab.add_note(cfg, "loose")
    _snip(cfg, "s")

    assert lab.move_entry(cfg, f"note:{note['id']}", "s")
    assert f"note:{note['id']}" in dict(_layout(cfg))["s"]


def test_nothing_moves_without_a_lab_record_or_entry(cfg):
    _start(cfg)
    assert lab.move_entry(cfg, "snip:nope.png", "s") is False
    assert lab.move_entry(cfg, "garbage", "s") is False
    cfg["lab_index"] = False
    assert lab.move_entry(cfg, "note:n001", "s") is False
    assert lab.outline(cfg)["record"] is False


def test_no_lab_no_outline(cfg):
    assert lab.outline(cfg) == {"name": "", "record": False, "sections": []}
