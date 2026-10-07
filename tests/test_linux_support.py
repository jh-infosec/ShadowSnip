"""Linux support: desktop-owned hotkeys, primary-selection copy, platform choice.

Xfce and X11 are faked, so this runs on any machine, Windows included.
"""

from __future__ import annotations

import subprocess

import pytest
from PySide6.QtWidgets import QApplication

import autocopy_linux
import hotkey
import hotkey_linux
import platforms


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


# -- platform choice -------------------------------------------------------------
def test_platforms_picks_one_implementation():
    if platforms.IS_LINUX:
        assert platforms.HotkeyManager is hotkey_linux.HotkeyManager
        assert platforms.AutoCopy is autocopy_linux.AutoCopy
    else:
        assert platforms.HotkeyManager is hotkey.HotkeyManager
    assert callable(platforms.foreground_process)
    assert callable(platforms.last_other_process)


# -- Xfce accelerators -------------------------------------------------------------
@pytest.mark.parametrize(
    "spec,expected",
    [
        ("ctrl+shift+s", "<Primary><Shift>s"),
        ("shift+ctrl+s", "<Primary><Shift>s"),
        ("ctrl+shift+n", "<Primary><Shift>n"),
        ("win+shift+x", "<Shift><Super>x"),
        ("prtsc", "Print"),
        ("alt+f5", "<Alt>F5"),
        ("ctrl+pageup", "<Primary>Page_Up"),
        ("  CtRl + S ", "<Primary>s"),
    ],
)
def test_xfce_accelerators(spec, expected):
    assert hotkey_linux.xfce_accelerator(spec) == expected


@pytest.mark.parametrize("spec", ["", "ctrl+shift", "ctrl+a+b", "ctrl+banana"])
def test_bad_specs_are_refused_like_on_windows(spec):
    with pytest.raises(hotkey.HotkeyError):
        hotkey_linux.xfce_accelerator(spec)


def test_the_launch_command_quotes_paths_with_spaces(monkeypatch):
    monkeypatch.setattr(hotkey_linux.sys, "executable", "/opt/My Apps/python3")
    command = hotkey_linux.launch_command("--snip")
    assert command.startswith("'/opt/My Apps/python3' ")
    assert "main.py" in command and command.endswith(" --snip")


# -- registering through a fake xfconf -------------------------------------------
class FakeXfconf:
    def __init__(self, existing=None):
        self.props = dict(existing or {})
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        path = args[args.index("-p") + 1]
        if "-r" in args:
            self.props.pop(path, None)
            return subprocess.CompletedProcess(args, 0, "", "")
        if "-s" in args:
            self.props[path] = args[args.index("-s") + 1]
            return subprocess.CompletedProcess(args, 0, "", "")
        if path in self.props:
            return subprocess.CompletedProcess(args, 0, self.props[path] + "\n", "")
        return subprocess.CompletedProcess(args, 1, "", "Property does not exist")


@pytest.fixture
def xfce(monkeypatch):
    fake = FakeXfconf()
    monkeypatch.setattr(hotkey_linux, "_xfconf", fake)
    monkeypatch.setattr(hotkey_linux, "is_xfce", lambda: True)
    monkeypatch.setattr(hotkey_linux, "launch_command", lambda flag: f"/usr/bin/shadowsnip {flag}")
    return fake


def test_register_writes_the_xfce_shortcut(xfce):
    manager = hotkey_linux.HotkeyManager()
    manager.register(None, "ctrl+shift+s", "snip")
    manager.register(None, "ctrl+shift+n", "note")
    assert xfce.props["/commands/custom/<Primary><Shift>s"] == "/usr/bin/shadowsnip --snip"
    assert xfce.props["/commands/custom/<Primary><Shift>n"] == "/usr/bin/shadowsnip --note"
    assert manager.spec("snip") == "ctrl+shift+s"
    assert manager.supported


def test_a_combination_used_for_something_else_is_taken_not_overwritten(xfce):
    xfce.props["/commands/custom/Print"] = "xfce4-screenshooter -f"
    manager = hotkey_linux.HotkeyManager()
    with pytest.raises(hotkey.HotkeyError, match="already used"):
        manager.register(None, "prtsc", "snip")
    assert xfce.props["/commands/custom/Print"] == "xfce4-screenshooter -f"


