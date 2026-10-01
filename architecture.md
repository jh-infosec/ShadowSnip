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
lab.py               lab sessions: numbering, sections, notes, the lab.md tree,
                     outline and moves
autocopy.py          copy on select: mouse hook, guards, clipboard read-back
toast.py             the one-second clip confirmation near the cursor
preview.py           post-snip window
labsnips.py          lab panel: snip list, report outline, rendered preview,
                     in-place editing, full-size viewer
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

**Built for pentest writeups.** The lab is the centre of the design: the
record (`lab.json`) is structured as the report is, sections first, so the
report is a rendering of what was captured rather than something assembled
afterwards. The outline and preview are views of that record, and every edit
made in them goes back through `lab.py`, so there is one writer and `lab.md`
never disagrees with what the window shows.

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
snip is already safe and the failure is reported. The generic history folder
is skipped for the duration so the same image is not written three times.

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

**The section is state, not a field on each entry the user fills in.** A lab
already has one piece of quiet routing state — which lab is engaged — and the
current section is the second. Everything captured while it is set inherits it,
which means the tree is recorded as a side effect of doing the work rather than
assembled from a pile of screenshots at the end. The alternative, tagging each
snip and note as it is made, is more flexible and would be used approximately
never at two in the morning.

It lives in `lab.json` rather than the config because it belongs to the lab:
resuming a lab a day later should put you back where you were, and two labs
should not share a breadcrumb.

**Notes are entries in the same list as snips.** One ordered record, one
rendering pass, one source of truth. A separate notes file would have needed
its own ordering, its own numbering, and a merge step at render time to
interleave the two — three things to get wrong for no gain.

**An attached note renders under its snip, but only within a section.** The
useful arrangement in a report is evidence then commentary, so a note attached
to a snip in the same section is rendered as a quote beneath the image. Across
sections it is not: a note that moved somewhere the user did not put it is a
worse failure than a note that is merely further from its screenshot, so it
stays where it was written and carries a reference instead.

**A mouse hook for copy on select, and only for that.** The hotkey argument
below still holds: a keyboard hook would see every keystroke typed anywhere,
which is not a thing this application should be trusted with. A mouse hook
sees coordinates and button states, and it is the only way to know a drag
finished, since Windows has no notification for "the user highlighted
something". The feature is off by default and engaged deliberately, because a
hook plus synthetic keystrokes plus automatic clipboard reads is a combination
worth opting into rather than inheriting.

**The synthetic Ctrl+C is the dangerous part, not the hook.** Reading mouse
events changes nothing; sending a keystroke into an arbitrary window does.
Consoles are skipped because Ctrl+C with no selection is a break, Explorer
because a rubber-band drag there selects files, ShadowSnip because its own
overlay is dragged with the same button, and any window at all while a
modifier is held. `GetClipboardSequenceNumber` is read before and after, so a
drag that selected nothing is detected as such rather than assumed.

**Two block lists, for opposite reasons.** The window-class list above is about
a copy that misfires. The process list — password managers, by executable name
— is about a copy that works: double-clicking an entry in KeePass copies the
password, so the check happens before the keystroke is sent rather than after,
and an unreadable process name is never treated as an allowed one. Failing
open is the wrong direction when the question is "should this window's
clipboard be read".

**Double-click is counted here, not reported by Windows.** A low-level mouse
hook receives only `WM_LBUTTONDOWN` and `WM_LBUTTONUP`; `WM_LBUTTONDBLCLK` is
synthesised when an event is dispatched to a window with `CS_DBLCLKS`, and so
exists only inside the target application. `_ClickRun` applies the same rule
Windows applies — two presses inside `GetDoubleClickTime()` and inside the
`SM_CXDOUBLECLK` rectangle — and is deliberately free of both Win32 and Qt, so
the rule can be tested without either.

**The hook callback records, the event loop acts.** Windows silently unhooks a
low-level hook whose callback overruns `LowLevelHooksTimeout`, so
`_on_mouse_event` stores two coordinates and returns. Everything else happens
from `QTimer.singleShot`, after the callback has already returned. The
callback object is kept on the instance as well, since a garbage-collected
ctypes callback takes the process with it.

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
- Mouse hook refused: reported as a tray notification and the toggle goes
  back off; nothing else about the application changes.
- Second launch: hands off over `QLocalServer` and exits rather than starting
  a competing tray icon and a second hotkey registration. The running copy
  opens its window (or snips, for `--snip`) and answers `ok`; the launch hands
  over its foreground right first so the window actually comes to the front.
  No answer within two seconds is reported as a stuck copy rather than
  swallowed.
- Mouse capture lost mid-drag: Qt reports it as a button release. The
  overlay checks the physical button, ignores the release while it is held,
  and follows the drag by polling the cursor until the button is really up.
- Snip start failure: caught in `_begin_snip`, reported, and `busy` cleared
  so the app does not refuse every later snip.
- Removing a lab snip: the image moves to `<lab>/removed/` and its record to
  `removed` in `lab.json`, so a mistaken removal is recoverable by hand.
- Lab folder unusable: reported when the lab is started, and no lab is
  engaged, so snips carry on going to the normal save folder.
- Lab name that could leave the labs root (`..`, separators, a drive prefix,
  a device name): refused by `lab.name_problem()` with the reason, and any
  path that does not resolve to a direct child of the root is refused too. A
  bad name already in the config reads as no lab.
- Latest file: the new file is written before stale `latest.*` files of other
  formats are removed, so a failed write never leaves neither.
- Lab index unwritable: swallowed. The image is already on disk and on the
  clipboard, which is not worth losing over a failed index write.
- Lab left engaged: the tray badge, the tooltip snip count and the menu entry
  reading `Stop lab (name)` all make it visible. Nothing stops it on its own.

## What is not here yet

Run at login, upload targets, freeform and window-mode capture, delayed
capture, annotation, and encryption at rest for lab folders. See `ROADMAP.md`.
