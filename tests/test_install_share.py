"""0.20.0, install and share: start at sign-in, the update check, the .deb and the release page."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import autostart
import config
import release_notes
import updates

HERE = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


# -- start at sign-in -----------------------------------------------------------------------------
@pytest.fixture
def linux_home(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(autostart.shutil, "which", lambda name: None)
    return tmp_path


def test_the_linux_entry_starts_it_in_the_tray(linux_home):
    assert not autostart.is_enabled()
    path = autostart.enable()
    assert path == linux_home / "config" / "autostart" / "shadowsnip.desktop"
    text = path.read_text()
    assert "[Desktop Entry]" in text and "Name=ShadowSnip" in text
    exec_line = next(line for line in text.splitlines() if line.startswith("Exec="))
    assert exec_line.endswith(" --tray") and "main.py" in exec_line
    assert autostart.is_enabled()
    autostart.disable()
    assert not path.exists() and not autostart.is_enabled()
    autostart.disable()   # already gone: nothing to do, no error


def test_the_launcher_on_the_path_is_preferred(linux_home, monkeypatch):
    monkeypatch.setattr(autostart.shutil, "which", lambda name: "/usr/bin/shadowsnip")
    assert autostart.program() == ["/usr/bin/shadowsnip"]
    assert "Exec=/usr/bin/shadowsnip --tray" in autostart.desktop_entry(autostart.program())


def test_a_path_with_spaces_is_quoted(linux_home, monkeypatch):
    monkeypatch.setattr(autostart, "program", lambda: ["/opt/my tools/ShadowSnip"])
    autostart.enable()
    assert "Exec='/opt/my tools/ShadowSnip' --tray" in autostart.entry_path().read_text()


def test_an_entry_turned_off_in_the_desktop_reads_as_off(linux_home):
    path = autostart.enable()
    path.write_text(path.read_text() + "Hidden=true\n")
    assert not autostart.is_enabled()


def test_an_entry_install_sh_wrote_reads_as_on(linux_home):
    folder = linux_home / "config" / "autostart"
    folder.mkdir(parents=True)
    (folder / "shadowsnip.desktop").write_text("[Desktop Entry]\nExec=/home/me/.local/bin/shadowsnip --tray\n")
    assert autostart.is_enabled()


def test_windows_uses_the_startup_folder(tmp_path, monkeypatch):
    import main   # before sys.platform is changed below: it is the real sys module

    monkeypatch.setattr(autostart.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    path = autostart.entry_path()
    assert path.name == "ShadowSnip.lnk"
    assert path.parent.name == "Startup" and "Start Menu" in path.parts
    # main.py recognises a start from there as a login start.
    assert main.started_at_login([], shortcut=str(path)) is True


def test_settings_shows_what_is_really_there(linux_home):
    from settings_dialog import SettingsDialog

    autostart.enable()
    dialog = SettingsDialog(config.load())
    assert dialog.login_check.isChecked() and dialog.wants_login_start()
    autostart.disable()
    assert not SettingsDialog(config.load()).login_check.isChecked()


def test_the_app_applies_the_switch(monkeypatch):
    import app as app_mod

    calls = []
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(autostart, "set_enabled", calls.append)

    class Tray:
        def showMessage(self, *args):
            calls.append(args[1])

    stand_in = type("S", (), {"tray": Tray(), "_warn": lambda self, text: calls.append(text)})()
    app_mod.ShadowSnipApp._apply_login_start(stand_in, True)
    assert calls[0] is True and "sign in" in calls[1]
    calls.clear()
    app_mod.ShadowSnipApp._apply_login_start(stand_in, False)   # already off: nothing
    assert calls == []


# -- the update check -------------------------------------------------------------------------------
def test_versions_compare_as_numbers():
    assert updates.parse_version("v0.20.1") == (0, 20, 1)
    assert updates.parse_version("ShadowSnip v1.2") == (1, 2, 0)
    assert updates.parse_version("nightly") == ()
    assert updates.is_newer("v0.20.0", "0.19.0")
    assert updates.is_newer("0.100.0", "0.99.9")
    assert not updates.is_newer("v0.19.0", "0.19.0")
    assert not updates.is_newer("v0.18.1", "0.19.0")
    assert not updates.is_newer("garbage", "0.19.0")


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_the_latest_release_is_read_from_github():
    seen = {}

    def opener(request, timeout):
        seen["url"], seen["agent"], seen["timeout"] = request.full_url, request.get_header("User-agent"), timeout
        return _Answer(json.dumps({"tag_name": "v0.21.0", "html_url": "https://github.com/x/releases/tag/v0.21.0",
                                   "name": "ShadowSnip v0.21.0"}).encode())

    release = updates.fetch_latest("0.20.0", opener)
    assert (release.version, release.tag) == ("0.21.0", "v0.21.0")
    assert release.url.endswith("/v0.21.0")
    assert seen["url"] == updates.API_URL and seen["agent"] == "ShadowSnip/0.20.0"
    assert seen["timeout"] == updates.TIMEOUT_SECONDS


@pytest.mark.parametrize("answer", [b"not json", json.dumps([1, 2]).encode(), json.dumps({"x": 1}).encode()])
def test_a_bad_answer_is_an_update_error(answer):
    with pytest.raises(updates.UpdateError):
        updates.fetch_latest("0.20.0", lambda request, timeout: _Answer(answer))


def test_no_network_is_an_update_error():
    def offline(request, timeout):
        raise OSError("Name or service not known")

    with pytest.raises(updates.UpdateError, match="Could not reach GitHub"):
        updates.fetch_latest("0.20.0", offline)


def test_the_daily_check_is_off_unless_turned_on():
    assert config.DEFAULTS["update_check"] is False
    assert not updates.due({"update_check": False, "update_last_check": 0})
    assert updates.due({"update_check": True, "update_last_check": 0}, now=1_000_000)
    assert not updates.due({"update_check": True, "update_last_check": 1_000_000}, now=1_000_000 + 3600)
    assert updates.due({"update_check": True, "update_last_check": 1_000_000},
                       now=1_000_000 + updates.DAY_SECONDS)
    # A clock set back does not stop the check for good.
    assert updates.due({"update_check": True, "update_last_check": 5_000_000}, now=1_000_000)


def test_the_background_check_reports_back():
    got = []
    done = threading.Event()
    updates.check_in_background("0.20.0", lambda r, e: (got.append((r, e)), done.set()),
                                opener=lambda request, timeout: _Answer(b'{"tag_name": "v0.20.0"}'))
    assert done.wait(5)
    assert got[0][0].version == "0.20.0" and got[0][1] == ""
    done.clear()
    updates.check_in_background("0.20.0", lambda r, e: (got.append((r, e)), done.set()),
                                opener=lambda request, timeout: (_ for _ in ()).throw(OSError("down")))
    assert done.wait(5)
    assert got[1][0] is None and "down" in got[1][1]


def test_check_now_in_settings(monkeypatch):
    from settings_dialog import SettingsDialog

    dialog = SettingsDialog(config.load())
    assert not dialog.update_check.isChecked()
    release = updates.Release("9.0.0", "v9.0.0", "https://github.com/jh-infosec/ShadowSnip/releases/tag/v9.0.0")
    monkeypatch.setattr(dialog, "_run_update_check", lambda version, done: done(release, ""))
    dialog._check_now()
    QApplication.processEvents()
    assert "ShadowSnip 9.0.0 is out" in dialog.update_result.text()
    assert "releases/tag/v9.0.0" in dialog.update_result.text()
    assert dialog.btn_check_now.isEnabled()
    monkeypatch.setattr(dialog, "_run_update_check", lambda version, done: done(None, "Could not reach GitHub"))
    dialog._check_now()
    QApplication.processEvents()
    assert dialog.update_result.text() == "Could not reach GitHub"
    dialog.update_check.setChecked(True)
    assert dialog.values()["update_check"] is True


def test_a_newer_release_is_announced_and_opens_its_page(monkeypatch):
    import app as app_mod

    shown, opened = [], []

    class Tray:
        def showMessage(self, title, text, *args):
            shown.append(text)

    stand_in = type("S", (), {"tray": Tray()})()
    newer = updates.Release("99.0.0", "v99.0.0", "https://example.invalid/v99")
    app_mod.ShadowSnipApp._on_update_answer(stand_in, newer, "")
    assert "99.0.0 is out" in shown[0] and stand_in._update_url == newer.url
    from PySide6.QtGui import QDesktopServices

    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    app_mod.ShadowSnipApp._on_tray_message_clicked(stand_in)
    assert opened == [newer.url] and stand_in._update_url == ""
    shown.clear()
    same = updates.Release(config.APP_VERSION, "v" + config.APP_VERSION, "x")
    app_mod.ShadowSnipApp._on_update_answer(stand_in, same, "")
    app_mod.ShadowSnipApp._on_update_answer(stand_in, None, "offline")
    assert shown == []   # a daily check that finds nothing says nothing


# -- the release page and the .deb -------------------------------------------------------------------
CHANGELOG = """# Changelog

