"""Config loading, saving and sanitising.

The point of _sanitise is that a hand-edited or older config file can never
put the application into a state it cannot run in, so most of these tests feed
it rubbish and check what comes back out.
"""

from __future__ import annotations

import json

import pytest

import config


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# -- round trip ------------------------------------------------------------
def test_save_then_load_round_trips(isolated_config):
    original = config.load()
    original["hotkey"] = "alt+f9"
    original["max_dimension"] = 2400
    original["keep_history"] = True
    config.save(original)

    assert isolated_config.exists()
    assert config.load() == original


def test_load_without_a_file_returns_defaults(isolated_config):
    assert config.load() == config._sanitise(dict(config.DEFAULTS))


def test_save_creates_the_directory(isolated_config):
    assert not isolated_config.parent.exists()
    config.save(dict(config.DEFAULTS))
    assert isolated_config.exists()


def test_save_leaves_no_temp_file_behind(isolated_config):
    config.save(dict(config.DEFAULTS))
    assert [p.name for p in isolated_config.parent.iterdir()] == ["config.json"]


def test_save_does_not_mutate_the_callers_dict(isolated_config):
    caller = dict(config.DEFAULTS)
    caller["png_compress_level"] = 99  # out of range
    config.save(caller)
    assert caller["png_compress_level"] == 99
    assert config.load()["png_compress_level"] == 9


# -- forwards and backwards compatibility ----------------------------------
def test_unknown_keys_are_dropped(isolated_config):
    _write(isolated_config, {"hotkey": "ctrl+1", "from_a_future_version": True})
    loaded = config.load()
    assert loaded["hotkey"] == "ctrl+1"
    assert "from_a_future_version" not in loaded


def test_missing_keys_fall_back_to_defaults(isolated_config):
    _write(isolated_config, {"hotkey": "ctrl+1"})
    loaded = config.load()
    assert loaded["hotkey"] == "ctrl+1"
    assert loaded["disk_format"] == config.DEFAULTS["disk_format"]
    assert set(loaded) == set(config.DEFAULTS)


@pytest.mark.parametrize("body", ["", "not json at all", "[1, 2, 3]", "null"])
def test_corrupt_config_falls_back_to_defaults(isolated_config, body):
    isolated_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_config.write_text(body, encoding="utf-8")
    assert config.load() == config._sanitise(dict(config.DEFAULTS))


# -- sanitising ------------------------------------------------------------
@pytest.mark.parametrize(
    "key,given,expected",
    [
        ("png_compress_level", 99, 9),
        ("png_compress_level", -4, 0),
        ("dim_opacity", 999, 255),
        ("dim_opacity", -1, 0),
        ("quantize_colors", 1000, 256),
        ("quantize_colors", 1, 2),
        ("quantize_min_saving", 200, 90),
        ("quantize_min_saving", -5, 0),
        ("max_dimension", 10**9, 30000),
        ("history_limit", 0, 1),
        ("auto_copy_min_drag", 5000, 200),
        ("webp_quality", 0, 1),
        ("jpeg_quality", 500, 100),
    ],
)
def test_numbers_are_clamped(key, given, expected):
    assert config._sanitise({**config.DEFAULTS, key: given})[key] == expected


@pytest.mark.parametrize("junk", ["banana", None, [], {}])
def test_non_numeric_values_fall_back(junk):
    cleaned = config._sanitise({**config.DEFAULTS, "png_compress_level": junk})
    assert cleaned["png_compress_level"] == config.DEFAULTS["png_compress_level"]


@pytest.mark.parametrize("fmt", ["tiff", "", None, "PNG", 7])
def test_unknown_disk_format_becomes_png(fmt):
    assert config._sanitise({**config.DEFAULTS, "disk_format": fmt})["disk_format"] == "png"


@pytest.mark.parametrize("fmt", ["png", "webp", "jpeg"])
def test_known_disk_formats_survive(fmt):
    assert config._sanitise({**config.DEFAULTS, "disk_format": fmt})["disk_format"] == fmt


@pytest.mark.parametrize(
    "given,expected",
    [("latest.png", "latest"), ("  shot  ", "shot"), ("", "latest"), ("   ", "latest")],
)
def test_latest_name_is_reduced_to_a_stem(given, expected):
    assert config._sanitise({**config.DEFAULTS, "latest_name": given})["latest_name"] == expected


