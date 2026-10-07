# ShadowSnip

**Evidence capture for penetration testing, and the writeup that comes out of
it.** ShadowSnip is a snipping tool for Windows and Linux built around one job: getting from
a live engagement, a lab or a CTF box to a finished report without losing
track of which screenshot proved what.

Start a lab, set the section you are working in, and snip as you go. Every
snip is numbered, filed under that section, and written into `lab.md`, a
markdown report that grows while you work. Captions and notes attach to the
evidence they describe. When the testing is done, the structure of the report
is already there: rearrange it in the **Outline**, read it in the **Preview**,
and paste it into your writeup.

```
Start lab "client-internal"  ->  section "10.0.0.5 / SMB"  ->  snip, caption, note
                             ->  section "10.0.0.5 / Web"  ->  snip, snip
lab.md: numbered evidence, under the right headings, with your notes in place
```

It is also a fast everyday snipping tool: a **compressed** PNG goes to the
clipboard the instant a snip finishes, and the same snip is written to disk in
the background.

## Why it exists

Screenshots are the evidence in a pentest report, and they are usually the
messiest part of writing one. Dozens of `Screenshot (143).png` files, taken in
a hurry, have to be matched back to hosts, services and findings days later,
and the one that proves the finding is always the one that is missing.

ShadowSnip records that structure while the work is happening instead:

- **Sections** say where you are (host, service, finding), so every snip and
  note is filed as it is taken.
- **Numbering** keeps evidence in capture order, which is the order the attack
  path happened in.
- **Captions and notes** put the sentence about a screenshot next to it, while
  you still remember what it shows.
- **The outline and preview** let you fix the report's structure before you
  paste it, rather than after.
- **Copy on select** catches commands and output as text without breaking
  stride.

