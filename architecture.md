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
lab.py               lab sessions: numbering, lab.json state, lab.md index
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
        +--> lab.save()            when a lab is engaged, numbered copy
        +--> storage.save_history()otherwise, optional and pruned
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

**Quantise only when it wins, and only where it is safe.** Screenshots are
mostly flat colour, so a 256-colour palette PNG is usually much smaller with
no visible difference. Text is the case where that reasoning breaks: anti-
aliased glyph edges are hundreds of near-identical colours, and a 256-entry
palette turns them to mush at exactly the sizes people need to read. So the
source is counted first with `getcolors()`, which returns None past a ceiling
and costs one pass; past it the image is kept truecolour. Under the ceiling
both versions are still encoded and the palette one has to be a set percentage
smaller before it is kept, rather than merely one byte smaller.

**Every disk write is atomic.** Config and images are written to a temp file
in the destination directory and then `os.replace`d, so an interrupted write
cannot leave a half-written `latest.png` for something else to read.

**One standing file.** `save_latest()` deletes stale siblings (`latest.png`
when the format switches to `latest.jpg`), so the folder never holds two files
claiming to be the current snip.

**A lab is a second destination, not a second mode.** Engaging a lab does not
change the pipeline: the clipboard copy and the standing `latest.png` still
happen first, and `lab.save()` runs after them. If the lab write fails, the
snip is already safe. The generic history folder is skipped for the duration
so the same image is not written three times.

**lab.json is the source of truth, lab.md is a render.** The index is
regenerated from the recorded entries on every change rather than appended to.
That is what makes a caption typed after the snip cheap: it edits one field
and re-renders, instead of trying to patch markdown in place.

**Numbering comes from the filenames.** `_next_number()` reads the highest
`NNN_` prefix in the folder rather than trusting a counter in `lab.json`, so
resuming a lab, deleting the state file, or dropping images in by hand all
still produce a sensible next number.

**Lab names are not validated.** The name is used as the folder name exactly
as typed. Windows rejects a few characters and a handful of reserved device
names, and pathlib rejects a null byte before the OS is even asked, so
`lab.start()` catches both and reports the name as unusable. The choice is
deliberate: fail loudly on the name the user actually typed rather than
silently create a folder they did not ask for. The catch is what stops it
being a silent failure.

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
- Lab folder unusable: reported when the lab is started, and no lab is
  engaged, so snips carry on going to the normal save folder.
- Lab index unwritable: swallowed. The image is already on disk and on the
  clipboard, which is not worth losing over a failed index write.
- Lab left engaged: the tray badge, the tooltip snip count and the menu entry
  reading `Stop lab (name)` all make it visible. Nothing stops it on its own.

## What is not here yet

Run at login, upload targets, freeform and window-mode capture, delayed
capture, annotation, and encryption at rest for lab folders. See `ROADMAP.md`.
