"""Copy text from a snip and Quick redact (0.10.0): ocr.py, the Text tool, quickredact.py."""

from __future__ import annotations

import shutil

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

import annotate as an
import edits
import ocr
import quickredact


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def W(text, x, y=10, line=0, w=None, h=14):
    return ocr.Word(text, x, y, w if w is not None else 8 * len(text), h, line)


def _line(text, line=0, y=10):
    """Words laid out left to right, 8 px a character, as OCR would report them."""
    words, x = [], 4
    for part in text.split(" "):
        words.append(W(part, x, y=y, line=line))
        x += 8 * len(part) + 8
    return words


def _kinds(found):
    return [(f.kind, f.text) for f in found]


# -- reading Tesseract's output -----------------------------------------------------------------
TSV_HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def _tsv(*rows):
    return "\n".join([TSV_HEADER, *("\t".join(str(c) for c in row) for row in rows)])


def test_parse_tsv_keeps_words_and_lines():
    tsv = _tsv(
        (1, 1, 0, 0, 0, 0, 0, 0, 500, 100, -1, ""),
        (5, 1, 1, 1, 1, 1, 10, 20, 60, 18, 96, "hello"),
        (5, 1, 1, 1, 1, 2, 80, 20, 60, 18, 91, "world"),
        (5, 1, 1, 1, 2, 1, 10, 50, 40, 18, 88, "next"),
    )
    words = ocr.parse_tsv(tsv)
    assert [w.text for w in words] == ["hello", "world", "next"]
    assert words[0].line == words[1].line != words[2].line
    assert ocr.text_of(words) == "hello world\nnext"


def test_parse_tsv_scales_boxes_back():
    tsv = _tsv((5, 1, 1, 1, 1, 1, 30, 60, 90, 45, 90, "x1"))
    (word,) = ocr.parse_tsv(tsv, scale=3.0)
    assert (word.x, word.y, word.w, word.h) == (10, 20, 30, 15)


def test_parse_tsv_keeps_unsure_hashes_but_drops_punctuation_noise():
    tsv = _tsv(
        (5, 1, 1, 1, 1, 1, 0, 0, 300, 18, 12, "aad3b435b51404eeaad3b435b51404ee:"),
        (5, 1, 1, 1, 1, 2, 310, 0, 10, 18, 40, "|"),
        (5, 1, 1, 1, 1, 3, 330, 0, 10, 18, -1, " "),
    )
    assert [w.text for w in ocr.parse_tsv(tsv)] == ["aad3b435b51404eeaad3b435b51404ee:"]


def test_parse_tsv_tolerates_rubbish():
    assert ocr.parse_tsv("") == []
    assert ocr.parse_tsv("not\ta\theader\nfoo") == []
    assert ocr.parse_tsv(_tsv((5, 1, 1, 1, 1, 1, "x", 0, 1, 1, 90, "bad"))) == []


def test_text_of_orders_lines_top_to_bottom_and_words_left_to_right():
    words = [W("b", 50, y=40, line=1), W("a", 10, y=40, line=1), W("top", 10, y=5, line=0)]
    assert ocr.text_of(words) == "top\na b"


# -- finding what to hide -----------------------------------------------------------------------
@pytest.mark.parametrize("text, kind, value", [
    ("password: hunter2", "secret", "hunter2"),
    ("api_key=AbC123xyz", "secret", "AbC123xyz"),
    ("crackmapexec smb 10.0.0.5 -u admin -p 'Sup3rS3cret!'", "secret", "Sup3rS3cret!"),
    ("SMB 10.0.0.5 445 LAME [+] LAME\\admin:Sup3rS3cret! (Pwn3d!)", "secret", "Sup3rS3cret!"),
    ("secretsdump.py corp/svc_sql:Winter2024@dc01.corp.local", "secret", "Winter2024"),
    ("key AKIAIOSFODNN7EXAMPLE here", "secret", "AKIAIOSFODNN7EXAMPLE"),
    ("hash 5f4dcc3b5aa765d61d8327deb882cf99 done", "hash", "5f4dcc3b5aa765d61d8327deb882cf99"),
    ("contact admin@corp.local now", "email", "admin@corp.local"),
    ("call +27 82 555 1234 today", "phone", "+27 82 555 1234"),
    ("host 10.10.10.3:445 open", "ip", "10.10.10.3:445"),
])
def test_find_sensitive_finds(text, kind, value):
    assert (kind, value) in _kinds(ocr.find_sensitive(_line(text)))


def test_secretsdump_line_finds_both_hashes():
    words = _line("Administrator: 500: aad3b435b51404eeaad3b435b51404ee: 31d6cfe0d16ae931b73c59d7e0c089c0:::")
    hashes = [f.text for f in ocr.find_sensitive(words) if f.kind == "hash"]
    assert hashes == ["aad3b435b51404eeaad3b435b51404ee", "31d6cfe0d16ae931b73c59d7e0c089c0"]


@pytest.mark.parametrize("text", [
    "started at 12:30:45 today",
    "on 2026-10-31 at noon",
    "build 1234567890123456789012345678901234 ok",  # long decimal, not a hash
    "just some ordinary words here",
])
def test_find_sensitive_leaves_ordinary_text_alone(text):
    found = [f for f in ocr.find_sensitive(_line(text)) if f.kind != "ip"]
    assert found == []


