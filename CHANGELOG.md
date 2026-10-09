# Changelog

## Latest: 0.7.6

**Fixed**: removing a snip could leave the lab half-changed if saving the lab
record failed (a full disk, a permissions error). The image had already moved
to `removed/` while `lab.json` still listed it in the lab. The image is now put
back, and the message says nothing was removed. Found in an external review of
0.7.5.

### 0.7.5 in brief

**Added**: shift-click or Ctrl-click in the snip list to select several snips
and remove them together, after one question. The button says how many.

**Added**: in the full-size view, **Copy** and **Remove from lab** buttons,
the same two on the right-click menu, and Ctrl+C and Delete. A copy is
confirmed in the view itself, where you are looking.

### 0.7.4 in brief

**Fixed**: after a snip the window could fail to appear on a setup with two
differently scaled screens (a laptop beside a TV at 300%). The snip worked and
reached the clipboard, but the window opened off every screen or as a small
minimised strip above the taskbar. It now always opens restored, on the screen
under the pointer, and shrunk to fit if that screen is smaller than the window.

### 0.7.3 in brief

**Restored**: the caption box, the note box, **Add note** and **Attach to this
snip** under the snip in the preview window, for the snip on screen, as before
0.7.0. The caption box is shown locked: hover to read a long caption in full,
double-click to write or edit it, Enter saves.

**Removed**: the caption and note fields in the lab panel beside the list.
Under the selected snip's thumbnail there is now just **Open** and **Remove
from lab**.

**Restored**: the **Offer a caption box** setting.

### 0.7.2 in brief

**Changed**: the pen, highlighter and eraser no longer carry an icon badge by
the pointer; their footprint is enough. Crop and redact keep theirs.

**Added**: right-click a redaction to switch it between black out and blur.

**Added**: right-click the snip with no tool in hand for **Save as...** and
**Copy**.

### 0.7.1 in brief

Fixes from the first Windows test of the mark-up tools.

**Changed**: the pen's colours are in six rows by family, each light to dark;
the highlighter's are in spectrum order.

**Changed**: left-click picks a tool up or puts it down, right-click opens its
options. Esc also puts the tool down, which is how redaction is stopped.

**Added**: over the screenshot, the pointer becomes the selected tool at its
real size, with a badge showing which tool it is. Hovering a tool explains it.

**Fixed**: the tool strip only appeared after the first snip. It is there from
launch, greyed out until there is a snip.

### 0.7.0 in brief

**Added**: mark up a snip right in the preview window. A tool strip above the
image has a **pen** (30 colours, adjustable width), a see-through
**highlighter** (6 colours, adjustable width), an **eraser** that removes a
whole mark, **crop**, and **redact** with a choice of **blur** or **black out**,
plus a round **undo** button (or Ctrl+Z). Click a tool again for its options.

**Added**: edits are saved as you go. The edited snip replaces the clipboard
copy, `latest.png`, the lab copy and the history copy, so a redaction never
leaves the original behind in ShadowSnip's own files.

**Changed**: the caption box and the note box under the image are gone. Captions
and notes are edited in the lab panel, where they are shown locked: hover to
read a long one in full, double-click to edit.

### 0.6.0 in brief

**Added**: ShadowSnip runs on **Linux** (X11; Kali's default Xfce desktop is
X11) as well as Windows. Same app, same labs, outline and preview, from one
codebase. On Xfce the Ctrl+Shift+S snip shortcut is set up for you; copy on
select uses X11's own selection, so no keystrokes are sent at all.
`./install.sh` installs it with a menu entry and, optionally, autostart.

**Added**: every version tag now builds both a Windows .exe and a Linux
download on GitHub automatically, after the tests pass on both systems.

The Windows code paths were moved behind a small switch but not changed.

### 0.5.1 in brief

Fixes for three issues found in an external code review of 0.5.0.

**Fixed**: a lab name could write outside the labs folder. A name such as
`..\..\Documents\other` placed snips, `lab.json` and `lab.md` elsewhere,
possibly over existing files. Lab names must now be one plain folder name and
anything else is refused with the reason.

**Fixed**: a triple-click could copy the word and then the line. Each run of
clicks now copies once; a double-click's word copy waits out the double-click
speed in case a third click is coming.

**Fixed**: changing the image format could lose the latest snip if the new
file failed to write. The new file is written before the old one is removed.

### 0.5.0 in brief

ShadowSnip is now described for what it is mostly for: capturing evidence
during a penetration test and turning it into the writeup.

**Added**: an **Outline** tab in the lab panel showing `lab.md` as a tree of
sections, snips and notes. Drag a snip or note onto a section to file it
there, or above or below another entry to move it. A snip takes its notes
with it.

**Added**: a **Preview** tab that shows `lab.md` rendered as the report will
read, screenshots scaled to fit, with a button to open the file itself.

**Changed**: the blue edge around the selected snip is thinner.

### 0.4.8 in brief

**Changed**: starting ShadowSnip by hand now opens its window straight away
instead of going quietly to the tray. Add `--tray` to the startup shortcut if
you want it to start hidden at login.

**Changed**: the selected snip in the lab list is outlined in blue, matching
the thumbnail's hover, instead of being filled with the system accent colour
(which was red on some machines).

**Changed**: the small thumbnails in the list rows are gone; the selected
snip's preview is right underneath. Hover previews stay.

**Added**: the version is shown bottom-right in the window.

### 0.4.7 in brief

**Added**: the lab snip list shows a thumbnail on every row, and hovering a
row shows a bigger preview with how the snip was filed.

**Added**: the selected snip is shown larger under the list, with its caption
and notes editable right there and a **Save changes** button. Empty a note and
save to remove it; type in the new box to add one. Moving to another snip
saves your edits first.

**Added**: click the thumbnail, press **Expand**, double-click a row or press
Space on the list to see a snip full size. Left and Right step through the
lab, and the list follows.

### 0.4.6 in brief

**Changed**: the lab button turns amber and reads **Stop lab: name** with a
dot while a lab is running, so it is obvious at a glance that snips are being
filed into a lab.

**Fixed**: the lab snip list now watches the lab folder and updates by itself
the moment a snip, removal, caption or note lands, with no refresh needed.
Starting a lab while a snip was on screen filed that snip without showing it
in the list; it shows now.

### 0.4.5 in brief

**Added**: a **Snip list** button on the toolbar while a lab runs, to show or
hide the lab snip list. Hidden, the image gets the full width. Your choice is
remembered between runs.

**Fixed**: the Open button under the snip list sat hard against the left
edge. Open and Remove from lab now share the row equally, inset from the image.

### 0.4.4 in brief

**Added**: a **Lab snips** list beside the image while a lab is running,
newest first. Each row shows the number, time, section, caption and attached
notes, and the box underneath spells out how the selected snip was filed. The
snip on screen is bold and marked with `*`.

