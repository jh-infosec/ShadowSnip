# ShadowSnip architecture

## Layout

Flat modules at the repo root; every module imports by bare name.

```
main.py              entry point, DPI awareness, single-instance guard,
                     --snip / --note / --tray / --show, telling a login start
                     from a start by hand, Wayland warning
app.py               tray icon, snip pipeline, settings plumbing
config.py            defaults, load/save, sanitising
capture.py           screen freezing and multi-monitor crop compositing
overlay.py           the dimmed selection windows: made once and reused,
                     repainting only what a drag moves
imageops.py          QImage -> Pillow, compression, DIB encoding
clipboard.py         Win32 clipboard writer (PNG + CF_DIB), Qt fallback
storage.py           latest-file replacement, history (the Recent snips list),
                     atomic writes
lab.py               lab sessions: numbering, sections, notes, command output,
                     findings, methodology phases, the lab.md tree, outline
                     and moves
report.py            exporting a lab: one model of the report, written as a
                     self-contained HTML page or a Word document (python-docx)
report_dialogs.py    the Finding and File command output dialogs
platforms.py         picks the Windows or Linux module for hotkeys and copy on
                     select; nothing else tests the platform for these
hotkey.py            Windows: RegisterHotKey and a native event filter
hotkey_linux.py      Linux: desktop-owned shortcuts (written into Xfce)
autocopy.py          Windows copy on select: mouse hook, guards, read-back
autocopy_linux.py    Linux copy on select: the X11 primary selection
toast.py             the one-second clip confirmation near the cursor
preview.py           post-snip window
annotate.py          marking up the snip: pen, highlighter, eraser, crop,
                     redaction, the Text tool, undo; the tool strip and its
                     popups
edits.py             keeping marks editable after leaving a snip: the
                     hidden .edits sidecars (marks and the original)
countdown.py         the countdown before a delayed snip (never takes focus)
recorder.py          recording an area to MP4 (frames pushed into Qt Multimedia)
recordbar.py         the red frame and the Pause/Stop bar while a clip records
clips.py             a clip's poster, finding the video beside it, GIF export
player.py            playing a clip inside ShadowSnip (main window and full-size view), the trim bar
cliptrim.py          trimming a clip: re-encoding the part kept, keeping and restoring the original
cvss.py              CVSS 3.1 and 4.0 vectors: parsing, scores, rating
vault.py             encrypted labs: keys, encrypting files, every decrypting reader, hidden names, private temp
lablock.py           locking an encrypted lab by itself: idle time, the computer locking or sleeping
hello.py             Windows Hello: a TPM-signed challenge that unlocks a copy of a lab's key
labkeys.py           the encrypted-lab windows: start, unlock, recovery key, new password
reportpdf.py         the PDF report, laid out with QTextDocument and painted onto QPdfWriter
removedview.py       the Removed snips window: list, preview, Restore
clipcheck.py         run by hand: does video recording work on this machine?
winlist.py           the windows on screen, for window snips (Windows: EnumWindows
                     and DWM frame bounds; X11: xprop and xwininfo)
ocr.py               reading text from a snip (Windows OCR or Tesseract) and
                     finding what Quick redact offers to hide
quickredact.py       the Quick redact window: kinds found, tick boxes
labsnips.py          lab panel: snip list, report outline, rendered preview,
                     full-size viewer with the mark-up tools; the
                     click-to-edit caption field
settings_dialog.py   tabbed settings form (fits the screen) and hotkey recorder
skins.py             the Original, Steel, Split and Console looks: recoloured stylesheets,
                     the painted window background, colours for painted parts
install.sh           Linux installer: launcher, menu entry, autostart
.github/workflows/   tests on Windows and Linux; builds both on a version tag
```

## Two platforms, one codebase

Only two things genuinely differ between Windows and Linux, and each has a
module per platform with the same surface:

| | Windows | Linux |
| --- | --- | --- |
| Global hotkeys | `hotkey.py`: `RegisterHotKey` | `hotkey_linux.py`: the desktop owns the shortcut and runs `--snip` / `--note`; the running copy takes it over the local socket |
| Copy on select | `autocopy.py`: mouse hook, synthetic Ctrl+C, read-back | `autocopy_linux.py`: copy the X11 primary selection once it settles |

