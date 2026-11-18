"""Encrypted labs (0.16.0): keys, files at rest, every reader, and the app's flows."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QRect, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QDialog

import clips
import config
import edits
import lab
import report
import storage
import vault

PASSWORD = "correct horse battery"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch):
    """Real labs use N=2^17; the tests would spend minutes on it."""
    monkeypatch.setattr(vault, "SCRYPT_N", 2 ** 10)
    yield
    vault.lock_all()


@pytest.fixture
def cfg_lab(cfg, tmp_path):
    cfg["lab_root"] = str(tmp_path / "labs")
    return cfg


def _png(colour=(200, 30, 30), width=60, height=30) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, "PNG")
    return buf.getvalue()


def _encrypted_lab(cfg, name="box") -> tuple[Path, str]:
    target = lab.folder(cfg, name)
    target.mkdir(parents=True)
    recovery = vault.create(target, PASSWORD)
    lab.start(cfg, name)
    cfg["active_lab"] = name
    return target, recovery


def _plain_files(folder: Path) -> list[str]:
    """Files in the folder that are not encrypted (besides the two meant to be plain)."""
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*")
                  if p.is_file() and p.name not in vault.PLAIN_NAMES and not vault.is_encrypted_file(p))


# -- keys ---------------------------------------------------------------------------------------
def test_a_new_lab_key_opens_with_the_password_and_the_recovery_key(tmp_path):
    recovery = vault.create(tmp_path, PASSWORD)
    assert len(recovery) == 39 and recovery.count("-") == 7
    record = json.loads((tmp_path / vault.KEY_NAME).read_text())
    assert record["format"] == 1 and record["password"]["kdf"] == "scrypt"
    assert PASSWORD not in json.dumps(record) and recovery not in json.dumps(record)
    secret = vault.vault_for(tmp_path).encrypt(b"hash: aad3b435")
    vault.lock(tmp_path)
    assert not vault.is_unlocked(tmp_path)
    vault.unlock(tmp_path, password=PASSWORD)
    assert vault.vault_for(tmp_path).decrypt(secret) == b"hash: aad3b435"
    vault.lock(tmp_path)
    vault.unlock(tmp_path, recovery=recovery.lower().replace("-", " "))   # typed loosely
    assert vault.vault_for(tmp_path).decrypt(secret) == b"hash: aad3b435"


def test_wrong_keys_are_refused(tmp_path):
    vault.create(tmp_path, PASSWORD)
    vault.lock(tmp_path)
    with pytest.raises(vault.WrongKey):
        vault.unlock(tmp_path, password="nope nope nope")
    with pytest.raises(vault.WrongKey):
        vault.unlock(tmp_path, recovery="AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA")
    assert not vault.is_unlocked(tmp_path)


def test_passwords_must_be_long_enough(tmp_path):
    assert vault.password_problem("short")
    assert vault.password_problem("long enough", "different") == "The two passwords are not the same."
    assert vault.password_problem("long enough", "long enough") == ""
    with pytest.raises(vault.VaultError):
        vault.create(tmp_path, "short")
    assert not (tmp_path / vault.KEY_NAME).exists()


def test_a_key_file_asking_for_silly_scrypt_settings_is_refused(tmp_path):
    vault.create(tmp_path, PASSWORD)
    vault.lock(tmp_path)
    record = json.loads((tmp_path / vault.KEY_NAME).read_text())
    record["password"]["n"] = 2 ** 30
    (tmp_path / vault.KEY_NAME).write_text(json.dumps(record))
    with pytest.raises(vault.VaultError, match="scrypt"):
        vault.unlock(tmp_path, password=PASSWORD)


def test_changing_the_password_keeps_the_files_and_replaces_the_recovery_key(tmp_path):
    old_recovery = vault.create(tmp_path, PASSWORD)
    blob = vault.vault_for(tmp_path).encrypt(b"loot")
    with pytest.raises(vault.WrongKey):
        vault.change_password(tmp_path, "a new passphrase", old_password="wrong one!")
    new_recovery = vault.change_password(tmp_path, "a new passphrase", old_password=PASSWORD)
    assert new_recovery != old_recovery
    vault.lock(tmp_path)
    with pytest.raises(vault.WrongKey):
        vault.unlock(tmp_path, password=PASSWORD)
    with pytest.raises(vault.WrongKey):
        vault.unlock(tmp_path, recovery=old_recovery)
    vault.unlock(tmp_path, password="a new passphrase")
    assert vault.vault_for(tmp_path).decrypt(blob) == b"loot"
    vault.lock(tmp_path)
    found = vault.unlock(tmp_path, recovery=new_recovery)
    third = vault.rewrap(tmp_path, found, "after recovery")
    vault.lock(tmp_path)
    vault.unlock(tmp_path, password="after recovery")
    vault.lock(tmp_path)
    vault.unlock(tmp_path, recovery=third)


def test_a_file_from_another_lab_or_tampered_with_does_not_open(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir(), two.mkdir()
    vault.create(one, PASSWORD)
    vault.create(two, PASSWORD)
    storage.write_atomic(one / "a.txt", b"secret one")
    (two / "a.txt").write_bytes((one / "a.txt").read_bytes())   # copied across
    with pytest.raises(vault.Damaged, match="another lab"):
        vault.read(two / "a.txt")
    blob = bytearray((one / "a.txt").read_bytes())
    blob[-1] ^= 1
    (one / "a.txt").write_bytes(bytes(blob))
    with pytest.raises(vault.Damaged):
        vault.read(one / "a.txt")
    (one / "b.txt").write_bytes(vault.MAGIC + b"short")
    with pytest.raises(vault.Damaged):
        vault.read(one / "b.txt")


# -- files at rest ----------------------------------------------------------------------------
def test_writes_inside_an_unlocked_lab_are_encrypted_and_reads_decrypted(tmp_path):
    vault.create(tmp_path, PASSWORD)
    storage.write_atomic(tmp_path / "sub" / "deep" / "x.json", b'{"a": 1}')
    raw = (tmp_path / "sub" / "deep" / "x.json").read_bytes()
    assert raw.startswith(vault.MAGIC) and b'"a"' not in raw
    assert vault.read(tmp_path / "sub" / "deep" / "x.json") == b'{"a": 1}'
    storage.write_atomic(tmp_path / ".gitignore", b"*\n")
    assert (tmp_path / ".gitignore").read_bytes() == b"*\n"
    storage.write_atomic(tmp_path / "export.html", b"<html>", plain=True)
    assert (tmp_path / "export.html").read_bytes() == b"<html>"


def test_a_locked_lab_refuses_writes_and_reads(tmp_path):
    vault.create(tmp_path, PASSWORD)
    storage.write_atomic(tmp_path / "lab.json", b"{}")
    vault.lock(tmp_path)
    with pytest.raises(vault.Locked):
        storage.write_atomic(tmp_path / "lab.json", b'{"overwritten": true}')
    with pytest.raises(vault.Locked):
        storage.write_atomic(tmp_path / "removed" / "x.png", b"plain")
    with pytest.raises(vault.Locked):
        vault.read(tmp_path / "lab.json")
    assert vault.load_image(tmp_path / "lab.json").isNull()


def test_plain_files_outside_labs_are_untouched(tmp_path):
    storage.write_atomic(tmp_path / "a.png", b"plain")
    assert vault.read(tmp_path / "a.png") == b"plain"
    assert vault.handoff(tmp_path / "a.png") == tmp_path / "a.png"
    assert vault.scratch(tmp_path / "a.mp4") is None


def test_an_encrypted_lab_works_end_to_end(cfg_lab, tmp_path):
    target, _recovery = _encrypted_lab(cfg_lab)
    lab.set_section(cfg_lab, "10.10.10.3/SMB")
    snip = lab.save(_png(), "png", cfg_lab)
    lab.add_note(cfg_lab, "password: Summer2026!", attach=[snip.name])
    lab.set_finding(cfg_lab, "10.10.10.3/SMB", {"severity": "High", "description": "guest share"})
    # Nothing readable on disk.
    assert _plain_files(target) == []
    for path in target.rglob("*"):
        if path.is_file():
            assert b"Summer2026" not in path.read_bytes()
    # Everything readable through ShadowSnip.
    assert "password: Summer2026!" in vault.read_text(target / lab.INDEX_NAME)
    rows = lab.snip_rows(cfg_lab)
    assert rows[0]["notes"] == ["password: Summer2026!"]
    assert vault.load_image(snip).width() == 60
    assert vault.image_size(snip).width() == 60
    data = report.model(target)
    assert data["findings"][0]["severity"] == "High"
    out = report.export(target, "html", tmp_path / "r.html")
    assert "Summer2026" in out.read_text(encoding="utf-8") and "data:image/png;base64" in out.read_text()
    pdf = report.export(target, "pdf", tmp_path / "r.pdf")
    assert pdf.read_bytes().startswith(b"%PDF")


def test_a_locked_encrypted_lab_cannot_be_started_over(cfg_lab):
    target, _ = _encrypted_lab(cfg_lab)
    lab.add_note(cfg_lab, "kept")
    before = (target / lab.STATE_NAME).read_bytes()
    vault.lock(target)
    with pytest.raises(lab.LabError, match="encrypted"):
        lab.start(cfg_lab, "box")
    assert (target / lab.STATE_NAME).read_bytes() == before
    lab.snip_rows(cfg_lab)   # reading a locked lab gives nothing and raises nothing
    vault.unlock(target, password=PASSWORD)
    assert [e["text"] for e in lab.entries(cfg_lab)] == ["kept"]


def test_kept_marks_survive_in_an_encrypted_lab(cfg_lab):
    from annotate import AnnotationDoc, Mark
    from PySide6.QtCore import QPointF

    target, _ = _encrypted_lab(cfg_lab)
    snip = lab.save(_png(), "png", cfg_lab)
    base = vault.load_image(snip)
    doc = AnnotationDoc(base)
    doc.ops.append(Mark(doc.new_id(), "rect", "#ff0000", QPointF(2, 2), QPointF(20, 20), 3.0))
    flat = doc.render()
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    flat.save(buffer, "PNG")
    storage.write_atomic(snip, bytes(raw.data()))
    edits.save(snip, doc, bytes(raw.data()))
    assert _plain_files(target) == []
    loaded = edits.load(snip)
    assert loaded is not None and loaded.ops and loaded.ops[0].kind == "rect"


def test_remove_and_restore_in_an_encrypted_lab(cfg_lab):
    target, _ = _encrypted_lab(cfg_lab)
    snip = lab.save(_png(), "png", cfg_lab)
    lab.remove_snip(cfg_lab, snip.name)
    rows = lab.removed_snips(cfg_lab)
    assert rows and vault.is_encrypted_file(rows[0]["path"])
    lab.restore_snip(cfg_lab, snip.name)
    assert snip.is_file() and vault.is_encrypted_file(snip) and _plain_files(target) == []


def test_handing_a_file_to_another_program_uses_a_private_temp_copy(cfg_lab):
    target, _ = _encrypted_lab(cfg_lab)
    snip = lab.save(_png(), "png", cfg_lab)
    copy = vault.handoff(snip)
    assert copy != snip and target not in copy.parents
    assert copy.read_bytes() == _png()
    vault.lock(target)
    assert not copy.exists() and not copy.parent.exists()
    with pytest.raises(vault.Locked):
        vault.handoff(snip)


# -- turning a lab's encryption on and off ---------------------------------------------------------
def test_an_existing_lab_is_encrypted_in_place_and_back(cfg_lab):
    lab.start(cfg_lab, "box")
    cfg_lab["active_lab"] = "box"
    target = lab.active_folder(cfg_lab)
    snip = lab.save(_png(), "png", cfg_lab)
    lab.add_note(cfg_lab, "creds in here")
    lab.remove_snip(cfg_lab, lab.save(_png((1, 2, 3)), "png", cfg_lab).name)
    assert _plain_files(target)
    vault.create(target, PASSWORD)
    seen = []
    count = vault.encrypt_folder(target, progress=lambda done, total, name: seen.append(name))
    assert count == len(seen) >= 4 and _plain_files(target) == []
    assert (target / ".gitignore").exists() is False or not vault.is_encrypted_file(target / ".gitignore")
    assert vault.encrypt_folder(target) == 0      # running it again finds nothing left to do
    assert "creds in here" in vault.read_text(target / lab.INDEX_NAME)
    count = vault.decrypt_folder(target)
    assert count >= 4 and not (target / vault.KEY_NAME).exists() and not vault.is_unlocked(target)
    assert "creds in here" in (target / lab.INDEX_NAME).read_text(encoding="utf-8")
    assert snip.read_bytes() == _png()


def test_an_interrupted_encryption_still_opens_and_finishes(cfg_lab):
    lab.start(cfg_lab, "box")
    cfg_lab["active_lab"] = "box"
    target = lab.active_folder(cfg_lab)
    for i in range(4):
        lab.save(_png((i, 0, 0)), "png", cfg_lab)
    vault.create(target, PASSWORD)
    stopped = vault.encrypt_folder(target, progress=lambda done, total, name: done < 2)
    assert stopped == 2
    mixed = _plain_files(target)
    assert mixed      # half done: some files plain, some encrypted
    assert len(lab.snip_rows(cfg_lab)) == 4
    assert all(not vault.load_image(row["path"]).isNull() for row in lab.snip_rows(cfg_lab))
    vault.encrypt_folder(target)
    assert _plain_files(target) == []


# -- clips --------------------------------------------------------------------------------------
def _wait(predicate, ms=15000) -> bool:
    loop = QEventLoop()
    poll = QTimer()
    poll.timeout.connect(lambda: predicate() and loop.quit())
    poll.start(20)
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    poll.stop()
    return bool(predicate())


def _record(tmp_path, seconds=1.5) -> tuple[Path, QImage, float]:
    import time

    import recorder
    from PySide6.QtGui import QGuiApplication

    t0 = []

    def grab(_screen, rect):
        if not t0:
            t0.append(time.monotonic())
        level = int((time.monotonic() - t0[0]) * 60) % 256
        img = QImage(rect.width(), rect.height(), QImage.Format.Format_RGB32)
        img.fill(QColor(level, level, level))
        return img

    geom = QGuiApplication.primaryScreen().geometry()
    rec = recorder.Recorder(QRect(geom.x(), geom.y(), 160, 90), tmp_path / "rec.mp4", fps=15, grab=grab)
    done = []
    rec.finished.connect(done.append)
    rec.failed.connect(lambda m: done.append(None))
    try:
        rec.start()
    except recorder.RecorderError as exc:
        pytest.skip(f"no video encoder here: {exc}")
    QTimer.singleShot(int(seconds * 1000), rec.stop)
    _wait(lambda: bool(done))
    if not done or done[0] is None:
        pytest.skip("this machine's encoder recorded nothing")
    return Path(done[0]), rec.first_frame, rec.elapsed()


def test_a_clip_in_an_encrypted_lab_is_encrypted_and_still_plays_trims_and_exports(cfg_lab, tmp_path):
    import cliptrim
    import player

    target, _ = _encrypted_lab(cfg_lab)
    video, frame, seconds = _record(tmp_path)
    poster = lab.save(clips.make_poster(frame, seconds), "png", cfg_lab, companion=video)
    clip = poster.with_suffix(".mp4")
    assert not video.exists() and vault.is_encrypted_file(clip) and _plain_files(target) == []
    assert clips.length_of(poster) == pytest.approx(seconds, abs=0.01)
    # Plays from memory.
    widget = player.ClipPlayer()
    widget.load(clip, vault.load_image(poster))
    widget.play()
    assert _wait(lambda: widget.screen_area.picture is not None and widget.is_playing(), 8000)
    widget.unload()
    # GIF export reads it too.
    assert clips.export_gif(clip, tmp_path / "c.gif") > 3
    # A trim writes the new clip through the private temp folder, then encrypts it in.
    new_length = cliptrim.trim(clip, 300, 1000)
    assert 0.5 < new_length < 0.9
    assert vault.is_encrypted_file(clip) and vault.is_encrypted_file(cliptrim.untrimmed_of(clip))
    assert _plain_files(target) == []
    assert cliptrim.untrim(clip) > 1.2 and vault.is_encrypted_file(clip)
    # Copy as a file hands over a decrypted copy, outside the lab.
    pasted = []
    import clipboard

    original = clipboard.copy_files
    clipboard.copy_files = pasted.extend
    try:
        clips.copy_file(clip)
    finally:
        clipboard.copy_files = original
    assert pasted and target not in Path(pasted[0]).parents and not vault.is_encrypted_file(pasted[0])


# -- the windows ----------------------------------------------------------------------------------
def test_the_start_window_offers_encryption_only_for_a_new_lab():
    import labkeys

    dialog = labkeys.StartLabDialog("", False, exists=lambda name: name == "old")
    dialog.name.setText("fresh")
    dialog.encrypt.setChecked(True)
    assert not dialog.btn_start.isEnabled()
    dialog.passwords.password.setText(PASSWORD)
    dialog.passwords.again.setText(PASSWORD)
    assert dialog.btn_start.isEnabled()
    assert dialog.values() == ("fresh", True, PASSWORD)
    dialog.name.setText("old")
    assert dialog.encrypt.isHidden() and dialog.btn_start.isEnabled()
    assert dialog.values() == ("old", False, "")


def test_the_start_window_can_default_to_encrypting():
    import labkeys

    dialog = labkeys.StartLabDialog("x", True)
    assert dialog.encrypt.isChecked()


def test_the_unlock_window_stays_open_on_a_wrong_password(tmp_path):
    import labkeys

    vault.create(tmp_path, PASSWORD)
    vault.lock(tmp_path)
    tries = []

    def attempt(password=None, recovery=None):
        tries.append(password or recovery)
        vault.unlock(tmp_path, password=password, recovery=recovery)

    dialog = labkeys.UnlockDialog("box", attempt)
    dialog.password.setText("wrong wrong")
    dialog._attempt()
    assert dialog.result() == 0 and not dialog.error.isHidden()
    assert "does not open" in dialog.error.text()
    dialog.password.setText(PASSWORD)
    dialog._attempt()
    assert dialog.result() == QDialog.DialogCode.Accepted and not dialog.recovered
    assert tries == ["wrong wrong", PASSWORD]


def test_the_recovery_key_window_waits_until_it_is_saved():
    import labkeys

    dialog = labkeys.RecoveryKeyDialog("box", "ABCD-EFGH-JKLM-NPQR-STUV-WXYZ-2345-6789")
    assert not dialog.btn_ok.isEnabled()
    dialog.show()
    dialog.reject()      # Esc before ticking does not close it
    assert dialog.isVisible()
    dialog.saved.setChecked(True)
    assert dialog.btn_ok.isEnabled()
    dialog._copy()
    assert QApplication.clipboard().text() == "ABCD-EFGH-JKLM-NPQR-STUV-WXYZ-2345-6789"
    QApplication.clipboard().clear()


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
    s.cfg["save_dir"] = str(tmp_path / "snips")
    s.cfg["lab_root"] = str(tmp_path / "labs")
    s.cfg["show_preview"] = False
    yield s
    s.autocopy.release()


def _answer_start(monkeypatch, name, encrypt=False, password=""):
    import labkeys

    monkeypatch.setattr(labkeys.StartLabDialog, "exec", lambda d: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(labkeys.StartLabDialog, "values", lambda d: (name, encrypt, password))
    shown = []
    monkeypatch.setattr(labkeys.RecoveryKeyDialog, "exec", lambda d: shown.append(d.key) or 1)
    return shown


def test_starting_an_encrypted_lab_from_the_app(shadow, monkeypatch):
    shown = _answer_start(monkeypatch, "secret", True, PASSWORD)
    shadow.start_lab()
    folder = lab.active_folder(shadow.cfg)
    assert vault.is_encrypted_lab(folder) and vault.is_unlocked(folder)
    assert len(shown) == 1 and shown[0].count("-") == 7
    assert "(encrypted)" in shadow.tray.toolTip()
    assert shadow.action_encrypt.text() == "Decrypt this lab..." and shadow.action_password.isEnabled()
    image = QImage(120, 80, QImage.Format.Format_RGB32)
    image.fill(QColor(90, 10, 10))
    shadow._handle_snip(image)
    assert _plain_files(folder) == []
    latest = list(Path(shadow.cfg["save_dir"]).glob("latest.*"))
    assert latest == []      # no plain copy outside the lab
    shadow.stop_lab()
    assert not vault.is_unlocked(folder)


def test_resuming_an_encrypted_lab_asks_for_its_password(shadow, monkeypatch):
    import labkeys

    _answer_start(monkeypatch, "secret", True, PASSWORD)
    shadow.start_lab()
    shadow.stop_lab()
    _answer_start(monkeypatch, "secret")
    asked = []

    def unlock_exec(dialog):
        asked.append(1)
        dialog.password.setText(PASSWORD)
        dialog._attempt()
        return dialog.result()

    monkeypatch.setattr(labkeys.UnlockDialog, "exec", unlock_exec)
    shadow.start_lab()
    assert asked == [1] and vault.is_unlocked(lab.active_folder(shadow.cfg))
    shadow.stop_lab()
    # Cancelled: the lab stays locked and does not start.
    monkeypatch.setattr(labkeys.UnlockDialog, "exec", lambda d: 0)
    shadow.start_lab()
    assert lab.active_name(shadow.cfg) == ""


def test_a_lab_left_running_is_unlocked_or_stopped_at_start(shadow, monkeypatch):
    import labkeys

    _answer_start(monkeypatch, "secret", True, PASSWORD)
    shadow.start_lab()
    folder = lab.active_folder(shadow.cfg)
    vault.lock(folder)   # as after a restart
    monkeypatch.setattr(labkeys.UnlockDialog, "exec", lambda d: 0)
    shadow._unlock_active_lab_at_start()
    assert lab.active_name(shadow.cfg) == "" and not vault.is_unlocked(folder)


def test_encrypting_and_decrypting_the_running_lab_from_the_menu(shadow, monkeypatch):
    import labkeys
    from PySide6.QtWidgets import QMessageBox

    _answer_start(monkeypatch, "plainlab")
    shadow.start_lab()
    folder = lab.active_folder(shadow.cfg)
    lab.add_note(shadow.cfg, "creds")
    monkeypatch.setattr(labkeys.PasswordDialog, "exec", lambda d: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(labkeys.PasswordDialog, "values", lambda d: ("", PASSWORD))
    shown = []
    monkeypatch.setattr(labkeys.RecoveryKeyDialog, "exec", lambda d: shown.append(d.key) or 1)
    shadow.toggle_lab_encryption()
    assert vault.is_encrypted_lab(folder) and _plain_files(folder) == [] and shown
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    shadow.toggle_lab_encryption()
    assert not vault.is_encrypted_lab(folder)
    assert "creds" in (folder / lab.INDEX_NAME).read_text(encoding="utf-8")


def test_changing_the_password_from_the_menu(shadow, monkeypatch):
    import labkeys

    _answer_start(monkeypatch, "secret", True, PASSWORD)
    shadow.start_lab()
    folder = lab.active_folder(shadow.cfg)
    answers = iter([("wrong one!", "a brand new one"), (PASSWORD, "a brand new one")])
    errors = []
    monkeypatch.setattr(labkeys.PasswordDialog, "exec", lambda d: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(labkeys.PasswordDialog, "values", lambda d: next(answers))
    monkeypatch.setattr(labkeys.PasswordDialog, "show_error", lambda d, text: errors.append(text))
    monkeypatch.setattr(labkeys.RecoveryKeyDialog, "exec", lambda d: 1)
    shadow.change_lab_password()
    assert errors == ["The current password is not right."]
    vault.lock(folder)
    vault.unlock(folder, password="a brand new one")


def test_exports_of_an_encrypted_lab_go_outside_it_and_say_so(cfg_lab):
    import report_dialogs

    target, _ = _encrypted_lab(cfg_lab)
    assert target not in report.default_path(target, "pdf").parents
    dialog = report_dialogs.ExportDialog("html", "full", 0, encrypted=True)
    from PySide6.QtWidgets import QLabel

    assert any("export is not" in label.text() for label in dialog.findChildren(QLabel))
    plain = report_dialogs.ExportDialog("html", "full", 0)
    assert not any("export is not" in label.text() for label in plain.findChildren(QLabel))


def test_settings_offer_encrypting_new_labs():
    import settings_dialog

    cfg = config._sanitise({**config.DEFAULTS, "lab_encrypt_default": True})
    dialog = settings_dialog.SettingsDialog(cfg)
    assert dialog.lab_encrypt_check.isChecked()
    dialog.lab_encrypt_check.setChecked(False)
    assert dialog.values()["lab_encrypt_default"] is False
