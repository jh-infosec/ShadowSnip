"""Exporting a lab as a report you can hand over (0.9.0).

`lab.md` plus a folder of images pastes into most things, but a report goes to
someone as one file. Two formats:

    HTML   one self-contained page: the images are inside it (base64), so the
           file can be mailed, opened in any browser and printed to PDF
    Word   a .docx with the images embedded, headings as real Word headings,
           ready to paste into a client template or edit as it is

Both are built from the same reading of lab.json as lab.md (`model()`), so the
three never disagree about order: the findings summary first, then the report
top to bottom, each finding block under its section's heading followed by the
snips, notes and command output filed there.

The Word export needs python-docx (in requirements.txt). It is imported only
when used, so ShadowSnip runs without it and says what to install if it is
missing.
"""

from __future__ import annotations

import base64
import html
import io
from pathlib import Path

import lab

EXPORT_FORMATS = ("html", "docx", "pdf")
# What goes in: the whole lab, or (0.15.0) only the findings and their evidence.
EXPORT_SCOPES = ("full", "findings")
FORMAT_NAMES = {"html": "Web page", "docx": "Word document", "pdf": "PDF"}

# Severity colours, shared by both exports: background, text.
SEVERITY_COLOURS = {
    "Critical": ("#7a0019", "#ffffff"),
    "High": ("#d6332e", "#ffffff"),
    "Medium": ("#f0a020", "#1a1a1a"),
    "Low": ("#2f8cff", "#ffffff"),
    "Info": ("#6c6c78", "#ffffff"),
}

_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


# Said in place of a snip whose image is missing or not inside the lab folder.
MISSING = "image not found in the lab folder, left out"


class ExportError(RuntimeError):
    """An export that could not be written, with the reason."""


# -- the shared reading of the lab ---------------------------------------------------------------

def _clip_line(block: dict) -> str:
    """For a clip's poster (0.14.0): which video it stands for, and how long it is.

    The video itself is not put into the report (an HTML file with a video
    inside would be enormous, and Word cannot play one); it stays beside the
    poster in the lab folder, and the caption says so.
    """
    import clips

    video = clips.clip_for(block.get("path"))
    if video is None:
        return ""
    length = clips.format_length(clips.length_of(block.get("path")))
    return f"Video clip {video.name}" + (f" ({length})" if length else "") + ", in the lab folder"

def model(folder: Path, scope: str = "full", meta: dict | None = None) -> dict:
    """The report, in order, as plain data.

    {"name", "started", "scope", "findings": [...], "blocks": [...]}, where each
    block is one of:

        {"type": "heading", "level": 1-6, "text"}
        {"type": "finding", **finding}
        {"type": "snip", "label", "time", "caption", "path"}
        {"type": "note", "text", "evidence": [files]}
        {"type": "code", "label", "text"}

    and every block carries "section", the section path it sits in ("" for the
    top of the report).

    `scope` "findings" (0.15.0) keeps only the findings: each one in summary
    order, most severe first, as a heading with its finding block and then
    the evidence filed in its section and the sections under it. Everything
    filed elsewhere is left out.
    """
    if scope not in EXPORT_SCOPES:
        raise ExportError(f"unknown report scope '{scope}'")
    folder = Path(folder)
    state = lab._load_state(folder)
    if not state:
        raise ExportError(
            "This lab has no record yet. Take a snip or add a note first, with "
            "Keep a lab record switched on in Settings."
        )
    grouped = lab._ordered_groups(state)
    consumed = lab._attached_note_ids(grouped)
    stored = lab._findings_of(state)
    blocks: list[dict] = []

    def entries(here, section=""):
        start = len(blocks)
        _entries(here)
        for block in blocks[start:]:
            block["section"] = section

    def _entries(here):
        for entry in here:
            if lab.entry_kind(entry) == "note":
                if str(entry.get("id", "")) in consumed:
                    continue
                blocks.append(_note_block(entry))
                continue
            filename = str(entry.get("file", ""))
            number = entry.get("number", 0)
            # Only an image that is really in the lab folder is read: see
            # lab.image_in. Anything else is reported in place, never embedded.
            image = lab.image_in(folder, filename)
            blocks.append({
                "type": "snip",
                "label": f"{number:03d}" if isinstance(number, int) else str(number),
                "time": str(entry.get("time", "")).strip(),
                "caption": str(entry.get("caption", "")).strip(),
                "path": str(image) if image is not None else "",
            })
            for note in here:
                if lab.entry_kind(note) == "note" and filename and filename in note.get("attach", ()):
                    block = _note_block(note)
                    block["evidence"] = []  # it sits right under its evidence
                    block["under_snip"] = True
                    blocks.append(block)

    entries(grouped.get("", []))
    for path, depth in lab._walk_sections(grouped):
        blocks.append({
            "type": "heading",
            "level": min(depth + 2, lab.MAX_HEADING_LEVEL),
            "text": path.rsplit(lab.SECTION_SEPARATOR, 1)[-1],
            "section": path,
            "depth": depth,
        })
        if path in stored:
            blocks.append({"type": "finding", **stored[path], "path": path,
                           "score": lab.finding_score(stored[path]), "section": path})
        entries(grouped.get(path, []), path)

    findings = lab.findings_of_state(state)
    if scope == "findings":
        blocks = _findings_only(blocks, findings)
    return {
        "name": str(state.get("name", folder.name)),
        "started": str(state.get("started", "")).replace("T", " ")[:19],
        "scope": scope,
        "meta": normalise_meta(meta, str(state.get("name", folder.name)), scope),
        "findings": findings,
        "blocks": blocks,
    }


