# ShadowSnip architecture

## Layout

Flat modules at the repo root; every module imports by bare name.

```
main.py              entry point, DPI awareness, single-instance guard
app.py               tray icon, snip pipeline, settings plumbing
config.py            defaults, load/save, sanitising
capture.py           screen freezing and multi-monitor crop compositing
overlay.py           the dimmed selection windows
imageops.py          QImage -> Pillow, compression, DIB encoding
clipboard.py         Win32 clipboard writer (PNG + CF_DIB), Qt fallback
storage.py           latest-file replacement, history, atomic writes
preview.py           post-snip window
settings_dialog.py   settings form and hotkey recorder
```

## The snip pipeline

```
hotkey / tray / --snip
        |
        v
app.request_snip()          hide our own preview window first
        |
        v
capture.grab_all_screens()  one QPixmap per screen, frozen
        |
        v
overlay.SelectionController one frameless window per screen, shared state
        |
        v
capture.compose_selection() crop out of the frozen frames
        |
        v
imageops.process()          downscale -> quantise -> PNG
        |
        +--> clipboard.copy()      PNG + optional CF_DIB
        +--> storage.save_latest() atomic replace
        +--> storage.save_history()optional, pruned
        |
        v
preview.PreviewWindow       optional; every control here is opt-in
```

## Design decisions

**Freeze first, select second.** Screens are captured before the overlay
appears. The overlay draws those frozen frames, so the picture cannot change
mid-drag (dropdowns closing, video playing) and the crop comes from real
pixels rather than a second grab that would include the overlay itself.

**Scale derived, not trusted.** `QScreen.grabWindow()` has returned pixmaps
with and without `devicePixelRatio` applied across Qt versions. `capture.py`
computes `pixmap.width() / geometry.width()` instead, which is correct in
every DPI mode. A selection spanning screens with different scale factors is
rendered at the highest scale involved so no detail is discarded.

**Two clipboard formats, PNG first.** The registered `PNG` format carries the
compressed bytes; `CF_DIB` is the uncompressed fallback for apps that only
understand bitmaps. Formats are offered in that order because some apps walk
the list and take the first they recognise. There is no way to put a
*compressed* bitmap on the clipboard — `CF_DIB` is uncompressed by
specification — so the fallback is the one thing that stays large, and it can
be switched off.

**Quantise only when it wins.** Screenshots are mostly flat colour, so a
256-colour palette PNG is usually much smaller with no visible difference.
Gradients and photographs are the exception, so `imageops.process()` encodes
both and keeps whichever is smaller.

**Every disk write is atomic.** Config and images are written to a temp file
in the destination directory and then `os.replace`d, so an interrupted write
cannot leave a half-written `latest.png` for something else to read.

**One standing file.** `save_latest()` deletes stale siblings (`latest.png`
when the format switches to `latest.jpg`), so the folder never holds two files
claiming to be the current snip.

**RegisterHotKey, not a keyboard hook.** A low-level hook would see every
keystroke in the system, needs to stay responsive to avoid being silently
unhooked by Windows, and looks exactly like a keylogger to endpoint security.
`RegisterHotKey` plus a `QAbstractNativeEventFilter` sees only the one
combination, needs no elevation, and fails loudly if the combination is taken.

## Failure handling

- Clipboard busy: `OpenClipboard` is retried ten times at 50 ms intervals;
  another process holding it open is normal and transient.
- Hotkey taken: registration failure becomes a tray notification, and the tray
  menu keeps working.
- Save folder unwritable: reported in the preview status line; the clipboard
  copy still happened.
- Second launch: hands off over `QLocalServer` and exits rather than starting
  a competing tray icon and a second hotkey registration.

## What is not here yet

Freeform and window-mode capture, delayed capture, annotation, and OCR — see
`ROADMAP.md`.
