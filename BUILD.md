# Building and installing ShadowSnip

ShadowSnip is one codebase for Windows and Linux. The few parts that differ
(hotkeys and copy on select) are picked at startup by `platforms.py`; see
`architecture.md`. PyInstaller only builds for the system it runs on, so the
Windows .exe is built on Windows and the Linux binary on Linux. The GitHub
workflow does both on every version tag (see [Releases](#releases)).

# Windows

Three ways to run it, from least to most portable.

## 1. Straight from source

```powershell
pip install -r requirements.txt
python main.py
```

A console window stays open behind it. Fine for development, not for daily use.

## 2. No-console launcher (no build)

Double-click `run_shadowsnip.pyw`. Because the extension is `.pyw`, Windows
runs it with `pythonw.exe` and no console appears. It still depends on your
Python install and the packages in `requirements.txt`.

To run it at login: right-click `run_shadowsnip.pyw`, **Send to > Desktop**,
then move that shortcut into the startup folder. Press **Win+R**, type
`shell:startup`, Enter, and drop the shortcut in. Add ` --tray` to the end of
the shortcut's **Target** to start in the tray without opening the window.

## 3. Standalone .exe (recommended)

One self-contained file, no Python required. This is the version to hand to
anyone else.

```powershell
pip install pyinstaller
python make_icon.py          # writes shadowsnip.ico
pyinstaller ShadowSnip.spec
```

The result is `dist\ShadowSnip.exe`. The `.spec` sets no console and embeds
`shadowsnip.ico`, so there is nothing more to pass.

To run it at login: right-click `ShadowSnip.exe`, **Create shortcut**, then
move the shortcut into `shell:startup` as above. A shortcut rather than the
exe itself, so Windows starts it from its real folder.

Started by hand, ShadowSnip opens its window. For login you probably want it
to start quietly in the tray instead: right-click the startup shortcut,
**Properties**, and add ` --tray` to the end of **Target**, after the closing
quote, so it reads `"...\ShadowSnip.exe" --tray`.

# Linux (X11)

Kali, Debian, Ubuntu and similar, on an X11 session. Kali's default Xfce
desktop is X11; on Wayland, snips come out black (ShadowSnip warns at startup).

## From a clone

```bash
sudo apt install python3-venv libxcb-cursor0 x11-utils
bash install.sh              # or: bash install.sh --autostart
shadowsnip
```

`install.sh` makes a `.venv` next to the code, installs the requirements into
it, and writes a `shadowsnip` command to `~/.local/bin`, a menu entry, and with
`--autostart` a login entry that starts it in the tray. Nothing is written
outside your home folder and nothing needs sudo; it only tells you which
system packages are missing. `bash install.sh --uninstall` removes it again and
leaves your snips and labs alone.

## The standalone binary

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pyinstaller
python make_icon.py          # writes shadowsnip.ico and shadowsnip.png
pyinstaller ShadowSnip.spec
```

The result is `dist/ShadowSnip`. Put it next to `install.sh` and
`shadowsnip.png` and run `bash install.sh`, which installs the binary instead of
setting up a venv. The release download is exactly that folder.

## Hotkeys on Linux

There is no polite way for an X11 application to take a global hotkey, so
ShadowSnip asks the desktop to own it: the shortcut runs `shadowsnip --snip`
(or `--note`), and the copy that is already running takes the request. On
Xfce this is set up automatically the first time ShadowSnip runs, and shows
under Settings > Keyboard > Application Shortcuts. A combination Xfce already
uses for something else is reported and never overwritten. On other desktops,
add the shortcut yourself; ShadowSnip shows the exact command.

# Releases

`.github/workflows/build.yml` runs the tests on Windows and Linux on every
push and pull request. Pushing a version tag also builds both and attaches
them to a GitHub release for that tag:

```powershell
git tag v0.6.0
git push origin v0.6.0
```

The release then carries `ShadowSnip-v0.6.0-windows.exe` and
`ShadowSnip-v0.6.0-linux.tar.gz` (the binary, `install.sh`, the icon and the
README).

## Before tagging: the Windows check

The tests cover logic, not the real desktop. Before pushing a tag, build the
.exe and spend five minutes on the parts only a real Windows desktop can show:

1. `Ctrl+Shift+S` snips, including a drag across both monitors.
2. The snip pastes into something (Word, a browser, Discord).
3. Copy on select: a drag, a double-click (word) and a triple-click (line),
   each copied once.
4. Start a lab, snip, add a note, then check the Outline and Preview tabs.
5. Click the taskbar pin while ShadowSnip is running: the window comes up.

On Linux, the same five, with the desktop shortcut for step 1 and a middle-click
paste check for step 3.

# Tests

```powershell
pip install -r requirements-dev.txt
pytest
```

The suite covers the modules that hold logic rather than pixels: config
sanitising, the standing file and history pruning, lab numbering and the index
render, hotkey string parsing, and the compression pipeline's quantise
decision, plus the Linux hotkey and primary-selection logic against a faked
Xfce and X11. It needs no display and runs on Windows and Linux alike; on a
headless machine set `QT_QPA_PLATFORM=offscreen` first. CI runs it on both.

Nothing that needs a real desktop is covered — the tray icon, the overlay, the
clipboard writer and the mouse hook are still tested by using the application.

## Notes

- Rebuild after any source change; the exe is a snapshot.
- SmartScreen will warn on first run of an unsigned exe. **More info > Run
  anyway**. Signed binaries are a roadmap item.
- `make_icon.py` only needs running when the icon changes; the `.ico` can be
  committed so a fresh clone can build without it.
- If antivirus flags the exe, that is the copy-on-select mouse hook plus
  PyInstaller's bootloader, a common false-positive combination. Building
  without `--onefile` (a `dist\ShadowSnip\` folder instead) often avoids it.
