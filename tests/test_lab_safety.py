"""0.18.0: locking a lab without stopping it, auto-lock, hidden names, RAM temp, Windows Hello."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog

import config
import hello
import lab
import lablock
import storage
import vault

PASSWORD = "correct horse battery"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fast_and_clean(monkeypatch, tmp_path):
    monkeypatch.setattr(vault, "SCRYPT_N", 2 ** 10)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    yield
    vault.lock_all()


@pytest.fixture
def fake_hello(monkeypatch):
    """A stand-in for Windows Hello: signs deterministically, like an RSA key does."""
    secret = os.urandom(32)
    calls = []

    def sign(challenge: bytes) -> bytes:
        calls.append(challenge)
        return hmac.new(secret, challenge, hashlib.sha512).digest() * 4

    monkeypatch.setattr(hello, "signer", sign)
    return calls


def _png(colour=(200, 30, 30)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 20), colour).save(buf, "PNG")
    return buf.getvalue()


def _encrypted(cfg, tmp_path, name="box", hide=False) -> Path:
    cfg["lab_root"] = str(tmp_path / "labs")
    target = lab.folder(cfg, name)
    target.mkdir(parents=True)
    vault.create(target, PASSWORD)
    if hide:
        vault.set_hide_names(target, True)
    lab.start(cfg, name)
    cfg["active_lab"] = name
    return target


def _names(folder: Path) -> set[str]:
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


# -- auto-lock -----------------------------------------------------------------------------------
def test_auto_lock_counts_idle_minutes():
    idle = {"s": 30.0}
    state = {"active": True, "busy": False, "minutes": 1}
    watcher = lablock.AutoLock(minutes=lambda: state["minutes"], active=lambda: state["active"],
                               busy=lambda: state["busy"], idle=lambda: idle["s"])
    watcher._last_use -= 3600   # ShadowSnip itself not used for an hour
    fired = []
    watcher.due.connect(fired.append)
    assert not watcher.check()
    idle["s"] = 61
    assert watcher.check() and fired == ["after 1 minute idle"]
    state["busy"] = True            # recording a clip holds it off
    assert not watcher.check()
    state["busy"] = False
    idle["s"] = 61
    watcher._last_use -= 3600
    state["minutes"] = 0            # never
    assert not watcher.check()
    state["minutes"], state["active"] = 1, False
    assert not watcher.check()
    watcher.timer.stop()


def test_without_a_system_clock_shadowsnips_own_use_counts():
    watcher = lablock.AutoLock(minutes=lambda: 1, idle=lambda: None)
    watcher._last_use -= 120
    assert watcher.idle_seconds() >= 120
    watcher.touch()
    assert watcher.idle_seconds() < 5
    watcher.timer.stop()


def test_system_idle_is_a_number_or_unknown():
    value = lablock.system_idle()
    assert value is None or value >= 0


def test_session_watcher_reports_lock_and_sleep():
    watcher = lablock.SessionWatcher(QApplication.instance())
    seen = []
    watcher.locking.connect(seen.append)
    watcher._on_lock()
    watcher._on_sleep(True)
    watcher._on_sleep(False)
    assert seen == ["when the session locked", "as the computer went to sleep"]


# -- the private temp folder ----------------------------------------------------------------------
def test_private_temp_is_in_ram_on_linux_and_private(tmp_path):
    folder = vault.private_temp()
    try:
        assert folder.name.startswith(f"{vault.TEMP_PREFIX}{os.getpid()}-")
        if sys.platform.startswith("linux") and Path("/dev/shm").is_dir():
            assert folder.parent == Path("/dev/shm")
        if os.name == "posix":
            assert (folder.stat().st_mode & 0o777) == 0o700
    finally:
        folder.rmdir()


def test_leftover_temp_folders_from_dead_processes_are_removed(monkeypatch, tmp_path):
    monkeypatch.setattr(vault, "temp_root", lambda: tmp_path)
    monkeypatch.setattr(vault.tempfile, "gettempdir", lambda: str(tmp_path))
    dead = tmp_path / f"{vault.TEMP_PREFIX}999999999-abc"
    mine = tmp_path / f"{vault.TEMP_PREFIX}{os.getpid()}-abc"
    other = tmp_path / "someone-elses"
    for folder in (dead, mine, other):
        folder.mkdir()
        (folder / "x.png").write_bytes(b"plain")
    assert vault.clean_stale_temp() == 1
    assert not dead.exists() and mine.exists() and other.exists()


# -- hiding names --------------------------------------------------------------------------------
def test_names_are_hidden_while_locked_and_come_back(cfg, tmp_path):
    target = _encrypted(cfg, tmp_path, hide=True)
    lab.set_section(cfg, "SMB")
    snips = [lab.save(_png((i, 0, 0)), "png", cfg) for i in range(3)]
    lab.remove_snip(cfg, snips[0].name)
    before = _names(target)
    assert any("2026" in name or name.startswith("00") for name in before)
    vault.lock(target)
    after = _names(target)
    assert len(after) == len(before) + 1          # + lab.names
    assert {vault.KEY_NAME, vault.NAMES_NAME} <= after
    hidden = after - {vault.KEY_NAME, vault.NAMES_NAME, ".gitignore"}
    assert all(len(Path(name).name) == 24 and "." not in Path(name).name for name in hidden)
    assert any(name.startswith("removed/") for name in hidden)   # folders keep their names
    vault.unlock(target, password=PASSWORD)
    assert _names(target) == before
    assert [row["file"] for row in lab.snip_rows(cfg)] == [s.name for s in snips[1:]]


def test_names_stay_when_the_lab_does_not_ask(cfg, tmp_path):
    target = _encrypted(cfg, tmp_path)
    lab.save(_png(), "png", cfg)
    before = _names(target)
    vault.lock(target)
    assert _names(target) == before


def test_an_interrupted_hide_is_put_right_on_unlock(cfg, tmp_path, monkeypatch):
    target = _encrypted(cfg, tmp_path, hide=True)
    for i in range(4):
        lab.save(_png((i, 0, 0)), "png", cfg)
    before = _names(target)
    real_replace = Path.replace
    count = {"n": 0}

    def flaky(self, other):
        count["n"] += 1
        if count["n"] == 3:
            raise OSError("in use")
        return real_replace(self, other)

    monkeypatch.setattr(Path, "replace", flaky)
    vault.lock(target)
    monkeypatch.setattr(Path, "replace", real_replace)
    vault.unlock(target, password=PASSWORD)
    assert _names(target) == before


def test_a_tampered_name_list_cannot_move_files_out_of_the_lab(cfg, tmp_path):
    target = _encrypted(cfg, tmp_path, hide=True)
    lab.save(_png(), "png", cfg)
    found = vault.vault_for(target)
    victim = tmp_path / "outside.txt"
    (target / "abc").write_bytes(b"x")
    storage.write_atomic(target / vault.NAMES_NAME,
                         json.dumps({"format": 1, "names": {"abc": "../../outside.txt"}}).encode())
    assert found is not None
    vault.reveal_names(target)
    assert not victim.exists() and (target / "abc").exists()


def test_password_changes_keep_the_hide_setting(cfg, tmp_path):
    target = _encrypted(cfg, tmp_path, hide=True)
    vault.change_password(target, "another passphrase", old_password=PASSWORD)
    assert vault.hides_names(target)
    vault.rewrap(target, vault.vault_for(target), "a third passphrase")
    assert vault.hides_names(target)
    vault.set_hide_names(target, False)
    assert not vault.hides_names(target)


def test_decrypting_leaves_names_alone(cfg, tmp_path):
    target = _encrypted(cfg, tmp_path, hide=True)
    snip = lab.save(_png(), "png", cfg)
    vault.decrypt_folder(target)
    assert snip.is_file() and not (target / vault.NAMES_NAME).exists()


# -- Windows Hello (with a stand-in signer) ------------------------------------------------------------
def test_hello_keeps_and_gives_back_the_lab_key(cfg, tmp_path, fake_hello):
    target = _encrypted(cfg, tmp_path)
    secret = vault.vault_for(target).encrypt(b"loot")
    assert not vault.hello_enrolled(target)
    vault.set_hello(target, True)
    assert vault.hello_enrolled(target) and len(fake_hello) == 2   # signed twice to check it repeats
    stored = list((tmp_path / "appdata" / "ShadowSnip" / "hello").glob("*.json"))
    assert len(stored) == 1 and b"loot" not in stored[0].read_bytes()
    vault.lock(target)
    vault.unlock_with_hello(target)
    assert vault.vault_for(target).decrypt(secret) == b"loot"
    vault.set_hello(target, False)
    assert not vault.hello_enrolled(target)
    vault.lock(target)
    with pytest.raises(hello.HelloError):
        vault.unlock_with_hello(target)


def test_hello_with_a_changed_key_falls_back(cfg, tmp_path, fake_hello, monkeypatch):
    target = _encrypted(cfg, tmp_path)
    vault.set_hello(target, True)
    vault.lock(target)
    monkeypatch.setattr(hello, "signer", lambda challenge: os.urandom(256))
    with pytest.raises(hello.HelloError, match="changed"):
        vault.unlock_with_hello(target)
    vault.unlock(target, password=PASSWORD)    # the password still works


def test_a_signer_that_does_not_repeat_is_refused(cfg, tmp_path, monkeypatch):
    target = _encrypted(cfg, tmp_path)
    monkeypatch.setattr(hello, "signer", lambda challenge: os.urandom(256))
    with pytest.raises(hello.HelloError, match="same way twice"):
        vault.set_hello(target, True)
    assert not vault.hello_enrolled(target)


def test_decrypting_forgets_hello(cfg, tmp_path, fake_hello):
    target = _encrypted(cfg, tmp_path)
    vault.set_hello(target, True)
    lab_id = json.loads((target / vault.KEY_NAME).read_text())["id"]
    vault.decrypt_folder(target)
    assert not hello.is_enrolled(lab_id)


def test_the_unlock_window_tries_hello_first(tmp_path):
    import labkeys

    tries = []

    def hello_ok():
        tries.append("hello")

    dialog = labkeys.UnlockDialog("box", lambda **k: None, try_hello=hello_ok)
    assert not dialog.btn_hello.isHidden()
    dialog._attempt_hello()
    assert tries == ["hello"] and dialog.used_hello and dialog.result() == QDialog.DialogCode.Accepted

    def cancelled():
        raise hello.HelloCancelled("no")

    dialog = labkeys.UnlockDialog("box", lambda **k: None, try_hello=cancelled)
    dialog._attempt_hello()
    assert dialog.result() == 0 and "cancelled" in dialog.error.text() and not dialog.used_hello
    plain = labkeys.UnlockDialog("box", lambda **k: None)
    assert plain.btn_hello.isHidden()


def test_the_unlock_window_switches_to_the_recovery_key_unshown():
    import labkeys

    dialog = labkeys.UnlockDialog("box", lambda **k: None)
    dialog._toggle_recovery()
    assert not dialog.recovery.isHidden() and dialog.password.isHidden()


def test_dialogs_offer_hiding_names():
    import labkeys

    start = labkeys.StartLabDialog("", False, exists=lambda name: False)
    start.name.setText("fresh")
    start.encrypt.setChecked(True)
    start.hide.setChecked(True)
    assert start.hide_names()
    start.encrypt.setChecked(False)
    assert not start.hide_names()
    encrypting = labkeys.PasswordDialog("Encrypt lab", "x", offer_hide=True)
    changing = labkeys.PasswordDialog("Change password", "x", ask_current=True)
    assert not encrypting.hide.isHidden() and changing.hide.isHidden()


def test_settings_for_locking():
    import settings_dialog

    cfg = config._sanitise({**config.DEFAULTS, "lab_autolock_minutes": 999, "lab_lock_with_session": False})
    assert cfg["lab_autolock_minutes"] == 240
    dialog = settings_dialog.SettingsDialog(cfg)
    assert dialog.lab_autolock_spin.value() == 240 and not dialog.lab_session_check.isChecked()
    dialog.lab_autolock_spin.setValue(0)
    assert dialog.values()["lab_autolock_minutes"] == 0
    assert config._sanitise({**config.DEFAULTS, "lab_autolock_minutes": "x"})["lab_autolock_minutes"] == 15


# -- the app -------------------------------------------------------------------------------------
@pytest.fixture
def shadow(tmp_path, monkeypatch):
    import app as app_mod
    import clipboard
    import platforms

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(clipboard, "copy", lambda *a, **k: None)
    monkeypatch.setattr(platforms.HotkeyManager, "register", lambda *a, **k: None)
    s = app_mod.ShadowSnipApp(QApplication.instance())
    s.autolock.timer.stop()
    s.cfg["save_dir"] = str(tmp_path / "snips")
    s.cfg["show_preview"] = False
    _encrypted(s.cfg, tmp_path, "secret")
    s._refresh_menu_text()
    yield s
    s.autocopy.release()


def _snip(shadow):
    image = QImage(80, 40, QImage.Format.Format_RGB32)
    image.fill(QColor(30, 90, 30))
    shadow._handle_snip(image)


def _answer_unlock(monkeypatch, ok=True):
    import labkeys

    asked = []

    def run(dialog):
        asked.append(1)
        if not ok:
            return 0
        dialog.password.setText(PASSWORD)
        dialog._attempt()
        return dialog.result()

    monkeypatch.setattr(labkeys.UnlockDialog, "exec", run)
    return asked


def test_locking_keeps_the_lab_running(shadow):
    folder = lab.active_folder(shadow.cfg)
    _snip(shadow)
    assert shadow.lock_lab("for the test")
    assert lab.active_name(shadow.cfg) == "secret" and shadow._lab_locked()
    assert not shadow.preview.snips_panel.locked_panel.isHidden()
    assert shadow.preview.snips_panel.splitter.isHidden()
    assert shadow.preview._image is None          # nothing of the lab left on screen
    assert shadow.action_lock.text() == "Unlock lab..." and not shadow.action_password.isEnabled()
    assert not vault.is_unlocked(folder)
    assert not shadow.lock_lab()      # already locked


def test_a_snip_into_a_locked_lab_asks_first(shadow, monkeypatch, tmp_path):
    folder = lab.active_folder(shadow.cfg)
    shadow.lock_lab()
    asked = _answer_unlock(monkeypatch)
    _snip(shadow)
    assert asked == [1] and lab.count(shadow.cfg) == 1 and vault.is_unlocked(folder)
    assert shadow.preview.snips_panel.locked_panel.isHidden()


def test_a_cancelled_unlock_saves_nothing_anywhere(shadow, monkeypatch, tmp_path):
    folder = lab.active_folder(shadow.cfg)
    shadow.lock_lab()
    _answer_unlock(monkeypatch, ok=False)
    before = _names(folder)
    _snip(shadow)
    assert _names(folder) == before
    save_dir = Path(shadow.cfg["save_dir"])
    plain = [p for p in save_dir.rglob("*") if p.is_file()] if save_dir.exists() else []
    assert plain == []
    assert "locked" in shadow.preview.status.text()


def test_unlocking_from_the_list(shadow, monkeypatch):
    shadow.lock_lab()
    _answer_unlock(monkeypatch)
    shadow.preview.snips_panel.btn_unlock.click()
    assert not shadow._lab_locked()


def test_the_idle_timer_and_the_session_lock_the_lab(shadow):
    shadow.autolock.due.emit("after 15 minutes idle")
    assert shadow._lab_locked()
    vault.unlock(lab.active_folder(shadow.cfg), password=PASSWORD)
    shadow.cfg["lab_lock_with_session"] = False
    shadow.session_watch.locking.emit("when Windows locked")
    assert not shadow._lab_locked()
    shadow.cfg["lab_lock_with_session"] = True
    shadow.session_watch.locking.emit("when Windows locked")
    assert shadow._lab_locked()


def test_a_recording_holds_the_lock_off(shadow):
    shadow.recorder = object()
    try:
        assert not shadow.lock_lab()
        shadow.stop_lab()
        assert lab.active_name(shadow.cfg) == "secret"   # not stopped mid-clip
    finally:
        shadow.recorder = None


def test_a_clip_of_an_encrypted_lab_records_into_the_private_folder(shadow, monkeypatch):
    import recorder

    seen = []

    class Fake:
        def __init__(self, rect, path, **kwargs):
            seen.append(Path(path))
            raise recorder.RecorderError("stop here")

    monkeypatch.setattr(recorder, "Recorder", Fake)
    monkeypatch.setattr(shadow, "_warn", lambda *a, **k: None)
    shadow._start_recording(QRect(0, 0, 100, 100))
    folder = lab.active_folder(shadow.cfg)
    assert seen and folder not in seen[0].parents
    assert seen[0].parent.parent == vault.vault_for(folder).handoff_dir()


def test_hello_from_the_menu_and_at_unlock(shadow, fake_hello, monkeypatch):
    import labkeys

    folder = lab.active_folder(shadow.cfg)
    shadow.set_lab_hello(True)
    assert vault.hello_enrolled(folder)
    shadow.lock_lab()
    used = []

    def run(dialog):
        used.append(dialog._try_hello is not None)
        dialog._attempt_hello()
        return dialog.result()

    monkeypatch.setattr(labkeys.UnlockDialog, "exec", run)
    assert shadow.unlock_lab() and used == [True]


def test_hiding_names_from_the_menu(shadow):
    folder = lab.active_folder(shadow.cfg)
    _snip(shadow)
    shadow.set_hide_lab_names(True)
    assert vault.hides_names(folder) and shadow.action_hide_names.isChecked()
    shadow.lock_lab()
    assert not any(name.startswith("001_") for name in _names(folder))
