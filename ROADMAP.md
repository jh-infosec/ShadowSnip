# ShadowSnip roadmap

## v0.2 - capture modes

- Window mode: highlight and grab the window under the cursor.
- Freeform (lasso) selection, matching Snipping Tool's freeform mode.
- Delayed capture (3s / 5s / 10s) so menus and tooltips can be caught.
- Snap the selection to detected UI element edges while dragging.
- Magnifier loupe near the cursor for pixel-exact edges.

## v0.3 - after the snip

- Lightweight annotation: pen, arrow, rectangle, highlighter, and a redaction
  block for screenshots that carry credentials or client data.
- Re-crop in the preview window without taking a new snip.
- Clipboard history strip: the last N snips, one click to re-copy.
- "Copy as" menu: PNG, JPEG, WebP, or a data URI.

## v0.4 - integration

- Optional upload target (SFTP or S3-compatible) that copies a link instead of
  the image, for snips too large to paste.
- Save straight into a chosen folder per hotkey, so different combinations
  route to different projects.
- Run at login toggle in Settings, writing the shortcut itself.
- Signed release binaries so SmartScreen stops warning on first run.

## Open questions

- Whether to add a second registered clipboard format some paste targets
  prefer (`image/png` is already offered; `DIBV5` would add alpha support but
  is inconsistently handled by receiving apps).
- Whether quantisation should be automatic based on measured colour count
  rather than the current encode-both-and-compare approach, which costs one
  extra PNG encode per snip.
- Whether the history folder should be encrypted at rest, given screenshots
  routinely contain tokens and internal hostnames.
