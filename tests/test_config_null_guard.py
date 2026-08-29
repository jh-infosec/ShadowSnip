"""A config file holding JSON nulls must still produce a runnable config."""

from __future__ import annotations

import json

import pytest

import config
import storage


@pytest.mark.parametrize(
    "key", ["hotkey", "save_dir", "latest_name", "disk_format", "active_lab", "lab_root"]
)
def test_a_null_string_setting_falls_back(isolated_config, key):
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text(json.dumps({key: None}), encoding="utf-8")
    loaded = config.load()
    assert isinstance(loaded[key], str)
    assert loaded[key] != "None"


def test_a_null_save_dir_still_gives_a_usable_folder(isolated_config, tmp_path):
    """Path(None) raises TypeError, which is not an OSError and not caught."""
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text(json.dumps({"save_dir": None}), encoding="utf-8")
    cfg = config.load()
    cfg["save_dir"] = str(tmp_path / "snips")  # only the type matters here
    assert storage.save_latest(b"x", "png", cfg).exists()


def test_a_null_hotkey_is_still_parseable(isolated_config):
    import hotkey

    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text(json.dumps({"hotkey": None}), encoding="utf-8")
    hotkey.parse(config.load()["hotkey"])