def _within(section: str, path: str) -> bool:
    return section == path or section.startswith(path + lab.SECTION_SEPARATOR)


def _findings_only(blocks: list[dict], findings: list[dict]) -> list[dict]:
    """Each finding with its evidence, most severe first, nothing else.

    A finding's heading is its whole breadcrumb ("10.10.10.3 / SMB"), since it
    no longer sits under its parents' headings; sections under it keep their
    own names, a level down. A finding filed inside another finding's section
    is shown under its own heading, not twice.
    """
    out: list[dict] = []
    paths = [item["path"] for item in findings]
    for item in findings:
        path = item["path"]
        nested = [other for other in paths if other != path and _within(other, path)]
        out.append({"type": "heading", "level": 2, "text": item["title"], "section": path})
        base_depth = path.count(lab.SECTION_SEPARATOR)
        for block in blocks:
            section = block.get("section", "")
            if not _within(section, path) or any(_within(section, other) for other in nested):
                continue
            if block["type"] == "heading":
                if section == path:
                    continue   # the finding's own heading is the one above
                depth = section.count(lab.SECTION_SEPARATOR) - base_depth
                out.append({**block, "level": min(2 + depth, lab.MAX_HEADING_LEVEL)})
            else:
                out.append(block)
    return out


def _note_block(entry: dict) -> dict:
    if lab.is_code(entry):
        return {"type": "code", "label": str(entry.get("label", "")).strip(),
                "text": str(entry.get("text", ""))}
    return {
        "type": "note",
        "text": str(entry.get("text", "")).strip(),
        "evidence": [str(n) for n in entry.get("attach", ()) if str(n).strip()],
    }


def default_path(folder: Path, fmt: str, scope: str = "full") -> Path:
    """Where an export is offered to go: the lab folder, or for an encrypted lab
    (0.16.0) the Documents folder, since an export is a plain file."""
    import vault

    folder = Path(folder)
    kind = "findings" if scope == "findings" else "report"
    where = folder
    if vault.is_encrypted_lab(folder):
        documents = Path.home() / "Documents"
        where = documents if documents.is_dir() else Path.home()
    return where / f"{folder.name}-{kind}.{fmt}"


def export(folder: Path, fmt: str, target: Path | None = None, scope: str = "full",
           meta: dict | None = None, template=None) -> Path:
    """Write the report for the lab in `folder`. Returns the file written."""
    if fmt not in EXPORT_FORMATS:
        raise ExportError(f"unknown export format '{fmt}'")
    data = model(folder, scope, meta)
    if scope == "findings" and not data["findings"]:
        raise ExportError(
            "This lab has no findings yet. Right-click a section in the Outline "
            "and choose Mark as finding, or export the full report."
        )
    target = Path(target) if target else default_path(folder, fmt, scope)
    if fmt == "html":
        payload = to_html(data)
    elif fmt == "docx":
        payload = to_docx(data, template=template)
    else:
        import reportpdf

        payload = reportpdf.to_pdf(data)
    try:
        import storage

        # Written as plain as asked, even into an encrypted lab's folder: a
        # report is for handing over (the export window says so).
        storage.write_atomic(target, payload, plain=True)
    except OSError as exc:
        raise ExportError(f"could not write {target}: {exc}") from exc
    return target


