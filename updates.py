"""Is there a newer ShadowSnip? (0.20.0)

Off unless you turn it on (Settings > Appearance > Check for a new version):
a tool for engagement work should not contact anything by itself. When on, it
asks GitHub at most once a day, a few seconds after ShadowSnip starts:

    GET https://api.github.com/repos/jh-infosec/ShadowSnip/releases/latest

That request carries nothing about you or your snips; GitHub sees your
address and a User-Agent of "ShadowSnip/<version>", as any web request
would. **Check now** in Settings asks once, whether or not the daily check is
on. When a newer release is out the tray says so, and clicking that opens
its release page. ShadowSnip never downloads or installs anything itself.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from dataclasses import dataclass

REPO = "jh-infosec/ShadowSnip"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases"
DAY_SECONDS = 24 * 60 * 60
TIMEOUT_SECONDS = 8


class UpdateError(OSError):
    pass


@dataclass
class Release:
    version: str        # "0.20.0"
    tag: str            # "v0.20.0"
    url: str            # its release page
    name: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    """(0, 20, 1) from "v0.20.1", "0.20.1" or "ShadowSnip v0.20.1"; () if there is none."""
    found = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(text or ""))
    if not found:
        return ()
    return tuple(int(part) for part in found.groups(default="0"))


def is_newer(latest: str, current: str) -> bool:
    new, old = parse_version(latest), parse_version(current)
    return bool(new) and bool(old) and new > old


def release_from(data: dict) -> Release:
    tag = str(data.get("tag_name") or "")
    version = ".".join(str(part) for part in parse_version(tag))
    if not version:
        raise UpdateError("GitHub's answer has no version in it.")
    return Release(version, tag, str(data.get("html_url") or RELEASES_URL), str(data.get("name") or tag))


def fetch_latest(current_version: str, opener=None) -> Release:
    """The latest release on GitHub. Raises UpdateError."""
    request = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"ShadowSnip/{current_version}",
    })
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=TIMEOUT_SECONDS) as answer:
            data = json.loads(answer.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc
    if not isinstance(data, dict):
        raise UpdateError("GitHub's answer was not what was expected.")
    return release_from(data)


def due(cfg: dict, now: float | None = None) -> bool:
    """Whether the daily check should run now."""
    if not cfg.get("update_check"):
        return False
    now = time.time() if now is None else now
    last = float(cfg.get("update_last_check") or 0)
    return now - last >= DAY_SECONDS or now < last


def describe(release: Release | None, current: str) -> str:
    if release is None:
        return ""
    if is_newer(release.version, current):
        return f"ShadowSnip {release.version} is out (you have {current})."
    return f"You have the latest version ({current})."


def check_in_background(current_version: str, done, opener=None) -> threading.Thread:
    """Ask GitHub on a worker thread; `done(release_or_None, error_text)` is called there.

    The caller hands the answer back to the Qt thread (a signal does that).
    """
    def work():
        try:
            done(fetch_latest(current_version, opener), "")
        except UpdateError as exc:
            done(None, str(exc))
        except Exception as exc:  # noqa: BLE001 - never take the app down over this
            done(None, f"The check failed: {exc}")

    thread = threading.Thread(target=work, name="shadowsnip-update-check", daemon=True)
    thread.start()
    return thread
