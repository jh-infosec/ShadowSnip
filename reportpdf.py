"""The PDF report (0.15.0).

Built with Qt alone, so nothing more is installed: the report is laid out as
a `QTextDocument` (Qt's rich text engine, which reads a subset of HTML) and
painted page by page onto a `QPdfWriter`. The text in the PDF is real text,
so it can be searched and copied, and the snips are embedded at their own
resolution, scaled to the page width when wider.

QTextDocument's HTML is not a browser's: no flexbox, no rounded corners, no
CSS variables, and borders only on tables. So the PDF gets its own markup
here rather than reusing the HTML export's, with tables where the web page
uses boxes: the severity chips are coloured table cells, a finding is a
one-cell table with a coloured left edge, and command output a shaded cell.

Pages are A4 with a footer on each: the lab's name and "Page n of m". An
image is never split across pages (Qt moves a line that does not fit to the
next page, and an image is one line).
"""

from __future__ import annotations

import html

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF, QRectF, QSizeF, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTextDocument,
)

import report

# Points of A4 not printed on (mm): top, right, bottom, left.
MARGINS_MM = (16, 16, 14, 16)
# The writer's resolution: one device pixel is one CSS pixel, so sizes below
# read as they would on a web page.
DPI = 96
FOOTER_PX = 28
BASE_PT = 10
# Images wider than this are downscaled before going in, to keep the file a
# sensible size; they are drawn at most page width anyway.
MAX_IMAGE_PX = 2000

_INK = "#1d1d22"
_DIM = "#5c5c66"
_RULE = "#c8c8d0"
_CODE = "#f4f4f7"


def _esc(text) -> str:
    return html.escape(str(text or ""), quote=True)


def _para(text: str) -> str:
    """Plain text with its line breaks kept."""
    return _esc(text).replace("\n", "<br>")


def _sev_cell(severity: str) -> str:
    bg, fg = report.SEVERITY_COLOURS.get(severity, ("#6c6c78", "#ffffff"))
    return (f'<td bgcolor="{bg}" style="color:{fg}; font-weight:600; padding:2px 8px;">'
            f"{_esc(severity)}</td>")


class _Builder:
    def __init__(self, document: QTextDocument, text_width: int):
        self.doc = document
        self.text_width = text_width
        self.parts: list[str] = []
        self._images = 0

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def image(self, path: str) -> str | None:
        """Register the picture with the document; the markup to show it, or None."""
        import vault

        picture = vault.load_image(path)
        if picture.isNull():
            return None
        if picture.width() > MAX_IMAGE_PX:
            picture = picture.scaledToWidth(MAX_IMAGE_PX, Qt.TransformationMode.SmoothTransformation)
        self._images += 1
        name = f"snip{self._images}.png"
        self.doc.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), picture)
        # Screenshots are in physical pixels: show them at their size, up to the page width.
        width = min(picture.width(), self.text_width)
        height = round(picture.height() * width / picture.width())
        return f'<img src="{name}" width="{width}" height="{height}">'


