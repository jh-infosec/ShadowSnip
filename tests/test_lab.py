"""Lab sessions: numbering, the lab.json record, and the rendered index."""

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


# -- locations -------------------------------------------------------------
def test_root_defaults_to_a_labs_folder_in_the_save_folder(cfg):
    assert lab.root(cfg) == Path(cfg["save_dir"]) / "labs"


def test_configured_lab_root_wins(cfg, tmp_path):
    cfg["lab_root"] = str(tmp_path / "elsewhere")
    assert lab.root(cfg) == tmp_path / "elsewhere"


def test_no_lab_is_active_by_default(cfg):
    assert lab.is_active(cfg) is False
    assert lab.active_name(cfg) == ""
    assert lab.active_folder(cfg) is None


# -- lifecycle -------------------------------------------------------------
def test_start_creates_the_folder_and_the_state_file(cfg):
    folder = _start(cfg)
    assert folder.is_dir()
    assert _state(folder)["name"] == "htb-lame"
    assert _state(folder)["entries"] == []


def test_start_writes_a_gitignore_into_the_labs_root(cfg):
    """Labs collect hashes and tokens by design; none of it belongs in a repo."""
    _start(cfg)
    ignore = lab.root(cfg) / lab.GITIGNORE_NAME
    assert ignore.read_text(encoding="utf-8").strip().endswith("*")


def test_an_existing_gitignore_is_not_overwritten(cfg):
    root = lab.root(cfg)
    root.mkdir(parents=True)
    (root / lab.GITIGNORE_NAME).write_text("# mine\n", encoding="utf-8")
    _start(cfg)
    assert (root / lab.GITIGNORE_NAME).read_text(encoding="utf-8") == "# mine\n"


@pytest.mark.parametrize("name", ["", "   ", "\t"])
def test_a_lab_needs_a_name(cfg, name):
    with pytest.raises(lab.LabError):
        lab.start(cfg, name)


def test_an_unusable_name_is_reported_rather_than_silently_replaced(cfg):
    """pathlib rejects a null byte before the OS is even asked."""
    with pytest.raises(lab.LabError):
        lab.start(cfg, "bad\x00name")


def test_start_trims_surrounding_whitespace(cfg):
    assert lab.start(cfg, "  spaced  ").name == "spaced"


def test_stop_clears_the_active_lab_and_returns_its_name(cfg):
    _start(cfg)
    assert lab.stop(cfg) == "htb-lame"
    assert lab.is_active(cfg) is False


def test_resuming_keeps_the_existing_record(cfg):
    folder = _start(cfg)
    lab.save(b"png", "png", cfg)
    lab.stop(cfg)

    lab.start(cfg, "htb-lame")
    assert len(_state(folder)["entries"]) == 1


# -- saving and numbering --------------------------------------------------
def test_save_does_nothing_without_an_active_lab(cfg):
    assert lab.save(b"png", "png", cfg) is None


def test_snips_are_numbered_in_capture_order(cfg):
    _start(cfg)
    first = lab.save(b"a", "png", cfg)
    second = lab.save(b"b", "png", cfg)
    assert first.name.startswith("001_")
    assert second.name.startswith("002_")
    assert second.read_bytes() == b"b"


def test_numbering_continues_after_a_resume(cfg):
    _start(cfg)
    lab.save(b"a", "png", cfg)
    lab.stop(cfg)
    _start(cfg)
    assert lab.save(b"b", "png", cfg).name.startswith("002_")


def test_numbering_is_derived_from_the_filenames_not_the_state_file(cfg):
    """Dropping images in by hand, or losing lab.json, still numbers sensibly."""
    folder = _start(cfg)
    (folder / "007_2026-01-01_00-00-00.png").write_bytes(b"x")
    assert lab.save(b"a", "png", cfg).name.startswith("008_")


def test_numbering_survives_a_deleted_state_file(cfg):
    folder = _start(cfg)
    lab.save(b"a", "png", cfg)
    (folder / lab.STATE_NAME).unlink()
    assert lab.save(b"b", "png", cfg).name.startswith("002_")


def test_the_extension_follows_the_disk_format(cfg):
    _start(cfg)
    assert lab.save(b"x", "webp", cfg).suffix == ".webp"


def test_count_counts_images_only(cfg):
    _start(cfg)
    lab.save(b"a", "png", cfg)
    lab.save(b"b", "png", cfg)
    assert lab.count(cfg) == 2  # lab.json and lab.md are not snips


