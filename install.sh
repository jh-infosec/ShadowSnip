#!/usr/bin/env bash
# ShadowSnip installer for Linux (Kali / Debian / Ubuntu on X11).
#
#   bash install.sh               install for this user
#   bash install.sh --autostart   ...and start it in the tray at login
#   bash install.sh --uninstall   remove it again (your snips and labs are kept)
#
# Run it from the unpacked release (next to the ShadowSnip binary) or from a
# clone of the repository (next to main.py). Nothing is written outside your
# home folder and nothing needs sudo, except installing a missing system
# package, which it only tells you how to do.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/shadowsnip"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
LAUNCHER="$BIN_DIR/shadowsnip"

autostart=0
uninstall=0
for arg in "$@"; do
  case "$arg" in
    --autostart) autostart=1 ;;
    --uninstall) uninstall=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ $uninstall -eq 1 ]]; then
  rm -f "$LAUNCHER" "$APPS_DIR/shadowsnip.desktop" "$AUTOSTART_DIR/shadowsnip.desktop"
  rm -rf "$APP_DIR"
  echo "ShadowSnip removed. Snips and labs in ~/Pictures/ShadowSnip (or your"
  echo "chosen save folder) were left alone. Remove any keyboard shortcuts it"
  echo "added in Settings > Keyboard > Application Shortcuts."
  exit 0
fi

mkdir -p "$APP_DIR" "$BIN_DIR" "$APPS_DIR"

# -- system packages Qt needs ---------------------------------------------------
missing=()
if command -v ldconfig >/dev/null 2>&1; then
  ldconfig -p | grep -q 'libxcb-cursor.so.0' || missing+=("libxcb-cursor0")
fi
command -v xprop >/dev/null 2>&1 || missing+=("x11-utils")
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "Missing system packages: ${missing[*]}"
  echo "  libxcb-cursor0  Qt needs it to open any window on X11"
  echo "  x11-utils       provides xprop, used to skip password managers in copy on select"
  echo "Install them with:"
  echo "  sudo apt install ${missing[*]}"
  echo
fi

# -- the program itself ----------------------------------------------------------
if [[ -x "$HERE/ShadowSnip" ]]; then
  # A release build: one self-contained binary.
  install -m 755 "$HERE/ShadowSnip" "$APP_DIR/ShadowSnip"
  cat > "$LAUNCHER" <<LAUNCH
#!/usr/bin/env bash
exec "$APP_DIR/ShadowSnip" "\$@"
LAUNCH
elif [[ -f "$HERE/main.py" ]]; then
  # A clone of the repository: run from source in its own virtualenv.
  command -v python3 >/dev/null 2>&1 || { echo "python3 is needed" >&2; exit 1; }
  if [[ ! -d "$HERE/.venv" ]]; then
    python3 -m venv "$HERE/.venv"
  fi
  "$HERE/.venv/bin/pip" install --quiet -r "$HERE/requirements.txt"
  cat > "$LAUNCHER" <<LAUNCH
#!/usr/bin/env bash
exec "$HERE/.venv/bin/python" "$HERE/main.py" "\$@"
LAUNCH
else
  echo "Run this next to the ShadowSnip binary or next to main.py." >&2
  exit 1
fi
chmod 755 "$LAUNCHER"

if [[ -f "$HERE/shadowsnip.png" ]]; then
  install -m 644 "$HERE/shadowsnip.png" "$APP_DIR/shadowsnip.png"
fi

# -- launcher entry, so it is in the applications menu ---------------------------
write_entry() {  # $1 = path, $2 = extra arguments
  cat > "$1" <<ENTRY
[Desktop Entry]
Type=Application
Name=ShadowSnip
GenericName=Screenshot and pentest evidence tool
Comment=Snip, file evidence into labs, and build the writeup as you go
Exec=$LAUNCHER $2
Icon=$APP_DIR/shadowsnip.png
Terminal=false
Categories=Utility;Graphics;Security;
StartupNotify=false
ENTRY
}
write_entry "$APPS_DIR/shadowsnip.desktop" ""

if [[ $autostart -eq 1 ]]; then
  mkdir -p "$AUTOSTART_DIR"
  write_entry "$AUTOSTART_DIR/shadowsnip.desktop" "--tray"
  echo "ShadowSnip will start in the tray at login."
fi

echo "Installed. Start it with:  shadowsnip"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "(~/.local/bin is not on your PATH yet; log out and back in, or run $LAUNCHER)" ;;
esac
if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; then
  echo
  echo "Note: this is a Wayland session. ShadowSnip's screen capture needs X11;"
  echo "choose an Xorg/X11 session at the login screen (Kali's Xfce default is X11)."
fi
echo "On Xfce the Ctrl+Shift+S snip shortcut is set up the first time it runs."