def test_only_the_value_is_covered_not_the_label():
    words = _line("password=hunter2")
    (found,) = ocr.find_sensitive(words, kinds={"secret"})
    (x, y, w, h) = found.boxes[0]
    word = words[0]
    # "password=" is 9 of the 16 characters: the box starts past it.
    assert x > word.x + 8 * 8 and x + w <= word.x + word.w + 4


def test_kinds_filter_and_priority():
    words = _line("password: admin@corp.local")
    assert _kinds(ocr.find_sensitive(words)) == [("secret", "admin@corp.local")]
    assert _kinds(ocr.find_sensitive(words, kinds={"email"})) == [("email", "admin@corp.local")]
    assert ocr.find_sensitive(words, kinds=set()) == []


def test_ip_addresses_are_off_by_default():
    assert ocr.KINDS["ip"][1] is False
    assert all(on for kind, (_, on) in ocr.KINDS.items() if kind != "ip")


def test_masked_never_shows_the_whole_value():
    assert quickredact.masked("abc") == "***"
    assert quickredact.masked("hunter2").startswith("hu") and "nter" not in quickredact.masked("hunter2")
    long = "5f4dcc3b5aa765d61d8327deb882cf99"
    shown = quickredact.masked(long)
    assert shown.startswith("5f4d") and shown.endswith("cf99") and long not in shown


def test_missing_engine_message_names_what_to_install(monkeypatch):
    monkeypatch.setattr(ocr, "_tesseract_path", lambda: None)
    monkeypatch.setattr(ocr, "_windows_engine_ready", lambda: False)
    assert ocr.engine() is None
    with pytest.raises(ocr.OcrError) as error:
        ocr.recognise(b"")
    assert str(error.value) == ocr.missing_engine_message()
    # Each platform names its own fix: Tesseract on Linux, the packages on Windows.
    import sys
    assert ("requirements.txt" if sys.platform == "win32" else "tesseract") in str(error.value)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")
def test_tesseract_reads_a_rendered_line():
    image = QImage(900, 120, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setPen(QColor("#000000"))
    font = QFont("DejaVu Sans Mono")
    font.setPixelSize(32)
    painter.setFont(font)
    painter.drawText(20, 70, "password: hunter2 admin@corp.local")
    painter.end()
    words = ocr._recognise_tesseract(an._png_of(image))
    text = ocr.text_of(words)
    assert "password" in text and "hunter2" in text
    assert ("secret", "hunter2") in _kinds(ocr.find_sensitive(words))


# -- the Text tool on the canvas ----------------------------------------------------------------
def _image(w=400, h=200):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#202020"))
    return img


@pytest.fixture
def canvas():
    widget = an.AnnotCanvas()
    widget.resize(420, 220)
    widget.show()
    widget.load(_image())
    QApplication.processEvents()
    yield widget
    widget.close()


def _give_words(widget, words):
    """As if OCR had already read this snip: no engine needed."""
    widget._words, widget._words_key = list(words), widget._text_key()
    widget._picked = set()


WORDS = [
    W("password:", 20, y=20, line=0, w=90), W("hunter2", 120, y=20, line=0, w=70),
    W("admin@corp.local", 20, y=60, line=1, w=160),
]


def _centre(widget, word) -> QPoint:
    return widget.to_widget(QPointF(word.x + word.w / 2, word.y + word.h / 2)).toPoint()


def test_click_picks_one_word_and_shift_adds(canvas):
    canvas.set_tool("text")
    _give_words(canvas, WORDS)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _centre(canvas, WORDS[1]))
    assert canvas.picked_text() == "hunter2"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, _centre(canvas, WORDS[2]))
    assert canvas.picked_text() == "hunter2\nadmin@corp.local"
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _centre(canvas, WORDS[0]))
    assert canvas.picked_text() == "password:"


def test_drag_picks_every_word_it_touches(canvas):
    canvas.set_tool("text")
    _give_words(canvas, WORDS)
    a = canvas.to_widget(QPointF(10, 10)).toPoint()
    b = canvas.to_widget(QPointF(200, 30)).toPoint()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    QTest.mouseMove(canvas, b)
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    assert canvas.picked_text() == "password: hunter2"


def test_copy_text_puts_words_on_the_clipboard(canvas):
    notices = []
    canvas.notice.connect(notices.append)
    canvas.set_tool("text")
    _give_words(canvas, WORDS)
    canvas.copy_text(selected=False)
    assert QApplication.clipboard().text() == "password: hunter2\nadmin@corp.local"
    assert "3 words" in notices[-1] and "2 lines" in notices[-1]
    canvas.pick_all_text()
    assert canvas.has_picked_text()


def test_words_outside_the_crop_are_not_offered(canvas):
    from PySide6.QtCore import QRect

    _give_words(canvas, WORDS)
    canvas.doc.add(an.Crop(canvas.doc.new_id(), QRect(0, 50, 400, 150)))
    _give_words(canvas, WORDS)
    assert [w.text for w in canvas.visible_words()] == ["admin@corp.local"]


