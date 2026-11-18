"""Removed snips, and putting them back (0.15.0).

Removing a snip has always moved it rather than deleting it: into the lab's
`removed/` folder (with its record kept in lab.json), or into
`history/removed` for the recent list. Getting one back meant moving the file
by hand and, in a lab, editing lab.json. This window lists them and puts them
back: in a lab with the notes that went with it, in the section it was filed
under and where it was in lab.md.

The window only shows and asks; `rows()` and `restore(names)` are given to it
by the app, which knows whether a lab is running.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

import clips

PREVIEW_SIZE = (320, 200)
COL_NUMBER, COL_NAME, COL_SECTION, COL_REMOVED = range(4)


def row_name(row: dict) -> str:
    """What a removed snip is called in the list: its caption, else its file name."""
    caption = str(row.get("caption") or "").strip()
    return caption or str(row.get("file", ""))


class RemovedDialog(QDialog):
    """The removed snips, with a preview and Restore."""

    # The snips put back: the app refreshes its lists.
    restored = Signal(list)

    def __init__(self, rows_fn, restore_fn, open_folder_fn=None, lab_name: str = "", parent=None):
        super().__init__(parent)
        self._rows_fn = rows_fn
        self._restore_fn = restore_fn
        self._open_folder_fn = open_folder_fn
        self._rows: dict[str, dict] = {}
        self.setWindowTitle(f"Removed snips - {lab_name}" if lab_name else "Removed snips")
        self.resize(760, 420)

        self.list = QTreeWidget()
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setHeaderLabels(["#", "Snip", "Section", "Removed"])
        header = self.list.header()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for column in (COL_NUMBER, COL_SECTION, COL_REMOVED):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.list.itemSelectionChanged.connect(self._show_selected)
        self.list.itemDoubleClicked.connect(lambda *_: self.restore_selected())

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedWidth(PREVIEW_SIZE[0])
        self.preview.setMinimumHeight(PREVIEW_SIZE[1])
        self.preview.setObjectName("SnipThumb")
        self.preview.setWordWrap(True)
        self.detail = QLabel()
        self.detail.setObjectName("SnipWhere")
        self.detail.setWordWrap(True)
        self.detail.setFixedWidth(PREVIEW_SIZE[0])
        self.detail.setTextFormat(Qt.TextFormat.PlainText)

        self.empty = QLabel("Nothing has been removed.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setObjectName("SnipWhere")

        self.status = QLabel("")
        self.status.setObjectName("SnipWhere")
        self.status.setWordWrap(True)

        self.btn_restore = QPushButton("Restore")
        self.btn_restore.setToolTip("Put the selected snips back where they were (double-click does the same)")
        self.btn_restore.clicked.connect(self.restore_selected)
        self.btn_folder = QPushButton("Show folder")
        self.btn_folder.setToolTip("Open the removed folder")
        self.btn_folder.clicked.connect(self._open_folder)
        self.btn_folder.setVisible(open_folder_fn is not None)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)

        side = QVBoxLayout()
        side.setSpacing(6)
        side.addWidget(self.preview)
        side.addWidget(self.detail)
        side.addStretch(1)
        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self.list, 1)
        body.addWidget(self.empty, 1)
        body.addLayout(side)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.status, 1)
        buttons.addWidget(self.btn_folder)
        buttons.addWidget(self.btn_restore)
        buttons.addWidget(self.btn_close)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)
        layout.addLayout(body, 1)
        layout.addLayout(buttons)
        self.reload()

    # -- the list ----------------------------------------------------------------------
    def reload(self) -> None:
        rows = list(self._rows_fn())
        self._rows = {row["stored"]: row for row in rows}
        self.list.clear()
        for row in rows:
            number = row.get("number")
            item = QTreeWidgetItem([
                f"{number:03d}" if isinstance(number, int) and number else "",
                row_name(row) + ("  ▶" if clips.clip_for(row.get("path")) else ""),
                str(row.get("section") or "").replace("/", " / "),
                str(row.get("removed") or ""),
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, row["stored"])
            if not row.get("path"):
                item.setDisabled(True)
                item.setToolTip(COL_NAME, "The image is no longer in the removed folder")
            self.list.addTopLevelItem(item)
        has_rows = bool(rows)
        self.list.setVisible(has_rows)
        self.empty.setVisible(not has_rows)
        if has_rows:
            self.list.setCurrentItem(self.list.topLevelItem(0))
        self._show_selected()

    def selected(self) -> list[str]:
        return [item.data(0, Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()
                if not item.isDisabled()]

    def _show_selected(self) -> None:
        names = self.selected()
        self.btn_restore.setEnabled(bool(names))
        self.btn_restore.setText(f"Restore {len(names)}" if len(names) > 1 else "Restore")
        row = self._rows.get(names[0]) if names else None
        if row is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("")
            self.detail.setText("")
            return
        import vault

        image = vault.load_image(row.get("path") or "")
        picture = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
        if picture.isNull():
            self.preview.setPixmap(QPixmap())
            self.preview.setText("No preview")
        else:
            self.preview.setText("")
            self.preview.setPixmap(picture.scaled(
                PREVIEW_SIZE[0], PREVIEW_SIZE[1], Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        lines = [row["file"]]
        if row.get("time"):
            lines.append(f"Taken {row['time']}")
        if row.get("section"):
            lines.append(f"Filed under {row['section'].replace('/', ' / ')}")
        if row.get("notes"):
            lines.append(f"{row['notes']} note{'s' if row['notes'] != 1 else ''} attached, restored with it")
        self.detail.setText("\n".join(lines))

    # -- actions ----------------------------------------------------------------------
    def restore_selected(self) -> None:
        names = self.selected()
        if not names:
            return
        done, problems = [], []
        for name in names:
            try:
                done.append(self._restore_fn(name))
            except (OSError, RuntimeError, ValueError) as exc:
                problems.append(str(exc))
        self.reload()
        if done:
            self.restored.emit(done)
        parts = []
        if done:
            parts.append(f"Restored {len(done)} snip{'s' if len(done) != 1 else ''}.")
        parts.extend(problems)
        self.status.setText(" ".join(parts))

    def _open_folder(self) -> None:
        if self._open_folder_fn is not None:
            self._open_folder_fn()
