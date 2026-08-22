# Changelog

## Latest: 0.4.0

**Added** — lab **sections** and **notes**, so the writeup builds itself while
you work instead of being assembled from a pile of screenshots afterwards. Copy
on select now fires on a **double-click** (word) and **triple-click** (line),
never touches a password manager, and shows a confirmation next to the cursor.

**Changed** — `lab.md` is a section tree rather than a flat list; `lab.json`
entries carry a kind and a section, and old labs still open unmigrated. One
hotkey manager now holds several keys.

**Fixed** — in 0.3.4: `F`/`Space` grabbing the wrong screen, a hook failure
reporting `error 0`, an unwritable save folder taking the lab copy down with
it, and a `null` in `config.json` losing a snip to a traceback.

---

## [0.4.0] - 2026-08-22

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