# -- HTML ---------------------------------------------------------------------------------------
_CSS = """
:root { --ink: #1d1d22; --dim: #5c5c66; --rule: #dcdce2; --code: #f4f4f7; --accent: #2f8cff; }
* { box-sizing: border-box; }
body { margin: 0; background: #ffffff; color: var(--ink);
  font: 15px/1.6 "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; }
main { max-width: 900px; margin: 0 auto; padding: 40px 32px 80px; }
.cover { padding: 40px 0 32px; margin-bottom: 24px; border-bottom: 1px solid var(--rule); }
.cover .kicker { color: var(--dim); text-transform: uppercase; letter-spacing: .08em; font-size: 13px; margin: 0; }
.cover h1 { font-size: 36px; line-height: 1.2; margin: 6px 0 20px; }
.cover table.meta th { text-align: left; color: var(--dim); font-weight: 500; padding: 2px 16px 2px 0; }
.cover .counts { margin-top: 16px; }
nav.toc ol { list-style: none; padding: 0; margin: 0 0 24px; }
nav.toc li { margin: 2px 0; } nav.toc li.l3 { padding-left: 20px; } nav.toc a { color: var(--ink); }
@media print { .cover { min-height: 90vh; page-break-after: always; } nav.toc { page-break-after: always; } }
h1 { font-size: 30px; margin: 0 0 4px; }
.started { color: var(--dim); margin: 0 0 28px; }
h2, h3, h4, h5, h6 { margin: 32px 0 12px; line-height: 1.3; }
h2 { font-size: 22px; border-bottom: 1px solid var(--rule); padding-bottom: 6px; }
h3 { font-size: 18px; } h4, h5, h6 { font-size: 16px; }
table.summary { border-collapse: collapse; width: 100%; margin: 8px 0 28px; }
.summary th, .summary td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--rule); }
.summary th { color: var(--dim); font-weight: 600; font-size: 13px; }
.sev { display: inline-block; padding: 1px 9px; border-radius: 4px; font-size: 12px; font-weight: 600; }
.finding { border: 1px solid var(--rule); border-left: 5px solid var(--sev); border-radius: 6px;
  padding: 12px 16px; margin: 6px 0 18px; break-inside: avoid; }
.finding .head { display: flex; gap: 14px; align-items: center; margin-bottom: 6px; }
.finding .host { color: var(--dim); }
.finding h5 { margin: 12px 0 2px; font-size: 13px; text-transform: uppercase; letter-spacing: .04em; color: var(--dim); }
.finding p { margin: 0 0 4px; white-space: pre-wrap; }
.finding p.vector { color: var(--dim); font: 12px/1.4 Consolas, "Cascadia Mono", "DejaVu Sans Mono", monospace; }
figure { margin: 14px 0 6px; }
figure img { max-width: 100%; border: 1px solid var(--rule); border-radius: 4px; display: block; }
figcaption { color: var(--dim); font-size: 13px; margin-top: 4px; }
figcaption b { color: var(--ink); }
blockquote { margin: 6px 0 16px; padding: 4px 14px; border-left: 3px solid var(--accent); color: #33333b; white-space: pre-wrap; }
p.note { white-space: pre-wrap; }
.evidence { color: var(--dim); font-size: 13px; font-style: italic; }
.cmd { font: 600 13px/1.4 Consolas, "Cascadia Mono", "DejaVu Sans Mono", monospace; margin: 12px 0 4px; }
pre { background: var(--code); border: 1px solid var(--rule); border-radius: 6px; padding: 10px 12px;
  overflow-x: auto; font: 13px/1.45 Consolas, "Cascadia Mono", "DejaVu Sans Mono", monospace; margin: 4px 0 16px; }
.missing { color: #b00020; font-style: italic; }
@media print { main { padding: 0; } pre { white-space: pre-wrap; } }
"""


