# ShadowSnip

A Snipping Tool work-alike for Windows that copies a **compressed** PNG to the
clipboard the instant a snip finishes, and writes the same snip to disk in the
background. Saving a permanent copy afterwards is optional. the next snip
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

ShadowSnip starts in the notification area. Press **Ctrl+Shift+S** (or click
the tray icon) to snip.

## Using it

| Action | Key |
| --- | --- |
| Start a snip | `Ctrl+Shift+S`, tray click, or `python main.py --snip` |
| Drag a region | left mouse button |
| Grab the whole screen under the cursor | `F` or `Space` |
| Cancel | `Esc` or right mouse button |
| Save a permanent copy (preview window) | `Ctrl+S` |
| Copy again (preview window) | `Ctrl+C` |
| Start or stop a lab | tray menu |

Selections can cross monitors, including monitors on different scale factors.

## Lab mode

A lab is a named folder that collects a whole session's worth of snips. Click
**Start lab...** in the tray menu, type a name, and every snip from then on is
also written into that lab, numbered in the order it was taken. Everything
else behaves exactly as before: the clipboard still gets the compressed PNG,
and `latest.png` is still replaced each time.

```
tray menu -> Start lab... -> "htb-lame"
snip, snip, snip
tray menu -> Stop lab (htb-lame)
```

While a lab is engaged the tray icon carries a green badge, the tooltip shows
the lab name and how many snips it holds, and **Open save folder** becomes
**Open lab folder**. **Open a lab** lists recent labs so an old one is one
click away.

Each lab folder holds the images plus two files:

| File | What it is |
| --- | --- |
| `lab.json` | the record: name, start time, one entry per snip |
| `lab.md` | rendered from `lab.json`, every image embedded in order |

`lab.md` is meant to be pasted straight into a writeup. If the caption box is
switched on, whatever is typed in the preview window after a snip appears in
the index above that image.

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

Right-click the tray icon → **Settings**.

| Setting | Effect |
| --- | --- |
| Snip hotkey | Click the field and press the combination you want |
| Save folder / replaced file name | Where the standing snip lives |
| Keep a timestamped copy | Turns on the `history` folder, pruned to a fixed count |
| File format | What goes to disk: PNG, WebP or JPEG. The clipboard always gets PNG |
| Longest edge | Downscale anything larger, in pixels. `Full size` disables it |
| Reduce the colour palette | Palette-quantise when it produces a smaller PNG; the truecolour version wins if it does not |
| PNG effort | zlib level 0–9 |
| Also copy a plain bitmap | Adds `CF_DIB` for apps that cannot read PNG from the clipboard |
| Show the preview window | Off means a tray notification instead |
| Labs folder | Where labs live. Blank means a `labs` folder inside the save folder |
| Write a lab.md index | Keeps `lab.json` and the rendered `lab.md` up to date |
| Offer a caption box | Shows a caption field in the preview window during a lab |

## Building a standalone .exe

```powershell
pip install pyinstaller
pyinstaller --noconsole --onefile --name ShadowSnip main.py
```

The result is `dist\ShadowSnip.exe` with no Python install required. The icon
is drawn at runtime, so there are no image assets to bundle.

To start it with Windows, put a shortcut to the exe in:

```
shell:startup
```

## Known limits

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
- Lab folders are not encrypted. Screenshots taken during a lab routinely
  contain hashes, tokens and internal hostnames, and they sit on disk in plain
  sight. A `.gitignore` is written into the labs root so none of it reaches a
  repository by accident, but that is the only protection there is so far.
