#!/usr/bin/env bash
# Builds the Kali / Debian / Ubuntu package from a release build (0.20.0).
#
#   bash build_deb.sh dist/ShadowSnip 0.20.0 out/
#
# makes out/shadowsnip_0.20.0_amd64.deb, which installs:
#
#   /opt/shadowsnip/ShadowSnip                       the program (PyInstaller, one file)
#   /opt/shadowsnip/gio-modules/                     empty: see install.sh on GIO modules
#   /usr/bin/shadowsnip                              the command, the same launcher install.sh writes
#   /usr/share/applications/shadowsnip.desktop       the applications menu entry
#   /usr/share/icons/hicolor/256x256/apps/shadowsnip.png
#
# Install it with   sudo apt install ./shadowsnip_0.20.0_amd64.deb
# (apt, not dpkg -i, so the system packages it needs come with it), and
# remove it with   sudo apt remove shadowsnip   (snips and labs are kept).
# Starting at login stays a per-user choice: Settings > Appearance.
#
# The GitHub workflow runs this for every release; it needs dpkg-deb, which
# every Debian-family system has.

set -euo pipefail

binary="${1:?usage: build_deb.sh <ShadowSnip binary> <version> <output folder>}"
version="${2:?version, e.g. 0.20.0}"
out="${3:?output folder}"
version="${version#v}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ -x "$binary" ]] || { echo "Not an executable: $binary" >&2; exit 1; }
[[ "$version" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || { echo "Not a version: $version" >&2; exit 1; }

root="$(mktemp -d)"
chmod 755 "$root"
trap 'rm -rf "$root"' EXIT

install -d "$root/DEBIAN" "$root/opt/shadowsnip/gio-modules" "$root/usr/bin" \
  "$root/usr/share/applications" "$root/usr/share/icons/hicolor/256x256/apps" \
  "$root/usr/share/doc/shadowsnip"
install -m 755 "$binary" "$root/opt/shadowsnip/ShadowSnip"
install -m 644 "$here/shadowsnip.png" "$root/usr/share/icons/hicolor/256x256/apps/shadowsnip.png"
install -m 644 "$here/README.md" "$root/usr/share/doc/shadowsnip/README.md"
touch "$root/opt/shadowsnip/gio-modules/.keep"

cat > "$root/usr/bin/shadowsnip" <<'LAUNCH'
#!/usr/bin/env bash
# ShadowSnip, installed from the .deb. The binary carries its own GLib, so
# the system's GIO plugins (gvfs, dconf) are kept away from it.
export GIO_MODULE_DIR=/opt/shadowsnip/gio-modules
exec /opt/shadowsnip/ShadowSnip "$@"
LAUNCH
chmod 755 "$root/usr/bin/shadowsnip"

cat > "$root/usr/share/applications/shadowsnip.desktop" <<'ENTRY'
[Desktop Entry]
Type=Application
Name=ShadowSnip
GenericName=Screenshot and pentest evidence tool
Comment=Snip, file evidence into labs, and build the writeup as you go
Exec=/usr/bin/shadowsnip
Icon=shadowsnip
Terminal=false
Categories=Utility;Graphics;Security;
StartupNotify=false
ENTRY

cat > "$root/usr/share/doc/shadowsnip/copyright" <<'COPY'
ShadowSnip: https://github.com/jh-infosec/ShadowSnip
The CVSS 4.0 scoring tables in cvss.py come from FIRST's calculator, under
its own licence, quoted in that file.
COPY

size_kb="$(du -sk "$root" | cut -f1)"
cat > "$root/DEBIAN/control" <<CONTROL
Package: shadowsnip
Version: $version
Section: graphics
Priority: optional
Architecture: amd64
Installed-Size: $size_kb
Depends: libxcb-cursor0, libegl1, libxkbcommon0, libfontconfig1, libdbus-1-3, libpulse0, x11-utils
Recommends: tesseract-ocr
Maintainer: jh-infosec <jh-infosec@users.noreply.github.com>
Homepage: https://github.com/jh-infosec/ShadowSnip
Description: Snipping tool for pentest evidence
 Snips are compressed to the clipboard, marked up and redacted in place,
 numbered and filed by section into a lab.md report you can paste straight
 into a writeup. Video clips, findings with CVSS, HTML, Word and PDF
 reports, and encrypted labs. Needs an X11 session (Kali's Xfce is X11).
CONTROL

cat > "$root/DEBIAN/postinst" <<'POST'
#!/bin/sh
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
POST
chmod 755 "$root/DEBIAN/postinst"

mkdir -p "$out"
target="$out/shadowsnip_${version}_amd64.deb"
dpkg-deb --root-owner-group --build "$root" "$target" >/dev/null
echo "$target"