## Latest: 0.20.0

Install and share.

**Added**: a thing.

## 0.19.0

Older.
"""


def test_the_release_text_is_the_changelog_section():
    assert release_notes.section(CHANGELOG, "0.20.0") == "Install and share.\n\n**Added**: a thing."
    assert release_notes.section(CHANGELOG, "0.19.0") == "Older."
    assert release_notes.section(CHANGELOG, "0.1.0") == ""


def test_the_release_page_lists_downloads_and_checksums():
    text = release_notes.notes("v0.20.0", CHANGELOG, "abc  ShadowSnip-v0.20.0-windows.exe\n"
                                                      "def  shadowsnip_0.20.0_amd64.deb\n")
    assert text.startswith("Install and share.")
    assert "`sudo apt install ./shadowsnip_0.20.0_amd64.deb`" in text
    assert "`ShadowSnip-v0.20.0-linux.tar.gz`" in text
    assert "| `ShadowSnip-v0.20.0-windows.exe` | `abc` |" in text
    assert "SHA256SUMS.txt" in text


def test_the_real_changelog_has_this_version():
    text = (HERE / "CHANGELOG.md").read_text(encoding="utf-8")
    assert release_notes.section(text, config.APP_VERSION)


@pytest.mark.skipif(shutil.which("dpkg-deb") is None or sys.platform == "win32", reason="needs dpkg-deb")
def test_the_deb_package(tmp_path):
    binary = tmp_path / "ShadowSnip"
    binary.write_text("#!/bin/sh\necho ShadowSnip\n")
    binary.chmod(0o755)
    out = subprocess.run(["bash", str(HERE / "build_deb.sh"), str(binary), "v0.20.0", str(tmp_path / "out")],
                         check=True, capture_output=True, text=True).stdout.strip()
    deb = Path(out)
    assert deb.name == "shadowsnip_0.20.0_amd64.deb" and deb.is_file()
    info = subprocess.run(["dpkg-deb", "-f", str(deb)], check=True, capture_output=True, text=True).stdout
    assert "Package: shadowsnip" in info and "Version: 0.20.0" in info
    assert "libpulse0" in info and "x11-utils" in info and "Recommends: tesseract-ocr" in info
    listing = subprocess.run(["dpkg-deb", "-c", str(deb)], check=True, capture_output=True, text=True).stdout
    for path in ("./opt/shadowsnip/ShadowSnip", "./usr/bin/shadowsnip", "./usr/share/applications/shadowsnip.desktop",
                 "./usr/share/icons/hicolor/256x256/apps/shadowsnip.png"):
        assert path in listing
    assert listing.splitlines()[0].startswith("drwxr-xr-x")   # never a locked-down /


def test_build_deb_refuses_a_bad_version(tmp_path):
    if shutil.which("bash") is None or sys.platform == "win32":
        pytest.skip("needs bash")
    binary = tmp_path / "ShadowSnip"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    result = subprocess.run(["bash", str(HERE / "build_deb.sh"), str(binary), "latest", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode != 0 and "Not a version" in result.stderr
