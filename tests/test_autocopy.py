"""The click-run counter behind double-click and triple-click selection.

A low-level mouse hook never sees WM_LBUTTONDBLCLK, so `_ClickRun` reimplements
the rule Windows applies further up the stack: a press continues a run when it
lands inside the double-click interval and inside the double-click rectangle of
the press before it. It is pure state with no Win32 and no Qt in it, which is
the whole reason it can be tested at all.

The rest of what is covered here is the decision-making around the Win32
calls rather than the calls themselves: which programs are excluded, and which
window counts as "the app I was just in". The Win32 surface is faked, so what
is actually under test is the filtering, not the API.
"""

from __future__ import annotations

import pytest

import autocopy
from autocopy import AutoCopy, BLOCKED_PROCESSES, CLICK_KINDS, MAX_CLICKS, _ClickRun


@pytest.fixture
def run():
    """A 500 ms interval and a 2 px rectangle, matching a default mouse."""
    return _ClickRun(interval_ms=500, slop=(2, 2))


# -- counting --------------------------------------------------------------
def test_first_press_is_click_one(run):
    assert run.press(1000, 50, 50) == 1


def test_a_second_press_in_time_and_place_is_a_double_click(run):
    run.press(1000, 50, 50)
    assert run.press(1200, 50, 50) == 2


def test_a_third_press_is_a_triple_click(run):
    run.press(1000, 50, 50)
    run.press(1200, 50, 50)
    assert run.press(1400, 50, 50) == 3


def test_a_run_keeps_counting_past_three(run):
    """Counting is honest; MAX_CLICKS is what decides to stop acting on it."""
    for expected in range(1, 6):
        assert run.press(1000 + 100 * expected, 50, 50) == expected


# -- what breaks a run -----------------------------------------------------
def test_a_slow_second_press_starts_a_new_run(run):
    run.press(1000, 50, 50)
    assert run.press(1501, 50, 50) == 1


def test_a_press_exactly_on_the_interval_still_counts(run):
    run.press(1000, 50, 50)
    assert run.press(1500, 50, 50) == 2


@pytest.mark.parametrize("dx,dy", [(3, 0), (0, 3), (3, 3), (-3, 0), (0, -3)])
def test_a_press_outside_the_rectangle_starts_a_new_run(run, dx, dy):
    run.press(1000, 50, 50)
    assert run.press(1100, 50 + dx, 50 + dy) == 1


@pytest.mark.parametrize("dx,dy", [(2, 0), (0, 2), (2, 2), (-2, -2), (1, -1)])
def test_a_press_on_the_edge_of_the_rectangle_counts(run, dx, dy):
    run.press(1000, 50, 50)
    assert run.press(1100, 50 + dx, 50 + dy) == 2


def test_drift_is_measured_against_the_previous_press_not_the_first(run):
    """Windows compares each press with the one before it, so slow drift adds up."""
    run.press(1000, 50, 50)
    assert run.press(1100, 52, 50) == 2
    assert run.press(1200, 54, 50) == 3


def test_a_backwards_timestamp_starts_a_new_run(run):
    """The hook's timestamp is a 32-bit tick count and wraps every ~49 days."""
    run.press(4_294_967_200, 50, 50)
    assert run.press(40, 50, 50) == 1


def test_reset_ends_the_run(run):
    run.press(1000, 50, 50)
    run.reset()
    assert run.press(1100, 50, 50) == 1
    assert run.count == 1


def test_count_reports_the_last_press(run):
    assert run.count == 0
    run.press(1000, 50, 50)
    run.press(1100, 50, 50)
    assert run.count == 2


# -- the metrics it is built from ------------------------------------------
def test_a_zero_interval_never_pairs_two_presses():
    """A machine reporting nonsense should miss double-clicks, not invent them."""
    run = _ClickRun(interval_ms=0, slop=(2, 2))
    run.press(1000, 50, 50)
    assert run.press(1001, 50, 50) == 1


def test_a_generous_interval_pairs_a_slow_second_press():
    run = _ClickRun(interval_ms=900, slop=(2, 2))
    run.press(1000, 50, 50)
    assert run.press(1850, 50, 50) == 2


# -- the guards ------------------------------------------------------------
def test_click_kinds_cover_every_count_that_fires():
    """Every count between 2 and MAX_CLICKS has a name for the status line."""
    assert set(CLICK_KINDS) == set(range(2, MAX_CLICKS + 1))


def test_blocked_processes_are_lowercase_with_an_extension():
    """They are compared against os.path.basename(...).lower(), so they must match it."""
    for name in BLOCKED_PROCESSES:
        assert name == name.lower()
        assert name.endswith(".exe")


def test_the_usual_password_managers_are_blocked():
    for name in ("keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe"):
        assert name in BLOCKED_PROCESSES


