# ShadowSnip

A Snipping Tool work-alike for Windows that copies a **compressed** PNG to the
clipboard the instant a snip finishes, and writes the same snip to disk in the
background. Saving a permanent copy afterwards is optional — the next snip
simply replaces the standing file.

```
press hotkey -> screens freeze -> drag -> clipboard + disk, immediately
```

## What it does differently

| Snipping Tool | ShadowSnip |
| --- | --- |
| Copies a raw bitmap to the clipboard | Copies a compressed PNG (plus an optional bitmap for older apps) |
| Saving is a separate deliberate step | Every snip is already written to disk when the drag ends |
| Each save asks for a filename | One standing file, replaced each time; **Save as...** is there when you want to keep one |

A 3840×2160 grab is about 24 MB as a raw bitmap. As a PNG from the same
pipeline it is typically 200–900 KB, so pasting into Slack, Teams, Discord,
Word or a browser moves far less data.

## Install

Needs Python 3.10+ on Windows.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

ShadowSnip starts in the notification area. Press **Ctrl+Shift+S** to snip;
click the tray icon to open the preview window.

## Using it

| Action | Key |
| --- | --- |
| Start a snip | `Ctrl+Shift+S`, the tray menu, or `python main.py --snip` |
| Jot a note into the lab | `Ctrl+Shift+N`, or **Add note...** in the tray menu |
| Open the window | click the tray icon |
| Start or stop a lab | **Start lab** in the preview window, or the tray menu |
| Drag a region | left mouse button |
| Grab the whole screen under the cursor | `F` or `Space` |
| Cancel | `Esc` or right mouse button |
| Save a permanent copy (preview window) | `Ctrl+S` |
| Copy again (preview window) | `Ctrl+C` |

Selections can cross monitors, including monitors on different scale factors.

## Copy on select

Toggle **Copy on select** in the preview window or the tray menu. While it is
on, highlighting text anywhere copies it, with no Ctrl+C and no right-click.
This is what Linux gives you for free with the PRIMARY selection.

| Gesture | What is copied |
| --- | --- |
| Drag across text | the selection |
| Double-click | the word |
| Triple-click | the line or paragraph |

A small confirmation appears next to the cursor for about a second, so a clip
that worked and a clip that quietly did nothing do not look the same.
Re-selecting the same text twice in a row is only announced once.

Windows has no API for "the user just highlighted something", so what happens
underneath is a mouse hook watching for a finished left-button drag, a
synthesised Ctrl+C into the focused window, and a check of the clipboard
sequence number to see whether anything actually moved. It also verifies that
focus stayed in that window and that the same process owns the new clipboard
contents before reading them. If anything is uncertain, it leaves the
clipboard alone and reports nothing.

Double-click takes a slightly different route. A low-level mouse hook never
receives `WM_LBUTTONDBLCLK` — that message is made further up the stack, when
an event is dispatched to a window, so it only exists inside the application
being clicked. ShadowSnip applies the same rule Windows does, two presses
inside your double-click speed and inside the double-click rectangle, and
counts them itself.

Because a stray Ctrl+C can do real damage, some windows are left alone:

| Window | Why |
| --- | --- |
| Consoles | Ctrl+C with nothing selected is a break, and cancelling a running scan by accident is not a good trade. Windows Terminal has `copyOnSelect` built in, which is the better answer there |
| VM consoles, RDP and SSH clients | The same reason, one level down. A Kali terminal inside VMware is a shell where Ctrl+C is SIGINT, but the window Windows sees is an ordinary VMware window, so the class list above cannot spot it. VMware, VirtualBox, `mstsc`, VNC, PuTTY and MobaXterm are skipped by executable name instead |
| Explorer and the desktop | A rubber-band drag selects files, and Ctrl+C would put those files on the clipboard |
| Password managers | Not a misfire risk — the opposite. Double-clicking an entry in KeePass copies the password, and a feature that reads the clipboard back automatically has no business near that |
| ShadowSnip itself | The selection overlay is dragged with the same button |