@pytest.mark.parametrize("truthy", [1, "yes", ["x"], True])
@pytest.mark.parametrize(
    "flag",
    [
        "quantize",
        "keep_history",
        "auto_copy",
        "lab_index",
        "auto_copy_double_click",
        "auto_copy_dedupe",
        "auto_copy_toast",
    ],
)
def test_flags_are_coerced_to_bool(flag, truthy):
    value = config._sanitise({**config.DEFAULTS, flag: truthy})[flag]
    assert value is True


@pytest.mark.parametrize("falsy", [0, "", [], None])
def test_falsy_flags_become_false(falsy):
    assert config._sanitise({**config.DEFAULTS, "quantize": falsy})["quantize"] is False


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_hotkey_falls_back(blank):
    assert config._sanitise({**config.DEFAULTS, "hotkey": blank})["hotkey"] == config.DEFAULTS["hotkey"]


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_save_dir_falls_back(blank):
    assert config._sanitise({**config.DEFAULTS, "save_dir": blank})["save_dir"] == config.DEFAULTS["save_dir"]


def test_lab_name_keeps_inner_characters_but_trims_edges():
    """Lab names are used verbatim as folder names; only edges are trimmed."""
    cleaned = config._sanitise({**config.DEFAULTS, "active_lab": "  htb lame v2  "})
    assert cleaned["active_lab"] == "htb lame v2"


# -- the extra blocklist ---------------------------------------------------
@pytest.mark.parametrize(
    "given,expected",
    [
        (["Vault.exe"], ["vault.exe"]),
        ("vault.exe, other.exe", ["vault.exe", "other.exe"]),
        ("vault.exe other.exe", ["vault.exe", "other.exe"]),
        ("  vault.exe  ,, ", ["vault.exe"]),
        (["a.exe", "A.exe", "a.exe"], ["a.exe"]),
        ([], []),
        ("", []),
        (None, []),
        (7, []),
        ([None, "", "  "], []),
        ([["nested"], "ok.exe"], ["ok.exe"]),
    ],
)
def test_extra_blocklist_is_normalised(given, expected):
    cleaned = config._sanitise({**config.DEFAULTS, "auto_copy_extra_blocked": given})
    assert cleaned["auto_copy_extra_blocked"] == expected


def test_extra_blocklist_survives_a_round_trip(isolated_config):
    """A list has to come back a list, since it is iterated as one."""
    cfg = config.load()
    cfg["auto_copy_extra_blocked"] = "Vault.exe, other.exe"
    config.save(cfg)
    assert config.load()["auto_copy_extra_blocked"] == ["vault.exe", "other.exe"]


def test_sanitising_does_not_mutate_the_default_list():
    """DEFAULTS holds a mutable list; a sanitise must not reach into it."""
    before = list(config.DEFAULTS["auto_copy_extra_blocked"])
    config._sanitise(dict(config.DEFAULTS))["auto_copy_extra_blocked"].append("x.exe")
    assert config.DEFAULTS["auto_copy_extra_blocked"] == before


def test_sanitise_is_idempotent():
    once = config._sanitise({**config.DEFAULTS, "png_compress_level": 99, "disk_format": "tiff"})
    assert config._sanitise(dict(once)) == once


# -- adding a program to the exclusion list --------------------------------
def test_add_name_appends_to_an_empty_field():
    assert config.add_name("", "Lightroom.exe") == "lightroom.exe"


def test_add_name_keeps_what_is_already_there():
    assert config.add_name("vault.exe", "lightroom.exe") == "vault.exe, lightroom.exe"


def test_add_name_ignores_a_program_already_listed():
    assert config.add_name("lightroom.exe", "lightroom.exe") == "lightroom.exe"


def test_add_name_ignores_the_other_spelling_of_the_same_program():
    """The block check treats the two the same, so the field must as well."""
    assert config.add_name("lightroom", "lightroom.exe") == "lightroom"
    assert config.add_name("lightroom.exe", "lightroom") == "lightroom.exe"


def test_add_name_tidies_a_hand_typed_field():
    assert config.add_name("vault.exe   other.exe,", "new.exe") == (
        "vault.exe, other.exe, new.exe"
    )


@pytest.mark.parametrize(
    "name,expected",
    [
        ("lightroom.exe", "lightroom"),
        ("lightroom", "lightroom"),
        ("setup.msi", "setup.msi"),
        ("my.app.exe", "my.app"),
        (".exe", ".exe"),
    ],
)
def test_without_exe_strips_only_a_real_exe_suffix(name, expected):
    assert config.without_exe(name) == expected