def _esc(text) -> str:
    return html.escape(str(text or ""), quote=True)


def _sev_chip(severity: str) -> str:
    bg, fg = SEVERITY_COLOURS.get(severity, ("#6c6c78", "#ffffff"))
    return f'<span class="sev" style="background:{bg};color:{fg}">{_esc(severity)}</span>'


def _data_uri(path: str) -> str | None:
    import vault

    file = Path(path)
    try:
        data = vault.read(file)   # decrypted, for a snip in an encrypted lab
    except OSError:
        return None
    kind = _IMAGE_TYPES.get(file.suffix.lower(), "image/png")
    return f"data:{kind};base64,{base64.b64encode(data).decode('ascii')}"


def cvss_version(item: dict) -> str:
    """'3.1' or '4.0' (or '3.0') for a finding's vector."""
    import cvss

    return cvss.version_of(item.get("cvss", "")) or "3.1"


def score_text(item: dict) -> str:
    """'9.8' for a finding with a CVSS score, '-' without."""
    score = item.get("score")
    return f"{score:.1f}" if score is not None else "-"


# -- the front matter (0.17.0) -----------------------------------------------------------------
META_FIELDS = ("title", "client", "author", "date")
MAX_META = 200


def default_title(name: str, scope: str = "full") -> str:
    return f"{name} findings report" if scope == "findings" else f"{name} penetration test report"


def normalise_meta(meta: dict | None, name: str, scope: str = "full") -> dict:
    """The cover page's details and whether to have a cover and contents.

    {"title", "client", "author", "date", "cover": bool, "toc": bool}. Empty
    title and date are filled in (the report's kind and today's date).
    """
    from datetime import date

    meta = dict(meta or {})
    out = {field: " ".join(str(meta.get(field, "") or "").split())[:MAX_META] for field in META_FIELDS}
    out["title"] = out["title"] or default_title(name, scope)
    out["date"] = out["date"] or date.today().strftime("%d %B %Y").lstrip("0")
    out["cover"] = bool(meta.get("cover"))
    out["toc"] = bool(meta.get("toc"))
    return out


def severity_counts(findings: list[dict]) -> list[tuple[str, int]]:
    """(severity, how many) for each severity that has findings, most severe first."""
    import lab

    counts = {name: 0 for name in lab.SEVERITIES}
    for item in findings:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1
    return [(name, counts[name]) for name in lab.SEVERITIES if counts.get(name)]


def contents(data: dict, deepest: int = 3) -> list[tuple[int, str, str]]:
    """(level, text, anchor) for the table of contents: the summary, then section headings."""
    out = []
    if data["findings"]:
        out.append((2, "Findings summary", "findings-summary"))
    for index, block in enumerate(data["blocks"]):
        if block["type"] == "heading" and block["level"] <= deepest:
            out.append((block["level"], block["text"], f"h{index}"))
    return out


def subtitle(data: dict) -> str:
    """The line under the lab's name: what this export is, and when the lab started."""
    bits = ["Findings report" if data.get("scope") == "findings" else ""]
    if data["started"]:
        bits.append(f"Started {data['started']}")
    return " - ".join(bit for bit in bits if bit)


def _html_cover(data: dict, meta: dict) -> str:
    rows = [(label, meta[key]) for label, key in (("Prepared for", "client"), ("Prepared by", "author"),
                                                  ("Date", "date")) if meta[key]]
    parts = ['<section class="cover">', f'<p class="kicker">{_esc(data["name"])}</p>',
             f"<h1>{_esc(meta['title'])}</h1>", '<table class="meta">']
    parts += [f"<tr><th>{_esc(label)}</th><td>{_esc(value)}</td></tr>" for label, value in rows]
    parts.append("</table>")
    counts = severity_counts(data["findings"])
    if counts:
        parts.append('<p class="counts">' + " ".join(
            f"{_sev_chip(name)} {count}" for name, count in counts) + "</p>")
    parts.append("</section>")
    return "".join(parts)


