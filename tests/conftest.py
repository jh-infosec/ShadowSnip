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