def test_words_read_before_a_mark_are_stale(canvas):
    _give_words(canvas, WORDS)
    assert canvas.visible_words()
    canvas.add_redactions([(0, 0, 10, 10)])
    QApplication.processEvents()
    assert canvas.visible_words() == []  # the snip changed: read again first


def test_reading_runs_in_the_background_and_reports_failure(canvas, monkeypatch):
    def fail(png):
        raise ocr.OcrError("no engine here")

    monkeypatch.setattr(ocr, "recognise", fail)
    notices = []
    canvas.notice.connect(notices.append)
    canvas.read_text()
    assert canvas.reading_text
    for _ in range(200):
        QApplication.processEvents()
        if not canvas.reading_text:
            break
        QTest.qWait(10)
    assert not canvas.reading_text and notices[-1] == "no engine here"


def test_reading_in_the_background_returns_the_words(canvas, monkeypatch):
    monkeypatch.setattr(ocr, "recognise", lambda png: list(WORDS))
    got = []
    canvas.read_text(then=lambda: got.append(canvas.visible_words()))
    for _ in range(200):
        QApplication.processEvents()
        if got:
            break
        QTest.qWait(10)
    assert [w.text for w in got[0]] == ["password:", "hunter2", "admin@corp.local"]


# -- Quick redact -------------------------------------------------------------------------------
def test_quick_redaction_is_one_undo_and_each_box_erasable(canvas):
    added = canvas.add_redactions([(10, 10, 40, 20), (60, 60, 40, 20), (500, 500, 10, 10)])
    assert added == 2  # the box off the image is skipped
    redactions = [op for op in canvas.doc.ops if isinstance(op, an.Redact)]
    assert len(redactions) == 2 and redactions[0].batch == redactions[1].batch != 0
    canvas.doc.add(an.Erase(canvas.doc.new_id(), frozenset({redactions[0].id})))
    assert redactions[0].id in canvas.doc.erased()
    canvas.doc.undo()  # the erase
    canvas.doc.undo()  # both redactions at once
    assert canvas.doc.ops == []


def test_quick_redact_batch_survives_the_sidecar(tmp_path, canvas):
    canvas.add_redactions([(10, 10, 40, 20), (60, 60, 40, 20)])
    snip = tmp_path / "snip.png"
    data = an._png_of(canvas.doc.render())
    snip.write_bytes(data)
    assert edits.save(snip, canvas.doc, data)
    doc = edits.load(snip)
    assert len(doc.ops) == 2
    doc.undo()
    assert doc.ops == []


def test_quick_redact_offers_and_hides_what_is_ticked(canvas, monkeypatch):
    shown = {}

    def fake_exec(self):
        shown["kinds"] = set(self.checks)
        self.checks["email"].setChecked(False)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(quickredact.QuickRedactDialog, "exec", fake_exec)
    notices = []
    canvas.notice.connect(notices.append)
    _give_words(canvas, WORDS)
    canvas.quick_redact()
    assert shown["kinds"] == {"secret", "email"}
    redactions = [op for op in canvas.doc.ops if isinstance(op, an.Redact)]
    assert len(redactions) == 1 and "hid 1 item" in notices[-1]
    assert canvas.prefs["quick_redact"] == ["secret"]


def test_quick_redact_cancel_hides_nothing(canvas, monkeypatch):
    monkeypatch.setattr(quickredact.QuickRedactDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    _give_words(canvas, WORDS)
    canvas.quick_redact()
    assert canvas.doc.ops == []


def test_quick_redact_with_nothing_found_says_so(canvas):
    notices = []
    canvas.notice.connect(notices.append)
    _give_words(canvas, [W("hello", 10), W("world", 60)])
    canvas.quick_redact()
    assert canvas.doc.ops == [] and "found nothing" in notices[-1]


def test_dialog_remembers_choices_and_needs_one_ticked():
    found = [ocr.Found("secret", "hunter2", [(0, 0, 1, 1)]), ocr.Found("ip", "10.0.0.1", [(0, 0, 1, 1)])]
    dialog = quickredact.QuickRedactDialog(found)
    assert dialog.chosen_kinds() == {"secret"}  # IP addresses start unticked
    dialog.checks["secret"].setChecked(False)
    assert not dialog.btn_hide.isEnabled()
    remembered = quickredact.QuickRedactDialog(found, remembered=["ip"])
    assert remembered.chosen_kinds() == {"ip"}


def test_sanitise_prefs_keeps_only_known_kinds():
    prefs = an.sanitise_prefs({"quick_redact": ["secret", "nonsense", "ip"]})
    assert sorted(prefs["quick_redact"]) == ["ip", "secret"]


def test_strip_has_text_tool_and_quick_redact_button():
    strip = an.AnnotToolbar()
    asked = []
    strip.quick_redact_requested.connect(lambda: asked.append(True))
    assert "text" in strip.buttons
    strip.set_available(False)
    assert not strip.btn_quick.isEnabled()
    strip.set_available(True)
    strip.btn_quick.click()
    assert asked == [True]
    strip.close()