def test_count_is_zero_without_an_active_lab(cfg):
    assert lab.count(cfg) == 0


# -- the index -------------------------------------------------------------
def test_save_records_an_entry_and_renders_the_index(cfg):
    folder = _start(cfg)
    path = lab.save(b"a", "png", cfg)

    entry = _state(folder)["entries"][0]
    assert entry["file"] == path.name
    assert entry["number"] == 1
    assert entry["caption"] == ""

    index = (folder / lab.INDEX_NAME).read_text(encoding="utf-8")
    assert index.startswith("# htb-lame")
    assert f"![001]({path.name})" in index


def test_the_index_can_be_switched_off(cfg):
    cfg["lab_index"] = False
    folder = _start(cfg)
    path = lab.save(b"a", "png", cfg)
    assert path.exists()
    assert _state(folder)["entries"] == []


def test_a_caption_lands_in_the_record_and_the_index(cfg):
    folder = _start(cfg)
    path = lab.save(b"a", "png", cfg)

    assert lab.set_caption(cfg, path.name, "  root shell via CVE-2019-0708  ") is True
    assert _state(folder)["entries"][0]["caption"] == "root shell via CVE-2019-0708"
    assert "root shell via CVE-2019-0708" in (folder / lab.INDEX_NAME).read_text(
        encoding="utf-8"
    )


def test_a_caption_for_an_unknown_file_is_refused(cfg):
    _start(cfg)
    lab.save(b"a", "png", cfg)
    assert lab.set_caption(cfg, "999_nope.png", "text") is False


def test_a_caption_without_an_active_lab_is_refused(cfg):
    assert lab.set_caption(cfg, "001_x.png", "text") is False


def test_the_index_is_re_rendered_rather_than_appended_to(cfg):
    """A caption edits one field and re-renders; the markdown is never patched."""
    folder = _start(cfg)
    first = lab.save(b"a", "png", cfg)
    second = lab.save(b"b", "png", cfg)
    lab.set_caption(cfg, first.name, "first")

    index = (folder / lab.INDEX_NAME).read_text(encoding="utf-8")
    assert index.count(f"![001]({first.name})") == 1
    assert index.index(first.name) < index.index(second.name)


def test_render_index_shape():
    rendered = lab.render_index(
        {
            "name": "demo",
            "started": "2026-08-11T14:30:00",
            "entries": [
                {"file": "001_x.png", "number": 1, "time": "2026-08-11 14:31:07", "caption": "note"},
                {"file": "002_y.png", "number": 2, "time": "2026-08-11 14:33:52", "caption": ""},
            ],
        }
    )
    assert rendered.startswith("# demo\n")
    assert "Started 2026-08-11 14:30:00" in rendered
    assert "note" in rendered
    assert "![002](002_y.png)" in rendered
    assert rendered.endswith("\n")


def test_render_index_handles_an_empty_lab():
    assert lab.render_index({"name": "empty", "entries": []}).startswith("# empty")


# -- sections --------------------------------------------------------------
@pytest.mark.parametrize(
    "given,expected",
    [
        ("  10.0.0.3 / SMB  ", "10.0.0.3/SMB"),
        ("a//b", "a/b"),
        ("/a/", "a"),
        ("one   two/three", "one two/three"),
        ("", ""),
        ("   ", ""),
        (None, ""),
        ("a/b/c/d/e/f/g/h", "a/b/c/d/e/f"),  # capped at MAX_SECTION_DEPTH
    ],
)
def test_section_paths_are_normalised(given, expected):
    assert lab.normalise_section(given) == expected


def test_a_section_part_is_capped_in_length():
    part = lab.normalise_section("x" * 500)
    assert len(part) == lab.MAX_SECTION_PART


def test_no_section_without_an_active_lab(cfg):
    assert lab.section(cfg) == ""
    assert lab.set_section(cfg, "anything") == ""


def test_the_section_is_stored_and_read_back(cfg):
    _start(cfg)
    assert lab.set_section(cfg, " 10.0.0.3 / SMB ") == "10.0.0.3/SMB"
    assert lab.section(cfg) == "10.0.0.3/SMB"


def test_the_section_survives_a_stop_and_resume(cfg):
    """It lives in lab.json, not the config, so it belongs to the lab."""
    _start(cfg)
    lab.set_section(cfg, "10.0.0.3/SMB")
    lab.stop(cfg)
    _start(cfg)
    assert lab.section(cfg) == "10.0.0.3/SMB"