`platforms.py` imports the right one, and `app.py` and `settings_dialog.py`
take `HotkeyManager`, `AutoCopy`, `foreground_process` and `last_other_process`
from it. The Windows modules were left as they were when Linux support was
added, so the Windows behaviour is the code that already shipped. The smaller
differences (clipboard, opening folders, DPI, the drag's button check) were
already guarded by `sys.platform` with a portable fallback.

Both copy-on-select implementations fail closed: when the program a selection
came from cannot be identified, nothing is copied, because the password
manager block list cannot be applied.

## Marking up a snip

`annotate.AnnotationDoc` holds the original capture and a list of operations:
strokes (pen or highlighter), redactions (blur or black), crops, and erases
(which hide earlier marks by id). Nothing is drawn into the original. The image
that gets saved is rendered fresh from it each time, so undo is dropping the
last operation and repeated edits do not degrade the picture. Coordinates are
in the original's pixels; stroke widths are converted from screen pixels when a
stroke starts.

`AnnotCanvas` turns drags into operations and announces each change. The
preview window waits half a second after the last one, then hands the rendered
image to `app.apply_snip_edit()`, which re-encodes it with the same settings as
a fresh snip and rewrites every copy the snip was saved to: the clipboard,
`latest`, the lab file and the history file (`_snip_paths`). Pending edits are
flushed before a new snip starts and when the window closes, so an edit is
never lost or saved onto the next snip. A lab snip removed while on screen is
dropped from `_snip_paths`, so an edit cannot recreate it.

### Shapes, words and moving marks (0.11.0)

Every mark added in 0.11 is one operation type, `Mark`, whose `kind` says
what it is (arrow, line, rect, ellipse, label, step, callout, spotlight,
magnify, stamp) and whose points mean what that kind needs. Moving, resizing
or retyping one adds a `Change` naming the mark and its new values;
`AnnotationDoc.effective()` applies the changes in order, so undo is still
just dropping the last operation, and a move is erasable history like
anything else. Strokes and redactions do not move: a redaction dragged off
what it covers is a leak waiting to happen.

Rendering stays a single pass over the operations. Marks paint with the same
painter as strokes. Spotlight and magnify read pixels, so like a blur they
end the painter first. All spotlights are applied together at the first one,
so several keep each other bright and later marks stay undimmed. The same
`paint_mark()` draws a mark being dragged, scaled to the screen with a
transform, so what you see while drawing is what gets saved.

Redo is a stack of the groups undo removed (a Quick redact batch is one
group); any new operation clears it. `edits.py` stores `Mark` and `Change`
like the rest, and rejects unknown kinds and fields.

### Marks that outlive the window (0.10.0)

The operation list is plain data, so `edits.py` writes it out: after each save
of a lab or history snip, `.edits/<name>.json` holds the operations and
`.edits/<name>.orig.png` the original capture (written once per place, not on
every edit). The record carries the SHA-256 of the snip file as written, and
`edits.load()` returns nothing unless the file still matches, so a snip changed
by another program is never reverted to ShadowSnip's idea of it. The full-size
view loads a snip through `edits.load()` first, and saving from it hands the
same doc back to the preview window when it is the snip on screen. Lab removal
and history pruning move or delete the sidecars with their snips; Settings can
switch the whole thing off (`edits.enabled`) and delete what is kept. The cost
is the one the README spells out: the original under every redaction sits on
disk next to the snip.

### Reading text (0.10.0)

`ocr.recognise()` takes a PNG and returns words with boxes in the image's
pixels and a line number each. On Windows it uses `Windows.Media.Ocr` through
the `winrt` packages; elsewhere, or when that is missing, the `tesseract`
program (its TSV output, the image greyed, inverted when dark, and enlarged
for small text first). Low-confidence words are kept on purpose: long hashes
are exactly what OCR is least sure of.

The canvas reads the snip as it looks now (`render_full`, before the crop)
on a background thread. The thread makes no Qt calls: it leaves the words in a
plain dict, and a timer on the canvas collects them (0.11.0; a signal emitted
from a Python thread could crash PySide6 when the canvas closed mid-read). The
result is keyed on the doc and its operation ids, so a mark made meanwhile
makes the read stale and it is read again. Picking and copying work on the
words inside the crop.

`ocr.find_sensitive()` joins each line's words, runs the patterns (in priority
order, so a span claimed as a secret is not also an email), and maps each
match's character range back to a share of each word's box: `password=hunter2`
covers `hunter2` only. Quick redact adds the boxes as ordinary `Redact`
operations sharing one `batch` number, which `AnnotationDoc.undo()` removes
together. They are erasable one by one and saved in the sidecar like any other
redaction.

## Snip modes (0.12.0)

