"""Regression tests for application-level recovery paths."""

from __future__ import annotations

from types import SimpleNamespace

import app


def test_no_capture_resumes_copy_on_select(monkeypatch):
    """A failed screen grab must not leave the mouse hook paused forever."""
    monkeypatch.setattr(app.capture, "grab_all_screens", lambda: [])
    resumed = []
    warnings = []
    state = SimpleNamespace(
        busy=True,
        controller=object(),
        _grabs=[object()],
        autocopy=SimpleNamespace(resume=lambda: resumed.append(True)),
        _warn=lambda message: warnings.append(message),
    )

    app.ShadowSnipApp._begin_snip(state)

    assert state.busy is False
    assert state.controller is None
    assert state._grabs == []
    assert resumed == [True]
    assert warnings == ["No screen could be captured."]


def test_a_snip_is_refused_while_a_modal_dialog_is_open(monkeypatch):
    """The overlay cannot take input behind a modal dialog, so do not start one."""
    monkeypatch.setattr(app, "_modal_dialog_open", lambda: True)
    began = []
    monkeypatch.setattr(app.QTimer, "singleShot", lambda _ms, fn: began.append(fn))
    blocked = []
    paused = []
    state = SimpleNamespace(
        busy=False,
        autocopy=SimpleNamespace(pause=lambda: paused.append(True)),
        _blocked_by_dialog=lambda: blocked.append(True),
    )

    app.ShadowSnipApp.request_snip(state)

    assert blocked == [True]
    assert began == []
    # busy must stay clear, or every later snip is refused as well.
    assert state.busy is False
    assert paused == []


def test_a_snip_still_runs_with_no_dialog_open(monkeypatch):
    monkeypatch.setattr(app, "_modal_dialog_open", lambda: False)
    began = []
    monkeypatch.setattr(app.QTimer, "singleShot", lambda _ms, fn: began.append(fn))
    state = SimpleNamespace(
        busy=False,
        autocopy=SimpleNamespace(pause=lambda: None),
        toast=SimpleNamespace(hide=lambda: None),
        preview=SimpleNamespace(isVisible=lambda: False, hide=lambda: None),
        _blocked_by_dialog=lambda: None,
        _begin_snip=lambda: None,
    )

    app.ShadowSnipApp.request_snip(state)

    assert state.busy is True
    assert len(began) == 1


class _Hotkeys:
    def __init__(self, specs, fail_for=()):
        self.specs = dict(specs)
        self.fail_for = set(fail_for)

    def spec(self, name):
        return self.specs.get(name, "")

    def unregister(self, name):
        self.specs.pop(name, None)

    def register(self, _qapp, spec, name):
        if spec in self.fail_for:
            raise app.hotkey_mod.HotkeyError(f"{spec} is unavailable")
        self.specs[name] = spec


def test_failed_hotkey_update_restores_the_previous_registration():
    old = {"hotkey": "ctrl+shift+s", "note_hotkey": "ctrl+shift+n"}
    warnings = []
    hotkeys = _Hotkeys({"snip": old["hotkey"], "note": old["note_hotkey"]}, {"ctrl+shift+x"})
    state = SimpleNamespace(
        HOTKEYS=app.ShadowSnipApp.HOTKEYS,
        cfg=old,
        hotkeys=hotkeys,
        qapp=object(),
        _warn=lambda message: warnings.append(message),
    )
    requested = {"hotkey": "ctrl+shift+x", "note_hotkey": "ctrl+shift+m"}

    changed = app.ShadowSnipApp._replace_hotkeys(state, requested)

    assert changed is False
    assert hotkeys.specs == {"snip": "ctrl+shift+s", "note": "ctrl+shift+n"}
    assert "Previous hotkeys were restored." in warnings[0]


def test_duplicate_hotkeys_are_rejected_without_unregistration():
    old = {"hotkey": "ctrl+shift+s", "note_hotkey": "ctrl+shift+n"}
    warnings = []
    hotkeys = _Hotkeys({"snip": old["hotkey"], "note": old["note_hotkey"]})
    state = SimpleNamespace(
        HOTKEYS=app.ShadowSnipApp.HOTKEYS,
        cfg=old,
        hotkeys=hotkeys,
        qapp=object(),
        _warn=lambda message: warnings.append(message),
    )

    changed = app.ShadowSnipApp._replace_hotkeys(
        state, {"hotkey": "ctrl+shift+x", "note_hotkey": "ctrl+shift+x"}
    )

    assert changed is False
    assert hotkeys.specs == {"snip": "ctrl+shift+s", "note": "ctrl+shift+n"}
    assert warnings == ["The snip and quick-note hotkeys must be different."]
