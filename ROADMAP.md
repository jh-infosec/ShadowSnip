# ShadowSnip roadmap

## v0.4 - integration (next)

- Run at login toggle in Settings, writing the shortcut itself and reading
  back the real state rather than a stored flag.
- Optional upload target (SFTP or S3-compatible) that copies a link instead
  of the image, for snips too large to paste.
- Per-lab remote folder, so an engaged lab uploads into its own directory and
  the lab index can carry links rather than local paths.
- Save straight into a chosen folder per hotkey, so different combinations
  route to different projects.
- Signed release binaries so SmartScreen stops warning on first run.

## v0.5 - capture modes

- Window mode: highlight and grab the window under the cursor.
- Freeform (lasso) selection, matching Snipping Tool's freeform mode.
- Delayed capture (3s / 5s / 10s) so menus and tooltips can be caught.
- Snap the selection to detected UI element edges while dragging.
- Magnifier loupe near the cursor for pixel-exact edges.

## v0.6 - after the snip

- Lightweight annotation: pen, arrow, rectangle, highlighter, and a redaction
  block for screenshots that carry credentials or client data.
- Re-crop in the preview window without taking a new snip.
- Clipboard history strip: the last N snips, one click to re-copy.
- "Copy as" menu: PNG, JPEG, WebP, or a data URI.
- Reorder or drop entries in a lab index without editing `lab.json` by hand.

## Copy on select, still open

- Every clip could go into the engaged lab. A lab already collects a session's
  screenshots; the hashes, tokens and hostnames highlighted during that same
  session are the same evidence, and they currently evaporate into the
  clipboard. A timestamped `clips.md` alongside `lab.md` would make a lab a
  full session record. The password-manager blocklist exists partly to make
  this safe to build.
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
  question the clipboard history strip in v0.6 would answer.

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