KeePass, KeePassXC, 1Password, Bitwarden, Dashlane, Enpass, NordPass, Keeper,
Proton Pass, RoboForm, LastPass and the Windows credential prompt are always
skipped, and that list is not switchable: the cost of it being wrong is that
you press Ctrl+C like everyone else, and the cost of the other mistake is a
password somewhere it should never be. **Never copy from** in Settings adds
your own executable names to it. A process whose name cannot be determined is
also skipped, so a protected or elevated app never becomes an exception.

Nothing fires while Ctrl, Shift, Alt or Win is held, since Ctrl+Shift+C means
other things in browsers and IDEs, and nothing fires for a drag shorter than
8 pixels unless it was part of a double-click.

One thing to expect: double-click means "open this" in plenty of in-app list
and tree views — a file tree, a message list — and in those the Ctrl+C is
harmless but may put something uninteresting on the clipboard. Turn
**Also copy on double-click** off if it gets in the way; drag-to-copy carries
on working.

It is off by default, and worth knowing why: it needs a system-wide mouse
hook, and a hook plus synthetic keystrokes plus automatic clipboard reads is
the same combination an infostealer uses. On your own machine that is fine.
On a managed machine, expect endpoint security to take an interest.

For the same reason it does not survive a restart. Leaving it on once does not
sign you up for it running every morning after that; ShadowSnip always starts
with it off, and you turn it on for the session you want it in.

## Lab mode

A lab is a named folder that collects a whole session's worth of snips. Click
**Start lab** in the preview window (or **Start lab...** in the tray menu),
type a name, and every snip from then on is also written into that lab,
numbered in the order it was taken. Starting a lab while a snip is on screen
files that snip into it too. Everything
else behaves exactly as before: the clipboard still gets the compressed PNG,
and `latest.png` is still replaced each time.

```
Start lab -> "htb-lame"
snip, snip, snip
Stop lab (htb-lame)
```

While a lab is engaged the tray icon carries a green badge, the tooltip shows
the lab name and how many snips it holds, and **Open save folder** becomes
**Open lab folder**. **Open a lab** lists recent labs so an old one is one
click away.

Each lab folder holds the images plus two files:

| File | What it is |
| --- | --- |
| `lab.json` | the record: name, start time, current section, one entry per snip and per note |
| `lab.md` | rendered from `lab.json`, the section tree with every image and note in place |

`lab.md` is meant to be pasted straight into a writeup. If the caption box is
switched on, whatever is typed in the preview window after a snip appears in
the index above that image.

### Sections

A lab carries a **current section**: a breadcrumb you set as you work.

```
10.10.10.3 / SMB / anonymous share
```

Everything captured while it is set — snips and notes alike — is filed under
it, and `lab.md` renders those paths as nested headings. That is where the
structure comes from, and it costs nothing at the end: there is no pile of
screenshots to sort into an order the night the report is due, because setting
the breadcrumb *is* how you say "I'm on SMB now".

Set it in the box in the preview window, or **Set section...** in the tray
menu. Levels are separated with `/`, whitespace is tidied up, and the depth is
capped at six because markdown has nowhere to put a seventh. Leave it empty and
things are filed at the root of the lab. The section lives in `lab.json` rather
than the config, so it belongs to the lab: resuming one puts you back where you
were.

The box is a **picker** as well as a text field — it lists every breadcrumb the
lab already uses, parents included. Returning to `10.0.0.3/SMB` after an hour on
HTTP is one click rather than retyping it from memory, which is how you end up
with `SCAN` and `SCANvv2` as two branches of the same tree and only notice in
the writeup.

**Move snip here** re-files the snip on screen under the current section. The
natural rhythm is snip first, name the section a moment later — which leaves
the snip at the root while the notes about it are filed under the breadcrumb.
This is the one-click repair, and it is a button rather than a guess.

Sections appear in `lab.md` in the order you first used them, not
alphabetically — the work happened in an order and the writeup should follow it.

