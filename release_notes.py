"""The text of a GitHub release page, from CHANGELOG.md (0.20.0).

    python release_notes.py v0.20.0 [SHA256SUMS.txt] > notes.md

Writes the version's CHANGELOG section, then which download is for which
system and how to install it, then the SHA-256 of every file attached, so
the release page says what changed and a download can be checked:

    sha256sum -c SHA256SUMS.txt                       (Linux)
    Get-FileHash ShadowSnip-v0.20.0-windows.exe       (Windows PowerShell)

The GitHub workflow runs it in the release job.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def section(changelog: str, version: str) -> str:
    """The CHANGELOG section for `version` ("0.20.0"), without its heading."""
    lines = changelog.splitlines()
    heading = re.compile(r"^##\s+(?:Latest:\s*)?v?" + re.escape(version) + r"\s*$")
    start = next((i for i, line in enumerate(lines) if heading.match(line.strip())), None)
    if start is None:
        return ""
    body = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body).strip()


def downloads(tag: str) -> str:
    version = tag.lstrip("v")
    return "\n".join([
        "## Downloads",
        "",
        "| System | File | Install |",
        "|---|---|---|",
        f"| Windows 10 / 11 | `ShadowSnip-{tag}-windows.exe` | Run it. No installer, no Python |",
        f"| Kali, Debian, Ubuntu | `shadowsnip_{version}_amd64.deb` | "
        f"`sudo apt install ./shadowsnip_{version}_amd64.deb`, then `shadowsnip` |",
        f"| Other Linux (X11) | `ShadowSnip-{tag}-linux.tar.gz` | Unpack it and run `./install.sh` |",
        "",
        "Linux needs an X11 session; Kali's default Xfce is one.",
    ])


def checksums(sums_text: str) -> str:
    rows = []
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            digest, name = parts
            rows.append(f"| `{name.lstrip('*')}` | `{digest}` |")
    if not rows:
        return ""
    return "\n".join([
        "## SHA-256",
        "",
        "| File | SHA-256 |",
        "|---|---|",
        *rows,
        "",
        "Check a download with `sha256sum -c SHA256SUMS.txt` on Linux, or "
        "`Get-FileHash <file>` in PowerShell.",
    ])


def notes(tag: str, changelog: str, sums_text: str = "") -> str:
    version = tag.lstrip("v")
    body = section(changelog, version) or f"See CHANGELOG.md for {tag}."
    parts = [body, downloads(tag)]
    sums = checksums(sums_text)
    if sums:
        parts.append(sums)
    return "\n\n".join(parts) + "\n"


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    tag = argv[0]
    sums = Path(argv[1]).read_text(encoding="utf-8") if len(argv) > 1 else ""
    changelog = (HERE / "CHANGELOG.md").read_text(encoding="utf-8")
    sys.stdout.write(notes(tag, changelog, sums))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