def test_setting_the_same_section_does_not_rewrite_the_file(cfg):
    """editingFinished fires on focus loss; that must not churn lab.json."""
    folder = _start(cfg)
    lab.set_section(cfg, "recon")
    before = (folder / lab.STATE_NAME).stat().st_mtime_ns
    assert lab.set_section(cfg, " recon ") == "recon"
    assert (folder / lab.STATE_NAME).stat().st_mtime_ns == before


def test_a_snip_records_the_section_it_was_taken_in(cfg):
    folder = _start(cfg)
    lab.set_section(cfg, "10.0.0.3/SMB")
    lab.save(b"a", "png", cfg)
    assert _state(folder)["entries"][-1]["section"] == "10.0.0.3/SMB"


# -- the section picker ----------------------------------------------------
def test_no_sections_without_an_active_lab(cfg):
    assert lab.sections(cfg) == []


def test_sections_lists_what_the_lab_has_used(cfg):
    _start(cfg)
    lab.set_section(cfg, "recon")
    lab.save(b"a", "png", cfg)
    lab.set_section(cfg, "exploit")
    lab.add_note(cfg, "note")
    assert lab.sections(cfg) == ["recon", "exploit"]


def test_sections_includes_ancestors_never_used_directly(cfg):
    """`a/b` is a heading under `a`, so going back up a level must be offered."""
    _start(cfg)
    lab.set_section(cfg, "10.0.0.3/SMB/shares")
    lab.add_note(cfg, "note")
    assert lab.sections(cfg) == ["10.0.0.3", "10.0.0.3/SMB", "10.0.0.3/SMB/shares"]


def test_sections_are_listed_parents_first_in_first_use_order(cfg):
    _start(cfg)
    lab.set_section(cfg, "zulu/two")
    lab.add_note(cfg, "note")
    lab.set_section(cfg, "alpha")
    lab.add_note(cfg, "note")
    assert lab.sections(cfg) == ["zulu", "zulu/two", "alpha"]


def test_sections_has_no_duplicates(cfg):
    _start(cfg)
    lab.set_section(cfg, "recon")
    lab.add_note(cfg, "one")
    lab.add_note(cfg, "two")
    lab.save(b"a", "png", cfg)
    assert lab.sections(cfg) == ["recon"]


def test_the_current_section_is_offered_before_anything_is_filed_in_it(cfg):
    _start(cfg)
    lab.set_section(cfg, "recon")
    assert lab.sections(cfg) == ["recon"]


def test_the_root_is_not_offered_as_a_section(cfg):
    _start(cfg)
    lab.save(b"a", "png", cfg)  # filed at the root
    assert lab.sections(cfg) == []


# -- moving a snip ---------------------------------------------------------
def test_moving_a_snip_refiles_it(cfg):
    folder = _start(cfg)
    path = lab.save(b"a", "png", cfg)  # taken before any section was set
    lab.set_section(cfg, "10.0.0.3/SMB")

    assert lab.move_snip(cfg, path.name, lab.section(cfg)) == "10.0.0.3/SMB"
    assert _state(folder)["entries"][0]["section"] == "10.0.0.3/SMB"


def test_moving_a_snip_reunites_it_with_its_attached_note(cfg):
    """The whole point: snip first, name the section after, notes follow."""
    folder = _start(cfg)
    path = lab.save(b"a", "png", cfg)
    lab.set_section(cfg, "SMB")
    lab.add_note(cfg, "world-writable", attach=[path.name])

    index = (folder / lab.INDEX_NAME).read_text(encoding="utf-8")
    assert "_Evidence:" in index  # orphaned: note here, snip at the root

    lab.move_snip(cfg, path.name, "SMB")
    index = (folder / lab.INDEX_NAME).read_text(encoding="utf-8")
    assert "_Evidence:" not in index
    assert "> world-writable" in index
    assert index.index("## SMB") < index.index(f"![001]({path.name})")


def test_moving_a_snip_to_the_same_section_is_a_no_op(cfg):
    folder = _start(cfg)
    lab.set_section(cfg, "recon")
    path = lab.save(b"a", "png", cfg)
    before = (folder / lab.STATE_NAME).stat().st_mtime_ns

    assert lab.move_snip(cfg, path.name, "recon") == "recon"
    assert (folder / lab.STATE_NAME).stat().st_mtime_ns == before


