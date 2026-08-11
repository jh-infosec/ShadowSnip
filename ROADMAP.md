# ShadowSnip roadmap

## v0.3 - integration (next)

- Run at login toggle in Settings, writing the shortcut itself and reading
  back the real state rather than a stored flag.
- Optional upload target (SFTP or S3-compatible) that copies a link instead
  of the image, for snips too large to paste.
- Per-lab remote folder, so an engaged lab uploads into its own directory and
  the lab index can carry links rather than local paths.
- Save straight into a chosen folder per hotkey, so different combinations
  route to different projects.
- Signed release binaries so SmartScreen stops warning on first run.

## v0.4 - capture modes

- Window mode: highlight and grab the window under the cursor.
- Freeform (lasso) selection, matching Snipping Tool's freeform mode.
- Delayed capture (3s / 5s / 10s) so menus and tooltips can be caught.
- Snap the selection to detected UI element edges while dragging.
- Magnifier loupe near the cursor for pixel-exact edges.

## v0.5 - after the snip

- Lightweight annotation: pen, arrow, rectangle, highlighter, and a redaction
  block for screenshots that carry credentials or client data.
- Re-crop in the preview window without taking a new snip.
- Clipboard history strip: the last N snips, one click to re-copy.
- "Copy as" menu: PNG, JPEG, WebP, or a data URI.
- Reorder or drop entries in a lab index without editing `lab.json` by hand.

## Open questions

- Whether lab folders should be encrypted at rest. Labs collect exactly the
  material that should not sit in plain text: hashes, tokens, internal
  hostnames. The `.gitignore` stops the obvious accident, not the disk.
- Whether a lab should stop itself after a period of inactivity. The badge and
  tooltip make an engaged lab visible, but neither stops one running for days.
- Whether to add a second registered clipboard format some paste targets
  prefer (`image/png` is already offered; `DIBV5` would add alpha support but
  is inconsistently handled by receiving apps).
- Whether quantisation should be automatic based on measured colour count
  rather than the current encode-both-and-compare approach, which costs one
  extra PNG encode per snip.
