"""Disk writes: atomicity, the single standing file, and history pruning."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

import storage


def _age(path: Path, seconds_ago: int) -> None:
    """Backdate a file so mtime ordering in the pruning tests is deterministic."""
    stamp = 1_700_000_000 - seconds_ago
    os.utime(path, (stamp, stamp))


# -- write_atomic ----------------------------------------------------------
def test_write_atomic_creates_missing_parents(tmp_path):
    target = tmp_path / "a" / "b" / "c.png"
    assert storage.write_atomic(target, b"data") == target
    assert target.read_bytes() == b"data"


def test_write_atomic_replaces_existing_content(tmp_path):
    target = tmp_path / "c.png"
    storage.write_atomic(target, b"first")
    storage.write_atomic(target, b"second")
    assert target.read_bytes() == b"second"


def test_write_atomic_leaves_no_temp_file(tmp_path):
    storage.write_atomic(tmp_path / "c.png", b"data")
    assert [p.name for p in tmp_path.iterdir()] == ["c.png"]


def test_write_atomic_cleans_up_when_the_replace_fails(tmp_path, monkeypatch):
    """A failed write must not leave a .tmp turd in the save folder."""
    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "replace", boom)
    with pytest.raises(OSError):
        storage.write_atomic(tmp_path / "c.png", b"data")
    assert list(tmp_path.iterdir()) == []


# -- save_latest -----------------------------------------------------------
def test_save_latest_writes_the_standing_file(cfg):
    path = storage.save_latest(b"png bytes", "png", cfg)
    assert path == Path(cfg["save_dir"]) / "latest.png"
    assert path.read_bytes() == b"png bytes"


def test_save_latest_replaces_rather_than_accumulates(cfg):
    storage.save_latest(b"one", "png", cfg)
    storage.save_latest(b"two", "png", cfg)
    folder = Path(cfg["save_dir"])
    assert [p.name for p in folder.iterdir()] == ["latest.png"]
    assert (folder / "latest.png").read_bytes() == b"two"


def test_save_latest_drops_a_stale_sibling_when_the_format_changes(cfg):
    storage.save_latest(b"png", "png", cfg)
    storage.save_latest(b"jpeg", "jpg", cfg)
    names = sorted(p.name for p in Path(cfg["save_dir"]).iterdir())
    assert names == ["latest.jpg"]


def test_save_latest_leaves_unrelated_files_alone(cfg):
    folder = Path(cfg["save_dir"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "latest.txt").write_text("notes", encoding="utf-8")
    (folder / "something_else.png").write_bytes(b"x")
    storage.save_latest(b"png", "png", cfg)
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["latest.png", "latest.txt", "something_else.png"]


def test_save_latest_honours_a_custom_name(cfg):
    cfg["latest_name"] = "shot"
    assert storage.save_latest(b"x", "webp", cfg).name == "shot.webp"


# -- history ---------------------------------------------------------------
def test_history_is_off_by_default(cfg):
    assert storage.save_history(b"x", "png", cfg) is None
    assert not (Path(cfg["save_dir"]) / storage.HISTORY_DIRNAME).exists()


def test_history_writes_a_timestamped_copy(cfg):
    cfg["keep_history"] = True
    path = storage.save_history(b"x", "png", cfg)
    assert path is not None
    assert path.parent.name == storage.HISTORY_DIRNAME
    assert re.fullmatch(r"snip_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d{3}\.png", path.name)


def test_history_is_pruned_to_the_limit(cfg):
    folder = Path(cfg["save_dir"]) / storage.HISTORY_DIRNAME
    folder.mkdir(parents=True)
    for i in range(10):
        path = folder / f"snip_{i}.png"
        path.write_bytes(b"x")
        _age(path, seconds_ago=10 - i)  # snip_9 is the newest

    cfg["history_limit"] = 3
    storage.prune_history(cfg)
    assert sorted(p.name for p in folder.iterdir()) == [
        "snip_7.png",
        "snip_8.png",
        "snip_9.png",
    ]


def test_pruning_ignores_files_that_are_not_images(cfg):
    folder = Path(cfg["save_dir"]) / storage.HISTORY_DIRNAME
    folder.mkdir(parents=True)
    (folder / "notes.txt").write_text("keep me", encoding="utf-8")
    for i in range(3):
        path = folder / f"snip_{i}.png"
        path.write_bytes(b"x")
        _age(path, seconds_ago=3 - i)

    cfg["history_limit"] = 1
    storage.prune_history(cfg)
    assert sorted(p.name for p in folder.iterdir()) == ["notes.txt", "snip_2.png"]


def test_pruning_a_missing_folder_is_a_no_op(cfg):
    storage.prune_history(cfg)  # must not raise


# -- misc ------------------------------------------------------------------
def test_save_dir_is_created_on_demand(cfg):
    folder = storage.save_dir(cfg)
    assert folder.is_dir()


def test_suggested_name_shape():
    assert re.fullmatch(
        r"snip_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.webp", storage.suggested_name("webp")
    )
