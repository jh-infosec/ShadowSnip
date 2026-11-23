"""CVSS 4.0 scores (0.17.0), checked against an independent implementation."""

from __future__ import annotations

import hashlib
import itertools
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import cvss
import lab
import report_dialogs

SAMPLES = Path(__file__).parent / "data" / "cvss40_samples.txt"
# sha256 of every base vector's score, one "9.3\n" per vector, in the order
# itertools.product walks cvss.METRICS_40. Made with Red Hat's cvss package
# (cvss.CVSS4), which shares no code with ShadowSnip's port of FIRST's calculator.
ALL_BASE_SCORES_SHA256 = "c03fa30a63957b282f68e73d0c6419de1af387cdb80a36e0a9e0c00e666f46a3"


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("vector, score, rating", [
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N", 9.3, "Critical"),
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:H/SI:H/SA:H", 10.0, "Critical"),
    ("CVSS:4.0/AV:L/AC:L/AT:N/PR:L/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N", 8.5, "High"),
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:N/VI:N/VA:N/SC:N/SI:N/SA:N", 0.0, "None"),
])
def test_well_known_vectors(vector, score, rating):
    assert cvss.score(vector) == (vector, score, rating)


def test_samples_with_threat_and_environmental_metrics():
    lines = [line.split(" ", 1) for line in SAMPLES.read_text().splitlines()
             if line and not line.startswith("#")]
    assert len(lines) == 400
    wrong = [(vector, expected, cvss.score(vector)[1]) for expected, vector in lines
             if cvss.score(vector)[1] != float(expected)]
    assert wrong == []


def test_every_base_vector_matches_the_independent_implementation():
    digest = hashlib.sha256()
    choices = [[code for code, _label in values] for _key, _name, values in cvss.METRICS_40]
    for combo in itertools.product(*choices):
        metrics = dict(zip(cvss.METRIC_KEYS_40, combo))
        digest.update(f"{cvss.score_40(metrics):.1f}\n".encode())
    assert digest.hexdigest() == ALL_BASE_SCORES_SHA256


def test_floating_point_noise_rounds_half_up():
    # One of the vectors plain rounding gets wrong (8.549999... must be 8.6).
    assert cvss.score("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:P/VC:H/VI:L/VA:N/SC:H/SI:H/SA:H")[1] == 8.6


def test_4_0_vectors_are_read_and_written():
    # No prefix but an AT metric: read as 4.0; lower case and any order.
    canonical, value, _ = cvss.score("sa:n/si:n/sc:n/va:h/vi:h/vc:h/ui:n/pr:n/at:n/ac:l/av:n")
    assert canonical == "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N" and value == 9.3
    # Threat, environmental and supplemental metrics are kept, X ones dropped.
    canonical, value, _ = cvss.score(
        "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N/E:U/CR:X/U:red/R:A")
    assert canonical.endswith("/E:U/R:A/U:Red") and value == 8.1
    assert cvss.version_of(canonical) == "4.0" and cvss.version_of("nonsense") == ""
    assert cvss.describe(canonical) == "8.1 High"


@pytest.mark.parametrize("vector, says", [
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N", "Missing SA"),
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:R/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N", "UI:R"),
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N/S:U", "S:U"),
    ("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N/C:H", "not a CVSS 4.0 metric"),
    ("CVSS:4.0/AV:N/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N", "twice"),
])
def test_bad_4_0_vectors_say_what_is_wrong(vector, says):
    with pytest.raises(cvss.CvssError) as err:
        cvss.parse(vector)
    assert says in str(err.value)


def test_a_4_0_finding_is_scored_and_labelled(cfg, tmp_path):
    cfg["lab_root"] = str(tmp_path / "labs")
    lab.start(cfg, "box")
    cfg["active_lab"] = "box"
    stored = lab.set_finding(cfg, "Web", {
        "severity": "Low", "cvss": "AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"})
    assert stored["severity"] == "Critical" and stored["cvss"].startswith("CVSS:4.0/")
    md = (lab.active_folder(cfg) / lab.INDEX_NAME).read_text(encoding="utf-8")
    assert "> CVSS 4.0 score: 9.3" in md and "| Critical | 9.3 |" in md


def test_the_finding_window_switches_to_4_0():
    dialog = report_dialogs.FindingDialog("Web")
    dialog.use_cvss.setChecked(True)
    assert dialog.cvss_version.currentData() == "3.1" and "S" in dialog.cvss_combos
    dialog.cvss_version.setCurrentIndex(dialog.cvss_version.findData("4.0"))
    assert set(dialog.cvss_combos) == set(cvss.METRIC_KEYS_40)
    assert dialog.values()["cvss"].startswith("CVSS:4.0/") and dialog.cvss_score.text() == "10.0 Critical"
    combo = dialog.cvss_combos["SC"]
    combo.setCurrentIndex(combo.findData("N"))
    assert dialog.cvss_score.text().startswith("9.") and "/SC:N/" in dialog.values()["cvss"]
    # Pasting a 3.1 vector switches back, and the pickers follow it.
    dialog.cvss_vector.setText("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H")
    assert dialog.cvss_version.currentData() == "3.1" and dialog.cvss_combos["AV"].currentData() == "L"
    # A pasted 4.0 vector keeps its threat metric when a picker changes.
    dialog.cvss_vector.setText("CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N/E:U")
    assert dialog.cvss_score.text() == "8.1 High"
    combo = dialog.cvss_combos["AC"]
    combo.setCurrentIndex(combo.findData("H"))
    assert dialog.values()["cvss"].endswith("/E:U") and "/AC:H/" in dialog.values()["cvss"]


def test_the_finding_window_opens_a_stored_4_0_vector():
    dialog = report_dialogs.FindingDialog("Web", {
        "severity": "Critical", "cvss": "CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N"})
    assert dialog.cvss_version.currentData() == "4.0" and dialog.cvss_score.text() == "9.3 Critical"
    assert dialog.cvss_combos["AT"].currentData() == "N"