**Added**: **Remove from lab**, for the wrong snip filed into a lab. It asks
first, then moves the image to a `removed` folder inside the lab (nothing is
deleted) and takes it out of `lab.md`. Notes attached only to that snip go
with it. The next snip reuses its number, so the sequence has no gap.

**Fixed**: clicking the taskbar pin, or starting ShadowSnip again, while it
was already running in the tray did nothing. It now brings the window up.

**Fixed**: a snip could end by itself partway through a drag across, or near,
the second monitor. Windows was taking the mouse capture away as the pointer
crossed onto the other screen's overlay, and that was being read as letting go
of the button.

---

## [0.7.6] - 2026-10-09

### Fixed
- `lab.remove_snip` moves the image before saving the record. When
  `_save_state` fails and the record on disk still lists the snip
  (`_record_lists`), the image is moved back and the error ends "Nothing was
  removed." If moving it back fails too, the error says where the image is.
  When only the `lab.md` render fails, the record is already right, so the
  move stands and the next change re-renders `lab.md`.

### Tests
- A failed `lab.json` write leaves the image and the record as they were; a
  failed `lab.md` render keeps the removal; when the image cannot be put back,
  the error names its place in `removed/`.

---

## [0.7.5] - 2026-10-09

### Added
- The snip list uses extended selection (shift-click a range, Ctrl-click to
  add or drop one). `LabSnipsPanel.selected_files()` returns every selected
  snip, newest first; `remove_requested` now carries a list. A refresh keeps
  the whole selection, not just the current row. The button reads
  **Remove N from lab** when N > 1.
- `ShadowSnipApp.remove_lab_snips()` asks once for all of them, listing up to
  12 by number and caption, then removes each through `lab.remove_snip()`, so
  each stays recoverable in `removed/`. A failure on one is reported and the
  rest still go. `remove_lab_snip()` remains for one file.
- `SnipViewer`: **Copy** and **Remove from lab** buttons, a right-click menu
  with both (`context_actions()`), Ctrl+C and Delete. Removing moves the view
  to the next snip. The confirmation opens over the viewer, not behind it.
- `ShadowSnipApp.copy_lab_snip()` copies a lab snip from its file.
  `imageops.clipboard_png_from_file()` re-encodes the saved file as PNG
  without processing it again, since it was scaled and reduced when taken.
  `SnipViewer.flash()` shows the result in place of the key hints.

### Tests
- Extended selection; a real shift-click selects the range; several removed
  in one request; the button text; a refresh keeps the selection; the viewer's
  buttons and menu; the message and the hints coming back; several removed
  after one question and all landing in `removed/`; No removes nothing; a lab
  snip copied from its file as a PNG of the right image.

---

## [0.7.4] - 2026-10-08

### Fixed
- The window could open off every screen or minimised after a snip. The snip
  path (`show_snip`) never placed the window, only a tray click or relaunch
  did, and only the first time. Both now go through `PreviewWindow._bring_up`:
  restore if minimised, show, and centre on the pointer's screen when it is
  the first showing or the title bar is on no screen (`_on_a_screen`).
- `center_on_cursor_screen` shrinks the window to fit the screen (never below
  its minimum size) and never places the title bar above or left of it. The
  default 1100 x 760 was taller than a laptop screen at 150%.

### Tests
- A window moved off every screen comes back on a relaunch and after a snip; a
  minimised window is restored; an oversized window is shrunk to fit with its
  title bar on the screen. Run at 100% and 300% scaling.

---

## [0.7.3] - 2026-10-07

### Fixed
- 0.7.0 removed the wrong set of fields. The boxes under the image are back
  and the editors in the lab panel are gone, which was the intent.

### Restored
- `preview.py`: the caption field (now a `ClickToEditLine`: locked, full text
  in a hover box when it overflows, double-click to edit, locked again on
  leaving it; saved on Enter or leaving, and only when it changed), the note
  box, **Add note**, **Attach to this snip**, Ctrl+Enter, and the `note_added`
  signal. `app._on_note_from_preview` files the note, attached to the snip on
  screen unless unticked.
- The **Offer a caption box after each snip in a lab** setting
  (`lab_caption`), enabled only with the lab record.

### Removed
- `labsnips.py`: the caption editor, the note editors, the new-note box,
  **Save changes**, `details_saved`, the save-on-switch logic and
  `ClickToEditNote`. The detail view is the thumbnail, the filing line,
  **Expand**, **Open** and **Remove from lab**.
- `app.save_snip_details` and the edit flush when a lab stops or the window
  closes, which only existed for the panel editors.

### Tests
- The panel has no editable fields; moving between snips changes the
  thumbnail; the boxes under the image exist and follow the lab; the caption
  starts locked, unlocks on double-click and locks on leaving; Enter saves once
  and locks; a long caption shows in full on hover; **Add note** emits the text
  and the attach choice; a caption and an attached note typed under the image
  land in the lab end to end.
- The pointer tests read pixels at the display's scaling: `grab()` returns
  physical pixels, so at 300% the logical point was three times too close to
  the corner and read the white snip. Checked at 100%, 150%, 200% and 300%.

---

## [0.7.2] - 2026-10-07

### Changed
- The icon badge beside the pointer is drawn for crop and redact only
  (`annotate.BADGED_TOOLS`), whose cursor is just guide lines. The pen,
  highlighter and eraser show their footprint alone.

### Added
- Right-click on a redaction, with or without a tool in hand: **Black out this
  redaction** / **Blur this redaction**, the current mode ticked. The switch is
  a `Restyle` operation, so undo switches it back, and choosing the mode it
  already has adds nothing. With redactions stacked, the topmost one under the
  pointer is the one changed; erased ones are skipped.
- Right-click on the snip with no tool in hand: **Save as...** and **Copy**.
  Both, and the toolbar buttons of the same names, save any pending mark-up
  first, so they always give the snip as it looks. With a tool in hand, a
  right-click away from a redaction offers nothing, so it never interrupts
  drawing; off the screenshot it offers nothing either.

### Tests
- Badges only for crop and redact, and none drawn beside the pen; switching a
  redaction and undoing it; the topmost visible redaction found; the menu's
  rows on a redaction, with no tool, both together, with a tool elsewhere and
  off the snip; Save as from the menu writing the edited snip.

---

## [0.7.1] - 2026-10-07

### Changed
- Pen palette rebuilt as six rows of five, one colour family per row (greys,
  reds, oranges and yellows, greens, blues, purples), each row running light
  to dark. The popup grid is five wide to match. Highlighter colours are in
  spectrum order: yellow, orange, pink, purple, blue, green. A stored colour
  no longer in the palette falls back to the default.
- Tool strip clicks: left-click picks a tool up, left-clicking it again puts
  it down; right-click opens the options (pen and highlighter: width and
  colour; redact: blur or black out) and picks the tool up. A tool without
  options says so on right-click. One tool at a time, shown in blue.
  Previously a second left-click opened the options, which meant redaction
  could not be put down without a third click.