The selection overlay's controller has a `mode`: rect, window or freeform.
Full screen stays an action (`take_screen`). The mode bar is painted by each
overlay window rather than built from widgets, so it costs nothing to show
and is never in the snip: the snip is cut from the frozen frames, not from
the screen.

Window mode asks `winlist.visible_windows()` the first time it is needed and
keeps the answer for that snip. Windows come back topmost first, in Qt's
logical coordinates: on Windows they are physical pixels from Win32,
converted per monitor (the one the window mostly sits on decides the scale),
which is what makes a 150% monitor beside a 100% one land exactly. ShadowSnip's
own windows are left out by process id on both platforms.

Freeform keeps the points drawn and finishes with their bounding box; the app
cuts that box as usual and `capture.mask_outside()` fills what lies outside
the outline. A release only ends a snip that a drag started: a click on the
bar or on a window has already done its work on the press.

### 0.13.0 additions

**Delayed snips** hide the window at once, count down in a ToolTip-type label
that is shown without activation and passes mouse events through (a menu
closes when another window is activated, so this is what lets a menu survive
into the snip), then hide the label and wait `COUNTDOWN_CLEAR_MS` before the
ordinary `request_snip()`. A running copy receives `snip:N` over the local
socket.

**The magnifier** is painted by the overlay window under the pointer, from the
same frozen pixmap as the rest, so it shows exactly the pixels that will be
cut. The controller tracks the pointer and repaints only the old and new
magnifier boxes.

**Covered windows**: `winlist.visible_windows()` returns `Window` records
(rectangle, native handle, covered). A covered window picked on Windows is
captured with `PrintWindow(PW_RENDERFULLCONTENT)` and trimmed to its DWM frame;
an all-black result counts as a failure and the screen is used.

**Mark styles**: a `Change` may also set `color`, `width` and `size`, so a
recolour or resize is one undo and is kept in the sidecar like a move.

### Video clips (0.14.0)

`recorder.Recorder` grabs the chosen area of one screen on a timer and sends
each picture, stamped with the time it was grabbed (pauses left out), into a
`QVideoFrameInput` on a `QMediaCaptureSession` whose `QMediaRecorder` writes
MP4. Grabbing only the area keeps 4K affordable; even frame sizes keep the
encoders happy; the time stamps keep a slow grab from speeding the clip up.
An encoder is not ready at once (Windows' hardware H.264 can take over a
second), and a frame offered early is refused: the first frame is offered
until it is taken, the clock starts then, a Stop during the wait is honoured
after it, and no frame within `WARMUP_SECONDS` is a reported failure.

A finished clip is filed through the same functions as a snip, `lab.save()`
and `storage.save_history()`, with the poster as the snip and the MP4 passed
as a `companion` that is moved in beside it under the same name before
lab.md is written. Everything that shows snips therefore shows clips with no
special case; the few places that act differently (play, copy, Save as GIF,
remove, history pruning) ask `clips.clip_for(path)` for the video beside an
image. Copying a clip puts a file on the clipboard (CF_HDROP through pywin32
on Windows, a uri-list through Qt elsewhere). GIF export plays the clip muted
at 8x into a `QVideoSink` and keeps a frame every 100 ms of the clip's own
clock.

The frame input is created without a frame format: PySide6 6.11 refuses
every frame of an input given one (6.12 does not), and the encoder takes the
size and pixel format from the first frame anyway.

### Playing clips (0.14.1)

`player.ClipPlayer` is a `QMediaPlayer` playing into a `QVideoSink`, with each
frame painted scaled to fit, not a `QVideoWidget`: that widget embeds a native
window that ignores the skins, draws over anything on top of it, and on some
drivers stays black until a resize. The main window and the full-size view
each hold a `QStackedWidget` of the snip canvas and a player and switch
between them by what is shown (`clips.clip_for()` on the image). A
`QAudioOutput` is attached only when the media reports audio, so silent clips
never open the sound system. Before a clip is moved or removed,
`PreviewWindow.let_go_of_files()` unloads any player holding it, because
Windows will not move an open file. `cfg["clip_player"]` ("app" or
"external") decides where the list's Play and Expand go.

### Trimming clips (0.14.2)