def test_a_snip_can_be_moved_back_to_the_root(cfg):
    folder = _start(cfg)
    lab.set_section(cfg, "recon")
    path = lab.save(b"a", "png", cfg)
    assert lab.move_snip(cfg, path.name, "") == ""
    assert _state(folder)["entries"][0]["section"] == ""


def test_moving_normalises_the_section(cfg):
    _start(cfg)
    path = lab.save(b"a", "png", cfg)
    assert lab.move_snip(cfg, path.name, "  10.0.0.3 / SMB  ") == "10.0.0.3/SMB"


def test_moving_an_unknown_snip_is_refused(cfg):
    _start(cfg)
    lab.save(b"a", "png", cfg)
    assert lab.move_snip(cfg, "999_nope.png", "recon") is None


def test_moving_without_an_active_lab_is_refused(cfg):
    assert lab.move_snip(cfg, "001_x.png", "recon") is None


def test_moving_needs_the_lab_record(cfg):
    cfg["lab_index"] = False
    _start(cfg)
    assert lab.move_snip(cfg, "001_x.png", "recon") is None


# -- notes -----------------------------------------------------------------
def test_a_note_is_recorded_in_the_current_section(cfg):
    folder = _start(cfg)
    lab.set_section(cfg, "10.0.0.3/SMB")
    entry = lab.add_note(cfg, "  anonymous login allowed  ")

    assert entry["kind"] == "note"
    assert entry["id"] == "n001"
    assert entry["text"] == "anonymous login allowed"
    assert entry["section"] == "10.0.0.3/SMB"
    assert _state(folder)["entries"][-1] == entry


def test_note_ids_increment(cfg):
    _start(cfg)
    assert lab.add_note(cfg, "one")["id"] == "n001"
    assert lab.add_note(cfg, "two")["id"] == "n002"


def test_note_ids_are_derived_from_the_record_not_a_counter(cfg):
    """A hand-edited record with entries removed still cannot collide."""
    folder = _start(cfg)
    lab.add_note(cfg, "one")
    lab.add_note(cfg, "two")

    state = _state(folder)
    state["entries"] = [e for e in state["entries"] if e.get("id") != "n001"]
    (folder / lab.STATE_NAME).write_text(json.dumps(state), encoding="utf-8")

    assert lab.add_note(cfg, "three")["id"] == "n003"


@pytest.mark.parametrize("text", ["", "   ", "\n\t ", None])
def test_an_empty_note_is_refused(cfg, text):
    _start(cfg)
    assert lab.add_note(cfg, text) is None


def test_a_note_without_an_active_lab_is_refused(cfg):
    assert lab.add_note(cfg, "text") is None


def test_notes_need_the_lab_record(cfg):
    cfg["lab_index"] = False
    _start(cfg)
    assert lab.add_note(cfg, "text") is None


def test_note_count(cfg):
    _start(cfg)
    lab.save(b"a", "png", cfg)
    lab.add_note(cfg, "one")
    lab.add_note(cfg, "two")
    assert lab.note_count(cfg) == 2
    assert lab.count(cfg) == 1  # notes are not snips


def test_attachments_are_recorded(cfg):
    _start(cfg)
    path = lab.save(b"a", "png", cfg)
    entry = lab.add_note(cfg, "world-writable", attach=[path.name, "", "  "])
    assert entry["attach"] == [path.name]


# -- reading the record ----------------------------------------------------
def test_entry_kind_defaults_for_records_written_before_notes_existed():
    assert lab.entry_kind({"file": "001_x.png"}) == "snip"
    assert lab.entry_kind({"text": "a note"}) == "note"
    assert lab.entry_kind({"kind": "note", "text": "x"}) == "note"
    assert lab.entry_kind({"kind": "nonsense", "file": "x.png"}) == "snip"


def test_entries_is_empty_without_an_active_lab(cfg):
    assert lab.entries(cfg) == []


# -- the section tree ------------------------------------------------------
def _render(entries, **extra):
    state = {"name": "demo", "entries": entries}
    state.update(extra)
    return lab.render_index(state)


def test_sections_become_nested_headings():
    rendered = _render(
        [
            {"kind": "snip", "file": "001.png", "number": 1, "section": "host/SMB"},
        ]
    )
    assert "## host" in rendered
    assert "### SMB" in rendered
    assert rendered.index("## host") < rendered.index("### SMB")