- Esc puts the tool in hand down; with no tool in hand it closes the window
  as before.

### Added
- The tool drawn on the snip: over the screenshot the pointer is replaced by
  the tool's footprint at its real size (a pen dot as wide as the line, the
  highlighter's square tip in its colour, the eraser's reach, or crosshair
  guides for crop and redact), outlined dark and light to show on any
  background, with a badge carrying the tool's icon; the redact badge shows
  whether black out or blur is armed. Clipped to the screenshot; outside it
  the normal arrow returns.
- Hover help: each tool's tooltip names it, says what it does and which
  click does what, and hovering a tool also shows that in the hint beside the
  strip.

### Fixed
- The tool strip was hidden until the first snip. It is shown from launch,
  with the tools and undo faded and disabled and the hint "Take a snip to mark
  it up." until there is a snip. Undo is faded whenever there is nothing to
  undo.

### Tests
- Left-click picks up and puts down; one tool at a time; right-click opens
  options and picks the tool up; no popup for tools without options; a
  left-click closes an open popup; hover help in tooltip and hint; the strip
  shown but unusable without a snip; palette rows light to dark and one
  family each; highlighters in spectrum order; the tool cursor only over the
  screenshot, at the real size, drawn at the pointer and not without a tool;
  the strip present from the start; Esc putting a tool down before closing.

---

## [0.7.0] - 2026-10-07

### Added
- `annotate.py`: marking up the snip on screen.
  - **Pen**: 30 colours in rows by hue, 1 to 24 px. **Highlighter**: six bright
    colours, 6 to 48 px, drawn see-through (alpha 110) and as one path, so
    overlapping segments do not stack into blotches. Both options popups show
    the width in px, a sample stroke at that width and colour (the highlighter's
    over sample text), a slider, and the colours as rounded squares. The
    current colour shows on the tool's icon.
  - **Eraser**: drag across a mark to remove the whole pen line, highlight or
    redaction box; one drag is one undo step.
  - **Crop**: drag the area to keep. Crops can be repeated; undo steps back.
  - **Redact**: drag over what to hide, as **Black out** (solid black, the
    original pixels replaced) or **Blur** (the region shrunk 14 times and
    scaled back, which destroys text detail but can leave layout visible). The
    popup says which to use for passwords and hashes.
  - **Undo**: a round arrow button at the end of the strip, and Ctrl+Z (a
    text box with focus keeps its own Ctrl+Z).
  - Clicking a tool picks it up, clicking it again opens its options, and
    clicking once more puts it down. A new snip starts with no tool selected.
    Colours, widths and the redact mode are remembered (`annotation` in the
    config, checked by `annotate.sanitise_prefs`).
- Every mark is an operation on top of the original capture; the saved image
  is rendered fresh from the original each time, so edits never degrade
  quality and undo can go all the way back. Stroke widths are converted from
  screen pixels, so a line is saved as thick as it looked.
- `app.apply_snip_edit()`: half a second after the last change, the edited
  snip is re-encoded like a fresh snip and replaces every copy it was saved to:
  the clipboard, the latest file, the lab file and the history file. A copy
  whose format no longer matches Settings is left alone and reported. Pending
  edits are saved before a new snip starts, when the window closes and on quit.
  A lab snip removed while on screen is not recreated by a later edit.
- Lab panel: the caption and the notes of the selected snip are shown locked.
  Hovering shows the full text when it does not fit the box; a double-click
  unlocks the field, and leaving it locks it again with the edit kept until
  **Save changes**. Enter in the caption saves and locks. A long caption opens
  at its start.

### Changed
- The caption box and the note box (with **Add note** and **Attach to this
  snip**) under the image are removed; the section row stays. Notes for a snip
  are added in the lab panel's **Add a note to this snip** box, and Ctrl+Enter
  now saves the lab panel's edits.
- Settings no longer has **Offer a caption box**, which controlled the removed
  box. The stored value is kept so older configs still load.

### Verified
- Live under X11 with real mouse input: the pen stroke, a black-out and an undo
  each reached the saved file within a second.

### Tests
- `test_annotate.py`: pen colour, highlighter transparency, black out leaving
  only black, blur destroying detail, a redaction covering earlier strokes,
  crop size, erase and undo, the eraser reaching boxes and missing empty
  space; canvas gestures for each tool, widths following the screen, crop
  mapping, clicks not counting as drags, one eraser drag being one step; the
  tool strip's select, options and put-down cycle, colour and width changes,
  the palettes, redact mode, undo state, and stored-prefs checking.
- `test_edit_saving.py` (through the real app): edits wait then save; a
  redaction reaches the lab, latest, clipboard and history copies; a crop
  changes the saved size and Save as; a new snip saves pending edits to the
  old one first; a removed lab snip is not recreated; tool settings persist;
  a new snip has no tool selected.
- Lab panel: fields start locked, double-click unlocks and leaving locks, long
  captions and notes show in full on hover, Enter saves and locks.

---

## [0.6.0] - 2026-10-05

### Added
- **Linux support (X11).** One codebase; `platforms.py` picks the Windows or
  Linux implementation of the two things that genuinely differ, and nothing
  else tests the platform for them:
  - `hotkey_linux.py`: global hotkeys owned by the desktop. The shortcut runs
    ShadowSnip with `--snip` or `--note`, and the running copy takes the
    request over its local socket. On Xfce the shortcuts are written through
    `xfconf-query` and take effect immediately; a combination Xfce already
    uses for something else is reported as taken and never overwritten. A
    ShadowSnip shortcut is recognised narrowly (this install's exact command,
    or one naming ShadowSnip and ending in its flag), so another tool's
    shortcut is never replaced or removed. Shortcuts stay after quitting, so
    the key also starts ShadowSnip. On other desktops the exact command to bind
    is shown once, in a single message.
  - `autocopy_linux.py`: copy on select from the X11 primary selection, copied
    to the clipboard once it has been still for 300 ms. No hook and no
    synthetic keystroke, so no SIGINT risk in a terminal. The password-manager
    list (with Linux names such as KeePassXC, Bitwarden and pinentry), **Never
    copy from**, dedupe and the pause during a snip carry over. It fails closed
    like the Windows version: without `xprop` it will not start, and a
    selection whose program cannot be identified is not copied.
- `--note` on the command line (for the Linux quick-note shortcut), handed to
  a running copy like `--snip`.
- A startup warning on a Wayland session, where screen capture is not
  allowed and snips would come out black.
- `install.sh`: installs a release binary or a clone (into its own `.venv`),
  with a `shadowsnip` command, a menu entry, `--autostart` for the tray at
  login, and `--uninstall`. Writes only inside your home folder, needs no sudo,
  and names any missing system packages (`libxcb-cursor0`, `x11-utils`).
