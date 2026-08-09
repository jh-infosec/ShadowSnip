# Changelog

All notable changes to ShadowSnip are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