def build(data: dict, document: QTextDocument, text_width: int) -> str:
    """The QTextDocument markup for a report model (see report.model)."""
    out = _Builder(document, text_width)
    out.add(f'<h1 style="font-size:22pt; margin-bottom:2px;">{_esc(data["name"])}</h1>')
    if report.subtitle(data):
        out.add(f'<p style="color:{_DIM}; margin-top:0;">{_esc(report.subtitle(data))}</p>')

    if data["findings"]:
        out.add('<h2 style="font-size:15pt;">Findings summary</h2>')
        out.add(f'<table width="100%" cellspacing="0" cellpadding="5" border="1" '
                f'style="border-color:{_RULE}; border-style:solid;">')
        out.add(f'<tr style="color:{_DIM};"><th align="left">#</th><th align="left">Finding</th>'
                '<th align="left">Severity</th><th align="left">CVSS</th><th align="left">Host</th></tr>')
        for index, item in enumerate(data["findings"], start=1):
            out.add(f"<tr><td>{index}</td><td>{_esc(item['title'])}</td>{_sev_cell(item['severity'])}"
                    f"<td>{report.score_text(item)}</td><td>{_esc(item['host'] or '-')}</td></tr>")
        out.add("</table>")

    for block in data["blocks"]:
        kind = block["type"]
        if kind == "heading":
            level = max(2, min(block["level"], 6))
            size = {2: 15, 3: 13, 4: 11.5, 5: 11, 6: 10.5}[level]
            out.add(f'<h{level} style="font-size:{size}pt; margin-top:14px;">{_esc(block["text"])}</h{level}>')
        elif kind == "finding":
            bg, _fg = report.SEVERITY_COLOURS.get(block["severity"], ("#6c6c78", "#ffffff"))
            head = [f"<b>Finding</b>&nbsp;&nbsp;"]
            chip = (f'<table cellspacing="0" cellpadding="0"><tr>{_sev_cell(block["severity"])}'
                    "</tr></table>")
            facts = []
            if block.get("score") is not None:
                facts.append(f"CVSS 3.1 <b>{block['score']:.1f}</b>")
            if block.get("host"):
                facts.append(f"Affected host: {_esc(block['host'])}")
            body = [f"<p>{''.join(head)}</p>", chip]
            if facts:
                body.append(f'<p style="color:{_DIM};">{" &nbsp;|&nbsp; ".join(facts)}</p>')
            if block.get("cvss"):
                body.append(f'<p style="color:{_DIM}; font-family:monospace; font-size:8.5pt;">'
                            f"{_esc(block['cvss'])}</p>")
            for field, heading in (("description", "Description"), ("impact", "Impact"),
                                   ("remediation", "Remediation")):
                if block.get(field):
                    body.append(f'<p style="color:{_DIM}; font-size:8.5pt; margin-top:8px; margin-bottom:0;">'
                                f"<b>{heading.upper()}</b></p><p style=\"margin-top:2px;\">{_para(block[field])}</p>")
            out.add(f'<table width="100%" cellspacing="0" cellpadding="0" style="margin-top:4px; margin-bottom:10px;">'
                    f'<tr><td width="5" bgcolor="{bg}"></td>'
                    f'<td style="padding:8px 12px; border:1px solid {_RULE};">{"".join(body)}</td></tr></table>')
        elif kind == "snip":
            picture = out.image(block["path"]) if block["path"] else None
            if picture is None:
                out.add(f'<p style="color:#b00020;"><i>Snip {_esc(block["label"])}: {report.MISSING}</i></p>')
                continue
            bits = [f"<b>{_esc(block['label'])}</b>"] + [_esc(x) for x in (block["time"], block["caption"]) if x]
            video = report._clip_line(block)
            if video:
                bits.append(_esc(video))
            out.add(f'<p style="margin-top:10px; margin-bottom:0;">{picture}</p>')
            out.add(f'<p style="color:{_DIM}; font-size:8.5pt; margin-top:3px;">{" - ".join(bits)}</p>')
        elif kind == "note":
            if block.get("under_snip"):
                out.add(f'<table width="100%" cellspacing="0" cellpadding="0"><tr><td width="3" bgcolor="#2f8cff"></td>'
                        f'<td style="padding:2px 10px; color:#33333b;">{_para(block["text"])}</td></tr></table>')
            else:
                out.add(f"<p>{_para(block['text'])}</p>")
                if block.get("evidence"):
                    out.add(f'<p style="color:{_DIM}; font-size:8.5pt;"><i>Evidence: '
                            f"{_esc(', '.join(block['evidence']))}</i></p>")
        elif kind == "code":
            if block["label"]:
                out.add(f'<p style="font-family:monospace; font-weight:600; margin-bottom:2px;">'
                        f"{_esc(block['label'])}</p>")
            out.add(f'<table width="100%" cellspacing="0" cellpadding="8" bgcolor="{_CODE}" '
                    f'style="border:1px solid {_RULE};"><tr><td>'
                    f'<pre style="font-family:monospace; font-size:8.5pt; white-space:pre-wrap;">'
                    f"{_esc(block['text'])}</pre></td></tr></table>")
    return "\n".join(out.parts)


def to_pdf(data: dict) -> bytes:
    """The report as PDF bytes. Needs a running QGuiApplication (ShadowSnip always has one)."""
    payload = QByteArray()
    buffer = QBuffer(payload)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buffer)
    writer.setResolution(DPI)
    writer.setTitle(f"{data['name']} report")
    writer.setCreator("ShadowSnip")
    top, right, bottom, left = MARGINS_MM
    writer.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Portrait,
                                     QMarginsF(left, top, right, bottom), QPageLayout.Unit.Millimeter))
    width, height = writer.width(), writer.height()
    page_height = height - FOOTER_PX

    document = QTextDocument()
    document.setDocumentMargin(0)
    font = QFont()
    font.setPointSizeF(BASE_PT)
    document.setDefaultFont(font)
    document.setDefaultStyleSheet(f"body {{ color: {_INK}; }} pre {{ margin: 0; }}")
    document.setPageSize(QSizeF(width, page_height))
    document.setHtml(build(data, document, width))
    pages = max(1, document.pageCount())

    painter = QPainter()
    if not painter.begin(writer):
        raise report.ExportError("The PDF could not be started.")
    try:
        footer_font = QFont(font)
        footer_font.setPointSizeF(8)
        for page in range(pages):
            if page:
                writer.newPage()
            painter.save()
            painter.setClipRect(QRectF(0, 0, width, page_height))
            painter.translate(0, -page * page_height)
            document.drawContents(painter, QRectF(0, page * page_height, width, page_height))
            painter.restore()
            painter.setFont(footer_font)
            painter.setPen(QColor(_DIM))
            painter.drawLine(0, height - FOOTER_PX + 6, width, height - FOOTER_PX + 6)
            footer = QRectF(0, height - FOOTER_PX + 8, width, FOOTER_PX - 8)
            painter.drawText(footer, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, data["name"])
            painter.drawText(footer, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"Page {page + 1} of {pages}")
    finally:
        painter.end()
    buffer.close()
    return bytes(payload.data())
