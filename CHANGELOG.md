# Changelog

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