It is built for Hack The Box and similar labs, practice exams, and client
engagements alike. See [Known limits](#known-limits) before using it on client
data: lab folders are not encrypted.

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

ShadowSnip runs on **Windows 10/11** and on **Linux with X11** (Kali, Debian,
Ubuntu and similar; Kali's default Xfce desktop is X11). Each release on
GitHub has a download for each:

| Platform | Download | Install |
| --- | --- | --- |
| Windows | `ShadowSnip-<version>-windows.exe` | Run it. No installer, no Python needed. |
| Linux | `ShadowSnip-<version>-linux.tar.gz` | Unpack it and run `./install.sh` (add `--autostart` to start in the tray at login) |

### From source, Windows

Needs Python 3.10+.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### From source, Linux

Needs Python 3.10+ and two system packages: `libxcb-cursor0`, which Qt needs to
open a window on X11, and `x11-utils`, which provides `xprop` for copy on
select.

```bash
sudo apt install python3-venv libxcb-cursor0 x11-utils
git clone https://github.com/jh-infosec/ShadowSnip.git
cd ShadowSnip
bash install.sh         # makes a .venv, installs a `shadowsnip` command and a menu entry
shadowsnip
```

ShadowSnip opens its window and puts an icon in the notification area. Press
**Ctrl+Shift+S** to snip; click the tray icon to bring the window back.
`--tray` starts it in the tray without the window, for the login shortcut.

### What differs on Linux

| | Windows | Linux |
| --- | --- | --- |
| Snip hotkey | Registered by ShadowSnip itself | Set in the desktop's own keyboard shortcuts. On Xfce ShadowSnip adds them for you the first time it runs (Settings > Keyboard > Application Shortcuts shows them); on other desktops it tells you the command to bind. The shortcut stays after ShadowSnip quits, so pressing it also starts ShadowSnip. |
| Quick-note hotkey | Registered by ShadowSnip | Same as the snip hotkey: a desktop shortcut that runs `shadowsnip --note` |
| Copy on select | A mouse hook and a synthetic Ctrl+C | X11 already puts highlighted text in the *primary selection* (what middle-click pastes); ShadowSnip copies it to the clipboard. No hook and no keystroke, so a terminal can never receive a stray Ctrl+C. Each selection is copied once it stops changing. |
| Settings file | `%APPDATA%\ShadowSnip\config.json` | `~/.config/shadowsnip/config.json` |
| Start at login | A shortcut in `shell:startup` with `--tray` | `bash install.sh --autostart` |

Everything else (snipping, labs, sections, notes, the outline and preview,
removal, the viewer) is the same code on both.

## Using it

| Action | Key |
| --- | --- |
| Start a snip | `Ctrl+Shift+S`, the tray menu, or `python main.py --snip` |
| Jot a note into the lab | `Ctrl+Shift+N`, or **Add note...** in the tray menu |
| Open the window | starting ShadowSnip opens it; afterwards click the tray icon, or start it again (the taskbar pin) |
| Start hidden in the tray | `ShadowSnip.exe --tray` on Windows, `shadowsnip --tray` on Linux (for the login shortcut) |
| Start or stop a lab | **Start lab** in the preview window, or the tray menu |
| Drag a region | left mouse button |
| Grab the whole screen under the cursor | `F` or `Space` |
| Cancel | `Esc` or right mouse button |
| Save a permanent copy (preview window) | `Ctrl+S` |
| Copy again (preview window) | `Ctrl+C` |
| Undo the last mark on the snip | `Ctrl+Z`, or the round undo button |
| Save caption and note edits in the lab panel | `Ctrl+Enter`, or **Save changes** |

## Marking up a snip

The snip in the preview window can be drawn on straight away. The tool strip
above it has:

| Tool | What it does |
| --- | --- |
| **Pen** | Draws in 30 colours, 1 to 24 px wide. The colours are in six rows by family (greys, reds, oranges and yellows, greens, blues, purples), each running light to dark |
| **Highlighter** | A see-through marker in six bright colours in spectrum order, 6 to 48 px wide, so the text under it stays readable |
| **Eraser** | Drag across a pen line, highlight or redaction to remove the whole mark |
| **Crop** | Drag the area to keep |
| **Redact** | Drag over something to hide it, with **Black out** (solid black, nothing of the original survives) or **Blur** (smeared; hides text, but the layout can still show) |
| **Undo** | The round arrow, or `Ctrl+Z`: takes back the last mark, erase or crop, one at a time |

**Left-click** a tool to pick it up, and left-click it again (or press Esc) to
put it down. **Right-click** a tool for its options: width and colour for the
pen and highlighter, blur or black out for redaction. One tool is in hand at a
time, shown in blue, and hovering any tool says what it does. Over the
screenshot, the pointer becomes the tool at its real size (the pen's dot, the
highlighter's tip, the eraser's circle, or guide lines for crop and redact,
which also carry a small badge saying which of the two is in hand). Widths and colours are remembered
between runs. The tools are shown from the first launch, greyed out until there
is a snip, and each new snip starts with no tool selected, so a stray click
cannot draw on it. With no tool in hand, Esc closes the window as before.

**Right-click on the snip** for more:

- On a redaction, any time: switch it between **Black out** and **Blur**. The
  current one is ticked, and undo switches it back.
- Anywhere on the snip with no tool in hand: **Save as...** and **Copy**, the
  same as the buttons, including any mark-up not yet saved.

**Edits are saved as you go.** Half a second after the last change, the edited
snip replaces every copy ShadowSnip made of it: the clipboard, `latest.png`,
the copy in the lab, and the history copy if history is on. Each edit is drawn
fresh from the original capture, so editing again and again costs nothing in
quality, and undo can always go back to the start.

For passwords, hashes and client details, use **Black out**: a blur can still
show how long a line was. A redaction protects the files ShadowSnip writes; a
copy pasted somewhere before you redacted, or held in Windows clipboard history
(`Win+V`), is outside its reach, so redact before pasting.

Selections can cross monitors, including monitors on different scale factors.
The snip finishes when you let go of the button, and only then: Windows can
take the mouse away from the overlay as the pointer crosses onto another
monitor, and ShadowSnip checks the physical button before believing it.

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

On Linux none of the following is needed: X11 tracks highlighted text itself,
and ShadowSnip copies it from there (see [What differs on Linux](#what-differs-on-linux)).
The password-manager list and **Never copy from** apply the same way, by
process name, and if the program in front cannot be identified the selection
is not copied.

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

Each run of clicks copies once. A double-click waits until your double-click
speed has passed (half a second by default) before copying the word, because
a third click can still arrive and turn it into a line. A triple-click copies
the line straight away.

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

`lab.md` is meant to be pasted straight into a writeup. Captions and notes are
added in the lab panel beside the image (see below), and appear in `lab.md`
above and beneath their image.

### The report: Outline and Preview

The lab panel beside the image has three tabs:

| Tab | What it is for |
| --- | --- |
| **Snips** | Every snip in the lab, newest first, with its section, caption and notes |
| **Outline** | `lab.md` as a tree: sections, the snips in them, the notes under those. Drag a snip or note onto a section to file it there, or above or below another entry to move it to that spot. A snip always takes its attached notes with it. |
| **Preview** | `lab.md` rendered as it will read, screenshots scaled to fit, with **Open lab.md** to edit the file itself |

Rearranging in the outline is saved to `lab.json` and `lab.md` straight away.
Once you have moved something by hand, the order of the sections is kept as it
is, so emptying a section's first snip does not reshuffle the report.

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
| **Add a note to this snip** in the lab panel, **Ctrl+Enter** or **Save changes** to file | Writing about a snip: the one on screen, or any other you select in the list |
| `Ctrl+Shift+N` from anywhere | One line, caught without breaking stride |

A note added in the lab panel is attached to the selected snip and renders
directly beneath that image as a quote: evidence, then the sentence about the
evidence, which is the arrangement a report wants. The quick-note hotkey never
attaches; it files a line on its own under the current section.

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

### The lab snip list, and removing a snip

While a lab is running, the preview window lists every snip in it beside the
image, newest first: number, time, section, caption and attached notes. Select
one and the box underneath shows exactly how it was filed. The snip on screen
is bold and marked `*`. The list updates by itself as soon as a snip lands. While
a lab runs the lab button is amber and reads **Stop lab: name**. The **Snip list** button on the toolbar hides or
shows the list, and ShadowSnip remembers which you chose.

Hovering a row shows a bigger preview, and the selected row is outlined in
blue. The
selected snip appears larger under the list with its caption and notes. They
are shown locked, so clicking through snips cannot change them by accident:
hover over one to see the whole text when it is too long for its box, and
double-click it to edit. **Save changes** (or Enter in the caption, or
Ctrl+Enter) writes them into `lab.md`, emptying a note removes it, and the
empty box at the bottom adds a new one. Moving to another snip saves what you
typed. Click the thumbnail, press **Expand**, double-click a row or
press Space to see the snip full size; Left and Right step through the lab.

**Remove from lab** (or Delete on the list) takes the selected snip out of the
lab after asking. Nothing is deleted: the image goes to a `removed` folder
inside the lab, its record goes to a `removed` list in `lab.json`, and `lab.md`
is re-rendered without it. Notes attached only to that snip go with it; a note
also attached to another snip stays. The next snip reuses the freed number. To
undo, move the image back up a level and its record back into `entries`.

Old labs from 0.3.x open and render without being migrated. Their entries have
no section, so they appear at the root of the tree.

Starting a lab with a name that already exists resumes it and carries on
numbering, so a crash or a restart costs nothing. The name is used as the
folder name exactly as typed, and it must be a single plain folder name inside
the labs folder: no `\` or `/`, no `.` or `..`, no drive letter, none of
`: * ? " < > |`, and not a Windows device name such as `CON` or `NUL`. Anything
else is refused with the reason, never adjusted, so a lab can never write
outside the labs folder.

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

On Windows, three options, least to most portable: from source with
`python main.py`, a no-console `run_shadowsnip.pyw` launcher, or a standalone
`ShadowSnip.exe`. The exe is the one to hand to anyone else. On Linux,
`install.sh` sets up either a clone of the repository or the release binary.
See `BUILD.md` for building both and for starting ShadowSnip at login.

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
- **Linux needs X11, not Wayland.** Wayland does not let an application read
  the screen, so snips on a Wayland session come out black, and copy on select
  cannot follow the selection there. ShadowSnip warns at startup on Wayland.
  Kali's default Xfce session is X11; on Ubuntu or Fedora, choose the Xorg
  session at the login screen.
- **On Linux, hotkeys outside Xfce are set by hand.** ShadowSnip writes the
  shortcuts into Xfce itself; on GNOME, KDE and others it shows the command to
  bind (`shadowsnip --snip`, `shadowsnip --note`) instead.
- **On Linux, copy on select copies once the selection stops changing**, about
  a third of a second after you let go, and reports every copy as a
  "selection": X11 does not say whether text was dragged over or
  double-clicked. It needs `xprop` (`x11-utils`) and will not start without it.
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