- `.github/workflows/build.yml`: tests on Windows and Linux on every push and
  pull request; on a `v*` tag, builds both with PyInstaller and attaches
  `ShadowSnip-<tag>-windows.exe` and `ShadowSnip-<tag>-linux.tar.gz` to the
  release.
- `make_icon.py` also writes `shadowsnip.png` for the Linux menu entry.
- BUILD.md has Linux build steps and a five-minute check to run on Windows
  before tagging a release.

### Changed
- Settings live in `~/.config/shadowsnip/` on Linux (XDG), unchanged on
  Windows (`%APPDATA%\ShadowSnip`).
- `ShadowSnip.spec` embeds the .ico on Windows only; Linux binaries carry no
  icon, and the menu entry points at the .png instead.
- The Windows hotkey and copy-on-select modules are unchanged; `app.py` and
  `settings_dialog.py` now take them from `platforms.py`.

### Verified on Linux
- Under a real X server (Xvfb, Openbox, a system tray): a plain launch opens
  the window, a second launch hands off, `--snip` snips and the PNG reaches
  the clipboard, and copy on select copies a terminal selection and respects
  **Never copy from**. `install.sh` installs and uninstalls cleanly in a
  scratch home folder, and the PyInstaller build on Linux runs and snips.

### Tests
- `test_linux_support.py`: platform choice, Xfce accelerator spelling, quoted
  launch commands, registering, taken combinations left alone, older
  ShadowSnip shortcuts replaced, changing a hotkey removing only our old one,
  quitting leaving the shortcut, other desktops told the command, which
  shortcut commands count as ours, copying the primary selection, dedupe,
  password managers and **Never copy from**, our own windows, blank
  selections and pausing, the settle timer, refusing without a primary
  selection or without `xprop`, not copying from an unidentified program,
  reading the front window through `xprop`, config folders on both systems,
  and the Wayland warning.

---

## [0.5.1] - 2026-10-01

Three issues from an external static review of v0.5.0 (commit `811c769`),
each confirmed and fixed with regression tests.

### Fixed
- **Lab names could escape the labs root (path traversal).** `folder()` joined
  the root and the name, and `start()` only trimmed whitespace, so `..`,
  separators, an absolute path or a drive-relative `C:name` sent captures and
  a freshly written `lab.json` and `lab.md` outside the labs folder, replacing
  whatever was there. `lab.name_problem()` now admits only a single plain
  folder name: no `\` or `/`, no `.` or `..`, none of `< > : " | ? *` or
  control characters, no trailing dot, not a Windows device name (`CON`,
  `NUL`, `COM1` and so on, with or without an extension), at most 120
  characters. `folder()` raises `LabError` with that reason, and as a second
  check refuses any path that does not resolve to a direct child of the labs
  root (a symlink or junction pointing elsewhere, for instance). A stored
  `active_lab` that fails the check, from a hand-edited or older config, now
  reads as no lab at all, rather than as a lab writing somewhere unexpected.
  The **Open a lab** menu builds its paths from the root directly.
- **A triple-click could send two copies.** The second click scheduled a word
  copy 60 ms later and the third scheduled a line copy, and nothing cancelled
  the first. Click copies now go through one restartable timer: a press that
  continues a run holds the pending copy, its release reschedules it with the
  new kind, and a drag, `pause()` or `release()` cancels it. Because a third
  click usually lands after 60 ms, cancelling alone was not enough, so a
  double-click now waits out the double-click interval (Windows' setting,
  500 ms by default) before copying the word. A triple-click, the most a run
  can have, still copies after the 60 ms settle. One copy per run, at the cost
  of a word copy arriving about half a second later.
- **Switching format could lose the latest snip.** `save_latest()` deleted
  `latest.*` files of other formats before writing the new one; if that write
  failed, neither remained. It now writes first and removes the stale
  siblings only after the write succeeded.

### Tests
- `test_review_fixes.py`: 18 names that could leave the root are refused and
  write nothing, ordinary names (including `con-test` and `a.b`) still work, a
  bad stored name means no lab, a symlinked lab folder pointing outside is
  refused, and the reason is reported; a double-click waits the interval, a
  triple-click copies only the line, the third press holds the pending copy, a
  drag and a pause cancel it; and the old latest file survives a failed write
  while a successful one still removes it.

---

## [0.5.0] - 2026-09-29

A minor version rather than a patch: the lab panel is now where a report is
arranged and read, not only where snips are listed, and the project is
positioned around pentest writeups.

### Added
- **Outline** tab (`labsnips.OutlineTree`): `lab.md` as a tree. Sections are
  bold with a snip count, nested as their breadcrumbs are; the top of the
  report is its own node; snips show number and caption with the hover
  preview; notes rendered under a snip are its children; loose notes stand on
  their own. The current section appears even when empty, so it can take a
  drop.
- Drag and drop in the outline. Onto a section: the end of that section.
  Above an entry: just before it. Onto or below an entry: just after it. Onto
  a note under a snip: after that snip. Onto empty space: the top of the
  report. Sections themselves are not draggable. The tree never moves an item
  itself; it asks, `app.py` calls `lab.move_entry()`, and the tree is rebuilt
  from the saved record, so it always shows what `lab.md` now says.
  Collapsed sections stay collapsed across rebuilds. Clicking a snip, or a
  note under one, selects that snip in the editor below, and selecting a snip
  in the Snips tab selects it in the outline.
- **Preview** tab (`labsnips.MarkdownPreview`): `lab.md` rendered by Qt, with
  images loaded at the panel's width so a full-screen capture fits. It is only
  re-rendered when the tab is showing. The snip editor hides on this tab to
  give the report the full height. **Open lab.md** opens the file in your
  default program.
- `lab.outline()` describes the report's shape; `lab.move_entry()` re-files a
  snip or note, or places it before another entry. A snip carries the notes
  rendered beneath it. The first manual move pins the section order into
  `section_order` in `lab.json`, and `render_index` honours it, so moving the
  first snip out of a section does not reorder the report's headings.
- README opens with what ShadowSnip is for (evidence capture and writeups for
  penetration testing) and a **Why it exists** section. ROADMAP sets v0.6 as
  the pentest report release: findings with severity, redaction, export,
  command output as text, methodology sections and annotation.

### Changed
- The selected-row edge in the lab lists is 1 px instead of 1.6 px.

### Tests
- `test_lab_outline.py`: the outline follows the report, an empty current
  section is offered, moving to a section, snips taking their notes,
  reordering within a section, a foreign `before` key falling back to the end,
  section order surviving the first section being emptied, moving loose
  notes, and refusals without a record or entry.
- `test_outline_tree.py`: the tree mirrors the report, every drop rule,
  no-op and section drags ignored, collapsed state and selection surviving a
  rebuild, clicks naming the snip, the preview scaling images to fit, the three
  tabs, and the Preview tab hiding the editor.