def to_html(data: dict) -> bytes:
    out = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_esc(data['name'])} report</title>",
        f"<style>{_CSS}</style></head><body><main>",
    ]
    meta = data.get("meta") or normalise_meta(None, data["name"], data.get("scope", "full"))
    if meta["cover"]:
        out.append(_html_cover(data, meta))
    else:
        out.append(f"<h1>{_esc(data['name'])}</h1>")
        if subtitle(data):
            out.append(f'<p class="started">{_esc(subtitle(data))}</p>')
    if meta["toc"]:
        out.append('<nav class="toc"><h2>Contents</h2><ol>')
        for level, text, anchor in contents(data):
            out.append(f'<li class="l{level}"><a href="#{anchor}">{_esc(text)}</a></li>')
        out.append("</ol></nav>")
    if data["findings"]:
        out.append('<h2 id="findings-summary">Findings summary</h2>')
        out.append('<table class="summary"><thead><tr><th>#</th><th>Finding</th>'
                   "<th>Severity</th><th>CVSS</th><th>Host</th></tr></thead><tbody>")
        for index, item in enumerate(data["findings"], start=1):
            out.append(
                f"<tr><td>{index}</td><td>{_esc(item['title'])}</td>"
                f"<td>{_sev_chip(item['severity'])}</td><td>{score_text(item)}</td>"
                f"<td>{_esc(item['host'] or '-')}</td></tr>"
            )
        out.append("</tbody></table>")

    for index, block in enumerate(data["blocks"]):
        kind = block["type"]
        if kind == "heading":
            level = block["level"]
            out.append(f'<h{level} id="h{index}">{_esc(block["text"])}</h{level}>')
        elif kind == "finding":
            bg, _fg = SEVERITY_COLOURS.get(block["severity"], ("#6c6c78", "#fff"))
            out.append(f'<div class="finding" style="--sev:{bg}"><div class="head">'
                       f"<b>Finding</b> {_sev_chip(block['severity'])}")
            if block.get("score") is not None:
                out.append(f'<span class="host">CVSS {cvss_version(block)} <b>{block["score"]:.1f}</b></span>')
            if block.get("host"):
                out.append(f'<span class="host">Affected host: {_esc(block["host"])}</span>')
            out.append("</div>")
            if block.get("cvss"):
                out.append(f'<p class="vector">{_esc(block["cvss"])}</p>')
            for field, heading in (("description", "Description"), ("impact", "Impact"),
                                   ("remediation", "Remediation")):
                if block.get(field):
                    out.append(f"<h5>{heading}</h5><p>{_esc(block[field])}</p>")
            out.append("</div>")
        elif kind == "snip":
            uri = _data_uri(block["path"]) if block["path"] else None
            label = f"<b>{_esc(block['label'])}</b>"
            bits = [label] + [_esc(x) for x in (block["time"], block["caption"]) if x]
            video = _clip_line(block)
            if video:
                bits.append(_esc(video))
            if uri is None:
                out.append(f'<p class="missing">Snip {_esc(block["label"])}: {MISSING}</p>')
            else:
                out.append(f'<figure><img src="{uri}" alt="Snip {_esc(block["label"])}">'
                           f"<figcaption>{' - '.join(bits)}</figcaption></figure>")
        elif kind == "note":
            if block.get("under_snip"):
                out.append(f"<blockquote>{_esc(block['text'])}</blockquote>")
            else:
                out.append(f'<p class="note">{_esc(block["text"])}</p>')
                if block["evidence"]:
                    out.append(f'<p class="evidence">Evidence: {_esc(", ".join(block["evidence"]))}</p>')
        elif kind == "code":
            if block["label"]:
                out.append(f'<div class="cmd">{_esc(block["label"])}</div>')
            out.append(f"<pre><code>{_esc(block['text'])}</code></pre>")
    out.append("</main></body></html>")
    return "\n".join(out).encode("utf-8")


# -- Word --------------------------------------------------------------------------------------
def docx_available() -> bool:
    """Whether the Word export can run: python-docx is installed and loads."""
    import importlib.util

    try:
        return importlib.util.find_spec("docx") is not None
    except (ImportError, ValueError):
        return False