def test_an_older_shadowsnip_shortcut_is_replaced(xfce):
    path = "/commands/custom/<Primary><Shift>s"
    xfce.props[path] = "/old/place/ShadowSnip --snip"
    hotkey_linux.HotkeyManager().register(None, "ctrl+shift+s", "snip")
    assert xfce.props[path] == "/usr/bin/shadowsnip --snip"


def test_changing_the_hotkey_removes_only_our_old_shortcut(xfce):
    manager = hotkey_linux.HotkeyManager()
    manager.register(None, "ctrl+shift+s", "snip")
    manager.register(None, "ctrl+alt+s", "snip")
    assert "/commands/custom/<Primary><Shift>s" not in xfce.props
    assert xfce.props["/commands/custom/<Primary><Alt>s"] == "/usr/bin/shadowsnip --snip"


def test_quitting_leaves_the_shortcut_in_place(xfce):
    manager = hotkey_linux.HotkeyManager()
    manager.register(None, "ctrl+shift+s", "snip")
    manager.release_all()
    assert "/commands/custom/<Primary><Shift>s" in xfce.props
    assert not manager.registered("snip")


def test_other_desktops_get_the_command_to_add_by_hand(monkeypatch):
    monkeypatch.setattr(hotkey_linux, "is_xfce", lambda: False)
    with pytest.raises(hotkey.HotkeyError, match="--snip"):
        hotkey_linux.HotkeyManager().register(None, "ctrl+shift+s", "snip")


# -- copy on select through the primary selection ----------------------------------
class FakeClipboard:
    def __init__(self, selection=""):
        self.selection = selection
        self.clipboard = ""

    def text(self, mode):
        return self.selection if mode == autocopy_linux.QClipboard.Mode.Selection else self.clipboard

    def setText(self, text, mode):
        assert mode == autocopy_linux.QClipboard.Mode.Clipboard
        self.clipboard = text


def _engaged(cfg=None, selection="", process="qterminal"):
    copy = autocopy_linux.AutoCopy(cfg or {"auto_copy_dedupe": True})
    copy._clipboard = FakeClipboard(selection)
    copy._engaged = True
    got = []
    copy.copied.connect(lambda text, kind: got.append((text, kind)))
    return copy, got


@pytest.fixture
def front(monkeypatch):
    state = {"process": "qterminal"}
    monkeypatch.setattr(autocopy_linux, "active_process", lambda: state["process"])
    return state


def test_a_selection_is_copied_to_the_clipboard(front):
    copy, got = _engaged(selection="nmap -sV 10.10.10.3")
    copy._capture()
    assert copy._clipboard.clipboard == "nmap -sV 10.10.10.3"
    assert got == [("nmap -sV 10.10.10.3", "selection")]


def test_the_same_selection_twice_is_copied_once(front):
    copy, got = _engaged(selection="same")
    copy._capture()
    copy._capture()
    assert len(got) == 1


def test_password_managers_are_never_copied_from(front):
    for process in ("keepassxc", "KeePassXC", "bitwarden", "pinentry-gnome3"):
        front["process"] = process
        copy, got = _engaged(selection="hunter2")
        copy._capture()
        assert got == [] and copy._clipboard.clipboard == ""


def test_never_copy_from_works_with_or_without_exe(front):
    front["process"] = "obsidian"
    for entry in (["obsidian"], ["obsidian.exe"], "obsidian"):
        copy, got = _engaged({"auto_copy_extra_blocked": entry}, selection="x")
        copy._capture()
        assert got == []


def test_shadowsnips_own_windows_are_skipped(front):
    front["process"] = "own"
    copy, got = _engaged(selection="from our own note box")
    copy._capture()
    assert got == []


def test_blank_selections_and_a_paused_copy_do_nothing(front):
    copy, got = _engaged(selection="   ")
    copy._capture()
    copy._clipboard.selection = "real"
    copy.pause()
    copy._capture()
    assert got == []
    copy.resume()
    copy._capture()
    assert got == [("real", "selection")]


