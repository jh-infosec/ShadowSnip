"""Started by Windows at login, ShadowSnip stays in the tray (0.8.0)."""

from __future__ import annotations

import pytest

import main

STARTUP = r"C:\Users\jh\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\ShadowSnip.lnk"
ALL_USERS = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp\ShadowSnip.lnk"
PIN = r"C:\Users\jh\AppData\Roaming\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\ShadowSnip.lnk"
DESKTOP = r"C:\Users\jh\Desktop\ShadowSnip.lnk"


@pytest.mark.parametrize("shortcut", [STARTUP, ALL_USERS, STARTUP.replace("\\", "/")])
def test_a_startup_folder_shortcut_is_a_login_start(shortcut):
    # Even without --tray, and however long after sign-in.
    assert main.started_at_login([], shortcut=shortcut, since_logon=3600)


@pytest.mark.parametrize("shortcut", [PIN, DESKTOP])
def test_any_other_shortcut_opens_the_window(shortcut):
    # Opened by hand straight after signing in still shows the window.
    assert not main.started_at_login([], shortcut=shortcut, since_logon=5)


def test_no_shortcut_soon_after_sign_in_is_a_login_start():
    # A Run entry, a scheduled task, or Windows reopening restartable apps.
    assert main.started_at_login([], shortcut="", since_logon=20)
    assert main.started_at_login([], shortcut="", since_logon=main.LOGIN_WINDOW_SECONDS - 1)


def test_no_shortcut_later_on_opens_the_window():
    assert not main.started_at_login([], shortcut="", since_logon=main.LOGIN_WINDOW_SECONDS + 1)


def test_unknown_launch_details_open_the_window():
    # Linux, or Windows refusing to say: only --tray keeps it quiet.
    assert not main.started_at_login([], shortcut=None, since_logon=None)
    assert not main.started_at_login([], shortcut=None, since_logon=5)
    assert main.started_at_login(["--tray"], shortcut=None, since_logon=None)


def test_the_flags_win():
    assert main.started_at_login(["--tray"], shortcut=DESKTOP, since_logon=9999)
    assert not main.started_at_login(["--show"], shortcut=STARTUP, since_logon=5)
    assert not main.started_at_login(["--show", "--tray"], shortcut="", since_logon=5)


def test_a_quiet_start_never_asks_the_running_copy_for_the_window():
    assert main.request_for(False, False, quiet=True) == b"tray"
    assert main.request_for(False, False, quiet=False) == b"show"
    assert main.request_for(True, False, quiet=True) == b"snip"
    assert main.request_for(False, True, quiet=False) == b"note"


def test_the_windows_probes_are_harmless_elsewhere(monkeypatch):
    monkeypatch.setattr(main.sys, "platform", "linux")
    assert main._launch_shortcut() is None
    assert main._seconds_since_logon() is None
    main._opt_out_of_restart_apps()  # does nothing, raises nothing
