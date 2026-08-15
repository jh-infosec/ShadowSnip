# Changelog

All notable changes to ShadowSnip are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