- End to end: a move in the outline lands in `lab.md` and the tree follows.

---

## [0.4.8] - 2026-09-29

### Changed
- A normal launch (double-clicking the .exe, the Start menu, a taskbar pin)
  opens the window once the tray icon is up. `--tray` starts in the tray
  without it, for the run-at-login shortcut; `--snip` still goes straight to a
  snip. BUILD.md shows where to add `--tray`.
- The lab snip list draws its own selection: a rounded 1.6 px blue edge
  (`#2f8cff`) with a faint blue wash, the same blue as the enlarged
  thumbnail's hover border, which is now 2 px to match. The Windows 11 style
  paints item selection in the system accent colour and ignores stylesheets
  for it, so the list is given the Fusion style and its highlight colour is
  pinned. That Fusion style is shared and owned by the application: a style
  freed before the widget using it crashes on exit.
- Row thumbnails removed from the list. At 56 x 34 they were too small to
  read, and the selected snip is shown larger just below. The hover preview
  and the thumbnail cache for the large preview remain.

### Added
- `ShadowSnip vX.Y.Z` bottom-right of the preview window, beside the status
  line, read from `config.APP_VERSION`.

### Tests
- No row thumbnails; the list's highlight colour is pinned rather than the
  platform's; the version label matches `config.APP_VERSION`.

---

## [0.4.7] - 2026-09-28

### Added
- `labsnips.py`, a new flat module holding the lab snip list, the selected
  snip's editor and the full-size viewer. The preview window embeds it; all
  writes still go through `app.py` into `lab.py`, so the panel is tested with
  plain dictionaries.
- Row thumbnails (56 x 34) in the snip list, decoded straight to their display
  size by `QImageReader` and cached per file until the file changes, so the
  list does not get slower as a lab grows.
- A hover tooltip on every row with a preview up to 380 x 260 and the snip's
  file, section, time, caption and notes.
- Under the list, in a splitter you can drag: the selected snip at 150 px
  high, its filing line, an **Expand** button, the caption, one box per
  attached note, and a box for a new note. **Save changes** (or Enter in the
  caption) writes them; it reads **Saved** and is disabled when there is
  nothing to save. Emptying a note and saving removes it to the `removed` list
  in `lab.json`. Unsaved edits are saved when you move to another snip, when a
  newer snip takes the selection, when the window closes and before a lab
  stops. A refresh from the folder watcher leaves edits in progress alone.
  Snips with no lab record (the record switched off, or an image copied in by
  hand) are shown read-only with the reason.
- A full-size viewer: a plain window sized to 85% of the screen under the
  pointer, opened by clicking the thumbnail, **Expand**, double-clicking a row,
  or Space or Enter on the list. Left and Right (or Up and Down) step through
  the lab in capture order, with Previous and Next buttons, and the list
  selection follows. It is not modal, so the snip hotkey still works, and it is
  closed before a snip so it cannot end up in the picture.
- `lab.update_note()` rewrites a note (recording when it was edited) or
  removes it when emptied; `lab.caption_of()` reads a snip's caption.
  `lab.snip_rows()` rows now carry `path`, `note_entries` (id and text) and
  `recorded`.

### Changed
- Double-clicking a row opens the viewer; **Open** still opens the image in
  your default program.
- The preview window opens at 1100 x 760 to fit the editor.

### Tests
- `test_lab_edit.py`: rewriting, removing by emptying, no write for the same
  text, unknown notes, `caption_of`, and the new row fields.
- `test_labsnips_panel.py`: row thumbnails, the selected snip's thumbnail and
  words, the hover preview, save emitting only what changed, new notes,
  save-on-move, refresh not wiping edits, read-only unrecorded snips, the
  viewer opening on the selected snip and cycling with the list following, and
  the thumbnail cache.
- End to end through the real app: an edit in the panel lands in `lab.json`
  and the list shows it.

---

## [0.4.6] - 2026-09-28

### Changed
- While a lab is running the lab button is amber, bold, and reads
  `● Stop lab: <name>` (names over 22 characters are shortened; the
  tooltip has the full name). Amber because green already means a toggle is on
  (Snip list, Attach to this snip) and red means Remove. Done with a
  `labActive` style property, so the look follows the lab state from every
  path that starts or stops one.

### Fixed
- The lab snip list is driven by a `QFileSystemWatcher` on the running lab's
  folder. Any change there (a snip, a removal, `lab.json` being replaced by a
  caption or note, an image dropped in from Explorer) rebuilds the list after
  a 120 ms pause that gathers the several writes one snip makes. The tray
  tooltip's snip and note count updates the same way. The watch moves with
  the lab and is dropped when it stops. Opening the window from the tray or a
  relaunch also rebuilds the list first.
- Starting a lab over a snip on screen filed that snip into the lab after the
  window had been refreshed, so the list opened without it. It refreshes after
  filing now.

### Tests
- `test_live_snip_list.py` drives the real app object: a snip is listed and
  selected immediately, an image dropped into the lab folder appears on its
  own, the watch follows the lab and stops with it, starting a lab over a snip
  lists that snip, and the lab button changes state with the lab.

---

## [0.4.5] - 2026-09-28

### Added
- A checkable **Snip list** button on the toolbar, beside **Stop lab**, shown
  only while a lab is running. Unchecked hides the lab snip list and gives the
  image the full width of the window. Stored as `lab_snip_list` (default on),
  so it stays how you left it across snips, labs and restarts. While hidden the
  list is not rebuilt, so nothing reads the lab folder for it.

### Fixed
- The **Open** button under the lab snip list sat flush against the left edge,
  with **Remove from lab** pushed to the far right and an empty gap between.
  The two buttons now split the row equally, and the whole panel is inset 6 px
  from a slightly wider splitter handle so it no longer butts up against the
  image.

### Tests
- The Snip list button appears only during a lab, hiding the list reports it,
  and restoring the stored state does not echo back as a new toggle.
- `lab_snip_list` defaults on and survives a save and load.

---

## [0.4.4] - 2026-09-27

### Added
- A **Lab snips** list in the preview window, beside the image, shown for as
  long as a lab is running. Newest first, with columns for number, time,
  section, caption and notes, and a detail box under it giving the selected
  snip's full section, caption and every attached note, since the columns cut
  long ones short. The snip on screen is bold and marked `*`, and is selected
  after each new snip so the buttons act on it; a refresh for a caption or a
  note keeps whatever you had selected. The list is built from the images in
  the lab folder and enriched from `lab.json`, so it is right with the lab
  record switched off and includes images copied in by hand. Double-click or
  **Open** opens the image.
