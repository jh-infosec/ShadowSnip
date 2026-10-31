"""Recent snips' columns (0.10.1): dimensions, size, marks, times, alignment, lines."""

from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

import edits
import labsnips as ls
import storage


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


TODAY = date(2026, 10, 31)


@pytest.mark.parametrize("when, shown", [
    ("2026-10-31 18:20:10", "18:20:10"),
    ("2026-10-30 16:41:22", "Yesterday 16:41"),
    ("2026-10-29 09:14:03", "29 Oct 09:14"),
    ("2025-12-31 23:59:00", "31 Dec 2025 23:59"),
    ("unknown", "unknown"),
    ("odd 12:00", "12:00"),
])
def test_when_text(when, shown):
    assert ls.when_text(when, today=TODAY) == shown


@pytest.mark.parametrize("count, shown", [
    (845, "845 B"), (2048, "2 KB"), (250_000, "244 KB"), (1_468_006, "1.4 MB"),
])
def test_size_text(count, shown):
    assert ls.size_text(count) == shown


def _snip(folder: Path, stamp: str, w: int, h: int) -> Path:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#336699"))
    path = folder / f"snip_{stamp}.png"
    img.save(str(path))
    return path


def test_snip_facts_reads_size_and_sees_edits(tmp_path):
    path = _snip(tmp_path, "2026-10-31_10-00-00", 320, 200)
    width, height, count, editable = ls.snip_facts(str(path))
    assert (width, height, count, editable) == (320, 200, path.stat().st_size, False)
    (tmp_path / edits.DIR_NAME).mkdir()
    (tmp_path / edits.DIR_NAME / f"{path.name}.json").write_text("{}")
    assert ls.snip_facts(str(path))[3] is True
    assert ls.snip_facts(str(tmp_path / "missing.png")) is None
    assert ls.snip_facts("") is None


@pytest.fixture
def recent(tmp_path):
    hist = tmp_path / "history"
    hist.mkdir()
    for i, (stamp, size) in enumerate([("2026-10-29_09-14-03", (1920, 1080)),
                                       ("2026-10-31_11-02-45", (640, 360))]):
        path = _snip(hist, stamp, *size)
        os.utime(path, (time.time() + i, time.time() + i))
    panel = ls.LabSnipsPanel()
    panel.set_lab_mode(False)
    panel.resize(600, 500)
    panel.show()
    rows = storage.history_rows({"save_dir": str(tmp_path)})
    panel.set_rows(rows, rows[-1]["file"])
    QApplication.processEvents()
    yield panel
    panel.close()


def test_recent_shows_dimensions_size_and_marks_not_lab_columns(recent):
    hidden = {c: recent.list.isColumnHidden(c) for c in range(len(ls.HEADERS))}
    assert not any(hidden[c] for c in (ls.COL_NUMBER, ls.COL_TIME, *ls.RECENT_ONLY))
    assert all(hidden[c] for c in ls.LAB_ONLY)
    top = recent.list.topLevelItem(0)
    assert top.text(ls.COL_DIMENSIONS) == "640 × 360"
    assert top.text(ls.COL_BYTES).endswith(("B", "KB", "MB"))
    oldest = recent.list.topLevelItem(1)
    assert oldest.text(ls.COL_DIMENSIONS) == "1920 × 1080"


def test_the_new_columns_come_straight_after_time(recent):
    header = recent.list.header()
    order = sorted(range(len(ls.HEADERS)), key=header.visualIndex)
    assert order[:5] == [ls.COL_NUMBER, ls.COL_TIME, *ls.RECENT_ONLY]


def test_lab_mode_hides_them_again(recent):
    recent.set_lab_mode(True)
    assert all(recent.list.isColumnHidden(c) for c in ls.RECENT_ONLY)
    assert not any(recent.list.isColumnHidden(c) for c in ls.LAB_ONLY)


def test_cells_and_headings_are_centred(recent):
    top = recent.list.topLevelItem(0)
    heading = recent.list.headerItem()
    for column in ls.CENTRED:
        assert top.textAlignment(column) & Qt.AlignmentFlag.AlignHCenter
        assert heading.textAlignment(column) & Qt.AlignmentFlag.AlignHCenter


def test_columns_fill_the_width_and_fit_their_contents(recent):
    widths = [recent.list.columnWidth(c) for c in (ls.COL_NUMBER, ls.COL_TIME, *ls.RECENT_ONLY)]
    assert abs(sum(widths) - recent.list.viewport().width()) <= 2
    for column in (ls.COL_TIME, ls.COL_DIMENSIONS):
        assert recent.list.columnWidth(column) >= recent.list.sizeHintForColumn(column)


def test_column_lines_sit_on_the_header_borders(recent):
    xs = recent.list.column_line_xs()
    assert len(xs) == 4  # five visible columns, four lines between them
    header = recent.list.header()
    first = header.sectionViewportPosition(ls.COL_NUMBER) + header.sectionSize(ls.COL_NUMBER) - 1
    assert xs[0] == first
    assert recent.list.column_lines and not ls.OutlinedTree().column_lines