### Notes

Two ways in, for two different moments:

| Route | For |
| --- | --- |
| The note box in the preview window, **Ctrl+Enter** to file | Writing about the snip you are looking at |
| `Ctrl+Shift+N` from anywhere | One line, caught without breaking stride |

A note typed in the preview window attaches to the snip on screen by default,
and renders directly beneath that image as a quote — evidence, then the
sentence about the evidence, which is the arrangement a report wants. Untick
**Attach to this snip** and it stands on its own in the section instead. The
quick-note hotkey never attaches; it just files a line under the current
section.

A note attached to a snip that ended up in a *different* section stays where it
was written and carries an `_Evidence: 002_...png_` reference instead. A note
never silently moves out of the section it was taken in.

The result reads like this:

```markdown
# htb-lame

## 10.10.10.3

### SMB

Anonymous login allowed on tmp.

**002** - 14:33:52 - smbclient share listing

![002](002_2026-08-11_14-33-52.png)

> tmp is world-writable, so we can drop a payload
```

Sections and notes both need the lab record switched on — that is the
**Keep a lab record** setting, which is on by default.

Old labs from 0.3.x open and render without being migrated. Their entries have
no section, so they appear at the root of the tree.

Starting a lab with a name that already exists resumes it and carries on
numbering, so a crash or a restart costs nothing. The name is used as the
folder name exactly as typed; if Windows will not accept it as a folder,
ShadowSnip says so rather than failing quietly.

## Where files go

```
%USERPROFILE%\Pictures\ShadowSnip\
├─ latest.png              replaced by every snip
├─ history\                only when history is switched on
│  └─ snip_2026-08-09_14-31-07-482.png
└─ labs\
   ├─ .gitignore           written on first use
   └─ htb-lame\
      ├─ 001_2026-08-11_14-31-07.png
      ├─ 002_2026-08-11_14-33-52.png
      ├─ lab.json
      └─ lab.md
```

The history folder is skipped while a lab is engaged, so a snip never lands in
three places at once.

Settings live in `%APPDATA%\ShadowSnip\config.json`.

## Settings

**Settings** in the preview window, on the right next to Close, or right-click
the tray icon → **Settings**.

| Setting | Effect |
| --- | --- |
| Snip hotkey | Click the field and press the combination you want |
| Quick note hotkey | The same, for the one-line note box |
| Save folder / replaced file name | Where the standing snip lives |
| Keep a timestamped copy | Turns on the `history` folder, pruned to a fixed count |
| File format | What goes to disk: PNG, WebP or JPEG. The clipboard always gets PNG |
| Longest edge | Downscale anything larger, in pixels. `Full size` disables it |
| Reduce the colour palette | Palette-quantise when it produces a much smaller PNG; the truecolour version wins if it does not |
| Skip above | Colour count past which palette reduction is skipped. Keeps small text sharp. `Never skip` disables the check |
| Only if it saves | How much smaller the palette version has to be before it is kept |
| PNG effort | zlib level 0–9 |
| Also copy a plain bitmap | Adds `CF_DIB` for apps that cannot read PNG from the clipboard |
| Show the preview window | Off means a tray notification instead |
| Copy highlighted text | Copy on select, as above. Always starts off after a restart |
| Also copy on double-click | Word on a double-click, line on a triple-click, as well as drags |
| Skip consoles, Explorer, the desktop, and VM/RDP/SSH windows | Leave the windows where a synthetic Ctrl+C would misfire |
| Ignore a repeated clip | Say nothing when a clip is identical to the one before it |
| Show a confirmation near the cursor | The one-second label that says what was copied |
| Shortest drag that counts | Below this, a drag is treated as a click |
| Never copy from | Extra executable names to leave alone, on top of the built-in password managers. Two buttons fill it in for you |
| Labs folder | Where labs live. Blank means a `labs` folder inside the save folder; stop an active lab before changing this or the save folder |
| Keep a lab record | Keeps `lab.json` and the rendered `lab.md` up to date. Sections and notes need it |
| Offer a caption box | Shows a caption field in the preview window during a lab |