# -- the user's own exclusion list -----------------------------------------
def _copy_excluding(*names):
    return AutoCopy({"auto_copy_extra_blocked": list(names)})


def test_an_excluded_program_is_blocked():
    assert _copy_excluding("lightroom.exe")._is_blocked("lightroom.exe")


def test_the_extension_does_not_have_to_be_typed():
    """Windows reports lightroom.exe; people write Lightroom."""
    assert _copy_excluding("lightroom")._is_blocked("lightroom.exe")


def test_an_excluded_name_still_has_to_match_the_whole_program():
    """`code` must not quietly disable copy on select in vscode.exe."""
    assert not _copy_excluding("code")._is_blocked("vscode.exe")
    assert not _copy_excluding("light")._is_blocked("lightroom.exe")


def test_a_non_exe_program_is_not_matched_by_its_stem():
    """Only .exe is stripped, so `setup` does not match a setup.msi shim."""
    assert not _copy_excluding("setup")._is_blocked("setup.msi")


def test_the_builtin_list_applies_regardless_of_the_users_entries():
    assert _copy_excluding("lightroom")._is_blocked("keepass.exe")


def test_an_unrelated_program_is_not_blocked():
    assert not _copy_excluding("lightroom")._is_blocked("notepad.exe")


class _User32:
    def __init__(self, foreground=101, owner=101):
        self.foreground = foreground
        self.owner = owner

    def GetForegroundWindow(self):
        return self.foreground

    def GetClipboardOwner(self):
        return self.owner


def test_an_unidentified_process_is_never_sent_ctrl_c(monkeypatch):
    """A protected/elevated process must be treated as blocked, not harmless."""
    copy = AutoCopy({})
    copy._hook = 1
    monkeypatch.setattr(autocopy, "_user32", _User32())
    monkeypatch.setattr(autocopy, "_modifier_held", lambda: False)
    monkeypatch.setattr(autocopy, "_is_own_window", lambda _window: False)
    monkeypatch.setattr(autocopy, "_class_name", lambda _window: "Notepad")
    monkeypatch.setattr(autocopy, "_process_name", lambda _window: None)
    sent = []
    monkeypatch.setattr(autocopy, "_send_ctrl_c", lambda: sent.append(True))

    copy._capture()

    assert sent == []


def test_read_back_ignores_a_clipboard_change_after_focus_moves(monkeypatch):
    copy = AutoCopy({})
    copy._hook = 1
    monkeypatch.setattr(autocopy, "_user32", _User32(foreground=202, owner=202))
    monkeypatch.setattr(autocopy, "_clipboard_sequence", lambda: 2)
    read = []
    monkeypatch.setattr(autocopy, "_clipboard_text", lambda: read.append(True) or "secret")

    copy._read_back(before=1, kind="selection", target_window=101)

    assert read == []


def test_read_back_ignores_a_clipboard_owner_from_another_process(monkeypatch):
    copy = AutoCopy({})
    copy._hook = 1
    monkeypatch.setattr(autocopy, "_user32", _User32(foreground=101, owner=202))
    monkeypatch.setattr(autocopy, "_clipboard_sequence", lambda: 2)
    monkeypatch.setattr(
        autocopy, "_window_pid", lambda window: {101: 10, 202: 20}[window]
    )
    read = []
    monkeypatch.setattr(autocopy, "_clipboard_text", lambda: read.append(True) or "secret")

    copy._read_back(before=1, kind="selection", target_window=101)

    assert read == []


# -- naming the app the user was just in -----------------------------------
class _Desktop:
    """A fake z-order: windows front to back, each with a title and a pid."""

    def __init__(self, windows):
        self.order = [hwnd for hwnd, _title, _pid in windows]
        self.titles = {hwnd: title for hwnd, title, _pid in windows}
        self.pids = {hwnd: pid for hwnd, _title, pid in windows}

    def GetTopWindow(self, _parent):
        return self.order[0] if self.order else 0

    def GetWindow(self, hwnd, _direction):
        index = self.order.index(hwnd) + 1
        return self.order[index] if index < len(self.order) else 0

    def IsWindowVisible(self, hwnd):
        return True

    def GetWindowTextLengthW(self, hwnd):
        return len(self.titles[hwnd])


def _desktop(monkeypatch, windows, own_pid=999):
    desktop = _Desktop(windows)
    monkeypatch.setattr(autocopy, "_user32", desktop)
    monkeypatch.setattr(autocopy, "_get_window_long", None)
    monkeypatch.setattr(autocopy, "_window_pid", lambda hwnd: desktop.pids[hwnd])
    monkeypatch.setattr(autocopy.os, "getpid", lambda: own_pid)
    monkeypatch.setattr(
        autocopy, "_process_name", lambda hwnd: f"app{desktop.pids[hwnd]}.exe"
    )
    return desktop


