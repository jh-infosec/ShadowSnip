# ShadowSnip roadmap

ShadowSnip's main purpose is evidence capture for penetration testing and the
writeup that follows. The next versions lean into that.

## Done in v0.6.0 - Linux

ShadowSnip runs on Linux (X11) as well as Windows, from one codebase, with
both builds attached to every GitHub release by the CI workflow.

## Linux, still open

- **Wayland.** Capture through the desktop's screenshot portal
  (`org.freedesktop.portal.Screenshot`), and the frozen-frame overlay drawn
  over the image the portal returns. Copy on select would need the
  compositor's primary-selection protocol.
- Hotkeys set automatically on GNOME and KDE as they are on Xfce (both store
  custom shortcuts where a tool can write them).
- A packaged install: an AppImage, or a .deb for Kali.

## Done in v0.7.0 - marking up

Pen, highlighter, eraser, crop, redaction (blur or black out) and undo, on the
snip in the preview window, saved to every copy as you go. Since v0.7.7 the
same tools work on any lab snip, in the full-size view.

## Done in v0.10.0 - text and editable marks

- Copy text from a snip: the Text tool reads it (Windows OCR, or Tesseract on
  Linux) and copies picked words or all of it.
- Quick redact: finds passwords, keys, hashes, emails and phone numbers (and
  IP addresses on request) and covers them in one undoable step.
- Marks stay editable after you leave a snip, redactions included, through
  the hidden `.edits` sidecars.

## Done in v0.11.0 - the rest of mark-up

Arrows, lines, boxes and ellipses; labels; numbered steps; callouts;
spotlight; magnify; the evidence stamp; Select to move, resize and retype any
of them; redo; Shift for straight lines.

## Marking up, still open

- Moving a pen line, highlight or redaction. Deliberately left out of 0.11:
  a redaction that can be dragged off what it hides is a way to leak a
  password by accident, and freehand lines are rarely worth moving.
- OCR in more languages on Linux depends on the Tesseract language packs
  installed; a hint in the Text tool when the result looks like the wrong
  language would help.

## Done in v0.9.0 - the pentest report

Findings (severity, host, description, impact, remediation) with a summary
table, export to a self-contained HTML page or a Word document, command output
filed as code blocks, and the methodology phases laid out in one click.

## The report, still open

- Exporting into a client's own Word template (styles and cover page).
- CVSS 4.0 vectors (3.1 is scored today; 4.0's score comes from a lookup
  table, not a formula).
- A cover page and table of contents in the PDF.

## Later - integration

- Run at login toggle in Settings, writing the shortcut itself and reading
  back the real state rather than a stored flag.
- Optional upload target (SFTP or S3-compatible) that copies a link instead
  of the image, for snips too large to paste.
- Per-lab remote folder, so an engaged lab uploads into its own directory and
  the lab index can carry links rather than local paths.
- Save straight into a chosen folder per hotkey, so different combinations
  route to different projects.
- Signed release binaries so SmartScreen stops warning on first run.

## Done in v0.12.0 - capture modes

Window and freeform snips from a mode bar on the snipping screen, the colour
picker, Alt+N for a new snip, and Print Screen as a snip key.

## Done in v0.14.0 - video clips

Recording an area to MP4 with pause, an optional microphone and a length
limit; clips filed like snips with a poster; copy as a file; Save as GIF.

## Done in v0.14.1 - clips play in ShadowSnip

A finished clip shows in the main window and is picked out in the list;
clips play in the main window and the full-size view, with the video player
one click away and a setting for which is the default.

## Done in v0.14.2 - trimming clips

Trim with a two-handled bar, frame-exact, with the recorded clip kept for
Undo trim; player controls styled and inset like the rest of the window.

## Done in v0.15.0 - the report

CVSS 3.1 scores on findings, PDF export, findings-only export in every
format, and restoring removed snips from inside ShadowSnip.

## Next: v0.16 - encrypted labs

Lab folders encrypted at rest, with the unlock and recovery choices still to
be settled.

## Video clips, still open