Every copy-on-select setting, **Never copy from** included, can be filled in
whether or not **Copy highlighted text** is ticked. Building the exclusion
list first and turning the feature on afterwards is the sensible order, and
the list is the thing you reach for when the feature is misbehaving.

Names in **Never copy from** are executable names, comma- or space-separated,
matched case-insensitively — `lightroom.exe` covers Lightroom. The `.exe` is
optional, and matching is on the whole name, so `code` does not catch
`vscode.exe`. The built-in password-manager list always applies on top of
yours.

You do not have to know the executable name. Two buttons under the field fill
it in:

| Button | When to use it |
| --- | --- |
| **Block the app I was just in** | You were in the program, opened Settings, and it is still the window behind ShadowSnip. Names whatever Alt+Tab would return to |
| **Pick an app (5s)** | Anything else. Click it, then click into the program you want excluded; whatever has focus when the countdown ends is added |

Either way the name is appended to the field, and a line underneath says what
happened — added, already listed, or nothing found. Nothing is saved until you
press OK.

The snip hotkey does nothing while Settings or another ShadowSnip dialog is
open: the selection overlay cannot take a drag from behind a modal window, so
instead of dimming the screen and getting stuck, ShadowSnip says so and brings
the dialog back to the front. Close it and snip as usual.

## Running it

Three options, least to most portable: from source with `python main.py`, a
no-console `run_shadowsnip.pyw` launcher, or a standalone `ShadowSnip.exe`.
The exe is the one to hand to anyone else. See `BUILD.md` for all three and
for starting ShadowSnip at login.

## Known limits

- **Compression is lossless apart from one step.** PNG throws nothing away;
  palette reduction does. It is skipped automatically on text-heavy and
  photographic grabs, so a code screenshot stays sharp and lands at roughly
  four times the size of the old palette version. Raise **Skip above** if you
  want the smaller files back.
- **PNG on the clipboard is not universal.** Chrome, Edge, Firefox, Word,
  Outlook, Slack, Teams, Discord, GIMP and Paint.NET all read it. A few older
  programs only understand `CF_DIB`, which is uncompressed by definition —
  that is what the bitmap fallback is for. Turning the fallback off makes the
  clipboard smaller but will break pasting in those apps.
- `Print Screen` can be claimed by the Windows Snipping Tool itself. If the
  hotkey does not register, ShadowSnip says so in a tray notification and
  keeps working from the tray menu.
- Windows only. The capture, overlay and image code are cross-platform, but
  the hotkey and clipboard layers are Win32.
- **Copy on select may go quiet while a VM or RDP session is syncing the
  clipboard.** Selecting *inside* one of those windows is skipped outright, as
  above, so this is about host applications while the sync runs in the
  background. Before reading a clip back, ShadowSnip checks that the process
  that now owns the clipboard is the one you highlighted in. That check stops an
  unrelated clipboard update being mistaken for your selection. But clipboard
  redirection works by taking ownership: `rdpclip.exe` on a remote desktop, or
  the guest additions in VMware and VirtualBox, can claim the clipboard inside
  the 120 ms read-back window. When that happens the clip is discarded as
  unverified — the text really is on the clipboard and Ctrl+V still pastes it,
  but no toast appears and nothing reaches the preview or a lab. Nothing is
  lost; it just looks like the feature stopped working. If it is happening
  constantly on a box you work in every day, say so and the ownership check
  can be made configurable.
- **Lab folders are not encrypted, and notes make that sharper.** Screenshots
  taken during a lab routinely contain hashes, tokens and internal hostnames,
  and they sit on disk in plain sight. Notes put the same material there as
  *searchable text* — a password typed into a note is a password in a plain
  file. A `.gitignore` is written into the labs root so none of it reaches a
  repository by accident, but that is the only protection there is so far.
  Treat a labs folder the way you would treat the engagement data itself.
