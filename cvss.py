"""CVSS 3.1 base scores for findings (0.15.0).

A finding can carry a CVSS vector such as

    CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H

and ShadowSnip works out its base score (9.8) and rating (Critical) the way
the FIRST specification does, section 7, including its own rounding-up rule,
so the number matches NVD's calculator. Only the eight base metrics are
scored; temporal and environmental metrics in a pasted vector are kept in the
text but do not change the score.

Version 3.1 rather than 4.0: 3.1 is still what most report templates, CVE
records and exam write-ups use, and 4.0's score comes from a large lookup
table rather than a formula. A 3.0 vector scores the same way and is kept as
3.0.

The rating sets the finding's severity: None is shown as Info, the rest by
name.
"""

from __future__ import annotations

import math
import re

# The eight base metrics, in the order a vector lists them, with their values.
METRICS = (
    ("AV", "Attack vector", (("N", "Network"), ("A", "Adjacent"), ("L", "Local"), ("P", "Physical"))),
    ("AC", "Attack complexity", (("L", "Low"), ("H", "High"))),
    ("PR", "Privileges required", (("N", "None"), ("L", "Low"), ("H", "High"))),
    ("UI", "User interaction", (("N", "None"), ("R", "Required"))),
    ("S", "Scope", (("U", "Unchanged"), ("C", "Changed"))),
    ("C", "Confidentiality", (("H", "High"), ("L", "Low"), ("N", "None"))),
    ("I", "Integrity", (("H", "High"), ("L", "Low"), ("N", "None"))),
    ("A", "Availability", (("H", "High"), ("L", "Low"), ("N", "None"))),
)
METRIC_KEYS = tuple(key for key, _name, _values in METRICS)
_ALLOWED = {key: {code for code, _label in values} for key, _name, values in METRICS}

_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}
_AC = {"L": 0.77, "H": 0.44}
_PR_UNCHANGED = {"N": 0.85, "L": 0.62, "H": 0.27}
_PR_CHANGED = {"N": 0.85, "L": 0.68, "H": 0.5}
_UI = {"N": 0.85, "R": 0.62}
_CIA = {"H": 0.56, "L": 0.22, "N": 0.0}

_PREFIX = re.compile(r"^CVSS:(3\.[01])/", re.IGNORECASE)
MAX_VECTOR = 200


class CvssError(ValueError):
    """A vector that cannot be scored, with what is wrong with it."""


def roundup(value: float) -> float:
    """CVSS 3.1's Roundup: the smallest one-decimal number not below `value`.

    Done in integers, as the specification's appendix A says, so 4.000000001
    from floating point does not become 4.1.
    """
    whole = round(value * 100_000)
    if whole % 10_000 == 0:
        return whole / 100_000.0
    return (math.floor(whole / 10_000) + 1) / 10.0


def parse(vector: str) -> tuple[str, dict[str, str]]:
    """("3.1", {"AV": "N", ...}) from a vector. Raises CvssError.

    The "CVSS:3.1/" prefix may be left off. Metrics may come in any order;
    metrics other than the eight base ones are allowed and ignored.
    """
    text = "".join(str(vector or "").split())
    if not text:
        raise CvssError("No vector given.")
    if len(text) > MAX_VECTOR:
        raise CvssError("That is too long to be a CVSS vector.")
    version = "3.1"
    match = _PREFIX.match(text)
    if match:
        version = match.group(1)
        text = text[match.end():]
    elif text.upper().startswith("CVSS:"):
        raise CvssError("Only CVSS 3.0 and 3.1 vectors are scored.")
    found: dict[str, str] = {}
    for part in text.split("/"):
        if not part:
            continue
        key, sep, value = part.partition(":")
        key, value = key.upper(), value.upper()
        if not sep or not key or not value:
            raise CvssError(f"'{part}' is not a metric (expected something like AV:N).")
        if key in found:
            raise CvssError(f"{key} is given twice.")
        if key in _ALLOWED and value not in _ALLOWED[key]:
            allowed = ", ".join(sorted(_ALLOWED[key]))
            raise CvssError(f"{key}:{value} is not a value {key} can take ({allowed}).")
        found[key] = value
    missing = [key for key in METRIC_KEYS if key not in found]
    if missing:
        raise CvssError(f"Missing {', '.join(missing)}.")
    return version, {key: found[key] for key in METRIC_KEYS}


def vector_of(metrics: dict[str, str], version: str = "3.1") -> str:
    """The canonical vector for eight base metrics."""
    return f"CVSS:{version}/" + "/".join(f"{key}:{metrics[key]}" for key in METRIC_KEYS)


def base_score(metrics: dict[str, str]) -> float:
    """The base score, 0.0 to 10.0, from the eight base metrics."""
    changed = metrics["S"] == "C"
    iss = 1 - (1 - _CIA[metrics["C"]]) * (1 - _CIA[metrics["I"]]) * (1 - _CIA[metrics["A"]])
    if changed:
        impact = 7.52 * (iss - 0.029) - 3.25 * (iss - 0.02) ** 15
    else:
        impact = 6.42 * iss
    privileges = (_PR_CHANGED if changed else _PR_UNCHANGED)[metrics["PR"]]
    exploitability = 8.22 * _AV[metrics["AV"]] * _AC[metrics["AC"]] * privileges * _UI[metrics["UI"]]
    if impact <= 0:
        return 0.0
    if changed:
        return roundup(min(1.08 * (impact + exploitability), 10))
    return roundup(min(impact + exploitability, 10))


def rating(score: float) -> str:
    """The qualitative rating: None, Low, Medium, High or Critical."""
    if score <= 0:
        return "None"
    if score < 4.0:
        return "Low"
    if score < 7.0:
        return "Medium"
    if score < 9.0:
        return "High"
    return "Critical"


def severity_for(score: float) -> str:
    """The finding severity a score gives: the rating, with None shown as Info."""
    name = rating(score)
    return "Info" if name == "None" else name


def score(vector: str) -> tuple[str, float, str]:
    """(canonical vector, base score, rating) for a vector. Raises CvssError."""
    version, metrics = parse(vector)
    value = base_score(metrics)
    return vector_of(metrics, version), value, rating(value)


def describe(vector: str) -> str:
    """'9.8 Critical' for a vector, or '' when it cannot be scored."""
    try:
        _canonical, value, name = score(vector)
    except CvssError:
        return ""
    return f"{value:.1f} {name}"
