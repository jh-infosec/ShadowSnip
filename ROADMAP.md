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

## v0.7 - the pentest report (next)

- **Findings.** Mark a section as a finding with a severity (Critical, High,
  Medium, Low, Info), the affected host, and description, impact and
  remediation fields. It renders in `lab.md` as a standard finding block, so
  the report drafts itself as findings are confirmed.
- **Redaction.** Blur or black-box part of a snip (passwords, hashes, client
  names) before it is filed. Client reports need it.
- **Export.** A single HTML file or a .docx with the images embedded, ready to
  hand over, instead of `lab.md` plus a folder of images.
- **Command output as text.** While a lab runs, highlighted text can be filed
  as a code block, so commands in the report are copyable.
- **Methodology sections.** One click to lay out Recon, Enumeration, Initial
  access, Privilege escalation and Post-exploitation when a lab starts.
- **Annotation.** Arrows, boxes and highlights to point at the line that
  matters.

## v0.8 - integration

- Run at login toggle in Settings, writing the shortcut itself and reading
  back the real state rather than a stored flag.
- Optional upload target (SFTP or S3-compatible) that copies a link instead
  of the image, for snips too large to paste.
- Per-lab remote folder, so an engaged lab uploads into its own directory and
  the lab index can carry links rather than local paths.
- Save straight into a chosen folder per hotkey, so different combinations
  route to different projects.
- Signed release binaries so SmartScreen stops warning on first run.

## v0.9 - capture modes

- Window mode: highlight and grab the window under the cursor.
- Freeform (lasso) selection, matching Snipping Tool's freeform mode.
- Delayed capture (3s / 5s / 10s) so menus and tooltips can be caught.
- Snap the selection to detected UI element edges while dragging.
- Magnifier loupe near the cursor for pixel-exact edges.

## v0.10 - after the snip

- Lightweight annotation: pen, arrow, rectangle, highlighter, and a redaction
  block for screenshots that carry credentials or client data.
- Re-crop in the preview window without taking a new snip.
- Clipboard history strip: the last N snips, one click to re-copy.
- "Copy as" menu: PNG, JPEG, WebP, or a data URI.

## Notes and sections, still open

- 0.4.4 added the lab snip list and removal, 0.4.7 editing captions and notes
  in place, and 0.5.0 the outline, where snips and notes are moved between
  sections by dragging. Still missing: editing a note that is not attached to
  any snip, reordering the sections themselves, and restoring a removed snip
  from inside the app.
- Export beyond markdown. `lab.md` pastes into most things, but a
  self-contained HTML with the images inlined, or a .docx built against a
  client template, would drop straight into a report rather than needing the
  images carried alongside.
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
  question the clipboard history strip in v0.10 would answer.

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