- **Remove from lab** under the list, and the Delete key on the list. It asks
  for confirmation, naming the snip, its caption and how many attached notes
  go with it. The image is moved to `<lab>/removed/`, not deleted. Its record,
  and any note attached to it and to nothing else, move from `entries` to a
  `removed` list in `lab.json` with a timestamp, and `lab.md` is re-rendered
  without them. A note also attached to another snip stays and only loses the
  reference. If the removed snip is the one on screen, the caption box, **Move
  snip here** and **Attach to this snip** switch off for it. Numbering is
  derived from the files in the lab folder, so the next snip takes the freed
  number. Only a bare image filename inside the active lab can be removed.

### Fixed
- Starting ShadowSnip while it was already running, which is what the taskbar
  pin does, sent a `ping` the running copy ignored, so nothing appeared. A
  relaunch now opens the window in the running copy, restoring it if it was
  minimised. The launch passes on its right to take the foreground
  (`AllowSetForegroundWindow`), without which Windows keeps the window behind
  whatever was in front. The running copy now answers; if it is running but
  does not answer within two seconds, the launch says so and points at Task
  Manager instead of silently exiting.
- A minimised preview window stayed minimised on a tray click, because
  `show()` and `raise_()` do not restore one.
- A snip could finish on its own mid-drag when the pointer crossed onto, or
  came close to, another monitor. The drag starts with the mouse captured by
  the overlay under the pointer; crossing onto another monitor's overlay could
  lose that capture, and Qt reports a lost capture as a button release. A
  release is now checked against the physical button (`GetAsyncKeyState`,
  honouring swapped buttons) and ignored while it is still held. From then on
  the drag follows the cursor by polling every 10 ms and finishes once the
  button has read "up" three polls in a row. A normal release still finishes
  at once.
- The selection rectangle could jump while dragging on a second monitor with
  a different scale factor, because move events arriving at the first
  overlay were converted with that overlay's scale. Moves now use the global
  cursor position.
- An exception while starting the overlay left `busy` set, so every later
  snip, hotkey and tray click was refused until restart. It is now caught,
  reported, and the snip state reset.
- Cancelling a snip started from the preview window left the window hidden.
  It comes back now.

### Tests
- `test_lab_remove.py`: removal moves rather than deletes, leaves the record
  and index, takes solely attached notes with it, keeps shared notes, frees
  the number, keeps both copies of a repeated name, works without a record,
  refuses anything that is not a bare snip filename in the active lab, and
  reports a failed move. The snip rows carry section, caption and attached
  notes, come in capture order, and work from the folder alone.
- `test_overlay_drag.py`: a release with the button held is ignored, polling
  then follows and finishes the drag, a single odd reading does not finish it,
  a real release finishes at once, and without a button probe the release is
  trusted as before.
- `test_preview_snips.py`: newest first, the on-screen snip is selected and
  marked, a refresh keeps the selection and a new snip takes it, Remove emits
  the selected file, and an empty lab disables the buttons.

---

## [0.4.3] - 2026-09-02

### Added
- A **Settings** button in the preview window, on the right of the button bar
  next to Close, in a muted violet so it reads as a different kind of control
  from the snip actions. It sits past the stretch with Close because those two
  stay in one place while the buttons on the left change with what is on
  screen and whether a lab is running. Settings was previously reachable only
  through the tray menu.
- **Never copy from** has two buttons under it, so a program can be excluded
  without knowing its executable name. **Block the app I was just in** walks
  the window z-order and names the frontmost window that is not ShadowSnip's
  own — the one Alt+Tab would return to. **Pick an app (5s)** counts down
  while you click into the program you want, then names whatever has focus.
  Both append to the field and report what happened; neither saves anything
  until OK is pressed.

### Fixed
- Copy on select engaged at startup without refreshing the tray menu or the
  preview button, so after a restart with the setting stored on, the hook was
  running while both toggles read "off". The first click then appeared to do
  nothing — it released a hook the button already claimed was released — and
  only the second click visibly changed anything, which is why it took several
  presses to settle. Every path in and out of the hook now updates the
  toggles, including the failure path, which previously left the menu claiming
  a hook that never started.
- Copy on select no longer resumes after a restart. It is a system-wide mouse
  hook that synthesises keystrokes and reads the clipboard back; leaving it on
  once should not sign you up for it running every morning afterwards. The
  stored value is cleared at launch rather than merely ignored, so Settings,
  the tray menu and the preview button agree from the first frame.
- Copy on select no longer synthesises Ctrl+C into a VM console, an RDP
  session or an SSH client. The existing guard matched window *class*, and a
  VMware, VirtualBox, `mstsc`, VNC, PuTTY or MobaXterm window is an ordinary
  application window to Windows — so a Kali terminal inside VMware, where
  Ctrl+C is SIGINT, got none of the protection a local console gets, and every
  drag-select was interrupting whatever was running. Those programs are now
  skipped by executable name, under the same switchable setting as the console
  and Explorer skips. Nothing is given up by it: a guest's clipboard reaches
  the host through VMware Tools or the RDP clipboard channel, which is slower
  than the 120 ms read-back, so the copy could not have been read back anyway.
- A snip requested while Settings, or any other ShadowSnip dialog, was open
  left the screen dimmed with an overlay that could not be dragged or
  cancelled. `QDialog.exec()` is application-modal, so the overlay received no
  mouse or key events, and the busy flag it set was never cleared — every
  later snip was silently refused and copy on select stayed paused until
  restart. The hotkey now declines the snip before anything is created, says
  why in a tray message, and raises the dialog that is waiting for an answer.
- Every copy-on-select setting was disabled while **Copy highlighted text**
  was off. That included **Never copy from**, which is the setting you reach
  for precisely because copy on select is misbehaving in some program — it
  could not be filled in until the misbehaving feature was switched back on.
  The coupling is gone; none of those settings do anything while the feature
  is off, so there was nothing to protect.

### Changed
- **Never copy from** accepts `lightroom` as well as `lightroom.exe`. Matching
  is still on the whole name, so `code` does not match `vscode.exe`.

### Documentation
- README and ROADMAP record the clipboard-redirection gap: `rdpclip.exe` on a
  remote desktop, and VMware or VirtualBox guest tools, can take clipboard
  ownership inside the 120 ms read-back window, which fails the owner check
  added in 0.4.2. The clip is discarded as unverified, so the toast, preview
  and lab see nothing even though the text is on the clipboard and pastes
  normally. Options for handling it are listed in the roadmap.
- The Settings section states that copy-on-select options can be configured
  before the feature is enabled, and that the snip hotkey is inert while a
  dialog is open.

### Tests
- A snip is refused, and `busy` left clear, while a modal dialog is open; a
  snip still starts when none is.
- The exclusion list matches with and without the extension, matches whole
  names only, and never displaces the built-in password-manager list.
- Adding a name to the field is idempotent across both spellings and tidies a
  hand-typed list.
- The z-order walk skips ShadowSnip's own windows and untitled helper windows,
  and answers nothing rather than guessing when there is no other window.
