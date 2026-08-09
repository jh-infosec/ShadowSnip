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

Selections can cross monitors, including monitors on different scale factors.

## Where files go

```
%USERPROFILE%\Pictures\ShadowSnip\
├─ latest.png              replaced by every snip
└─ history\                only when history is switched on
   └─ snip_2026-08-09_14-31-07-482.png
```

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