def test_an_intermediate_section_gets_a_heading_even_with_nothing_in_it():
    """`host/SMB` implies a `host` node, even if nothing was filed there."""
    rendered = _render(
        [{"kind": "note", "id": "n001", "text": "x", "section": "host/SMB"}]
    )
    assert "## host" in rendered


def test_sections_appear_in_first_use_order_not_alphabetically():
    """The work happened in an order, and the writeup should follow it."""
    rendered = _render(
        [
            {"kind": "note", "id": "n001", "text": "z", "section": "zulu"},
            {"kind": "note", "id": "n002", "text": "a", "section": "alpha"},
        ]
    )
    assert rendered.index("## zulu") < rendered.index("## alpha")


def test_root_entries_render_above_every_heading():
    rendered = _render(
        [
            {"kind": "note", "id": "n001", "text": "kickoff", "section": ""},
            {"kind": "note", "id": "n002", "text": "later", "section": "host"},
        ]
    )
    assert rendered.index("kickoff") < rendered.index("## host")


def test_a_deeper_tree_than_markdown_can_express_shares_the_last_level():
    rendered = _render(
        [{"kind": "note", "id": "n001", "text": "x", "section": "a/b/c/d/e/f"}]
    )
    assert "###### e" in rendered
    assert "###### f" in rendered
    assert "####### " not in rendered


def test_an_attached_note_renders_under_its_snip_as_a_quote():
    rendered = _render(
        [
            {"kind": "snip", "file": "001.png", "number": 1, "section": "host"},
            {
                "kind": "note", "id": "n001", "text": "world-writable",
                "section": "host", "attach": ["001.png"],
            },
        ]
    )
    assert "![001](001.png)" in rendered
    assert "> world-writable" in rendered
    assert rendered.index("![001]") < rendered.index("> world-writable")
    assert rendered.count("world-writable") == 1  # not also on its own


def test_a_multi_line_attached_note_is_quoted_on_every_line():
    rendered = _render(
        [
            {"kind": "snip", "file": "001.png", "number": 1, "section": "host"},
            {
                "kind": "note", "id": "n001", "text": "first\nsecond",
                "section": "host", "attach": ["001.png"],
            },
        ]
    )
    assert "> first" in rendered
    assert "> second" in rendered


def test_a_note_attached_across_sections_stays_put_and_references_the_snip():
    """A note must never silently move out of the section it was taken in."""
    rendered = _render(
        [
            {"kind": "snip", "file": "001.png", "number": 1, "section": "host/SMB"},
            {
                "kind": "note", "id": "n001", "text": "see the share listing",
                "section": "host/HTTP", "attach": ["001.png"],
            },
        ]
    )
    assert "_Evidence: 001.png_" in rendered
    assert rendered.index("### HTTP") < rendered.index("see the share listing")


def test_records_written_before_sections_existed_render_at_the_root():
    rendered = _render(
        [{"file": "001_x.png", "number": 1, "time": "14:31:07", "caption": "old"}]
    )
    assert "![001](001_x.png)" in rendered
    assert "##" not in rendered


def test_a_snip_header_carries_the_number_time_and_caption():
    rendered = _render(
        [
            {
                "kind": "snip", "file": "001.png", "number": 1,
                "time": "14:31:07", "caption": "nmap output", "section": "",
            }
        ]
    )
    assert "**001** - 14:31:07 - nmap output" in rendered


def test_render_survives_a_junk_record():
    """A hand-mangled lab.json should still produce a readable index."""
    assert lab.render_index({"name": "x", "entries": "not a list"}).startswith("# x")
    assert lab.render_index({}).startswith("# lab")


# -- recent ----------------------------------------------------------------
def test_recent_lists_labs_newest_first(cfg):
    import os

    for i, name in enumerate(["oldest", "middle", "newest"]):
        folder = lab.folder(cfg, name)
        folder.mkdir(parents=True)
        stamp = 1_700_000_000 + i
        os.utime(folder, (stamp, stamp))
    assert lab.recent(cfg) == ["newest", "middle", "oldest"]


def test_recent_respects_the_limit(cfg):
    for i in range(5):
        lab.folder(cfg, f"lab{i}").mkdir(parents=True)
    assert len(lab.recent(cfg, limit=2)) == 2


def test_recent_is_empty_when_nothing_exists(cfg):
    assert lab.recent(cfg) == []
