"""0.17.0: cover page, contents, Word templates, and remembering the report details."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog

import config
import lab
import report
import report_dialogs

META = {"cover": True, "toc": True, "client": "Hack The Box", "author": "JHinfosec", "date": "23 November 2026"}


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _png(colour=(200, 30, 30), width=60, height=30) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def lame(cfg, tmp_path):
    cfg["lab_root"] = str(tmp_path / "labs")
    lab.start(cfg, "Lame")
    cfg["active_lab"] = "Lame"
    lab.set_section(cfg, "10.10.10.3/Recon")
    lab.save(_png((10, 10, 10)), "png", cfg)
    lab.set_section(cfg, "10.10.10.3/SMB")
    lab.save(_png((200, 0, 0), height=900), "png", cfg)    # tall, to push FTP onto a later page
    lab.add_note(cfg, "root via usermap")
    lab.set_section(cfg, "10.10.10.3/FTP")
    lab.add_note(cfg, "anonymous login")
    lab.set_finding(cfg, "10.10.10.3/SMB", {"severity": "Critical", "host": "10.10.10.3"})
    lab.set_finding(cfg, "10.10.10.3/FTP", {"severity": "Low", "host": "10.10.10.3"})
    return cfg


def _docx_text(data: bytes, part: str = "word/document.xml") -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read(part).decode("utf-8")


# -- the details ---------------------------------------------------------------------------------
def test_details_are_filled_in_and_cleaned():
    meta = report.normalise_meta({"title": "  ", "client": " Acme\n Corp ", "cover": 1}, "Lame")
    assert meta["title"] == "Lame penetration test report" and meta["client"] == "Acme Corp"
    assert meta["cover"] is True and meta["toc"] is False and meta["date"]
    assert report.normalise_meta(None, "Lame", "findings")["title"] == "Lame findings report"
    assert len(report.normalise_meta({"author": "x" * 999}, "L")["author"]) == report.MAX_META


def test_contents_and_counts(lame):
    data = report.model(lab.active_folder(lame))
    entries = report.contents(data)
    assert entries[0] == (2, "Findings summary", "findings-summary")
    assert [text for _level, text, _anchor in entries[1:]] == ["10.10.10.3", "Recon", "SMB", "FTP"]
    assert report.severity_counts(data["findings"]) == [("Critical", 1), ("Low", 1)]


def test_the_lab_remembers_its_title_and_client(lame):
    assert lab.report_details(lame) == {"title": "", "client": ""}
    lab.set_report_details(lame, "Lame  internal test", "HTB")
    assert lab.report_details(lame) == {"title": "Lame internal test", "client": "HTB"}


def test_report_settings_are_checked():
    cfg = config._sanitise({**config.DEFAULTS, "report_cover": "yes", "report_author": None})
    assert cfg["report_cover"] is True and cfg["report_author"] == ""


# -- HTML ----------------------------------------------------------------------------------------
def test_html_cover_and_contents_link_to_the_sections(lame, tmp_path):
    out = report.export(lab.active_folder(lame), "html", tmp_path / "r.html", meta=META)
    text = out.read_text(encoding="utf-8")
    assert '<section class="cover">' in text and "Lame penetration test report" in text
    assert "Hack The Box" in text and "JHinfosec" in text and "23 November 2026" in text
    assert '<nav class="toc">' in text and 'href="#findings-summary"' in text
    anchors = [line for line in text.split("<li") if 'href="#h' in line]
    assert len(anchors) == 4
    for line in anchors:
        anchor = line.split('href="#', 1)[1].split('"', 1)[0]
        assert f'id="{anchor}"' in text


def test_html_without_front_pages_is_as_before(lame, tmp_path):
    text = report.export(lab.active_folder(lame), "html", tmp_path / "r.html").read_text(encoding="utf-8")
    assert '<section class="cover">' not in text and '<nav class="toc">' not in text
    assert "<h1>Lame</h1>" in text


# -- PDF -----------------------------------------------------------------------------------------
def test_pdf_contents_page_numbers_point_at_the_right_pages(lame):
    import reportpdf
    from PySide6.QtGui import QTextDocument

    data = report.model(lab.active_folder(lame), meta=META)
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setPageSize(reportpdf.QSizeF(700, 900))
    document.setHtml(reportpdf.build(data, document, 700, title=False))
    pages = reportpdf.heading_pages(document, 900)
    names = [text for _level, text, _page in pages]
    assert names[:2] == ["Findings summary", "10.10.10.3"] and "FTP" in names
    by_name = {text: page for _level, text, page in pages}
    assert by_name["Findings summary"] == 0 and by_name["FTP"] > by_name["Recon"]


def test_pdf_with_cover_and_contents(lame, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    plain = report.export(lab.active_folder(lame), "pdf", tmp_path / "plain.pdf")
    front = report.export(lab.active_folder(lame), "pdf", tmp_path / "front.pdf", meta=META)
    plain_pages = len(pypdf.PdfReader(plain).pages)
    reader = pypdf.PdfReader(front)
    assert len(reader.pages) == plain_pages + 2
    squash = lambda text: "".join(text.split())  # noqa: E731
    cover, contents = (squash(reader.pages[i].extract_text()) for i in (0, 1))
    if not cover:
        pytest.skip("no fonts on this machine: the PDF has no text to read")
    assert "Lamepenetrationtestreport" in cover and "HackTheBox" in cover and "Page1of" not in cover
    assert contents.startswith("Contents") and "Page2of" in contents
    # "FTP" in the contents carries the page FTP is really on.
    ftp_page = next(i for i, page in enumerate(reader.pages[2:], start=3)
                    if "anonymouslogin" in squash(page.extract_text()))
    assert f"FTP{ftp_page}" in contents


def test_pdf_cover_only(lame, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    out = report.export(lab.active_folder(lame), "pdf", tmp_path / "c.pdf", meta={**META, "toc": False})
    plain = report.export(lab.active_folder(lame), "pdf", tmp_path / "p.pdf")
    assert len(pypdf.PdfReader(out).pages) == len(pypdf.PdfReader(plain).pages) + 1


# -- Word ----------------------------------------------------------------------------------------
def test_word_cover_and_contents_field(lame, tmp_path):
    pytest.importorskip("docx")
    out = report.export(lab.active_folder(lame), "docx", tmp_path / "r.docx", meta=META)
    xml = _docx_text(out.read_bytes())
    assert "Lame penetration test report" in xml and "Hack The Box" in xml and "1 Critical, 1 Low" in xml
    assert 'TOC \\o "1-3" \\h \\z \\u' in xml and 'w:dirty="true"' in xml
    assert "updateFields" in _docx_text(out.read_bytes(), "word/settings.xml")
    assert xml.count('w:type="page"') >= 2


def _template(path: Path, headings: bool = True, mark: bool = True) -> Path:
    """A client template: cover with split placeholders, a header, {{report}}, an appendix."""
    from docx import Document
    from docx.enum.text import WD_BREAK

    doc = Document()
    cover = doc.add_paragraph()
    for piece in ("{{ti", "tle}}", " for {{client}}"):     # split the way Word splits typing
        cover.add_run(piece).bold = True
    doc.add_paragraph("Tester: {{author}}, {{date}}")
    doc.sections[0].header.paragraphs[0].text = "CONFIDENTIAL - {{lab}}"
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    if mark:
        doc.add_paragraph("{{report}}")
    doc.add_paragraph("Appendix A: methodology")
    if not headings:
        styles = doc.styles.element
        for style in list(styles):
            style_id = style.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}styleId") or ""
            if style_id.startswith("Heading") or style_id in ("Title", "TableGrid"):
                styles.remove(style)
    doc.save(path)
    return path


def test_word_template_fills_placeholders_and_places_the_report(lame, tmp_path):
    pytest.importorskip("docx")
    template = _template(tmp_path / "acme.docx")
    out = report.export(lab.active_folder(lame), "docx", tmp_path / "r.docx", meta=META, template=template)
    data = out.read_bytes()
    xml = _docx_text(data)
    assert "{{" not in xml
    assert "Lame penetration test report for Hack The Box" in xml.replace("</w:t></w:r><w:r><w:t>", "")
    assert "Tester: JHinfosec, 23 November 2026" in xml
    header = next(name for name in zipfile.ZipFile(io.BytesIO(data)).namelist() if name.startswith("word/header"))
    assert "CONFIDENTIAL - Lame" in _docx_text(data, header)
    # The report sits where {{report}} was: after the cover, before the appendix.
    assert xml.index("Tester:") < xml.index("Findings summary") < xml.index("root via usermap") \
        < xml.index("Appendix A")
    assert xml.index("Tester:") < xml.index(">Contents<") < xml.index("Findings summary")
    # A template has its own cover: none is added.
    assert "Prepared for" not in xml


def test_word_template_without_a_report_mark_gets_the_report_at_the_end(lame, tmp_path):
    pytest.importorskip("docx")
    template = _template(tmp_path / "plain.docx", mark=False)
    xml = _docx_text(report.export(lab.active_folder(lame), "docx", tmp_path / "r.docx",
                                   meta=META, template=template).read_bytes())
    assert xml.index("Appendix A") < xml.index("Findings summary")


def test_word_template_without_heading_styles_still_exports(lame, tmp_path):
    pytest.importorskip("docx")
    template = _template(tmp_path / "bare.docx", headings=False)
    xml = _docx_text(report.export(lab.active_folder(lame), "docx", tmp_path / "r.docx",
                                   meta=META, template=template).read_bytes())
    assert "Findings summary" in xml and "tblBorders" in xml


def test_a_dotx_template_opens(lame, tmp_path):
    pytest.importorskip("docx")
    docx = _template(tmp_path / "acme.docx")
    dotx = tmp_path / "acme.dotx"
    with zipfile.ZipFile(docx) as source, zipfile.ZipFile(dotx, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = data.replace(b"wordprocessingml.document.main+xml", b"wordprocessingml.template.main+xml")
            target.writestr(item, data)
    xml = _docx_text(report.export(lab.active_folder(lame), "docx", tmp_path / "r.docx",
                                   meta=META, template=dotx).read_bytes())
    assert "Findings summary" in xml and "Tester: JHinfosec" in xml


@pytest.mark.parametrize("name, content", [("t.txt", b"hello"), ("t.docx", b"not a zip"), ("t.dotx", b"nope")])
def test_a_bad_template_says_so(lame, tmp_path, name, content):
    pytest.importorskip("docx")
    template = tmp_path / name
    template.write_bytes(content)
    with pytest.raises(report.ExportError):
        report.export(lab.active_folder(lame), "docx", tmp_path / "r.docx", template=template)
    with pytest.raises(report.ExportError):
        report.export(lab.active_folder(lame), "docx", tmp_path / "r.docx", template=tmp_path / "missing.docx")


# -- the window ----------------------------------------------------------------------------------
def test_the_export_window_collects_the_front_pages():
    dialog = report_dialogs.ExportDialog("pdf", "full", 2, meta={"cover": True, "author": "JH"}, lab_name="Lame")
    assert dialog.cover.isChecked() and not dialog.toc.isChecked() and not dialog.details.isHidden()
    assert dialog.title.placeholderText() == "Lame penetration test report"
    assert dialog.template_row.isHidden()
    dialog.client.setText("HTB")
    dialog.toc.setChecked(True)
    meta = dialog.front_matter()
    assert meta["cover"] and meta["toc"] and meta["client"] == "HTB" and meta["author"] == "JH"
    dialog.scope_findings.setChecked(True)
    assert dialog.title.placeholderText() == "Lame findings report"


def test_the_export_window_takes_a_word_template(tmp_path, monkeypatch):
    template = tmp_path / "acme.dotx"
    template.write_bytes(b"x")
    dialog = report_dialogs.ExportDialog("docx", "full", 1, meta={"cover": True})
    assert not dialog.template_row.isHidden() and dialog.cover.isEnabled()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(template), ""))
    dialog._choose_template()
    assert dialog.template() == str(template) and "acme.dotx" in dialog.template_label.text()
    assert not dialog.cover.isEnabled()           # the template brings its own cover
    assert dialog.front_matter()["cover"] is False and dialog.front_matter()["cover_wanted"] is True
    dialog.format_buttons["pdf"].setChecked(True)
    assert dialog.template() == "" and dialog.cover.isEnabled()
    dialog.format_buttons["docx"].setChecked(True)
    dialog.btn_no_template.click()
    assert dialog.template() == ""


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
    yield s
    s.autocopy.release()


def test_the_app_remembers_and_passes_the_front_pages(shadow, monkeypatch, tmp_path):
    import app as app_mod

    lab.add_note(shadow.cfg, "x")
    seen = {}

    def fake_exec(dialog):
        seen["meta"] = (dialog.cover.isChecked(), dialog.author.text(), dialog.client.text())
        dialog.format_buttons["pdf"].setChecked(True)
        dialog.cover.setChecked(True)
        dialog.toc.setChecked(True)
        dialog.author.setText("JHinfosec")
        dialog.client.setText("HTB")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(report_dialogs.ExportDialog, "exec", fake_exec)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "r.pdf"), ""))
    monkeypatch.setattr(app_mod.storage, "open_file", lambda p: None)
    shadow.export_report()
    assert seen["meta"] == (False, "", "")
    assert (tmp_path / "r.pdf").read_bytes().startswith(b"%PDF")
    assert shadow.cfg["report_cover"] and shadow.cfg["report_toc"] and shadow.cfg["report_author"] == "JHinfosec"
    assert lab.report_details(shadow.cfg)["client"] == "HTB"
    shadow.export_report()
    assert seen["meta"] == (True, "JHinfosec", "HTB")
