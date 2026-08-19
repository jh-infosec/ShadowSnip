# Building and installing ShadowSnip

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
`shell:startup`, Enter, and drop the shortcut in.

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

## Tests

```powershell
pip install -r requirements-dev.txt
pytest
```

The suite covers the modules that hold logic rather than pixels: config
sanitising, the standing file and history pruning, lab numbering and the index
render, hotkey string parsing, and the compression pipeline's quantise
decision. It needs no display and no Windows, so it runs anywhere; on a
headless machine set `QT_QPA_PLATFORM=offscreen` first.

Nothing that needs a real desktop is covered — the tray icon, the overlay, the
clipboard writer and the mouse hook are still tested by using the application.

### Notes

- Rebuild after any source change; the exe is a snapshot.
- SmartScreen will warn on first run of an unsigned exe. **More info > Run
  anyway**. Signed binaries are a roadmap item.
- `make_icon.py` only needs running when the icon changes; the `.ico` can be
  committed so a fresh clone can build without it.
- If antivirus flags the exe, that is the copy-on-select mouse hook plus
  PyInstaller's bootloader, a common false-positive combination. Building
  without `--onefile` (a `dist\ShadowSnip\` folder instead) often avoids it.
