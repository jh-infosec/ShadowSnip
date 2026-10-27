"""Shared test setup.

ShadowSnip's modules sit flat at the repo root and import each other by bare
name, so the root goes on sys.path before anything is imported.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

import config as config_mod  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    """A default config pointed at a temporary save folder."""
    values = dict(config_mod.DEFAULTS)
    values["save_dir"] = str(tmp_path / "snips")
    return config_mod._sanitise(values)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Redirect config.CONFIG_PATH so tests never touch the real %APPDATA%."""
    path = tmp_path / "cfgdir" / "config.json"
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    return path


@pytest.fixture(autouse=True)
def _original_skin():
    """Every test starts and ends in the original look; the skin is module state."""
    import skins

    skins.set_current(skins.ORIGINAL)
    yield
    skins.set_current(skins.ORIGINAL)


@pytest.fixture(autouse=True)
def _no_real_message_boxes(monkeypatch):
    """A test must never stop and wait for someone to click OK.

    ShadowSnip reports problems in message boxes, and a real one opened during
    a test sits on screen until it is clicked, holding the whole run up (as it
    did in 0.9.0 when python-docx was not installed). These stand-ins answer
    at once instead: OK for the information boxes, No for a question, so a test
    that has not chosen an answer never deletes or quits anything. A test that
    needs a particular answer patches the one it uses, as before.
    """
    from PySide6.QtWidgets import QMessageBox

    shown = []

    def box(kind, answer):
        def stand_in(*args, **kwargs):
            shown.append((kind, args[2] if len(args) > 2 else ""))
            return answer
        return stand_in

    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, kind, box(kind, QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question", box("question", QMessageBox.StandardButton.No))
    return shown
