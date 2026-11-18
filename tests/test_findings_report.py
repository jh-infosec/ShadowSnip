"""0.15.0: CVSS on findings, PDF export, findings-only export, and restoring removed snips."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog

import config
import cvss
import lab
import report
import report_dialogs
import storage


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def cfg_lab(cfg, tmp_path):
    cfg["lab_root"] = str(tmp_path / "labs")
    lab.start(cfg, "box")
    cfg["active_lab"] = "box"
    return cfg


def _png(colour=(200, 30, 30), width=60, height=30) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, "PNG")
    return buf.getvalue()


def _md(cfg) -> str:
    return (lab.active_folder(cfg) / lab.INDEX_NAME).read_text(encoding="utf-8")


# -- CVSS 3.1 --------------------------------------------------------------------------------------
@pytest.mark.parametrize("vector, score, rating", [
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8, "Critical"),
    ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H", 9.9, "Critical"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0, "Critical"),
    ("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", 7.8, "High"),
    ("CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 8.8, "High"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N", 6.1, "Medium"),
    ("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:N/A:N", 5.9, "Medium"),
    ("CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 6.8, "Medium"),
    ("CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:U/C:L/I:L/A:N", 3.8, "Low"),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N", 0.0, "None"),
])
def test_scores_match_the_specification(vector, score, rating):
    canonical, value, name = cvss.score(vector)
    assert (canonical, value, name) == (vector, score, rating)


def test_roundup_works_in_whole_numbers():
    assert cvss.roundup(4.0) == 4.0
    assert cvss.roundup(4.000001) == 4.0      # floating point noise is not a step up
    assert cvss.roundup(4.02) == 4.1
    assert cvss.roundup(9.81) == 9.9


def test_vectors_are_read_leniently_and_written_canonically():
    # No prefix, any order, lower case, spaces, and temporal metrics ignored.
    canonical, value, _ = cvss.score(" av:n / ac:l/pr:n/ui:n/s:u/c:h/i:h/a:h/E:P ")
    assert canonical == "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H" and value == 9.8
    assert cvss.score("S:U/AV:N/AC:L/PR:N/UI:N/C:H/I:H/A:H")[1] == 9.8
    assert cvss.score("CVSS:3.0/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H")[0].startswith("CVSS:3.0/")
    assert cvss.describe("AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == "9.8 Critical"
    assert cvss.describe("nonsense") == ""


@pytest.mark.parametrize("vector, says", [
    ("", "No vector"),
    ("AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H", "Missing A"),
    ("AV:X/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", "AV:X"),
    ("AV:N/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", "twice"),
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N", "3.0 and 3.1"),
    ("AV/AC:L", "not a metric"),
    ("A" * 300, "too long"),
])
def test_bad_vectors_say_what_is_wrong(vector, says):
    with pytest.raises(cvss.CvssError) as err:
        cvss.parse(vector)
    assert says in str(err.value)


def test_none_is_shown_as_info():
    assert cvss.severity_for(0.0) == "Info"
    assert cvss.severity_for(3.9) == "Low" and cvss.severity_for(4.0) == "Medium"
    assert cvss.severity_for(8.9) == "High" and cvss.severity_for(9.0) == "Critical"


# -- findings with a score --------------------------------------------------------------------------
def test_the_score_decides_the_severity(cfg_lab):
    stored = lab.set_finding(cfg_lab, "10.10.10.3/SMB", {
        "severity": "Low", "host": "10.10.10.3", "cvss": "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"})
    assert stored["severity"] == "Critical"
    assert stored["cvss"] == "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
    md = _md(cfg_lab)
    assert "| # | Finding | Severity | CVSS | Host |" in md
    assert "| 1 | 10.10.10.3 / SMB | Critical | 9.8 | 10.10.10.3 |" in md
    assert "> CVSS 3.1 base score: 9.8 (`CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H`)" in md


def test_a_vector_that_does_not_score_is_dropped(cfg_lab):
    stored = lab.set_finding(cfg_lab, "Web", {"severity": "High", "cvss": "AV:N/oops"})
    assert stored["severity"] == "High" and "cvss" not in stored
    assert lab.finding_score(stored) is None


def test_findings_sort_by_severity_then_score(cfg_lab):
    lab.set_finding(cfg_lab, "A", {"severity": "High"})
    lab.set_finding(cfg_lab, "B", {"severity": "High", "cvss": "AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H"})  # 7.8
    lab.set_finding(cfg_lab, "C", {"severity": "High", "cvss": "AV:A/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"})  # 8.8
    lab.set_finding(cfg_lab, "D", {"severity": "Critical"})
    assert [f["path"] for f in lab.findings(cfg_lab)] == ["D", "C", "B", "A"]
    assert [f["score"] for f in lab.findings(cfg_lab)] == [None, 8.8, 7.8, None]


def test_the_finding_dialog_builds_and_reads_vectors():
    dialog = report_dialogs.FindingDialog("10.10.10.3/SMB")
    assert not dialog.use_cvss.isChecked() and dialog.cvss_box.isHidden()
    assert dialog.values()["cvss"] == ""
    dialog.use_cvss.setChecked(True)
    assert not dialog.severity.isEnabled()
    assert dialog.values()["cvss"] == "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
    assert dialog.severity.currentText() == "Critical" and dialog.cvss_score.text() == "9.8 Critical"
    # A picker changes the vector and the score.
    combo = dialog.cvss_combos["C"]
    combo.setCurrentIndex(combo.findData("N"))
    assert "/C:N/" in dialog.values()["cvss"] and dialog.cvss_score.text() == "9.1 Critical"
    # Pasting a vector sets the pickers.
    dialog.cvss_vector.setText("AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N")
    assert dialog.cvss_combos["S"].currentData() == "C" and dialog.severity.currentText() == "Medium"
    # A bad one is not saved.
    dialog.cvss_vector.setText("AV:Q")
    assert dialog.cvss_score.text() == "Not scored" and dialog.values()["cvss"] == ""
    dialog.use_cvss.setChecked(False)
    assert dialog.severity.isEnabled() and dialog.values()["cvss"] == ""


def test_the_finding_dialog_opens_with_the_stored_vector():
    dialog = report_dialogs.FindingDialog("x", {"severity": "High",
                                                "cvss": "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H"})
    assert dialog.use_cvss.isChecked() and dialog.cvss_score.text() == "7.8 High"
    assert dialog.cvss_combos["AV"].currentData() == "L"


# -- findings-only reports --------------------------------------------------------------------------
@pytest.fixture
def lame(cfg_lab):
    """Recon (no finding), SMB (Critical, with a sub-section), FTP (Low), Notes (nothing)."""
    lab.set_section(cfg_lab, "10.10.10.3/Recon")
    lab.save(_png((10, 10, 10)), "png", cfg_lab)
    lab.add_note(cfg_lab, "nmap says smb and ftp")
    lab.set_section(cfg_lab, "10.10.10.3/SMB")
    smb = lab.save(_png((200, 0, 0)), "png", cfg_lab)
    lab.add_note(cfg_lab, "root via usermap", attach=[smb.name])
    lab.set_section(cfg_lab, "10.10.10.3/SMB/Loot")
    lab.add_note(cfg_lab, "hash dumped", fmt="code", label="cat /etc/shadow")
    lab.set_section(cfg_lab, "10.10.10.3/FTP")
    lab.save(_png((0, 0, 200)), "png", cfg_lab)
    lab.set_section(cfg_lab, "10.10.10.3/Notes")
    lab.add_note(cfg_lab, "distcc not tried")
    lab.set_finding(cfg_lab, "10.10.10.3/FTP", {"severity": "Low", "host": "10.10.10.3",
                                                "description": "Anonymous login"})
    lab.set_finding(cfg_lab, "10.10.10.3/SMB", {"severity": "High", "host": "10.10.10.3",
                                                "cvss": "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                                                "description": "CVE-2007-2447"})
    return cfg_lab


def test_every_block_knows_its_section(lame):
    data = report.model(lab.active_folder(lame))
    sections = {block["type"] + ":" + block.get("section", "?") for block in data["blocks"]}
    assert "note:10.10.10.3/Recon" in sections and "code:10.10.10.3/SMB/Loot" in sections
    finding = next(b for b in data["blocks"] if b["type"] == "finding" and b["path"] == "10.10.10.3/SMB")
    assert finding["score"] == 9.8 and finding["severity"] == "Critical"


def test_findings_only_keeps_each_finding_with_its_evidence(lame):
    data = report.model(lab.active_folder(lame), "findings")
    assert data["scope"] == "findings"
    headings = [(b["level"], b["text"]) for b in data["blocks"] if b["type"] == "heading"]
    assert headings == [(2, "10.10.10.3 / SMB"), (3, "Loot"), (2, "10.10.10.3 / FTP")]
    texts = [b.get("text", "") for b in data["blocks"]]
    assert "root via usermap" in texts and "hash dumped" in texts
    assert "nmap says smb and ftp" not in texts and "distcc not tried" not in texts
    snips = [b for b in data["blocks"] if b["type"] == "snip"]
    assert len(snips) == 2   # SMB's and FTP's, not Recon's
    kinds = [b["type"] for b in data["blocks"]]
    assert kinds.count("finding") == 2


def test_a_finding_inside_a_finding_is_not_shown_twice(lame):
    lab.set_finding(lame, "10.10.10.3/SMB/Loot", {"severity": "Medium"})
    data = report.model(lab.active_folder(lame), "findings")
    codes = [b for b in data["blocks"] if b["type"] == "code"]
    assert len(codes) == 1
    headings = [b["text"] for b in data["blocks"] if b["type"] == "heading"]
    assert headings == ["10.10.10.3 / SMB", "10.10.10.3 / SMB / Loot", "10.10.10.3 / FTP"]


def test_findings_only_without_findings_says_so(cfg_lab):
    lab.add_note(cfg_lab, "nothing yet")
    with pytest.raises(report.ExportError, match="no findings"):
        report.export(lab.active_folder(cfg_lab), "html", scope="findings")


def test_an_unknown_scope_is_refused(lame):
    with pytest.raises(report.ExportError):
        report.model(lab.active_folder(lame), "everything")


def test_findings_only_html(lame, tmp_path):
    out = report.export(lab.active_folder(lame), "html", tmp_path / "f.html", scope="findings")
    text = out.read_text(encoding="utf-8")
    assert "Findings report" in text and "<th>CVSS</th>" in text and "<td>9.8</td>" in text
    assert "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H" in text
    assert "nmap says smb and ftp" not in text and "root via usermap" in text


def test_default_names_say_which_report(tmp_path):
    assert report.default_path(tmp_path / "box", "pdf").name == "box-report.pdf"
    assert report.default_path(tmp_path / "box", "pdf", "findings").name == "box-findings.pdf"


def test_word_has_the_cvss_column(lame, tmp_path):
    pytest.importorskip("docx")
    out = report.export(lab.active_folder(lame), "docx", tmp_path / "r.docx")
    xml = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    assert ">CVSS<" in xml and ">9.8<" in xml and "CVSS:3.1/AV:N" in xml


# -- PDF ---------------------------------------------------------------------------------------------
def test_pdf_export_writes_pages(lame, tmp_path):
    out = report.export(lab.active_folder(lame), "pdf", tmp_path / "r.pdf")
    data = out.read_bytes()
    assert data.startswith(b"%PDF") and data.rstrip().endswith(b"%%EOF")
    assert out.stat().st_size > 2000


def test_pdf_text_and_pages(lame, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    full = report.export(lab.active_folder(lame), "pdf", tmp_path / "full.pdf")
    only = report.export(lab.active_folder(lame), "pdf", tmp_path / "only.pdf", scope="findings")
    full_text = "".join(page.extract_text() for page in pypdf.PdfReader(full).pages)
    only_reader = pypdf.PdfReader(only)
    only_text = "".join(page.extract_text() for page in only_reader.pages)
    squash = lambda text: "".join(text.split())  # noqa: E731 - fonts vary in spacing
    if "Findings" not in full_text and not squash(full_text):
        pytest.skip("no fonts on this machine: the PDF has no text to read")
    assert "Findingssummary" in squash(full_text) and "nmapsayssmbandftp" in squash(full_text)
    assert "Findingsreport" in squash(only_text) and "nmapsayssmbandftp" not in squash(only_text)
    assert "Page1of" in squash(only_text)
    assert only_reader.metadata.title == "box report"


def test_pdf_images_fit_the_page(lame, tmp_path):
    import reportpdf
    from PySide6.QtGui import QTextDocument

    lab.set_section(lame, "10.10.10.3/SMB")
    lab.save(_png((0, 120, 0), width=3000, height=200), "png", lame)
    data = report.model(lab.active_folder(lame))
    document = QTextDocument()
    markup = reportpdf.build(data, document, 600)
    import re

    widths = [int(w) for w in re.findall(r'<img src="[^"]+" width="(\d+)"', markup)]
    assert widths and max(widths) == 600 and min(widths) == 60
    assert reportpdf.to_pdf(data).startswith(b"%PDF")


def test_pdf_reports_a_missing_image_in_place(lame, tmp_path):
    import reportpdf
    from PySide6.QtGui import QTextDocument

    data = report.model(lab.active_folder(lame))
    for block in data["blocks"]:
        if block["type"] == "snip":
            block["path"] = str(tmp_path / "gone.png")
    markup = reportpdf.build(data, QTextDocument(), 600)
    assert report.MISSING in markup and "<img" not in markup


# -- the export dialog --------------------------------------------------------------------------------
def test_the_export_dialog_remembers_and_offers():
    dialog = report_dialogs.ExportDialog("pdf", "findings", 2)
    assert dialog.values() == ("pdf", "findings")
    assert "2 findings" in dialog.scope_findings.text()
    dialog.format_buttons["docx"].setChecked(True)
    dialog.scope_full.setChecked(True)
    assert dialog.values() == ("docx", "full")


def test_the_export_dialog_without_findings_or_word():
    dialog = report_dialogs.ExportDialog("docx", "findings", 0, docx_ok=False)
    assert not dialog.scope_findings.isEnabled() and dialog.values() == ("html", "full")
    assert not dialog.format_buttons["docx"].isEnabled()


def test_export_settings_are_checked():
    cfg = config._sanitise({**config.DEFAULTS, "report_format": "odt", "report_scope": "some"})
    assert (cfg["report_format"], cfg["report_scope"]) == ("html", "full")


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
    lab.start(s.cfg, "box")
    s.cfg["active_lab"] = "box"
    s._refresh_menu_text()
    yield s
    s.autocopy.release()


def test_a_findings_pdf_from_the_window(shadow, monkeypatch, tmp_path):
    import app as app_mod

    lab.set_section(shadow.cfg, "Web")
    lab.add_note(shadow.cfg, "sqli")
    lab.set_finding(shadow.cfg, "Web", {"severity": "High"})
    monkeypatch.setattr(report_dialogs.ExportDialog, "exec", lambda d: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(report_dialogs.ExportDialog, "values", lambda d: ("pdf", "findings"))
    asked = []

    def save_name(*args, **kwargs):
        asked.append(args[2])
        return str(tmp_path / "out" / "web"), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", save_name)
    opened = []
    monkeypatch.setattr(app_mod.storage, "open_file", lambda p: opened.append(Path(p)))
    shadow.export_report()
    assert asked[0].endswith("box-findings.pdf")
    assert opened == [tmp_path / "out" / "web.pdf"] and opened[0].read_bytes().startswith(b"%PDF")
    assert (shadow.cfg["report_format"], shadow.cfg["report_scope"]) == ("pdf", "findings")


def test_a_cancelled_export_dialog_writes_nothing(shadow, monkeypatch):
    monkeypatch.setattr(report_dialogs.ExportDialog, "exec", lambda d: QDialog.DialogCode.Rejected)
    called = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: called.append(1) or ("", ""))
    shadow.export_report()
    assert called == []


# -- restoring removed snips ------------------------------------------------------------------------
def test_a_removed_snip_comes_back_where_it_was(cfg_lab):
    lab.set_section(cfg_lab, "Recon")
    first = lab.save(_png((1, 1, 1)), "png", cfg_lab)
    second = lab.save(_png((2, 2, 2)), "png", cfg_lab)
    lab.add_note(cfg_lab, "about the second", attach=[second.name])
    third = lab.save(_png((3, 3, 3)), "png", cfg_lab)
    lab.set_section(cfg_lab, "Exploit")
    lab.remove_snip(cfg_lab, second.name)
    assert not second.exists()
    rows = lab.removed_snips(cfg_lab)
    assert [r["file"] for r in rows] == [second.name]
    assert rows[0]["notes"] == 1 and rows[0]["section"] == "Recon" and rows[0]["path"]
    before = _md(cfg_lab)
    assert "about the second" not in before

    lab.restore_snip(cfg_lab, second.name)
    assert second.is_file() and lab.removed_snips(cfg_lab) == []
    files = [e.get("file") for e in lab.entries(cfg_lab) if lab.entry_kind(e) == "snip"]
    assert files == [first.name, second.name, third.name]
    entry = next(e for e in lab.entries(cfg_lab) if e.get("file") == second.name)
    assert entry["section"] == "Recon" and "removed" not in entry and "removed_as" not in entry
    md = _md(cfg_lab)
    assert "about the second" in md
    assert md.index(first.name) < md.index(second.name) < md.index(third.name)


def test_a_renamed_removal_is_found_and_restored(cfg_lab):
    snip = lab.save(_png(), "png", cfg_lab)
    bin_dir = lab.active_folder(cfg_lab) / lab.REMOVED_DIR
    bin_dir.mkdir()
    (bin_dir / snip.name).write_bytes(b"an older one")   # the name is taken in removed/
    lab.remove_snip(cfg_lab, snip.name)
    rows = [r for r in lab.removed_snips(cfg_lab) if r["recorded"]]
    assert rows[0]["stored"] != snip.name and Path(rows[0]["path"]).is_file()
    lab.restore_snip(cfg_lab, snip.name)
    assert snip.read_bytes() == _png() and (bin_dir / snip.name).read_bytes() == b"an older one"


def test_restore_never_overwrites(cfg_lab):
    snip = lab.save(_png(), "png", cfg_lab)
    lab.remove_snip(cfg_lab, snip.name)
    snip.write_bytes(b"something new")
    with pytest.raises(lab.LabError, match="already"):
        lab.restore_snip(cfg_lab, snip.name)
    assert snip.read_bytes() == b"something new" and lab.removed_snips(cfg_lab)


def test_restore_of_something_not_removed(cfg_lab):
    with pytest.raises(lab.LabError):
        lab.restore_snip(cfg_lab, "007_nothing.png")
    snip = lab.save(_png(), "png", cfg_lab)
    lab.remove_snip(cfg_lab, snip.name)
    for row in lab.removed_snips(cfg_lab):
        Path(row["path"]).unlink()
    assert lab.removed_snips(cfg_lab)[0]["path"] == ""
    with pytest.raises(lab.LabError, match="no longer"):
        lab.restore_snip(cfg_lab, snip.name)


def test_a_loose_file_in_removed_can_be_restored(cfg_lab):
    bin_dir = lab.active_folder(cfg_lab) / lab.REMOVED_DIR
    bin_dir.mkdir()
    (bin_dir / "009_by_hand.png").write_bytes(_png())
    rows = lab.removed_snips(cfg_lab)
    assert rows[0]["file"] == "009_by_hand.png" and not rows[0]["recorded"] and rows[0]["number"] == 9
    lab.restore_snip(cfg_lab, "009_by_hand.png")
    assert (lab.active_folder(cfg_lab) / "009_by_hand.png").is_file()


def test_a_clip_comes_back_with_its_video(cfg_lab, tmp_path):
    video = tmp_path / "rec.mp4"
    video.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    poster = lab.save(_png(), "png", cfg_lab, companion=video)
    lab.remove_snip(cfg_lab, poster.name)
    assert not poster.with_suffix(".mp4").exists()
    lab.restore_snip(cfg_lab, poster.name)
    assert poster.with_suffix(".mp4").is_file()


def test_history_snips_come_back(cfg):
    first = storage.save_history(_png(), "png", cfg)
    storage.remove_from_history(cfg, first.name)
    rows = storage.removed_history(cfg)
    assert [r["file"] for r in rows] == [first.name] and rows[0]["path"]
    storage.restore_history(cfg, first.name)
    assert first.is_file() and storage.removed_history(cfg) == []
    storage.remove_from_history(cfg, first.name)
    first.write_bytes(b"new")
    with pytest.raises(FileExistsError):
        storage.restore_history(cfg, first.name)
    with pytest.raises(FileNotFoundError):
        storage.restore_history(cfg, "nothing.png")


def test_the_removed_window_restores(cfg_lab):
    import removedview

    lab.set_section(cfg_lab, "Recon")
    snips = [lab.save(_png((i, i, i)), "png", cfg_lab) for i in range(3)]
    lab.set_caption(cfg_lab, snips[0].name, "wrong tab")
    for snip in snips[:2]:
        lab.remove_snip(cfg_lab, snip.name)
    back = []
    dialog = removedview.RemovedDialog(lambda: lab.removed_snips(cfg_lab),
                                       lambda name: lab.restore_snip(cfg_lab, name)["file"])
    dialog.restored.connect(back.extend)
    assert dialog.list.topLevelItemCount() == 2 and dialog.empty.isHidden()
    names = [dialog.list.topLevelItem(i).text(1) for i in range(2)]
    assert "wrong tab" in names
    assert "Filed under Recon" in dialog.detail.text()
    dialog.list.selectAll()
    assert dialog.btn_restore.text() == "Restore 2"
    dialog.restore_selected()
    assert sorted(back) == sorted(s.name for s in snips[:2])
    assert dialog.list.topLevelItemCount() == 0 and not dialog.empty.isHidden()
    assert "Restored 2 snips." in dialog.status.text()


def test_the_removed_window_says_why_not(cfg_lab):
    import removedview

    snip = lab.save(_png(), "png", cfg_lab)
    lab.remove_snip(cfg_lab, snip.name)
    snip.write_bytes(b"taken")
    dialog = removedview.RemovedDialog(lambda: lab.removed_snips(cfg_lab),
                                       lambda name: lab.restore_snip(cfg_lab, name)["file"])
    dialog.restore_selected()
    assert "already" in dialog.status.text() and dialog.list.topLevelItemCount() == 1


def test_the_window_counts_and_opens_the_removed(shadow, monkeypatch):
    import removedview

    snip = lab.save(_png(), "png", shadow.cfg)
    lab.remove_snip(shadow.cfg, snip.name)
    shadow._refresh_snip_list()
    assert shadow.preview.snips_panel.btn_removed.text() == "Removed (1)"
    shown = []

    def fake_exec(dialog):
        shown.append(dialog.list.topLevelItemCount())
        dialog.list.selectAll()
        dialog.restore_selected()
        return 0

    monkeypatch.setattr(removedview.RemovedDialog, "exec", fake_exec)
    shadow.show_removed()
    assert shown == [1] and snip.is_file()
    assert shadow.preview.snips_panel.btn_removed.text() == "Removed"
    assert shadow._last_lab_file == snip.name