- Engaging copy on select updates the toggles, and so does a failed engage.
- No keystroke reaches a VM, RDP or SSH window; an ordinary window still gets
  one; the skip is switchable, and switching it off does not expose the
  always-on password-manager list.

---

## [0.4.2] - 2026-09-01

### Security and reliability
- Copy on select now blocks a foreground process that cannot be identified,
  including protected or elevated processes. The password-manager exclusion is
  therefore fail-closed rather than dependent on a successful process lookup.
- Its delayed clipboard read-back confirms that focus is still in the original
  window and that the clipboard owner is in the same process. An unrelated
  clipboard update is ignored instead of being shown in the toast or preview.
- Bound the Win32 process-ID call with pointer-safe `ctypes` declarations, so
  64-bit window handles cannot be truncated during the safety checks.
- A failed screen grab clears capture state and resumes copy on select.
- Settings refuse to move an active lab by changing the save or labs root.
- Lab index and privacy-marker failures now surface to the user; screenshots
  remain on disk when their follow-up record write fails.
- A hotkey update is transactional: duplicate combinations are rejected and a
  failed registration restores the prior working keys.

### Documentation
- Corrected the tray-icon instruction: it opens the preview window; it does
  not start a capture.
- Documented the stricter copy-on-select and active-lab safeguards.

### Tests
- Added regression coverage for protected-process blocking, clipboard
  focus/ownership checks, capture recovery, hotkey rollback, and lab-write
  failures.

---

## [0.4.1] - 2026-08-29

The two things the first real lab session tripped over.

### Added
- The section box is a **picker** as well as a text field, listing every
  breadcrumb the lab already uses, ancestors included. Retyping `10.0.0.3/SMB`
  from memory an hour later is how one section quietly becomes two — the first
  session with 0.4.0 produced a `SCAN` and a `SCANvv2` within five minutes, and
  a near-miss like that is invisible until the writeup.
- **Move snip here** in the preview window re-files the snip on screen under the
  current section. Snipping first and naming the section a moment later is the
  natural order, and it left the snip at the root while the notes about it were
  filed under the breadcrumb — so they rendered as an `_Evidence:_` reference
  instead of sitting under the image. A button rather than a guess: the
  application has no business deciding which section a snip "really" belonged
  to.
- `lab.sections()` and `lab.move_snip()`, with tests for both.

### Changed
- The pixel-equality tests compare `tobytes()` rather than `getdata()`, which
  Pillow deprecated for removal in Pillow 14. Same comparison — a mode change
  still fails it, because the buffers differ in length — and the suite now runs
  without warnings.

## [0.4.0] - 2026-08-29

Pentest notes, and copy on select that catches a double-click.

### Added
- **Sections.** A lab now carries a current breadcrumb — `10.10.10.3/SMB` —
  and everything captured while it is set is filed under it. `lab.md` renders
  those paths as nested headings, in the order the sections were first used
  rather than alphabetically, because that is the order the work happened in.
  The structure is therefore recorded during the engagement instead of being
  reconstructed from a pile of screenshots afterwards. It lives in `lab.json`
  rather than the config, so it belongs to the lab and resuming one restores
  it. Set it in the preview window or from **Set section...** in the tray.
- **Notes.** Text entries alongside the snips in one ordered record. A
  multi-line box in the preview window (**Ctrl+Enter** files it) for writing
  about the snip on screen, and a global **Ctrl+Shift+N** for catching one line
  without breaking stride. A note typed against a snip attaches to it and
  renders as a quote directly beneath that image — evidence, then the sentence
  about the evidence. A note attached to a snip filed in another section stays
  where it was written and carries an `_Evidence:_` reference instead, so a
  note never silently moves out of its own section.
- Copy on select now fires on a **double-click** (the word) and a
  **triple-click** (the line), not only on a drag. A low-level mouse hook never
  receives `WM_LBUTTONDBLCLK` — it is synthesised further up the stack, when an
  event is dispatched to a window with `CS_DBLCLKS`, so it only ever exists
  inside the target application. `_ClickRun` applies the same rule Windows
  does, two presses inside `GetDoubleClickTime()` and inside the
  `SM_CXDOUBLECLK` rectangle, and counts them here. Its own setting, on by
  default, so drag-to-copy can be kept without it.
- A **password-manager blocklist**. KeePass, KeePassXC, 1Password, Bitwarden,
  Dashlane, Enpass, NordPass, Keeper, Proton Pass, RoboForm, LastPass and the
  Windows credential prompt never receive the synthetic Ctrl+C at all. This one
  is not about the copy misfiring: double-clicking an entry in KeePass copies
  the password, and with double-click selection added, a feature that reads the
  clipboard back automatically would have read it. Always applied; **Never copy
  from** in Settings adds to it.
- A **confirmation near the cursor** when a clip is captured, for about a
  second. Copy on select acted invisibly unless the preview window happened to
  be open, which is never the window you are looking at when you highlight
  something. It cannot take focus (`Qt.ToolTip` plus `WA_ShowWithoutActivating`)
  and cannot swallow a click (`WA_TransparentForMouseEvents`).
- Clips identical to the one before are ignored, since re-selecting the same
  word is the commonest gesture there is and announcing it every time turns a
  useful confirmation into noise.
- Test coverage for everything above: the click-run counter, the clip summary,
  section normalising, note records, and the section-tree walk with its
  attachment rendering.

### Changed
- `lab.md` is now a section tree rather than a flat list of `## 001` headings.
  A lab with no sections set renders as one flat run under the title, so a lab
  from 0.3.x looks much as it did.
- `lab.json` entries carry `kind` and `section`. Records written before this
  have neither: they read as snips at the root of the tree, so old labs open
  and render without being migrated.
- `HotkeyManager` registers named hotkeys and emits `triggered(name)` instead
  of managing exactly one. They share a single native event filter — that
  filter runs for every message the process receives, and a second Python
  callback on every mouse move is a poor price for a dictionary lookup.
- **Write a lab.md index** is now **Keep a lab record**, which is what it
  always did. Sections and notes need it, and the label now says so.
- `AutoCopy.copied` carries the kind of clip alongside the text — `selection`,
  `word` or `line` — so the confirmation and the status line can say which
  gesture produced it.

## [0.3.4] - 2026-08-21

Bug fixes, and a test suite to catch the next ones.

### Fixed
- `F` and `Space` grabbed the primary screen rather than the screen under the
  pointer. Both the overlay and the preview window worked out "where the cursor
  is" from `primaryScreen().geometry().center()`, which is a fixed point on one
  monitor and never the cursor. Overlay focus and the preview window's centring
  now both come from `QCursor.pos()`.
- A refused mouse hook reported `error 0`. `ctypes.get_last_error()` reads the
  copy ctypes keeps only for libraries built with `use_last_error=True`, which
  `ctypes.windll` is not; `ctypes.GetLastError()` is the one that answers.
