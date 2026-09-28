# Changelog

## Latest: 0.4.5

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
