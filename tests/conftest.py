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


@pytest.fixture(autouse=True)
def _edits_on():
    """Keep marks editable is on unless a test turns it off; it is module state."""
    import edits

    edits.enabled = True
    yield
    edits.enabled = True


@pytest.fixture(autouse=True)
def _no_lab_targets():
    """Quick redact's lab hook is module state: no test leaves one behind."""
    import ocr

    ocr.target_source = None
    yield
    ocr.target_source = None



@pytest.fixture(scope="session", autouse=True)
def _empty_clipboard_at_the_end():
    """Qt crashes tearing down if the clipboard still holds data it was given
    (seen with file lists, 0.14.0). The app never quits that way in tests'
    place, so the test run leaves the clipboard empty when it is done."""
    yield
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is not None:
        QApplication.clipboard().clear()


def pytest_sessionfinish(session, exitstatus):
    """Tear the test windows down while Python can still see them (0.18.1).

    The suite opens hundreds of ShadowSnip windows. Left for PySide to destroy
    at interpreter exit, one of them can be reached through a Python wrapper
    whose C++ object Qt has already deleted, and the process dies with a
    segfault after every test has passed (exit code 139 on GitHub's Linux
    runner, about three runs in four). Closing and deleting them here, and
    letting Qt run the deletions, leaves nothing for that last sweep.
    """
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    import gc

    for widget in list(QApplication.topLevelWidgets()):
        try:
            widget.hide()
            widget.deleteLater()
        except RuntimeError:  # already gone on the C++ side
            pass
    for _ in range(3):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        gc.collect()


def _annotation(text: str) -> str:
    """GitHub's workflow-command escaping for a message."""
    return str(text).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """On GitHub Actions, name each failing test in an annotation (0.18.1).

    A run's logs need a GitHub sign-in to read, but its annotations show on
    the public run page. So every failure (and collection error) is also
    printed as an ::error line, with the test's file and line and the last
    lines of what went wrong, which is enough to see why a build failed
    without the log.
    """
    import os

    if not os.environ.get("GITHUB_ACTIONS"):
        return
    reports = terminalreporter.stats.get("failed", []) + terminalreporter.stats.get("error", [])
    for report in reports[:10]:
        path, line, _name = report.location
        text = getattr(report, "longreprtext", "") or str(report.longrepr)
        tail = "\n".join(text.strip().splitlines()[-12:])
        title = f"{report.when} failed: {report.nodeid}"
        terminalreporter.write_line(
            f"::error file=tests/{Path(path).name},line={(line or 0) + 1},"
            f"title={_annotation(title).replace(',', ';').replace(':', ' ')}::{_annotation(tail)}"
        )
    if len(reports) > 10:
        terminalreporter.write_line(f"::error title=More failures::{len(reports) - 10} more failed; see the log.")