def test_a_drag_is_copied_once_it_settles(front):
    copy, _got = _engaged(selection="growing")
    copy._on_selection_changed()
    assert copy._settle.isActive()
    assert copy._settle.interval() == autocopy_linux.SETTLE_MS


def test_engage_refuses_without_a_primary_selection(monkeypatch):
    class NoSelection:
        def supportsSelection(self):
            return False

    monkeypatch.setattr(autocopy_linux.QGuiApplication, "clipboard", lambda: NoSelection())
    with pytest.raises(autocopy_linux.AutoCopyError, match="primary selection"):
        autocopy_linux.AutoCopy({}).engage()


def test_xprop_missing_means_no_process_not_a_crash(monkeypatch):
    monkeypatch.setattr(autocopy_linux.shutil, "which", lambda _name: None)
    assert autocopy_linux.active_process() is None
    assert autocopy_linux.last_other_process() is None


def test_without_xprop_copy_on_select_will_not_start(monkeypatch):
    """Fail closed, as on Windows: no way to spot a password manager, no copying."""
    class WithSelection:
        def supportsSelection(self):
            return True

    monkeypatch.setattr(autocopy_linux.QGuiApplication, "clipboard", lambda: WithSelection())
    monkeypatch.setattr(autocopy_linux.shutil, "which", lambda _name: None)
    with pytest.raises(autocopy_linux.AutoCopyError, match="xprop"):
        autocopy_linux.AutoCopy({}).engage()


def test_an_unidentified_program_is_not_copied_from(front):
    front["process"] = None
    copy, got = _engaged(selection="could be anything")
    copy._capture()
    assert got == [] and copy._clipboard.clipboard == ""


@pytest.mark.parametrize(
    "command,ours",
    [
        ("/usr/bin/shadowsnip --snip", True),
        ("/home/kali/.local/bin/shadowsnip --note", True),
        ("'/opt/ShadowSnip/ShadowSnip' --snip", True),
        ("python3 /home/kali/tools/main.py --snip", False),
        ("xfce4-screenshooter -f", False),
        ("shadowsnip-helper --snipe", False),
    ],
)
def test_only_shadowsnip_shortcuts_count_as_ours(command, ours):
    assert hotkey_linux._is_ours(command) is ours


def test_the_front_window_is_read_through_xprop(monkeypatch):
    outputs = {
        ("-root", "_NET_ACTIVE_WINDOW"): "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3a00007\n",
        ("-id", "0x3a00007", "_NET_WM_PID"): "_NET_WM_PID(CARDINAL) = 4242\n",
    }
    monkeypatch.setattr(autocopy_linux, "_xprop", lambda *args: outputs.get(args, ""))
    real_open = open

    def fake_open(path, *a, **k):
        if path == "/proc/4242/comm":
            import io
            return io.StringIO("qterminal\n")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)
    assert autocopy_linux.active_process() == "qterminal"
    assert autocopy_linux.foreground_process() == "qterminal"


# -- where settings live ---------------------------------------------------------
def test_windows_keeps_appdata(monkeypatch, tmp_path):
    import config

    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert config.config_dir() == tmp_path / "Roaming" / "ShadowSnip"


def test_linux_uses_the_xdg_config_folder(monkeypatch, tmp_path):
    import config

    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert config.config_dir() == tmp_path / "cfg" / "shadowsnip"
    monkeypatch.delenv("XDG_CONFIG_HOME")
    # Path.home() rather than HOME: Windows ignores HOME, and this suite runs
    # on Windows too.
    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: tmp_path))
    assert config.config_dir() == tmp_path / ".config" / "shadowsnip"


# -- Wayland ---------------------------------------------------------------------
def test_wayland_is_warned_about_on_linux_only(monkeypatch):
    import main

    monkeypatch.setattr(main.sys, "platform", "linux")
    assert "X11" in main.wayland_warning({"XDG_SESSION_TYPE": "wayland"})
    assert main.wayland_warning({"XDG_SESSION_TYPE": "x11"}) == ""
    assert main.wayland_warning({}) == ""
    monkeypatch.setattr(main.sys, "platform", "win32")
    assert main.wayland_warning({"XDG_SESSION_TYPE": "wayland"}) == ""
