"""CVSS scores for findings: 3.1 (0.15.0) and 4.0 (0.17.0).

A finding can carry a CVSS vector such as

    CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H

and ShadowSnip works out its base score (9.8) and rating (Critical) the way
the FIRST specification does, section 7, including its own rounding-up rule,
so the number matches NVD's calculator. Only the eight base metrics are
scored; temporal and environmental metrics in a pasted vector are kept in the
text but do not change the score.

A 3.0 vector scores the same way as 3.1 and is kept as 3.0.

## CVSS 4.0 (0.17.0)

A vector such as

    CVSS:4.0/AV:N/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N

scores 9.3. 4.0 has no formula: the vector is sorted into one of 270
"macrovectors" whose scores FIRST's experts set by hand, and the score is
moved down from there by how far the vector sits below the most severe
vector of its macrovector. That table (`_LOOKUP_40`) and the algorithm are
ported from FIRST's own calculator (github.com/FIRSTdotorg/cvss-v4-calculator,
BSD-2-Clause, Copyright FIRST, Red Hat, and contributors), and the tests check
the result against Red Hat's independent implementation for thousands of
vectors. The eleven base metrics are required; threat (E), environmental and
supplemental metrics in a pasted vector are kept and, as in FIRST's
calculator, threat and environmental ones count towards the score.

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

_PREFIX = re.compile(r"^CVSS:(3\.[01]|4\.0)/", re.IGNORECASE)
VERSIONS = ("3.1", "4.0")
_EPSILON_40 = 10 ** -6

# -- CVSS 4.0 ---------------------------------------------------------------------------------
METRICS_40 = (
    ("AV", "Attack vector", (("N", "Network"), ("A", "Adjacent"), ("L", "Local"), ("P", "Physical"))),
    ("AC", "Attack complexity", (("L", "Low"), ("H", "High"))),
    ("AT", "Attack requirements", (("N", "None"), ("P", "Present"))),
    ("PR", "Privileges required", (("N", "None"), ("L", "Low"), ("H", "High"))),
    ("UI", "User interaction", (("N", "None"), ("P", "Passive"), ("A", "Active"))),
    ("VC", "Confidentiality (system)", (("H", "High"), ("L", "Low"), ("N", "None"))),
    ("VI", "Integrity (system)", (("H", "High"), ("L", "Low"), ("N", "None"))),
    ("VA", "Availability (system)", (("H", "High"), ("L", "Low"), ("N", "None"))),
    ("SC", "Confidentiality (others)", (("H", "High"), ("L", "Low"), ("N", "None"))),
    ("SI", "Integrity (others)", (("H", "High"), ("L", "Low"), ("N", "None"))),
    ("SA", "Availability (others)", (("H", "High"), ("L", "Low"), ("N", "None"))),
)
METRIC_KEYS_40 = tuple(key for key, _name, _values in METRICS_40)
# Every metric a 4.0 vector may carry, in the order the specification lists them.
_ORDER_40 = {
    "AV": "NALP", "AC": "LH", "AT": "NP", "PR": "NLH", "UI": "NPA",
    "VC": "HLN", "VI": "HLN", "VA": "HLN", "SC": "HLN", "SI": "HLN", "SA": "HLN",
    "E": "XAPU",
    "CR": "XHML", "IR": "XHML", "AR": "XHML",
    "MAV": "XNALP", "MAC": "XLH", "MAT": "XNP", "MPR": "XNLH", "MUI": "XNPA",
    "MVC": "XHLN", "MVI": "XHLN", "MVA": "XHLN", "MSC": "XHLN", "MSI": "XSHLN", "MSA": "XSHLN",
    "S": "XNP", "AU": "XNY", "R": "XAUI", "V": "XDC", "RE": "XLMH",
    "U": ("X", "CLEAR", "GREEN", "AMBER", "RED"),
}

# MacroVector scores, from FIRST's calculator (cvss_lookup.js, BSD-2-Clause).
_LOOKUP_40 = {
    "000000": 10, "000001": 9.9, "000010": 9.8, "000011": 9.5, "000020": 9.5, "000021": 9.2,
    "000100": 10, "000101": 9.6, "000110": 9.3, "000111": 8.7, "000120": 9.1, "000121": 8.1,
    "000200": 9.3, "000201": 9, "000210": 8.9, "000211": 8, "000220": 8.1, "000221": 6.8,
    "001000": 9.8, "001001": 9.5, "001010": 9.5, "001011": 9.2, "001020": 9, "001021": 8.4,
    "001100": 9.3, "001101": 9.2, "001110": 8.9, "001111": 8.1, "001120": 8.1, "001121": 6.5,
    "001200": 8.8, "001201": 8, "001210": 7.8, "001211": 7, "001220": 6.9, "001221": 4.8,
    "002001": 9.2, "002011": 8.2, "002021": 7.2, "002101": 7.9, "002111": 6.9, "002121": 5,
    "002201": 6.9, "002211": 5.5, "002221": 2.7, "010000": 9.9, "010001": 9.7, "010010": 9.5,
    "010011": 9.2, "010020": 9.2, "010021": 8.5, "010100": 9.5, "010101": 9.1, "010110": 9,
    "010111": 8.3, "010120": 8.4, "010121": 7.1, "010200": 9.2, "010201": 8.1, "010210": 8.2,
    "010211": 7.1, "010220": 7.2, "010221": 5.3, "011000": 9.5, "011001": 9.3, "011010": 9.2,
    "011011": 8.5, "011020": 8.5, "011021": 7.3, "011100": 9.2, "011101": 8.2, "011110": 8,
    "011111": 7.2, "011120": 7, "011121": 5.9, "011200": 8.4, "011201": 7, "011210": 7.1,
    "011211": 5.2, "011220": 5, "011221": 3, "012001": 8.6, "012011": 7.5, "012021": 5.2,
    "012101": 7.1, "012111": 5.2, "012121": 2.9, "012201": 6.3, "012211": 2.9, "012221": 1.7,
    "100000": 9.8, "100001": 9.5, "100010": 9.4, "100011": 8.7, "100020": 9.1, "100021": 8.1,
    "100100": 9.4, "100101": 8.9, "100110": 8.6, "100111": 7.4, "100120": 7.7, "100121": 6.4,
    "100200": 8.7, "100201": 7.5, "100210": 7.4, "100211": 6.3, "100220": 6.3, "100221": 4.9,
    "101000": 9.4, "101001": 8.9, "101010": 8.8, "101011": 7.7, "101020": 7.6, "101021": 6.7,
    "101100": 8.6, "101101": 7.6, "101110": 7.4, "101111": 5.8, "101120": 5.9, "101121": 5,
    "101200": 7.2, "101201": 5.7, "101210": 5.7, "101211": 5.2, "101220": 5.2, "101221": 2.5,
    "102001": 8.3, "102011": 7, "102021": 5.4, "102101": 6.5, "102111": 5.8, "102121": 2.6,
    "102201": 5.3, "102211": 2.1, "102221": 1.3, "110000": 9.5, "110001": 9, "110010": 8.8,
    "110011": 7.6, "110020": 7.6, "110021": 7, "110100": 9, "110101": 7.7, "110110": 7.5,
    "110111": 6.2, "110120": 6.1, "110121": 5.3, "110200": 7.7, "110201": 6.6, "110210": 6.8,
    "110211": 5.9, "110220": 5.2, "110221": 3, "111000": 8.9, "111001": 7.8, "111010": 7.6,
    "111011": 6.7, "111020": 6.2, "111021": 5.8, "111100": 7.4, "111101": 5.9, "111110": 5.7,
    "111111": 5.7, "111120": 4.7, "111121": 2.3, "111200": 6.1, "111201": 5.2, "111210": 5.7,
    "111211": 2.9, "111220": 2.4, "111221": 1.6, "112001": 7.1, "112011": 5.9, "112021": 3,
    "112101": 5.8, "112111": 2.6, "112121": 1.5, "112201": 2.3, "112211": 1.3, "112221": 0.6,
    "200000": 9.3, "200001": 8.7, "200010": 8.6, "200011": 7.2, "200020": 7.5, "200021": 5.8,
    "200100": 8.6, "200101": 7.4, "200110": 7.4, "200111": 6.1, "200120": 5.6, "200121": 3.4,
    "200200": 7, "200201": 5.4, "200210": 5.2, "200211": 4, "200220": 4, "200221": 2.2,
    "201000": 8.5, "201001": 7.5, "201010": 7.4, "201011": 5.5, "201020": 6.2, "201021": 5.1,
    "201100": 7.2, "201101": 5.7, "201110": 5.5, "201111": 4.1, "201120": 4.6, "201121": 1.9,
    "201200": 5.3, "201201": 3.6, "201210": 3.4, "201211": 1.9, "201220": 1.9, "201221": 0.8,
    "202001": 6.4, "202011": 5.1, "202021": 2, "202101": 4.7, "202111": 2.1, "202121": 1.1,
    "202201": 2.4, "202211": 0.9, "202221": 0.4, "210000": 8.8, "210001": 7.5, "210010": 7.3,
    "210011": 5.3, "210020": 6, "210021": 5, "210100": 7.3, "210101": 5.5, "210110": 5.9,
    "210111": 4, "210120": 4.1, "210121": 2, "210200": 5.4, "210201": 4.3, "210210": 4.5,
    "210211": 2.2, "210220": 2, "210221": 1.1, "211000": 7.5, "211001": 5.5, "211010": 5.8,
    "211011": 4.5, "211020": 4, "211021": 2.1, "211100": 6.1, "211101": 5.1, "211110": 4.8,
    "211111": 1.8, "211120": 2, "211121": 0.9, "211200": 4.6, "211201": 1.8, "211210": 1.7,
    "211211": 0.7, "211220": 0.8, "211221": 0.2, "212001": 5.3, "212011": 2.4, "212021": 1.4,
    "212101": 2.4, "212111": 1.2, "212121": 0.5, "212201": 1, "212211": 0.3, "212221": 0.1,
}
# The most severe vectors of each macrovector part (max_composed.js).
_MAX_COMPOSED_40 = {
    "eq1": {0: ["AV:N/PR:N/UI:N/"], 1: ["AV:A/PR:N/UI:N/", "AV:N/PR:L/UI:N/", "AV:N/PR:N/UI:P/"],
            2: ["AV:P/PR:N/UI:N/", "AV:A/PR:L/UI:P/"]},
    "eq2": {0: ["AC:L/AT:N/"], 1: ["AC:H/AT:N/", "AC:L/AT:P/"]},
    "eq3": {
        0: {"0": ["VC:H/VI:H/VA:H/CR:H/IR:H/AR:H/"],
            "1": ["VC:H/VI:H/VA:L/CR:M/IR:M/AR:H/", "VC:H/VI:H/VA:H/CR:M/IR:M/AR:M/"]},
        1: {"0": ["VC:L/VI:H/VA:H/CR:H/IR:H/AR:H/", "VC:H/VI:L/VA:H/CR:H/IR:H/AR:H/"],
            "1": ["VC:L/VI:H/VA:L/CR:H/IR:M/AR:H/", "VC:L/VI:H/VA:H/CR:H/IR:M/AR:M/",
                  "VC:H/VI:L/VA:H/CR:M/IR:H/AR:M/", "VC:H/VI:L/VA:L/CR:M/IR:H/AR:H/",
                  "VC:L/VI:L/VA:H/CR:H/IR:H/AR:M/"]},
        2: {"1": ["VC:L/VI:L/VA:L/CR:H/IR:H/AR:H/"]},
    },
    "eq4": {0: ["SC:H/SI:S/SA:S/"], 1: ["SC:H/SI:H/SA:H/"], 2: ["SC:L/SI:L/SA:L/"]},
    "eq5": {0: ["E:A/"], 1: ["E:P/"], 2: ["E:U/"]},
}
# The depth of each macrovector part, plus one (max_severity.js).
_MAX_SEVERITY_40 = {
    "eq1": {0: 1, 1: 4, 2: 5},
    "eq2": {0: 1, 1: 2},
    "eq3eq6": {0: {0: 7, 1: 6}, 1: {0: 8, 1: 8}, 2: {1: 10}},
    "eq4": {0: 6, 1: 5, 2: 4},
}
_LEVELS_40 = {
    "AV": {"N": 0.0, "A": 0.1, "L": 0.2, "P": 0.3}, "PR": {"N": 0.0, "L": 0.1, "H": 0.2},
    "UI": {"N": 0.0, "P": 0.1, "A": 0.2}, "AC": {"L": 0.0, "H": 0.1}, "AT": {"N": 0.0, "P": 0.1},
    "VC": {"H": 0.0, "L": 0.1, "N": 0.2}, "VI": {"H": 0.0, "L": 0.1, "N": 0.2},
    "VA": {"H": 0.0, "L": 0.1, "N": 0.2}, "SC": {"H": 0.1, "L": 0.2, "N": 0.3},
    "SI": {"S": 0.0, "H": 0.1, "L": 0.2, "N": 0.3}, "SA": {"S": 0.0, "H": 0.1, "L": 0.2, "N": 0.3},
    "CR": {"H": 0.0, "M": 0.1, "L": 0.2}, "IR": {"H": 0.0, "M": 0.1, "L": 0.2},
    "AR": {"H": 0.0, "M": 0.1, "L": 0.2},
}
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

    The "CVSS:3.1/" prefix may be left off (a vector without one is read as
    3.1, or as 4.0 when it has 4.0's AT metric). Metrics may come in any
    order. For 3.x, metrics other than the eight base ones are allowed and
    ignored; for 4.0 every metric must be one 4.0 defines, and all are kept.
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
        raise CvssError("Only CVSS 3.0, 3.1 and 4.0 vectors are scored.")
    elif re.search(r"(^|/)AT:", text, re.IGNORECASE):
        version = "4.0"
    if version == "4.0":
        return version, _parse_40(text)
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


def _parse_40(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for part in text.split("/"):
        if not part:
            continue
        key, sep, value = part.partition(":")
        key, value = key.upper(), value.upper()
        if not sep or not key or not value:
            raise CvssError(f"'{part}' is not a metric (expected something like AV:N).")
        if key not in _ORDER_40:
            raise CvssError(f"{key} is not a CVSS 4.0 metric.")
        if key in found:
            raise CvssError(f"{key} is given twice.")
        allowed = _ORDER_40[key]
        if value not in allowed:
            raise CvssError(f"{key}:{value} is not a value {key} can take ({', '.join(allowed)}).")
        found[key] = value
    missing = [key for key in METRIC_KEYS_40 if key not in found]
    if missing:
        raise CvssError(f"Missing {', '.join(missing)}.")
    return found


def metrics_for(version: str):
    """The base metrics the finding window offers pickers for."""
    return METRICS_40 if version == "4.0" else METRICS


def vector_of(metrics: dict[str, str], version: str = "3.1") -> str:
    """The canonical vector: base metrics, then (4.0) any others not left at X."""
    if version == "4.0":
        parts = [f"{key}:{metrics[key]}" for key in METRIC_KEYS_40]
        parts += [f"{key}:{_case_u(key, metrics[key])}" for key in _ORDER_40
                  if key not in METRIC_KEYS_40 and metrics.get(key, "X") != "X"]
        return "CVSS:4.0/" + "/".join(parts)
    return f"CVSS:{version}/" + "/".join(f"{key}:{metrics[key]}" for key in METRIC_KEYS)


def _case_u(key: str, value: str) -> str:
    """U (urgency) values are written Clear, Green, Amber, Red; the rest are letters."""
    return value.title() if key == "U" else value


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
    """(canonical vector, score, rating) for a vector. Raises CvssError."""
    version, metrics = parse(vector)
    value = score_40(metrics) if version == "4.0" else base_score(metrics)
    return vector_of(metrics, version), value, rating(value)


def version_of(vector: str) -> str:
    """'3.1', '3.0' or '4.0' for a vector, or '' when it cannot be read."""
    try:
        return parse(vector)[0]
    except CvssError:
        return ""


# -- CVSS 4.0 scoring, after FIRST's cvss_score.js ----------------------------------------------
def _m40(metrics: dict[str, str], key: str) -> str:
    """A metric's effective value: X threat and requirement metrics count as worst case,
    and a modified (M...) metric, when set, replaces its base metric."""
    value = metrics.get(key, "X")
    if key == "E" and value == "X":
        return "A"
    if key in ("CR", "IR", "AR") and value == "X":
        return "H"
    modified = metrics.get("M" + key)
    if modified is not None and modified != "X":
        return modified
    return value


def macrovector(metrics: dict[str, str]) -> str:
    """The six-digit macrovector a 4.0 vector falls in (EQ1 to EQ6)."""
    m = lambda key: _m40(metrics, key)  # noqa: E731
    av, pr, ui = m("AV"), m("PR"), m("UI")
    if av == "N" and pr == "N" and ui == "N":
        eq1 = 0
    elif (av == "N" or pr == "N" or ui == "N") and av != "P":
        eq1 = 1
    else:
        eq1 = 2
    eq2 = 0 if m("AC") == "L" and m("AT") == "N" else 1
    vc, vi, va = m("VC"), m("VI"), m("VA")
    if vc == "H" and vi == "H":
        eq3 = 0
    elif vc == "H" or vi == "H" or va == "H":
        eq3 = 1
    else:
        eq3 = 2
    if m("MSI") == "S" or m("MSA") == "S":
        eq4 = 0
    elif m("SC") == "H" or m("SI") == "H" or m("SA") == "H":
        eq4 = 1
    else:
        eq4 = 2
    eq5 = {"A": 0, "P": 1, "U": 2}[m("E")]
    eq6 = 0 if ((m("CR") == "H" and vc == "H") or (m("IR") == "H" and vi == "H")
                or (m("AR") == "H" and va == "H")) else 1
    return f"{eq1}{eq2}{eq3}{eq4}{eq5}{eq6}"


def _value_in(key: str, vector: str) -> str:
    for part in vector.split("/"):
        name, _sep, value = part.partition(":")
        if name == key:
            return value
    return ""


def score_40(metrics: dict[str, str]) -> float:
    """A CVSS 4.0 score (base, or with threat and environmental metrics when given)."""
    m = lambda key: _m40(metrics, key)  # noqa: E731
    if all(m(key) == "N" for key in ("VC", "VI", "VA", "SC", "SI", "SA")):
        return 0.0
    macro = macrovector(metrics)
    value = _LOOKUP_40[macro]
    eq1, eq2, eq3, eq4, eq5, eq6 = (int(ch) for ch in macro)

    def look(*digits):
        return _LOOKUP_40.get("".join(str(d) for d in digits))

    lower_eq1 = look(eq1 + 1, eq2, eq3, eq4, eq5, eq6)
    lower_eq2 = look(eq1, eq2 + 1, eq3, eq4, eq5, eq6)
    if eq3 == 1 and eq6 == 1:
        lower_eq3eq6 = look(eq1, eq2, eq3 + 1, eq4, eq5, eq6)
    elif eq3 == 0 and eq6 == 1:
        lower_eq3eq6 = look(eq1, eq2, eq3 + 1, eq4, eq5, eq6)
    elif eq3 == 1 and eq6 == 0:
        lower_eq3eq6 = look(eq1, eq2, eq3, eq4, eq5, eq6 + 1)
    elif eq3 == 0 and eq6 == 0:
        left = look(eq1, eq2, eq3, eq4, eq5, eq6 + 1)
        right = look(eq1, eq2, eq3 + 1, eq4, eq5, eq6)
        # As the calculator: the left path only when both exist and it is higher.
        lower_eq3eq6 = left if (left is not None and right is not None and left > right) else right
    else:
        lower_eq3eq6 = look(eq1, eq2, eq3 + 1, eq4, eq5, eq6 + 1)
    lower_eq4 = look(eq1, eq2, eq3, eq4 + 1, eq5, eq6)
    lower_eq5 = look(eq1, eq2, eq3, eq4, eq5 + 1, eq6)

    maxes = [a + b + c + d + e
             for a in _MAX_COMPOSED_40["eq1"][eq1]
             for b in _MAX_COMPOSED_40["eq2"][eq2]
             for c in _MAX_COMPOSED_40["eq3"][eq3][str(eq6)]
             for d in _MAX_COMPOSED_40["eq4"][eq4]
             for e in _MAX_COMPOSED_40["eq5"][eq5]]
    distance: dict[str, float] = {}
    for max_vector in maxes:
        distance = {key: levels[m(key)] - levels[_value_in(key, max_vector)]
                    for key, levels in _LEVELS_40.items()}
        if all(value_ >= 0 for value_ in distance.values()):
            break   # the first most severe vector at or above this one

    step = 0.1
    current = {
        "eq1": distance["AV"] + distance["PR"] + distance["UI"],
        "eq2": distance["AC"] + distance["AT"],
        "eq3eq6": (distance["VC"] + distance["VI"] + distance["VA"]
                   + distance["CR"] + distance["IR"] + distance["AR"]),
        "eq4": distance["SC"] + distance["SI"] + distance["SA"],
    }
    depth = {
        "eq1": _MAX_SEVERITY_40["eq1"][eq1] * step,
        "eq2": _MAX_SEVERITY_40["eq2"][eq2] * step,
        "eq3eq6": _MAX_SEVERITY_40["eq3eq6"][eq3][eq6] * step,
        "eq4": _MAX_SEVERITY_40["eq4"][eq4] * step,
    }
    total, existing = 0.0, 0
    for name, lower in (("eq1", lower_eq1), ("eq2", lower_eq2), ("eq3eq6", lower_eq3eq6),
                        ("eq4", lower_eq4), ("eq5", lower_eq5)):
        if lower is None:
            continue
        existing += 1
        if name != "eq5":   # EQ5's proportion is always 0
            total += (value - lower) * (current[name] / depth[name])
    if existing:
        value -= total / existing
    value = min(10.0, max(0.0, value))
    # Half up, after nudging past floating point noise: 8.6 - 7.15 is
    # 1.4499999999999993 in floating point and must round to 1.5. FIRST's
    # current calculator and Red Hat's implementation both do this.
    from decimal import ROUND_HALF_UP, Decimal

    return float(Decimal(value + _EPSILON_40).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def describe(vector: str) -> str:
    """'9.8 Critical' for a vector, or '' when it cannot be scored."""
    try:
        _canonical, value, name = score(vector)
    except CvssError:
        return ""
    return f"{value:.1f} {name}"