- System sound (Windows' loopback capture), which Qt does not offer.
- Marking up a clip (an arrow that stays on screen for a few seconds).

## Done in v0.13.0 - catching what disappears

Delayed snips, the magnifier while snipping, covered windows from the window
itself on Windows, the Blur shape, changing a mark's colour and size after it
is drawn, and Quick redact learning the lab's targets.

## Capture modes, still open

- Snap the selection to detected UI element edges while dragging.
- Window snips on Wayland, which does not let one program list another's
  windows; the screenshot portal's own window picker is the likely route.
- Covered windows on Linux, which would need a compositor that keeps each
  window's picture (X11 has none of its own).

## After the snip

- Clipboard history strip: the last N snips, one click to re-copy. (0.8.0's Recent snips list already re-copies any recent snip from the window; the strip would do it without opening it.)
- "Copy as" menu: PNG, JPEG, WebP, or a data URI.

## Notes and sections, still open

- 0.4.4 added the lab snip list and removal, 0.4.7 editing captions and notes
  in place, and 0.5.0 the outline, where snips and notes are moved between
  sections by dragging. Still missing: editing a note that is not attached to
  any snip, reordering the sections themselves, and restoring a removed snip
  from inside the app.
- Export beyond markdown: done in 0.9.0 (HTML and Word). A client-template
  export is listed under the report above.
- A note is filed against whatever section is set at that moment, so a note
  typed after moving on lands in the new section. Whether an attached note
  should instead inherit its snip's section is a real question; today the
  answer is no, and the `_Evidence:_` reference is the compromise. **Move snip
  here** covers the common case from the other direction, by moving the snip to
  the note rather than the note to the snip.
- Notes can now be moved between sections by dragging them in the outline.

## Copy on select, still open

- An allow-list mode -- off everywhere except a named set of programs -- was
  considered and deliberately left out. Two lists with opposite meanings in
  one settings window is a good way to be confused about why nothing copied,
  and the block list plus the built-in class and process guards cover the
  cases seen so far. Worth revisiting only if the block list starts growing
  faster than the list of programs the feature is actually wanted in.

- Every clip could become a note in the current section. Notes and sections
  now exist, so this is a two-line connection rather than a feature: the
  hashes, tokens and hostnames highlighted during a session are the same
  evidence as the screenshots, and they still evaporate into the clipboard. The
  password-manager blocklist exists partly to make this safe. The open question
  is not how but whether — an automatic clip is unreviewed text landing in the
  writeup, and a lab would fill with noise unless it is opt-in per lab, or held
  in a staging list the user promotes from.
- The clipboard-owner check is the right default and the wrong one under
  clipboard redirection. RDP's `rdpclip.exe` and VMware/VirtualBox guest tools
  take clipboard ownership as part of syncing it to the host, and if that
  lands inside the 120 ms read-back the clip is thrown away as unverified. The
  text is still on the clipboard, so nothing is lost, but the feature looks
  dead in exactly the environment a pentest lives in. Options, in rough order
  of preference: accept a known redirection helper as a proxy for the target
  process; fall back to the sequence-number check alone when the owner is one
  of those helpers; or a plain **Trust the clipboard in remote sessions**
  setting. Needs measuring on a real RDP session first — the race may be rare
  enough not to matter.
- Shift+click to extend a selection is missed, because every modifier blocks.
  Fixable by clearing the modifier state in the injected keystroke rather than
  refusing outright, which needs `SendInput` instead of `keybd_event`.
- Middle-click paste, the other half of what Linux gives you. The mouse hook is
  already there. Off by default, since middle-click closes tabs and starts
  autoscroll.
- UI Automation `TextPattern` could read a selection without synthesising a
  keystroke at all, which would remove the whole class of misfire risk. It
  needs `comtypes`, and support is patchy: good in Office and native controls,
  partial in Chromium, absent in terminals. Worth measuring before adopting.
- Copy on select silently replaces a snip on the clipboard. Whether the two
  should share a small history, rather than one overwriting the other, is the
  question the clipboard history strip in v0.12 would answer.

## Open questions

- Whether lab folders should be encrypted at rest. Labs collect exactly the
  material that should not sit in plain text: hashes, tokens, internal
  hostnames. The `.gitignore` stops the obvious accident, not the disk.
- Whether a lab should stop itself after a period of inactivity. The badge and
  tooltip make an engaged lab visible, but neither stops one running for days.
- Whether to add a second registered clipboard format some paste targets
  prefer (`image/png` is already offered; `DIBV5` would add alpha support but
  is inconsistently handled by receiving apps).
- Whether the colour-count ceiling should adapt to the grab rather than being
  a fixed number, and whether the extra PNG encode under the ceiling is worth
  keeping now that the count is measured anyway.
