"""Tray application and the snip pipeline.

Pipeline for one snip:

    freeze screens -> overlay -> crop -> compress -> clipboard -> disk -> preview

The clipboard and disk writes both happen automatically. Everything in the
preview window afterwards is optional.

When a lab is engaged the same snip also lands in that lab's folder, numbered
in capture order. Nothing else about the pipeline changes.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QRect, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

import autocopy as autocopy_mod
import capture
import clipboard
import config
import hotkey as hotkey_mod
import imageops
import lab
import platforms
import storage
from overlay import SelectionController
from preview import PreviewWindow
from settings_dialog import SettingsDialog
from toast import ClipToast


class ShadowSnipApp(QObject):
    def __init__(self, qapp, parent=None):
        super().__init__(parent)
        self.qapp = qapp
        self.cfg = config.load()
        self.busy = False
        self.controller: SelectionController | None = None
        self._grabs = []
        self._last_png = b""
        self._last_image = None
        self._last_disk: tuple[bytes, str] | None = None
        # The lab filename of the snip on screen, so a note can attach to it.
        self._last_lab_file: str = ""

        self.preview = PreviewWindow(icon=build_icon())
        self.preview.new_snip_requested.connect(self.request_snip)
        self.preview.lab_toggle_requested.connect(self.toggle_lab)
        self.preview.auto_copy_toggled.connect(self.toggle_auto_copy)
        self.preview.section_changed.connect(self.set_section)
        self.preview.snip_edited.connect(self.apply_snip_edit)
        self.preview.annotation_prefs_changed.connect(self._save_annotation_prefs)
        self.preview.set_annotation_prefs(self.cfg.get("annotation") or {})
        # Every file the snip on screen was written to, so an edit (above all
        # a redaction) replaces each of them and leaves no original behind.
        self._snip_paths: dict[str, Path] = {}
        self.preview.snip_move_requested.connect(self.move_current_snip)
        self.preview.settings_requested.connect(self.open_settings)
        self.preview.snip_remove_requested.connect(self.remove_lab_snip)
        self.preview.snip_open_requested.connect(self.open_lab_snip)
        self.preview.snip_list_toggled.connect(self.set_snip_list_shown)
        self.preview.note_added.connect(self._on_note_from_preview)
        self.preview.lab_entry_move_requested.connect(self.move_lab_entry)
        self.preview.lab_md_open_requested.connect(self.open_lab_md)

        # The snip list follows the lab folder itself rather than relying on
        # every code path that writes into it remembering to refresh. A snip,
        # a removal, a caption or note (lab.json is replaced), even an image
        # copied in by hand in Explorer: the folder changes, the list follows.
        # Changes are gathered for a moment first, because one snip is several
        # writes (the image, lab.json, lab.md) and the list only needs
        # rebuilding once.
        self._watched_lab = ""
        self._lab_watcher = QFileSystemWatcher(self)
        self._lab_watcher.directoryChanged.connect(self._on_lab_folder_changed)
        self._snip_list_timer = QTimer(self)
        self._snip_list_timer.setSingleShot(True)
        self._snip_list_timer.setInterval(120)
        self._snip_list_timer.timeout.connect(self._refresh_snip_list)
        # Whether the window was up when a snip started, so a cancelled snip
        # can put it back instead of leaving you with nothing on screen.
        self._reshow_preview = False

        self.tray = QSystemTrayIcon(build_icon(), self)
        self.tray.setToolTip("ShadowSnip")
        self.tray.activated.connect(self._on_tray_activated)
        self._build_menu()
        self.tray.show()

        self.hotkeys = platforms.HotkeyManager(self)
        self.hotkeys.triggered.connect(self._on_hotkey)
        self._register_hotkeys(startup=True)

        self.toast = ClipToast()
        self.autocopy = platforms.AutoCopy(self.cfg, self)
        self.autocopy.copied.connect(self._on_auto_copied)
        # Copy on select does not survive a restart, and the stored value is
        # cleared rather than merely ignored so that Settings, the tray menu
        # and the preview button all agree from the first frame.
        #
        # It is a system-wide mouse hook that synthesises keystrokes and reads
        # the clipboard back. Something with that reach should be switched on
        # for the session you want it in, deliberately, rather than resuming
        # days later because it was left on once -- and a feature that is
        # quietly running while every toggle in the app reads "off" is worse
        # than one that needs a click.
        self.cfg["auto_copy"] = False
        self._refresh_menu_text()

    # -- tray --------------------------------------------------------------
    def _build_menu(self) -> None:
        menu = QMenu()
        self.action_new = QAction("New snip", self)
        self.action_new.triggered.connect(self.request_snip)
        menu.addAction(self.action_new)

        self.action_folder = QAction("Open save folder", self)
        self.action_folder.triggered.connect(self._open_save_folder)
        menu.addAction(self.action_folder)

        menu.addSeparator()
        self.action_lab = QAction("Start lab...", self)
        self.action_lab.triggered.connect(self.toggle_lab)
        menu.addAction(self.action_lab)

        self.action_note = QAction("Add note...", self)
        self.action_note.triggered.connect(self.quick_note)
        menu.addAction(self.action_note)

        self.action_section = QAction("Set section...", self)
        self.action_section.triggered.connect(self.ask_section)
        menu.addAction(self.action_section)

        self.action_auto = QAction("Copy on select", self)
        self.action_auto.setCheckable(True)
        self.action_auto.triggered.connect(self.toggle_auto_copy)
        menu.addAction(self.action_auto)

        self.labs_menu = QMenu("Open a lab", menu)
        self.labs_menu.aboutToShow.connect(self._fill_labs_menu)
        menu.addMenu(self.labs_menu)

        menu.addSeparator()
        action_settings = QAction("Settings...", self)
        action_settings.triggered.connect(self.open_settings)
        menu.addAction(action_settings)

        action_quit = QAction("Quit ShadowSnip", self)
        action_quit.triggered.connect(self.quit)
        menu.addAction(action_quit)

        self.tray.setContextMenu(menu)
        self._refresh_menu_text()

    def _refresh_menu_text(self) -> None:
        label = hotkey_mod.describe(self.cfg["hotkey"])
        self.action_new.setText(f"New snip\t{label}")
        self.action_note.setText(
            f"Add note...\t{hotkey_mod.describe(self.cfg['note_hotkey'])}"
        )

        name = lab.active_name(self.cfg)
        keeping_record = bool(self.cfg["lab_index"])
        if name:
            self.action_lab.setText(f"Stop lab ({name})")
            self.action_folder.setText("Open lab folder")
            self.tray.setToolTip(
                f"ShadowSnip - lab: {name} "
                f"({lab.count(self.cfg)} snips, {lab.note_count(self.cfg)} notes)"
            )
        else:
            self.action_lab.setText("Start lab...")
            self.action_folder.setText("Open save folder")
            self.tray.setToolTip(f"ShadowSnip - press {label} to snip")
        self.tray.setIcon(build_icon(active=bool(name)))
        self.preview.set_lab_name(name)

        # Notes and sections live in the lab record, so they are only offered
        # when there is a lab and a record is being kept.
        notes_live = bool(name) and keeping_record
        self.action_note.setEnabled(notes_live)
        self.action_section.setEnabled(notes_live)
        self.preview.set_notes_visible(notes_live)
        if notes_live:
            where = lab.section(self.cfg)
            # Offer the list first, then the current value: set_sections clears
            # the box, so filling it afterwards would blank the breadcrumb.
            self.preview.set_sections(lab.sections(self.cfg))
            self.preview.set_section_text(where)
            self.action_section.setText(f"Set section... ({where or 'root'})")
        else:
            self.action_section.setText("Set section...")

        # The snip list is built from the images in the lab folder, so it is
        # shown for any running lab, record or not.
        shown = bool(self.cfg.get("lab_snip_list", True))
        self.preview.set_snips_visible(bool(name), shown)
        self._watch_lab_folder()
        self._refresh_snip_list()

        engaged = self.autocopy.engaged if hasattr(self, "autocopy") else False
        self.action_auto.setChecked(engaged)
        self.preview.set_auto_copy(engaged)

    def _on_tray_activated(self, reason) -> None:
        # A left click, single or double, brings up the window. Snipping is the
        # hotkey, the menu, and the New snip button; clicking the tray icon and
        # losing whatever was on screen to an accidental snip is a poor default.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    # -- the live snip list -------------------------------------------------
    def _watch_lab_folder(self) -> None:
        """Point the folder watcher at the running lab, or at nothing."""
        target = lab.active_folder(self.cfg)
        wanted = str(target) if target is not None and target.is_dir() else ""
        if wanted == self._watched_lab:
            return
        watched = self._lab_watcher.directories()
        if watched:
            self._lab_watcher.removePaths(watched)
        if wanted:
            self._lab_watcher.addPath(wanted)
        self._watched_lab = wanted

    def _on_lab_folder_changed(self, _path: str) -> None:
        self._snip_list_timer.start()

    def _refresh_snip_list(self) -> None:
        """Rebuild the snip list and the tray count from the lab folder."""
        name = lab.active_name(self.cfg)
        if not name:
            return
        self.tray.setToolTip(
            f"ShadowSnip - lab: {name} "
            f"({lab.count(self.cfg)} snips, {lab.note_count(self.cfg)} notes)"
        )
        if not self.cfg.get("lab_snip_list", True):
            return
        self.preview.set_lab_snips(lab.snip_rows(self.cfg), self._last_lab_file)
        folder = lab.active_folder(self.cfg)
        try:
            md_text = (folder / lab.INDEX_NAME).read_text(encoding="utf-8")
        except (OSError, ValueError):
            md_text = ""
        self.preview.set_lab_outline(lab.outline(self.cfg), md_text, folder)

    def show_window(self) -> None:
        """Bring the window up for a relaunch or a tray click.

        During a snip the overlay owns the screen, and the window is hidden
        on purpose so it is not in the picture; it comes back afterwards.
        """
        if self.busy:
            self._reshow_preview = True
            return
        self._refresh_snip_list()
        self.preview.open_window()

    def _open_save_folder(self) -> None:
        target = lab.active_folder(self.cfg)
        if target is not None:
            storage.open_folder(target)
            return
        folder = storage.save_dir(self.cfg)
        storage.reveal(folder / f"{self.cfg['latest_name']}.{self.cfg['disk_format']}")

    # -- labs --------------------------------------------------------------
    def toggle_lab(self) -> None:
        if lab.is_active(self.cfg):
            self.stop_lab()
        else:
            self.start_lab()

    def start_lab(self) -> None:
        """Ask for a name, then send every following snip to that folder.

        An existing name resumes that lab and carries on numbering from where
        it stopped, which doubles as crash recovery.
        """
        parent = self.preview if self.preview.isVisible() else None
        name, ok = QInputDialog.getText(
            parent, "Start lab", "Lab name:", text=lab.active_name(self.cfg)
        )
        if not ok or not name.strip():
            return
        try:
            folder = lab.start(self.cfg, name)
        except lab.LabError as exc:
            self._warn(str(exc))
            return

        self.cfg["active_lab"] = name.strip()
        self._persist()
        self._refresh_menu_text()

        existing = lab.count(self.cfg)
        where = lab.section(self.cfg)
        state = f"resumed, {existing} snips already in it" if existing else "new lab"
        if where:
            state += f", filing under {where}"

        # Starting a lab while looking at a snip means that snip belongs in it.
        if self.preview.isVisible() and self._last_disk is not None:
            self._file_current_snip_into_lab()

        self.tray.showMessage(
            "ShadowSnip",
            f"Lab '{self.cfg['active_lab']}' engaged ({state})\n{folder}",
            build_icon(active=True),
            4000,
        )

    def _file_current_snip_into_lab(self) -> None:
        data, ext = self._last_disk
        try:
            lab_path = lab.save(data, ext, self.cfg)
        except (OSError, lab.LabError) as exc:
            self.preview.set_status(f"Could not write into the lab: {exc}")
            return
        if lab_path is None:
            return
        self._last_lab_file = lab_path.name
        self._snip_paths["lab"] = lab_path
        caption_cb = None
        if self.cfg["lab_index"] and self.cfg["lab_caption"]:
            caption_cb = self._caption_setter(lab_path.name)
        self.preview.attach_lab(lab_path.parent, caption_cb)
        self.preview.set_status(
            f"Lab {lab.active_name(self.cfg)} started; this snip filed as "
            f"{lab_path.name}"
        )
        # Filed after the menu refresh in start_lab, so without this the list
        # opened empty with the snip you were looking at missing from it.
        self._refresh_menu_text()

    # -- marking up the snip on screen -------------------------------------
    def apply_snip_edit(self, image) -> None:
        """Save the marked-up snip everywhere the original went.

        The clipboard, the standing latest file, the lab copy and the history
        copy are all replaced, from the edited image re-encoded with the same
        settings as a fresh snip. A redaction that only reached some of them
        would leave the original sitting in the others.
        """
        if image is None or image.isNull():
            return
        result = imageops.process(image, self.cfg)
        self._last_png = result.png
        self._last_image = result.image
        self._last_disk = (result.disk.data, result.disk.ext)
        self.preview.set_disk_bytes(result.disk.data, result.disk.ext)

        done, problems = [], []
        try:
            clipboard.copy(
                result.png,
                result.image,
                include_dib=self.cfg["clipboard_dib_fallback"],
            )
            done.append("clipboard")
        except Exception as exc:  # noqa: BLE001 - reported to the user
            problems.append(f"clipboard failed ({exc})")

        for key, path in list(self._snip_paths.items()):
            if path.suffix.lower().lstrip(".") != result.disk.ext.lower():
                # The image format was changed in Settings since this snip was
                # taken. Writing new-format bytes under the old extension would
                # make a file nothing can open, so say so instead.
                problems.append(f"{path.name} kept as it was (format changed since)")
                continue
            try:
                storage.write_atomic(path, result.disk.data)
                done.append({"latest": path.name, "lab": f"lab {path.name}",
                             "history": "history"}[key])
            except OSError as exc:
                problems.append(f"could not update {path.name} ({exc})")

        width, height = result.image.size
        line = f"Edit saved ({width} x {height}): " + ", ".join(done)
        if problems:
            line += "   |   " + "; ".join(problems)
        self.preview.set_status(line)
        if "lab" in self._snip_paths:
            # The thumbnail and the viewer read the file; the folder watcher
            # sees the change too, this just makes it immediate.
            self._refresh_snip_list()

    def _save_annotation_prefs(self, prefs: dict) -> None:
        self.cfg["annotation"] = dict(prefs)
        self._persist()

    def stop_lab(self) -> None:
        name = lab.active_name(self.cfg)
        total = lab.count(self.cfg)
        lab.stop(self.cfg)
        self._last_lab_file = ""
        self._persist()
        self._refresh_menu_text()
        self.preview.attach_lab(None, None)
        if name:
            self.tray.showMessage(
                "ShadowSnip",
                f"Lab '{name}' closed with {total} snips. Snips go back to the "
                "normal save folder.",
                build_icon(),
                3000,
            )

    def _fill_labs_menu(self) -> None:
        """Rebuilt each time it opens, so new labs appear without a restart."""
        self.labs_menu.clear()
        names = lab.recent(self.cfg)
        if not names:
            empty = self.labs_menu.addAction("No labs yet")
            empty.setEnabled(False)
            return
        for name in names:
            action = self.labs_menu.addAction(name)
            action.triggered.connect(
                lambda _checked=False, n=name: storage.open_folder(
                    lab.root(self.cfg) / n
                )
            )

    # -- sections and notes ------------------------------------------------
    def set_section(self, path: str) -> None:
        """Point the lab at a section. Everything captured now lands there."""
        if not lab.is_active(self.cfg):
            return
        try:
            cleaned = lab.set_section(self.cfg, path)
        except lab.LabError as exc:
            self.preview.set_status(f"Could not update the lab section: {exc}")
            return
        self.preview.set_section_text(cleaned)
        self._refresh_menu_text()
        where = cleaned or "the root of the lab"
        self.preview.set_status(f"Filing under {where}")

    def ask_section(self) -> None:
        parent = self.preview if self.preview.isVisible() else None
        current = lab.section(self.cfg)
        path, ok = QInputDialog.getText(
            parent,
            "Set section",
            "Where should snips and notes be filed?\n"
            "Separate the levels with / - they become the headings in lab.md.",
            text=current,
        )
        if ok:
            self.set_section(path)

    def move_current_snip(self) -> None:
        """Re-file the snip on screen under the current section.

        The repair for the commonest ordering: snip first, name the section a
        moment later, and the snip is left at the root while the notes about it
        are filed under the breadcrumb.
        """
        if not self._last_lab_file:
            self.preview.set_status(
                "There is no lab snip on screen to move. Take one while a lab "
                "is engaged first."
            )
            return
        where = lab.section(self.cfg)
        try:
            moved = lab.move_snip(self.cfg, self._last_lab_file, where)
        except lab.LabError as exc:
            self.preview.set_status(f"Could not update the lab record: {exc}")
            return
        if moved is None:
            self.preview.set_status(
                f"{self._last_lab_file} is not in this lab's record, so it "
                "could not be moved."
            )
            return
        self.preview.set_status(
            f"{self._last_lab_file} filed under {moved or 'the root of the lab'}"
        )
        self._refresh_menu_text()

    def remove_lab_snip(self, filename: str) -> None:
        """Take a snip out of the running lab, after asking.

        For the wrong snip filed into the lab. The image goes to the lab's
        `removed` folder rather than the recycle bin, so a slip of the mouse on
        this button costs nothing either.
        """
        if not filename or not lab.is_active(self.cfg):
            return
        row = next(
            (r for r in lab.snip_rows(self.cfg) if r["file"] == filename), None
        )
        if row is None:
            self.preview.set_status(f"{filename} is no longer in this lab.")
            self._refresh_menu_text()
            return

        label = f"{row['number']:03d}"
        detail = [f"Snip {label} ({filename})"]
        if row["caption"]:
            detail.append(f"Caption: {row['caption']}")
        if row["notes"]:
            detail.append(
                f"{len(row['notes'])} attached note(s) go with it unless they "
                "are also attached to another snip."
            )
        detail.append(
            "\nThe image is moved to the lab's 'removed' folder and dropped "
            "from lab.md. It is not deleted."
        )
        answer = QMessageBox.question(
            self.preview if self.preview.isVisible() else None,
            "Remove snip from lab",
            "\n".join(detail),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            removed = lab.remove_snip(self.cfg, filename)
        except lab.LabError as exc:
            self.preview.set_status(f"Could not remove the snip: {exc}")
            return
        if removed is None:
            self.preview.set_status(f"{filename} is not in this lab.")
            self._refresh_menu_text()
            return

        if filename == self._last_lab_file:
            self._last_lab_file = ""
            # The file is in removed/ now; an edit must not recreate it.
            self._snip_paths.pop("lab", None)
            self.preview.forget_snip_on_screen()
        notes = removed["notes"]
        extra = f" with note {', '.join(notes)}" if notes else ""
        self.preview.set_status(
            f"Snip {label} removed from lab {lab.active_name(self.cfg)}{extra}. "
            f"It is in {lab.REMOVED_DIR}\\ inside the lab folder."
        )
        self._refresh_menu_text()

    def _on_note_from_preview(self, text: str, attach: bool) -> None:
        """A note typed under the image: filed, attached to the snip on screen if asked."""
        target = []
        if attach and self._last_lab_file:
            target = [self._last_lab_file]
        if self._file_note(text, attach=bool(target), attach_to=target):
            self.preview.clear_note()

    def move_lab_entry(self, key: str, section: str, before: str) -> None:
        """A drag in the outline: re-file a snip or note, or reorder it."""
        if not lab.is_active(self.cfg):
            return
        try:
            moved = lab.move_entry(self.cfg, key, section, before or None)
        except lab.LabError as exc:
            self.preview.set_status(f"Could not rearrange the lab: {exc}")
            return
        kind, _, ident = key.partition(":")
        what = f"snip {ident.split('_', 1)[0]}" if kind == "snip" else f"note {ident}"
        if moved:
            self.preview.set_status(
                f"Moved {what} to {lab.normalise_section(section) or 'the top of the report'}"
            )
        else:
            self.preview.set_status(f"Could not move {what}: it is not in the lab record.")
        # Rebuilt after the drop has finished, not from inside it.
        QTimer.singleShot(0, self._refresh_menu_text)

    def open_lab_md(self) -> None:
        folder = lab.active_folder(self.cfg)
        if folder is None:
            return
        path = folder / lab.INDEX_NAME
        if not path.is_file():
            self.preview.set_status("There is no lab.md yet. It is written with the first snip or note.")
            return
        try:
            storage.open_file(path)
        except OSError as exc:
            self.preview.set_status(f"Could not open lab.md: {exc}")

    def set_snip_list_shown(self, on: bool) -> None:
        """The Snip list button. Remembered, so it stays how you left it."""
        self.cfg["lab_snip_list"] = bool(on)
        self._persist()
        self._refresh_menu_text()

    def open_lab_snip(self, filename: str) -> None:
        target = lab.active_folder(self.cfg)
        if target is None or not filename:
            return
        path = target / filename
        if not path.is_file():
            self.preview.set_status(f"{filename} is no longer in the lab folder.")
            self._refresh_menu_text()
            return
        try:
            storage.open_file(path)
        except OSError as exc:
            self.preview.set_status(f"Could not open {filename}: {exc}")

    def quick_note(self) -> None:
        """The hotkey and tray path: one line, filed into the current section.

        Deliberately single-line. The point of this route is to catch a thought
        without breaking stride; anything longer belongs in the preview
        window's note box, where there is room to write it.
        """
        if not lab.is_active(self.cfg) or not self.cfg["lab_index"]:
            self.tray.showMessage(
                "ShadowSnip",
                "Notes go into a lab. Start one first, and leave the lab "
                "record switched on in Settings.",
                build_icon(),
                4000,
            )
            return

        parent = self.preview if self.preview.isVisible() else None
        where = lab.section(self.cfg) or "the root of the lab"
        text, ok = QInputDialog.getText(
            parent, "Add note", f"Note for {where}:"
        )
        if ok:
            self._file_note(text, attach=False)

    def _file_note(self, text: str, attach: bool = False, attach_to=None) -> bool:
        try:
            entry = lab.add_note(self.cfg, text, attach=attach_to or ())
        except lab.LabError as exc:
            self.preview.set_status(f"Could not save the note: {exc}")
            return False
        if entry is None:
            self.preview.set_status("The note was empty, so nothing was filed.")
            return False
        where = entry["section"] or "the root of the lab"
        detail = f" against {attach_to[0]}" if attach and attach_to else ""
        self.preview.set_status(f"Note {entry['id']} filed under {where}{detail}")
        self._refresh_menu_text()
        return True

    # -- copy on select ----------------------------------------------------
    def toggle_auto_copy(self) -> None:
        if self.autocopy.engaged:
            self.autocopy.release()
            self.cfg["auto_copy"] = False
        else:
            self._engage_auto_copy()
        self._persist()
        self._refresh_menu_text()

    def _engage_auto_copy(self, announce: bool = True) -> None:
        # Every exit from this method refreshes the menu and the preview
        # button. Whether the hook is running is not something the user can
        # see directly -- the toggles are the only report of it -- so a state
        # change that does not reach them leaves the app lying about what it
        # is doing, and a toggle whose first click appears to do nothing.
        try:
            self.autocopy.engage()
        except autocopy_mod.AutoCopyError as exc:
            self.cfg["auto_copy"] = False
            self._refresh_menu_text()
            self.tray.showMessage(
                "ShadowSnip",
                f"Copy on select could not start: {exc}",
                QSystemTrayIcon.MessageIcon.Warning,
                5000,
            )
            return
        self.cfg["auto_copy"] = True
        self._refresh_menu_text()
        if announce:
            gesture = (
                "Highlight text, or double-click a word, and it goes straight "
                "to the clipboard."
                if self.cfg["auto_copy_double_click"]
                else "Highlight text anywhere and it goes straight to the "
                "clipboard."
            )
            self.tray.showMessage(
                "ShadowSnip",
                f"Copy on select is on. {gesture} Consoles, Explorer, VM and "
                "remote-session windows, and password managers are skipped.",
                build_icon(),
                4000,
            )

    def _on_auto_copied(self, text: str, kind: str) -> None:
        if self.cfg["auto_copy_toast"]:
            self.toast.show_clip(text, kind)
        if self.preview.isVisible():
            snippet = text.strip().replace("\n", " ")
            if len(snippet) > 60:
                snippet = snippet[:57] + "..."
            self.preview.set_status(
                f"Copied {len(text)} characters ({kind}): {snippet}"
            )

    def _persist(self) -> None:
        try:
            config.save(self.cfg)
        except OSError as exc:
            self._warn(f"Settings could not be written: {exc}")

    # -- hotkeys -----------------------------------------------------------
    HOTKEYS = (
        ("snip", "hotkey", "Snip from the tray icon"),
        ("note", "note_hotkey", "Add notes from the tray menu"),
    )

    def _on_hotkey(self, name: str) -> None:
        if name == "note":
            self.quick_note()
        else:
            self.request_snip()

    def _register_hotkeys(self, startup: bool = False) -> None:
        """Register every hotkey, reporting each failure on its own.

        One combination being taken by another program is no reason to lose
        the other, so a failure is reported and the loop carries on.
        """
        failures = []
        for name, key, fallback in self.HOTKEYS:
            try:
                self.hotkeys.register(self.qapp, self.cfg[key], name)
            except hotkey_mod.HotkeyError as exc:
                failures.append((exc, fallback))
        if failures and platforms.IS_LINUX and not self.hotkeys.supported:
            # A desktop whose shortcuts cannot be set from here: one message
            # with every shortcut to add, not one warning per hotkey.
            self.tray.showMessage(
                "ShadowSnip",
                "Add these in your desktop's keyboard shortcut settings:\n"
                + "\n".join(str(exc) for exc, _fallback in failures),
                QSystemTrayIcon.MessageIcon.Information,
                10000,
            )
        else:
            for exc, fallback in failures:
                self.tray.showMessage(
                    "ShadowSnip",
                    f"Hotkey not active: {exc}. {fallback}, or pick another "
                    "combination in Settings.",
                    QSystemTrayIcon.MessageIcon.Warning,
                    6000,
                )
        if not startup:
            self._refresh_menu_text()

    # -- snipping ----------------------------------------------------------
    def request_snip(self) -> None:
        if self.busy:
            return
        # Mark-up still waiting to be saved belongs to the snip on screen, so
        # it is saved now, before a new snip takes that snip's place.
        self.preview.flush_edits()
        if _modal_dialog_open():
            # The overlay would be frozen behind the dialog: dimmed, unable to
            # take the drag, unable to take Esc, and `busy` would never clear,
            # so every later snip would be refused too. Point at the dialog
            # instead of starting something that cannot finish.
            self._blocked_by_dialog()
            return
        self.busy = True
        self.autocopy.pause()
        # Otherwise a toast still fading out is part of the frozen screen and
        # ends up inside the snip.
        self.toast.hide()
        # The full-size viewer would otherwise be frozen into the snip.
        self.preview.hide_viewer()
        was_visible = self.preview.isVisible() and not self.preview.isMinimized()
        self._reshow_preview = was_visible
        if was_visible:
            self.preview.hide()
        # Give the compositor a moment to actually remove our own window
        # before the screen is frozen.
        QTimer.singleShot(140 if was_visible else 0, self._begin_snip)

    def _blocked_by_dialog(self) -> None:
        """Say why the snip was refused, and show the window that refused it."""
        self.tray.showMessage(
            "ShadowSnip",
            "Close the open ShadowSnip dialog first. A snip cannot run while "
            "one is waiting for an answer.",
            build_icon(),
            4000,
        )
        modal = QApplication.activeModalWidget()
        if modal is not None:
            modal.raise_()
            modal.activateWindow()

    def _begin_snip(self) -> None:
        try:
            self._start_overlay()
        except Exception as exc:  # noqa: BLE001 - reported, then recovered
            # Anything escaping here would leave `busy` set, and every later
            # snip, tray click and hotkey would be refused until a restart.
            if self.controller is not None:
                try:
                    self.controller.close_all()
                except Exception:  # noqa: BLE001
                    pass
            self._on_cancelled()
            self._warn(f"The snip could not start: {exc}")

    def _start_overlay(self) -> None:
        grabs = capture.grab_all_screens()
        if not grabs:
            self.controller = None
            self._grabs = []
            self.busy = False
            self.autocopy.resume()
            self._warn("No screen could be captured.")
            return
        self._grabs = grabs
        self.controller = SelectionController(grabs, self.cfg["dim_opacity"], self)
        self.controller.selected.connect(self._on_selected)
        self.controller.cancelled.connect(self._on_cancelled)
        self.controller.start()

    def _on_cancelled(self) -> None:
        self.controller = None
        self._grabs = []
        self.busy = False
        self.autocopy.resume()
        # The window was hidden so it would not be in the snip. With no snip
        # taken, put it back rather than leave it looking as if it had closed.
        if getattr(self, "_reshow_preview", False):
            self._reshow_preview = False
            self.preview.open_window()

    def _on_selected(self, rect: QRect) -> None:
        self.controller = None
        grabs, self._grabs = self._grabs, []
        try:
            image = capture.compose_selection(grabs, rect)
            if image is None:
                if self._reshow_preview:
                    self.preview.open_window()
                return
            self._handle_snip(image)
        finally:
            self._reshow_preview = False
            self.busy = False
            self.autocopy.resume()

    def _handle_snip(self, image) -> None:
        result = imageops.process(image, self.cfg)
        self._last_png = result.png
        self._last_image = result.image
        self._last_disk = (result.disk.data, result.disk.ext)

        notes = []
        try:
            clipboard.copy(
                result.png,
                result.image,
                include_dib=self.cfg["clipboard_dib_fallback"],
            )
        except Exception as exc:  # noqa: BLE001 - reported to the user
            notes.append(f"clipboard failed ({exc})")

        latest_path: Path | None = None
        lab_path: Path | None = None
        history_path: Path | None = None
        try:
            latest_path = storage.save_latest(
                result.disk.data, result.disk.ext, self.cfg
            )
        except OSError as exc:
            notes.append(f"could not write to the save folder ({exc})")

        # The second destination gets its own attempt. A lab can sit on a
        # different drive from the save folder, and a full or read-only save
        # folder is no reason to also lose the copy filed into the lab.
        in_lab = lab.is_active(self.cfg)
        try:
            if in_lab:
                # The lab folder is the history for as long as it is engaged,
                # so the same snip does not land in three places at once.
                lab_path = lab.save(result.disk.data, result.disk.ext, self.cfg)
            else:
                history_path = storage.save_history(
                    result.disk.data, result.disk.ext, self.cfg
                )
        except (OSError, lab.LabError) as exc:
            notes.append(
                f"could not write to the {'lab' if in_lab else 'history folder'} "
                f"({exc})"
            )

        self._last_lab_file = lab_path.name if lab_path is not None else ""
        self._snip_paths = {
            key: path
            for key, path in (("latest", latest_path), ("lab", lab_path), ("history", history_path))
            if path is not None
        }
        caption_cb = None
        if lab_path is not None and self.cfg["lab_index"] and self.cfg["lab_caption"]:
            caption_cb = self._caption_setter(lab_path.name)

        status = self._status_line(result, latest_path, lab_path, notes)
        if self.cfg["show_preview"]:
            self.preview.show_snip(
                image=image,
                disk_bytes=result.disk.data,
                ext=result.disk.ext,
                latest_path=latest_path,
                status=status,
                copy_again=self._copy_again,
                folder_path=lab_path.parent if lab_path else None,
                caption_cb=caption_cb,
            )
        else:
            self.tray.showMessage(
                "ShadowSnip", status, build_icon(active=lab_path is not None), 3000
            )

        if lab_path is not None:
            self._refresh_menu_text()

    def _caption_setter(self, filename: str):
        def apply(text: str) -> bool:
            done = lab.set_caption(self.cfg, filename, text)
            if done:
                self._refresh_menu_text()
            return done

        return apply

    def _status_line(self, result, latest_path, lab_path, notes) -> str:
        width, height = result.source_size
        out_w, out_h = result.image.size
        size_part = f"{width} x {height}"
        if (out_w, out_h) != (width, height):
            size_part += f" -> {out_w} x {out_h}"
        saving = (
            100 - (len(result.png) * 100 / result.raw_bytes)
            if result.raw_bytes
            else 0
        )
        parts = [
            size_part,
            f"{imageops.human_size(result.raw_bytes)} raw -> "
            f"{imageops.human_size(len(result.png))} on the clipboard "
            f"({saving:.0f}% smaller)",
        ]
        if latest_path is not None:
            parts.append(f"saved to {latest_path}")
        if lab_path is not None:
            parts.append(f"lab {lab.active_name(self.cfg)}: {lab_path.name}")
        if notes:
            parts.append("; ".join(notes))
        return "   |   ".join(parts)

    def _copy_again(self) -> None:
        if not self._last_png or self._last_image is None:
            return
        clipboard.copy(
            self._last_png,
            self._last_image,
            include_dib=self.cfg["clipboard_dib_fallback"],
        )

    # -- settings ----------------------------------------------------------
    def open_settings(self) -> None:
        dialog = SettingsDialog(self.cfg)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        new_cfg = dialog.values()
        new_cfg["active_lab"] = self.cfg.get("active_lab", "")
        if lab.is_active(self.cfg) and lab.root(new_cfg) != lab.root(self.cfg):
            self._warn(
                "Stop the active lab before changing its root folder or the "
                "save folder. This keeps one lab from being split across two "
                "locations."
            )
            return
        hotkeys_changed = any(
            new_cfg[key] != self.cfg[key] for _, key, _ in self.HOTKEYS
        )
        if hotkeys_changed and not self._replace_hotkeys(new_cfg):
            return
        self.cfg = new_cfg
        try:
            config.save(self.cfg)
            self.cfg = config.load()
        except OSError as exc:
            self._warn(f"Settings could not be written: {exc}")
        self.autocopy.configure(self.cfg)
        if self.cfg["auto_copy"] and not self.autocopy.engaged:
            self._engage_auto_copy(announce=False)
        elif not self.cfg["auto_copy"] and self.autocopy.engaged:
            self.autocopy.release()
        self._refresh_menu_text()

    def _replace_hotkeys(self, new_cfg: dict) -> bool:
        """Replace changed hotkeys atomically, restoring the old ones on error."""
        desired = {name: new_cfg[key] for name, key, _ in self.HOTKEYS}
        if len(set(desired.values())) != len(desired):
            self._warn("The snip and quick-note hotkeys must be different.")
            return False

        changed = [
            name for name, key, _ in self.HOTKEYS if new_cfg[key] != self.cfg[key]
        ]
        previous = {name: self.hotkeys.spec(name) for name in changed}
        for name in changed:
            self.hotkeys.unregister(name)

        registered: list[str] = []
        try:
            for name, key, _ in self.HOTKEYS:
                if name in changed:
                    self.hotkeys.register(self.qapp, desired[name], name)
                    registered.append(name)
        except hotkey_mod.HotkeyError as exc:
            for name in registered:
                self.hotkeys.unregister(name)
            restore_failures = []
            for name in changed:
                if not previous[name]:
                    continue
                try:
                    self.hotkeys.register(self.qapp, previous[name], name)
                except hotkey_mod.HotkeyError:
                    restore_failures.append(name)
            detail = " Previous hotkeys were restored."
            if restore_failures:
                detail = " Some previous hotkeys could not be restored."
            self._warn(f"Hotkeys were not changed: {exc}.{detail}")
            return False
        return True

    def _warn(self, message: str) -> None:
        QMessageBox.warning(None, "ShadowSnip", message)

    def quit(self) -> None:
        self.preview.flush_edits()
        self.toast.hide()
        self.autocopy.release()
        if hasattr(self.hotkeys, "release_all"):
            # Linux: the shortcut lives in the desktop's settings and should
            # stay there, so pressing it can start ShadowSnip again.
            self.hotkeys.release_all()
        else:
            self.hotkeys.unregister()
        self.tray.hide()
        self.qapp.quit()


def _modal_dialog_open() -> bool:
    """True while one of ShadowSnip's own dialogs is waiting for an answer.

    A Qt modal dialog blocks input to every other window in the application,
    and the selection overlay is one of those windows. Freezing the screen
    behind Settings therefore produces the worst possible failure: the desktop
    dims, the drag does nothing, Esc goes to the dialog rather than the
    overlay, and because neither `selected` nor `cancelled` ever fires, `busy`
    stays set and copy on select stays paused until ShadowSnip is restarted.

    A module-level function rather than a method so the guard can be tested
    without a QApplication.
    """
    return QApplication.activeModalWidget() is not None


def build_icon(size: int = 64, active: bool = False) -> QIcon:
    """Draw the app icon so it ships without any image assets.

    `active` adds a badge dot, so a lab that has been left engaged is visible
    at a glance instead of quietly collecting screenshots for three days.

    Several sizes are rendered into one QIcon so Windows can pick a crisp
    pixmap for the taskbar, alt-tab and title bar instead of scaling one.
    """
    icon = QIcon()
    for edge in (16, 24, 32, 48, 64, 256):
        icon.addPixmap(_draw_icon_pixmap(edge, active))
    return icon


def _draw_icon_pixmap(size: int, active: bool) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(24, 24, 28))
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 10, 10)

    marquee = QPen(QColor(235, 235, 240))
    marquee.setWidth(max(2, size // 16))
    marquee.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(marquee)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inset = size // 5
    painter.drawRect(inset, inset, size - inset * 2, size - inset * 2)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(10, 99, 196))
    dot = size // 5
    painter.drawEllipse(size - inset - dot // 2, size - inset - dot // 2, dot, dot)

    if active:
        badge = size // 4
        painter.setBrush(QColor(46, 204, 113))
        painter.drawEllipse(size - badge - 3, 3, badge, badge)

    painter.end()
    return pixmap