def test_the_frontmost_other_window_is_the_one_named(monkeypatch):
    _desktop(monkeypatch, [(1, "Lightroom", 10), (2, "Notepad", 20)])
    assert autocopy.last_other_process() == "app10.exe"


def test_shadowsnips_own_windows_are_skipped(monkeypatch):
    """Settings is in front while it is open, so it must never be the answer."""
    _desktop(monkeypatch, [(1, "Settings", 999), (2, "Lightroom", 10)])
    assert autocopy.last_other_process() == "app10.exe"


def test_untitled_windows_are_skipped(monkeypatch):
    """Message-only and hidden helper windows sit near the top of the z-order."""
    _desktop(monkeypatch, [(1, "", 30), (2, "Lightroom", 10)])
    assert autocopy.last_other_process() == "app10.exe"


def test_an_empty_desktop_names_nothing(monkeypatch):
    _desktop(monkeypatch, [])
    assert autocopy.last_other_process() is None


def test_a_desktop_of_our_own_windows_names_nothing(monkeypatch):
    _desktop(monkeypatch, [(1, "Settings", 999), (2, "Preview", 999)])
    assert autocopy.last_other_process() is None


def test_the_foreground_lookup_ignores_our_own_window(monkeypatch):
    """A countdown nobody switched away from must add nothing."""
    monkeypatch.setattr(autocopy, "_user32", _User32(foreground=1))
    monkeypatch.setattr(autocopy, "_window_pid", lambda _hwnd: 999)
    monkeypatch.setattr(autocopy.os, "getpid", lambda: 999)
    monkeypatch.setattr(autocopy, "_process_name", lambda _hwnd: "shadowsnip.exe")
    assert autocopy.foreground_process() is None


def test_the_foreground_lookup_names_another_program(monkeypatch):
    monkeypatch.setattr(autocopy, "_user32", _User32(foreground=1))
    monkeypatch.setattr(autocopy, "_window_pid", lambda _hwnd: 10)
    monkeypatch.setattr(autocopy.os, "getpid", lambda: 999)
    monkeypatch.setattr(autocopy, "_process_name", lambda _hwnd: "lightroom.exe")
    assert autocopy.foreground_process() == "lightroom.exe"


# -- VM, RDP and SSH windows -----------------------------------------------
def _capture_into(monkeypatch, process, cfg=None, window_class="Notepad"):
    """Run a capture against a fake foreground window; report the keystroke."""
    copy = AutoCopy(cfg if cfg is not None else {})
    copy._hook = 1
    monkeypatch.setattr(autocopy, "_user32", _User32())
    monkeypatch.setattr(autocopy, "_modifier_held", lambda: False)
    monkeypatch.setattr(autocopy, "_is_own_window", lambda _window: False)
    monkeypatch.setattr(autocopy, "_class_name", lambda _window: window_class)
    monkeypatch.setattr(autocopy, "_process_name", lambda _window: process)
    monkeypatch.setattr(autocopy, "_clipboard_sequence", lambda: 1)
    monkeypatch.setattr(autocopy.QTimer, "singleShot", lambda _ms, _fn: None)
    sent = []
    monkeypatch.setattr(autocopy, "_send_ctrl_c", lambda: sent.append(True))
    copy._capture()
    return sent


def test_guest_processes_are_lowercase_with_an_extension():
    for name in autocopy.GUEST_PROCESSES:
        assert name == name.lower()
        assert name.endswith(".exe")


@pytest.mark.parametrize(
    "process", ["vmware.exe", "virtualboxvm.exe", "mstsc.exe", "putty.exe"]
)
def test_no_ctrl_c_reaches_a_vm_or_remote_session(monkeypatch, process):
    """Ctrl+C in the shell inside one of these is SIGINT, not copy."""
    assert _capture_into(monkeypatch, process) == []


def test_an_ordinary_window_still_gets_the_keystroke(monkeypatch):
    assert _capture_into(monkeypatch, "notepad.exe") == [True]


def test_turning_the_skip_setting_off_lets_a_vm_window_through(monkeypatch):
    """It is misfire avoidance, not a hard block, so it has to be switchable."""
    sent = _capture_into(
        monkeypatch, "vmware.exe", cfg={"auto_copy_skip_consoles": False}
    )
    assert sent == [True]


def test_a_password_manager_is_blocked_even_with_the_skip_setting_off(monkeypatch):
    """The always-on list must not be reachable through a settings toggle."""
    sent = _capture_into(
        monkeypatch, "keepass.exe", cfg={"auto_copy_skip_consoles": False}
    )
    assert sent == []