Qt Multimedia's FFmpeg can decode and encode but has no cut, and no FFmpeg
program ships with ShadowSnip, so `cliptrim.reencode()` plays the clip muted
at 2x from the start point into a `QVideoSink` and sends each frame up to the
end point into a new `QVideoFrameInput` / `QMediaRecorder`, its time shifted
back by the start. Frames queue for the encoder; above `QUEUE_HIGH` playback
pauses until the queue drains below `QUEUE_LOW`, so no frame is skipped and
memory stays flat through the encoder's start-up. The cut is frame-exact.
Sound is dropped (no way to cut it with Qt alone). `trim()` writes to
`<name>.trimming.mp4`, moves the clip as recorded to `<name>.untrimmed.mp4`
the first time only, puts the new file in place and remakes the poster;
`untrim()` reverses it. `clips.move_with()` carries the `.untrimmed` file
with its clip.

A trim replaces a file another player may hold open, which Windows forbids,
so `ClipPlayer` emits `about_to_change` first (the window unloads every
player showing that clip) and `changed` after (they reload, and the app
writes the new length into lab.json / lab.md with `lab.set_clip_seconds()`
and refreshes the list).

## The report (0.15.0)

`report.model(folder, scope)` is the one reading of lab.json that every
export uses. Each block now carries the section path it sits in, which is
what makes the findings-only scope a filter rather than a second renderer:
for each finding in summary order, its heading (the full breadcrumb), then
every block whose section is the finding's or below it, minus those inside a
nested finding (shown under that finding instead). Sub-section headings keep
their names and drop to sit under the finding.

CVSS lives in `cvss.py` (pure Python, no Qt). A finding stores only the
canonical vector; the score is recomputed wherever it is shown, so there is
no stored number to drift from the vector. `lab.normalise_finding` sets the
severity from the score, so the two cannot disagree in lab.json.

The PDF (`reportpdf.py`) is a separate builder because QTextDocument reads a
subset of HTML (no flexbox, borders only on tables): coloured table cells
stand in for the HTML export's chips and boxes. The writer runs at 96 dpi so
one device pixel is one CSS pixel; the document is paginated by Qt at the
page height minus a footer, and each page is painted with a translated
`drawContents`, then the footer drawn under it. An image is one text line,
and Qt never splits a line, so a snip never breaks across pages.

Restoring a removed snip (`lab.restore_snip`) moves the files back first and
then the records (the snip and the notes removed with it, matched by the
same `removed` stamp), inserting them before the first later-numbered snip.
If lab.json cannot be written, the files go back into `removed/`, so folder
and record never disagree.

## Report front pages, templates and CVSS 4.0 (0.17.0)

`report.model(folder, scope, meta)` carries `meta` (title, client, author,
date, cover, toc; `normalise_meta` fills the gaps), and `report.contents()`
lists what a table of contents shows, with anchors the HTML headings carry.

The PDF is three QTextDocuments painted in turn: cover, contents, body. The
body is laid out first; `heading_pages()` reads each heading's page from
`blockBoundingRect().top() // page_height`, and `keep_headings_with_text()`
gives any heading within `ORPHAN_PX` of a page's foot a page break before it
(QTextDocument has no keep-with-next), repeating until none is stranded. The
contents are laid out once with zero page numbers to learn how many pages they
take, then again with the real numbers offset by cover and contents pages.