- A save folder that could not be written took the lab copy down with it. The
  standing file and the second destination shared one `try`, so a full or
  read-only save folder skipped `lab.save()` entirely even when the lab sat on
  a different drive. Each destination now gets its own attempt and its own note
  in the status line.
- A `null` in `config.json` sanitised to the string `"None"` and was accepted
  as a real value. A null `save_dir` then reached `Path()` as `None` and raised
  `TypeError`, which is not an `OSError` and so was not caught where the writes
  happen — the snip was lost with a traceback. Null string settings now fall
  back to their defaults.

### Added
- A test suite (`pytest`) over the modules that hold logic rather than pixels:
  config sanitising and round-tripping, the standing file and history pruning,
  lab numbering, captions and the index render, hotkey string parsing, and the
  compression pipeline's quantise decision. No display and no Windows required.
- `requirements-dev.txt`, and a **Tests** section in `BUILD.md`.

## [0.3.3] - 2026-08-11

### Added
- The preview window now carries the ShadowSnip icon in its title bar, the
  taskbar and alt-tab, drawn at several sizes so Windows picks a crisp one.
- `make_icon.py` renders that icon to a multi-size `shadowsnip.ico` for the
  build to embed in the executable.
- `ShadowSnip.spec` for a one-file, no-console PyInstaller build, and
  `run_shadowsnip.pyw` as a no-build no-console launcher.
- `BUILD.md` covering all three ways to run it and how to start it at login,
  plus a `.gitignore`.

### Changed
- `build_icon` renders 16 through 256 px into one icon rather than scaling a
  single 64 px pixmap.

## [0.3.2] - 2026-08-11

### Changed
- Clicking the tray icon now opens the window instead of starting a snip.
  Losing whatever was on screen to an accidental snip from a stray click was a
  poor default. Snipping stays on the hotkey, the tray menu, and the New snip
  button. The window opens centred even before the first snip of a session.

## [0.3.1] - 2026-08-11

### Fixed
- Copy on select froze the mouse and flooded PowerShell with
  `OverflowError: int too long to convert`. The Win32 hook functions were not
  prototyped, so ctypes defaulted their arguments to 32-bit `int` and
  overflowed on the 64-bit `lParam` pointer on every mouse event; Windows then
  throttled and dropped the hook. `SetWindowsHookExW`, `CallNextHookEx` and
  `UnhookWindowsHookEx` now declare their argument and return types, the
  `lParam` cast goes through `c_void_p`, and the callback chains to the next
  hook first and unconditionally so a fault in our own logic can never stall
  the event.

## [0.3.0] - 2026-08-11

Copy on select.

### Added
- **Copy on select** toggle on the preview toolbar and in the tray menu. While
  it is on, finishing a left-button drag copies the highlighted text, so a
  selection reaches the clipboard without Ctrl+C. Off by default; the state is
  remembered between runs.
- `autocopy.py`, holding the WH_MOUSE_LL hook and the guards around it:
  console, Explorer and desktop windows are skipped, ShadowSnip's own windows
  are skipped, nothing fires while a modifier is held or for a drag shorter
  than `auto_copy_min_drag`, and the clipboard sequence number is checked so a
  drag that selected nothing changes nothing.
- Settings: copy on select on/off, the window exclusions, and the shortest
  drag that counts.

### Changed
- Copy on select is suspended for the duration of a snip, since dragging the
  selection overlay is itself a left-button drag.

## [0.2.1] - 2026-08-11

Readability over size, and a lab button where people look for it.

### Added
- **Start lab** button on the preview window toolbar, which toggles to
  **Stop lab (name)** while one is engaged. Starting a lab while a snip is on
  screen files that snip into the new lab straight away.
- `quantize_max_source_colors`: palette reduction is skipped once a grab holds
  more distinct colours than this (4096 by default).
- `quantize_min_saving`: the palette version has to be at least this much
  smaller before it is kept (25% by default).

### Changed
- Palette reduction no longer applies to text-heavy or photographic grabs.
  Anti-aliased small text is made of hundreds of near-identical colours, and
  flattening those into a 256-entry palette is what made code and terminal
  screenshots look mushy. Those now stay truecolour, which makes them roughly
  four times larger and actually readable. Flat UI panels still quantise and
  are unaffected.

## [0.2.0] - 2026-08-11

Lab sessions.

### Added
- Lab mode: **Start lab...** in the tray menu asks for a name, and every snip
  taken while the lab is engaged is also written into that lab's folder,
  numbered in capture order (`003_2026-08-11_14-31-07.png`).
- Starting a lab with a name that already exists resumes it and carries on
  numbering from where it left off, which doubles as crash recovery.
- `lab.json` per lab holding the record of every snip, and a `lab.md` index
  rendered from it with each image embedded in order, ready to paste into a
  writeup.
- Optional caption box in the preview window while a lab is engaged; what is
  typed lands in the lab index next to that snip.
- **Open a lab** submenu listing recent labs, one click to open the folder.
- The active lab is stored in the config, so a restart resumes it instead of
  quietly dropping back to normal mode.
- A tray icon badge, a tray tooltip showing the lab name and snip count, and
  an **Open lab folder** menu entry while a lab is engaged.
- A `.gitignore` written into the labs root on creation, since lab folders
  collect credentials and internal hostnames by design.
- Settings: labs folder location, lab index on/off, caption box on/off.

### Changed
- The timestamped history folder is skipped while a lab is engaged; the lab
  folder is the history for that period, so a snip never lands in three
  places at once.
- The preview window's **Open folder** button follows the lab when one is
  active, and **Save as...** starts in the same folder.

## [0.1.0] - 2026-08-09

First working version.

### Added
- Global hotkey (`Ctrl+Shift+S` by default) via `RegisterHotKey`, plus a tray
  icon and a `--snip` command line flag.
- Freeze-frame capture across all monitors, with a dimmed drag overlay, a live
  size badge, whole-screen capture on `F`/`Space`, and `Esc` to cancel.
- Selections that span monitors, including monitors on different DPI scales.
- Automatic clipboard copy of a compressed PNG, with an optional `CF_DIB`
  bitmap for applications that cannot read PNG from the clipboard.
- Automatic disk write to a single standing file that each snip replaces;
  optional pruned history folder alongside it.
- Compression pipeline: optional downscale, optional palette quantisation that
  is kept only when it produces a smaller file, PNG effort level.
- Disk formats: PNG, WebP and JPEG, independent of the clipboard format.
- Preview window with `Save as...`, `Copy again`, `Open folder`, and a size
  read-out showing raw versus compressed bytes.
- Settings dialog with a hotkey recorder.
- Single-instance guard; a second launch wakes the running copy instead.
- Atomic writes for both the config file and saved images.
