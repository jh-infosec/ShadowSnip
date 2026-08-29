"""Hotkey string parsing.

`parse` and `describe` are pure string work, so they are testable off Windows
even though registering the hotkey is not.
"""

from __future__ import annotations

import pytest

import hotkey


def test_parse_returns_mask_and_vk():
    mods, key = hotkey.parse("ctrl+shift+s")
    assert mods == hotkey.MOD_CONTROL | hotkey.MOD_SHIFT | hotkey.MOD_NOREPEAT
    assert key == ord("S")


def test_norepeat_is_always_set():
    for spec in ("s", "ctrl+s", "win+shift+x", "prtsc"):
        mods, _ = hotkey.parse(spec)
        assert mods & hotkey.MOD_NOREPEAT


def test_parse_ignores_case_and_whitespace():
    assert hotkey.parse("  CtRl + ShIfT + S  ") == hotkey.parse("ctrl+shift+s")


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("control", hotkey.MOD_CONTROL),
        ("ctrl", hotkey.MOD_CONTROL),
        ("alt", hotkey.MOD_ALT),
        ("shift", hotkey.MOD_SHIFT),
        ("win", hotkey.MOD_WIN),
        ("super", hotkey.MOD_WIN),
        ("meta", hotkey.MOD_WIN),
    ],
)
def test_modifier_aliases(alias, expected):
    mods, _ = hotkey.parse(f"{alias}+s")
    assert mods & expected


@pytest.mark.parametrize(
    "spec,code",
    [
        ("prtsc", 0x2C),
        ("printscreen", 0x2C),
        ("print", 0x2C),
        ("insert", 0x2D),
        ("pagedown", 0x22),
        ("esc", 0x1B),
        ("escape", 0x1B),
        ("f1", 0x70),
        ("f5", 0x74),
        ("f24", 0x87),
    ],
)
def test_named_keys(spec, code):
    assert hotkey.parse(spec)[1] == code


def test_digit_key():
    assert hotkey.parse("ctrl+4")[1] == ord("4")


@pytest.mark.parametrize(
    "spec",
    [
        "",
        "   ",
        "+++",
        "ctrl",  # modifiers but no key
        "ctrl+shift",
        "ctrl+a+b",  # two keys
        "ctrl+nonsense",
        "ctrl+;",
    ],
)
def test_bad_specs_raise(spec):
    with pytest.raises(hotkey.HotkeyError):
        hotkey.parse(spec)


@pytest.mark.parametrize(
    "spec,pretty",
    [
        ("ctrl+shift+s", "Ctrl+Shift+S"),
        ("win+shift+x", "Win+Shift+X"),
        ("alt+f4", "Alt+F4"),
        ("prtsc", "Prtsc"),
        ("s", "S"),
    ],
)
def test_describe(spec, pretty):
    assert hotkey.describe(spec) == pretty


def test_describe_skips_blank_segments():
    assert hotkey.describe("ctrl++s") == "Ctrl+S"


def test_describe_accepts_what_parse_accepts():
    """Anything describe() shows in a menu should still be parseable."""
    for spec in ("ctrl+shift+s", "alt+f4", "win+shift+x", "prtsc"):
        hotkey.parse(hotkey.describe(spec).lower())