def _picture_stream(path: str):
    """The image as something Word can hold (PNG or JPEG), and its pixel size."""
    from PIL import Image

    import vault

    data = vault.read(path)
    with Image.open(io.BytesIO(data)) as img:
        size = img.size
        if img.format in ("PNG", "JPEG"):
            return io.BytesIO(data), size
        buf = io.BytesIO()
        img.convert("RGBA" if "A" in img.getbands() else "RGB").save(buf, "PNG")
        buf.seek(0)
        return buf, size


# -- Word templates (0.17.0) -----------------------------------------------------------------
TEMPLATE_SUFFIXES = (".docx", ".dotx")
# What a template may hold, replaced wherever it appears: body, tables, headers, footers.
PLACEHOLDERS = ("{{lab}}", "{{title}}", "{{client}}", "{{author}}", "{{date}}")
REPORT_MARK = "{{report}}"


def _open_template(path):
    """A python-docx Document from a .docx or .dotx template. Raises ExportError."""
    import zipfile

    from docx import Document

    path = Path(path)
    if path.suffix.lower() not in TEMPLATE_SUFFIXES:
        raise ExportError(f"{path.name} is not a Word template (.docx or .dotx).")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ExportError(f"The Word template could not be read: {exc}") from exc
    if path.suffix.lower() == ".dotx":
        # A .dotx is a .docx whose main part says "template"; python-docx
        # only opens the document kind, so the zip is copied with that changed.
        try:
            source = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile as exc:
            raise ExportError(f"{path.name} could not be opened as a Word template: {exc}") from exc
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as copy:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "[Content_Types].xml":
                    data = data.replace(b"wordprocessingml.template.main+xml",
                                        b"wordprocessingml.document.main+xml")
                copy.writestr(item, data)
        raw = out.getvalue()
    try:
        return Document(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001 - python-docx raises several kinds
        raise ExportError(f"{path.name} could not be opened as a Word document: {exc}") from exc


def _paragraphs_everywhere(doc):
    """Every paragraph in the body, its tables, and every header and footer."""
    def walk(container):
        for paragraph in container.paragraphs:
            yield paragraph
        for table in getattr(container, "tables", []):
            for row in table.rows:
                for cell in row.cells:
                    yield from walk(cell)

    yield from walk(doc)
    for section in doc.sections:
        for part in (section.header, section.footer, section.first_page_header,
                     section.first_page_footer, section.even_page_header, section.even_page_footer):
            try:
                yield from walk(part)
            except Exception:  # noqa: BLE001 - a missing header part
                continue


def _fill_placeholders(doc, values: dict) -> None:
    """{{lab}} and the rest replaced. A placeholder split across runs (as Word
    often stores typed text) is still found: the paragraph's text is joined,
    replaced and put back in its first run."""
    for paragraph in _paragraphs_everywhere(doc):
        text = paragraph.text
        if "{{" not in text:
            continue
        new = text
        for key, value in values.items():
            new = new.replace("{{" + key + "}}", value)
        if new == text:
            continue
        runs = paragraph.runs
        if not runs:
            continue
        runs[0].text = new
        for run in runs[1:]:
            run.text = ""


def to_docx(data: dict, template=None) -> bytes:
    try:
        from docx import Document
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Inches, Pt, RGBColor
    except ImportError as exc:
        raise ExportError(
            "The Word export needs python-docx. Install it with:  "
            "pip install python-docx  (or pip install -r requirements.txt)"
        ) from exc

    def shade(cell_or_par, hex_fill: str) -> None:
        props = (cell_or_par._tc.get_or_add_tcPr() if hasattr(cell_or_par, "_tc")
                 else cell_or_par._p.get_or_add_pPr())
        fill = OxmlElement("w:shd")
        fill.set(qn("w:val"), "clear")
        fill.set(qn("w:color"), "auto")
        fill.set(qn("w:fill"), hex_fill.lstrip("#"))
        props.append(fill)

    def mono(run) -> None:
        run.font.name = "Consolas"
        run.font.size = Pt(9)
        rpr = run._r.get_or_add_rPr()
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is None:
            fonts = OxmlElement("w:rFonts")
            rpr.append(fonts)
        for attr in ("w:ascii", "w:hAnsi", "w:cs"):
            fonts.set(qn(attr), "Consolas")

    meta = data.get("meta") or normalise_meta(None, data["name"], data.get("scope", "full"))
    doc = _open_template(template) if template else Document()
    section = doc.sections[0]
    usable = section.page_width - section.left_margin - section.right_margin
    body = doc.element.body
    # What the report adds goes in before the closing section properties, so it
    # starts where they stand now.
    start = len(body) - (1 if len(body) and body[-1].tag == qn("w:sectPr") else 0)
    mark = next((p for p in doc.paragraphs if REPORT_MARK in p.text), None)
    if template:
        _fill_placeholders(doc, {"lab": data["name"], "title": meta["title"], "client": meta["client"],
                                 "author": meta["author"], "date": meta["date"]})

    def heading(text: str, level: int):
        """A heading in the template's own heading style, or a bold line when it has none."""
        try:
            return doc.add_heading(text, level=level)
        except KeyError:
            para = doc.add_paragraph()
            run = para.add_run(text)
            run.bold = True
            run.font.size = Pt({0: 26, 1: 18, 2: 15, 3: 13}.get(level, 12))
            return para

    def grid(table) -> None:
        """Table Grid, or (in a template without it) the same borders drawn directly."""
        try:
            table.style = "Table Grid"
            return
        except (KeyError, ValueError):
            pass
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            line = OxmlElement(f"w:{edge}")
            line.set(qn("w:val"), "single")
            line.set(qn("w:sz"), "4")
            line.set(qn("w:color"), "BFBFBF")
            borders.append(line)
        table._tbl.tblPr.append(borders)

    def page_break() -> None:
        from docx.enum.text import WD_BREAK

        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    has_body = any(p.text.strip() for p in doc.paragraphs) or bool(doc.tables)
    if template and mark is None and has_body:
        page_break()   # after the template's own pages
    if meta["cover"] and not template:
        heading(data["name"].upper(), 3)
        heading(meta["title"], 0)
        facts = [(label, meta[key]) for label, key in (("Prepared for", "client"), ("Prepared by", "author"),
                                                      ("Date", "date")) if meta[key]]
        for label, value in facts:
            para = doc.add_paragraph()
            para.add_run(f"{label}:  ").bold = True
            para.add_run(value)
        counts = severity_counts(data["findings"])
        if counts:
            para = doc.add_paragraph()
            para.add_run("Findings:  ").bold = True
            para.add_run(", ".join(f"{count} {name}" for name, count in counts))
        page_break()
    elif not template:
        heading(data["name"], 0)
        if subtitle(data):
            doc.add_paragraph(subtitle(data))
    if meta["toc"]:
        heading("Contents", 1)
        _toc_field(doc, OxmlElement, qn)
        page_break()

    if data["findings"]:
        heading("Findings summary", 1)
        table = doc.add_table(rows=1, cols=5)
        grid(table)
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        for cell, text in zip(table.rows[0].cells, ("#", "Finding", "Severity", "CVSS", "Host")):
            cell.text = ""
            cell.paragraphs[0].add_run(text).bold = True
        for index, item in enumerate(data["findings"], start=1):
            cells = table.add_row().cells
            cells[0].text = str(index)
            cells[1].text = item["title"]
            cells[3].text = score_text(item)
            cells[4].text = item["host"] or "-"
            bg, fg = SEVERITY_COLOURS.get(item["severity"], ("#6c6c78", "#ffffff"))
            cells[2].text = ""
            run = cells[2].paragraphs[0].add_run(item["severity"])
            run.bold = True
            run.font.color.rgb = RGBColor.from_string(fg.lstrip("#").upper())
            shade(cells[2], bg)
        doc.add_paragraph()

    for block in data["blocks"]:
        kind = block["type"]
        if kind == "heading":
            heading(block["text"], max(1, min(block["level"] - 1, 9)))
        elif kind == "finding":
            bg, fg = SEVERITY_COLOURS.get(block["severity"], ("#6c6c78", "#ffffff"))
            rows = 1 + bool(block.get("host")) + bool(block.get("cvss"))
            table = doc.add_table(rows=rows, cols=2)
            grid(table)
            table.rows[0].cells[0].text = ""
            table.rows[0].cells[0].paragraphs[0].add_run("Severity").bold = True
            table.rows[0].cells[1].text = ""
            run = table.rows[0].cells[1].paragraphs[0].add_run(block["severity"])
            run.bold = True
            run.font.color.rgb = RGBColor.from_string(fg.lstrip("#").upper())
            shade(table.rows[0].cells[1], bg)
            row = 1
            if block.get("cvss"):
                table.rows[row].cells[0].text = ""
                table.rows[row].cells[0].paragraphs[0].add_run(f"CVSS {cvss_version(block)}").bold = True
                table.rows[row].cells[1].text = ""
                cell = table.rows[row].cells[1].paragraphs[0]
                cell.add_run(f"{block['score']:.1f}  ").bold = True
                mono(cell.add_run(block["cvss"]))
                row += 1
            if block.get("host"):
                table.rows[row].cells[0].text = ""
                table.rows[row].cells[0].paragraphs[0].add_run("Affected host").bold = True
                table.rows[row].cells[1].text = block["host"]
            doc.add_paragraph()
            for field, label in (("description", "Description"), ("impact", "Impact"),
                                 ("remediation", "Remediation")):
                if block.get(field):
                    para = doc.add_paragraph()
                    para.add_run(label).bold = True
                    for line in block[field].split("\n"):
                        doc.add_paragraph(line)
        elif kind == "snip":
            try:
                if not block["path"]:
                    raise FileNotFoundError(block["label"])
                stream, (w, h) = _picture_stream(block["path"])
            except Exception:  # noqa: BLE001 - a missing image is reported in place
                doc.add_paragraph().add_run(f"Snip {block['label']}: {MISSING}").italic = True
                continue
            # 96 dpi to inches, never wider than the page.
            width = min(Inches(w / 96), usable)
            doc.add_picture(stream, width=width)
            caption = doc.add_paragraph()
            caption.add_run(block["label"]).bold = True
            rest = " - ".join(x for x in (block["time"], block["caption"], _clip_line(block)) if x)
            if rest:
                caption.add_run(f" - {rest}")
            caption.runs[-1].font.size = Pt(9)
        elif kind == "note":
            for line in block["text"].split("\n"):
                para = doc.add_paragraph(line)
                if block.get("under_snip"):
                    para.paragraph_format.left_indent = Inches(0.3)
                    for run in para.runs:
                        run.italic = True
            if block.get("evidence"):
                para = doc.add_paragraph()
                run = para.add_run(f"Evidence: {', '.join(block['evidence'])}")
                run.italic = True
                run.font.size = Pt(9)
        elif kind == "code":
            if block["label"]:
                para = doc.add_paragraph()
                run = para.add_run(block["label"])
                run.bold = True
                mono(run)
            para = doc.add_paragraph()
            shade(para, "#f4f4f7")
            lines = block["text"].split("\n")
            for i, line in enumerate(lines):
                run = para.add_run(line)
                mono(run)
                if i < len(lines) - 1:
                    run.add_break()

    if mark is not None:
        # Move everything the report added to where {{report}} was, and drop the mark.
        added = [element for element in list(body)[start:] if element.tag != qn("w:sectPr")]
        for element in added:
            mark._p.addprevious(element)
        mark._p.getparent().remove(mark._p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _toc_field(doc, OxmlElement, qn) -> None:
    """A Word table of contents field (headings 1 to 3), filled in when Word opens the file.

    Word lays out pages, so only Word can number them: the field is marked
    dirty and the document told to update fields on opening, and Word asks
    once whether to. Until then it shows a line saying so.
    """
    para = doc.add_paragraph()
    run = para.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin.set(qn("w:dirty"), "true")
    code = OxmlElement("w:instrText")
    code.set(qn("xml:space"), "preserve")
    code.text = 'TOC \\o "1-3" \\h \\z \\u'
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    run._r.append(begin)
    run._r.append(code)
    run._r.append(separate)
    shown = para.add_run("The contents fill in when Word opens this file (answer Yes to updating fields).")
    shown.italic = True
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    para.add_run()._r.append(end)
    settings = doc.settings.element
    if settings.find(qn("w:updateFields")) is None:
        update = OxmlElement("w:updateFields")
        update.set(qn("w:val"), "true")
        settings.append(update)