The Word export opens the template (a `.dotx` has its content type rewritten
in memory so python-docx will open it), fills placeholders paragraph by
paragraph (joined text, so split runs are found; the paragraph keeps its
first run's formatting), builds the report at the end of the body as before,
then moves every element added (everything after the old end, before
`sectPr`) to just before the `{{report}}` paragraph and removes it. Headings
and grids fall back to direct formatting when the template lacks the styles.
The contents are a `TOC \o "1-3" \h \z \u` field marked dirty, with
`updateFields` set in settings.xml.

CVSS 4.0 (`cvss.score_40`) follows FIRST's `cvss_score.js` step for step,
including its quirks (the choice between the two lower macrovectors when EQ3
and EQ6 are both 0), and rounds half up after adding 10^-6, as FIRST's current
calculator and Red Hat's library do; without that, 522 of the 104,976 base
vectors came out 0.1 low. `tests/test_cvss40.py` hashes all base scores
against a digest made with Red Hat's package and checks 400 stored samples
with threat and environmental metrics.

## Test run on GitHub (0.18.1)

`tests/conftest.py` ends the session by hiding and deleting every top-level
window and running Qt's deferred deletions. Without it, PySide's own sweep at
interpreter exit could reach a window whose C++ object was already gone and
segfault after a fully passing run (exit code 139 on the Linux runner). When
`GITHUB_ACTIONS` is set, `pytest_terminal_summary` also prints each failure
as an `::error` workflow command, so the public run page names the failing
tests and their errors without the signed-in log.

Widgets never take a QWidget method's name as an attribute: a dialog's
`self.hide = QCheckBox(...)` hid `hide()` and broke the session cleanup.

## Lab safety (0.18.0)

A lab can be the running lab and locked at once: `active_lab` is set,
`lab.key` exists, and `vault._open` has no entry. `app._lab_locked()` tests
exactly that. `lock_lab()` clears the screen (`PreviewWindow.hide_for_lock`:
flushes edits, closes the viewer, unloads players, empties the outline) and
calls `vault.lock()`; `LabSnipsPanel.set_locked()` swaps the list for a lock
message with an Unlock button. Entry points that write into the lab
(`_handle_snip`, `request_record`) call `unlock_lab()` first; writes from
anywhere else are refused by `vault.guard` as before.

`lablock.AutoLock` polls every 20 s: system idle (`GetLastInputInfo`, or
XScreenSaver through ctypes) where it can be measured, ShadowSnip's own last
use otherwise (`touch()` on each snip and unlock), the smaller of the two.
It has no Qt parent: owned by the app in Python only, because with both a Qt
parent and a Python owner PySide freed it twice at interpreter exit (heap
corruption in roughly half the test runs). `lablock.SessionWatcher` uses a
native event filter for `WM_WTSSESSION_CHANGE`/`WM_POWERBROADCAST` after
`WTSRegisterSessionNotification` on the main window, and logind's `Lock` and
`PrepareForSleep` over the system D-Bus on Linux.

Hidden names: `vault.lock()` calls `hide_names()` when `lab.key` says
`hide_names`. It writes `lab.names` (encrypted: hidden relative path to real
one) before renaming anything, then renames file by file within each folder;
`_opened()` (every unlock path) calls `reveal_names()`, which renames back
whatever is still hidden, skips anything that resolves outside the lab, and
deletes `lab.names` only when all went back. `decrypt_folder` forgets the key
directly rather than through `lock()`, so it never hides a plain lab's names.

Windows Hello (`hello.py`): `KeyCredentialManager` opens or creates one
credential for ShadowSnip; its RSA key signs a 32-byte random challenge stored
per lab, and HKDF-SHA256 of the signature is the AES-GCM key wrapping the data
key. Enrolling signs twice and refuses a signer whose signatures differ. WinRT
calls run on a worker thread under `asyncio.run`, with the Qt loop pumped
while Hello's prompt is up. `hello.signer` is the seam the tests replace.

The private temp folder (`vault.private_temp`) is `shadowsnip-<pid>-*` in
`/dev/shm` on Linux, the system temp elsewhere, chmod 700;
`clean_stale_temp()` at start removes any whose process is gone.

## Encrypted labs (0.16.0)

`vault.py` holds the unlocked labs (`_open`: resolved folder to `Vault`, the
data key in memory) and is the only place files in a lab are encrypted or
decrypted. Encryption is per file, AES-256-GCM, the lab's id as associated
data, and recognised by an 8-byte magic rather than by name, so names (and
everything that finds files by name: numbering, the list, sidecars, clips
beside posters, removed/) are untouched, and a half-converted lab still reads.

Two choke points keep it from leaking:

- **Writes**: `storage.write_atomic` passes every write through
  `vault.guard()`. Inside an unlocked lab the bytes are encrypted; inside a
  locked one (any folder up to three levels above with a `lab.key`) the write
  raises `Locked`. `plain=True` is for user exports and Save as.
- **Reads**: `vault.read`, `read_text`, `load_image`, `image_reader`,
  `image_size` and `media_source` replace direct file reads in lab, edits,
  imageops, labsnips, player, preview, removedview, clips, cliptrim, report and
  reportpdf. Plain files pass straight through, so labs that are not
  encrypted, and the history folder, behave exactly as before.

Qt can only record or re-encode video to a file path, so a recording (in
`.recording` under the save folder) and a trim (in the vault's private temp
folder, `vault.scratch`) are written plain and then sealed into the lab
(`vault.seal`). Anything handed to another program goes through
`vault.handoff`, a decrypted copy in that temp folder; `lock()` wipes it, and
`quit()` locks every lab.

`lab.start()` refuses an encrypted lab that is not unlocked, because
`_load_state` of a locked lab reads as empty and a blank record would
otherwise be written (it would be refused by guard() anyway).

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
capture, and encryption at rest for lab folders. See
`ROADMAP.md`.
