"""Combine what two camera angles saw into one verdict per fault.

This is the whole reason to film twice. Half of the faults in the taxonomy are
best judged from the front (crossover entry, scissor kick, rotation...) and a
side-on camera cannot judge them at all. A single side clip used to report
those as "not judgeable" every time; a second angle rescues most of them.

The rule, in order:

  1. Prefer the clip whose camera angle matches the fault's documented plane.
     A front fault seen from the front beats the same fault guessed at from the
     side, whatever the confidences say.
  2. Failing a plane match, take the higher confidence.
  3. A fault is only reported as not judgeable when NO angle could assess it.

Rule 1 deliberately overrides confidence: a model looking at the wrong plane is
confidently wrong, which is exactly the failure this exists to stop.

The input comes from the browser, so every field is treated as untrusted and
re-validated here.
"""

from __future__ import annotations

import math

from . import config, recommend, security, taxonomy, wording

SLOTS = ("side", "front")
READABLE = {"side", "front", "rear", "above", "underwater", "mixed", "unclear"}
MAX_TIMESTAMPS = 8


class CombineError(ValueError):
    pass


# --------------------------------------------------------------------------
# input hygiene
# --------------------------------------------------------------------------

def _num(v, lo: float, hi: float) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return max(lo, min(hi, float(v)))


def _within(v, lo: float, hi: float) -> float | None:
    """Like _num but out-of-range is rejected, not clamped: a timestamp of -4 or
    1e9 is not "the start" or "the end", it is nonsense."""
    n = _num(v, -math.inf, math.inf)
    return n if n is not None and lo <= n <= hi else None


def _text(v, limit: int = 1200) -> str:
    return v[:limit] if isinstance(v, str) else ""


def _image(v) -> str | None:
    """Only ever hand back URLs this server itself issued."""
    if not isinstance(v, str) or not v.startswith("/overlay/"):
        return None
    parts = v.split("/")
    if len(parts) == 4 and security.RUN_RE.match(parts[2]) and security.FILE_RE.match(parts[3]):
        return v
    return None


def _clean_assessment(a) -> dict | None:
    if not isinstance(a, dict) or a.get("faultId") not in taxonomy.fault_by_id():
        return None
    dev, conf = _num(a.get("deviation"), 0, 1), _num(a.get("confidence"), 0, 1)
    if dev is None or conf is None:
        return None

    stamps: list[float] = []
    for t in (a.get("timestamps") or [])[:MAX_TIMESTAMPS * 2]:
        v = _within(t, 0, 36000)
        if v is not None and all(abs(v - s) >= 0.5 for s in stamps):
            stamps.append(round(v, 1))

    measurements = []
    for m in (a.get("measurements") or [])[:6]:
        if not isinstance(m, dict) or _num(m.get("value"), -1e6, 1e6) is None:
            continue
        measurements.append({
            "id": _text(m.get("id"), 40), "label": _text(m.get("label"), 80),
            "value": round(float(m["value"]), 2), "unit": _text(m.get("unit"), 8),
            "reference": _text(m.get("reference"), 160),
            "confident": bool(m.get("confident")),
            "verdict": m.get("verdict") if m.get("verdict") in
            ("good", "mild", "pronounced", "unknown") else "unknown",
        })

    frame = None
    fr = a.get("frame")
    if isinstance(fr, dict) and _image(fr.get("image")):
        frame = {"t": _num(fr.get("t"), 0, 36000) or 0.0, "image": fr["image"]}

    stills = []
    for ev in (a.get("evidenceFrames") or [])[:MAX_TIMESTAMPS]:
        if isinstance(ev, dict) and _image(ev.get("image")):
            t, at = _num(ev.get("t"), 0, 36000), _num(ev.get("at"), 0, 36000)
            if t is not None:
                stills.append({"t": t, "at": at if at is not None else t, "image": ev["image"]})

    return {
        "faultId": a["faultId"], "deviation": round(dev, 2), "confidence": round(conf, 2),
        "timestamps": stamps, "evidence": _text(a.get("evidence")),
        "measurements": measurements, "frame": frame, "evidenceFrames": stills,
    }


def _clean_angle(slot: str, result) -> dict:
    if not isinstance(result, dict):
        raise CombineError(f"The {slot} result is not valid.")
    read = result.get("viewpoint") if result.get("viewpoint") in READABLE else "unclear"
    window = result.get("window") if isinstance(result.get("window"), dict) else {}
    visible = bool(result.get("swimmerVisible", False))

    assessments = [c for c in (_clean_assessment(a) for a in (result.get("assessments") or [])[:40]) if c]
    not_assessable = []
    for n in (result.get("notAssessable") or [])[:40]:
        if isinstance(n, dict) and n.get("faultId") in taxonomy.fault_by_id():
            not_assessable.append({"faultId": n["faultId"], "reason": _text(n.get("reason"), 400)})

    provider = result.get("provider") if result.get("provider") in config.PROVIDER_IDS else None
    mode = result.get("mode") if result.get("mode") in ("video", "frames") else None
    return {
        "slot": slot, "viewpoint": read, "swimmerVisible": visible, "provider": provider, "mode": mode,
        "summary": _text(result.get("summary")),
        "strokeCount": int(result["strokeCount"]) if isinstance(result.get("strokeCount"), int)
        and not isinstance(result.get("strokeCount"), bool) and 0 <= result["strokeCount"] < 500 else None,
        "durationSec": _num(result.get("durationSec"), 0, 36000) or 0.0,
        "startSec": _num(window.get("startSec"), 0, 36000) or 0.0,
        "assessments": assessments, "notAssessable": not_assessable,
        "reportThreshold": _num(result.get("reportThreshold"), 0, 1),
    }


# --------------------------------------------------------------------------
# the merge
# --------------------------------------------------------------------------

def _wins(challenger: dict, ch_match: bool, incumbent: dict, inc_match: bool) -> bool:
    if ch_match != inc_match:
        return ch_match
    return challenger["confidence"] > incumbent["confidence"]


def merge_angles(angles: list[dict]) -> tuple[list[dict], list[dict]]:
    """Best assessment per fault, and the faults no angle could assess."""
    best: dict[str, tuple[dict, bool]] = {}
    planes = {f["id"]: f["plane"] for f in taxonomy.faults()}

    for angle in angles:
        for a in angle["assessments"]:
            match = planes.get(a["faultId"]) == angle["viewpoint"]
            tagged = {**a, "fromViewpoint": angle["viewpoint"], "fromClip": angle["slot"],
                      "clipStartSec": angle["startSec"]}
            held = best.get(a["faultId"])
            if held is None or _wins(tagged, match, held[0], held[1]):
                best[a["faultId"]] = (tagged, match)

    # Keep the reason from the angle with the best claim to judge the fault, so
    # the swimmer is told why the RIGHT camera could not see it.
    unassessed: dict[str, dict] = {}
    for angle in angles:
        for n in angle["notAssessable"]:
            if n["faultId"] in best:
                continue
            if n["faultId"] not in unassessed or planes.get(n["faultId"]) == angle["viewpoint"]:
                unassessed[n["faultId"]] = {**n, "faultName": taxonomy.fault_name(n["faultId"]),
                                            "fromClip": angle["slot"]}

    merged = sorted((v[0] for v in best.values()),
                    key=lambda a: a["deviation"] * a["confidence"], reverse=True)
    return merged, list(unassessed.values())


def _moments(a: dict) -> list[dict]:
    """Every moment a fault was seen: when, and a still if we have one."""
    stills = {round(ev["t"], 1): ev for ev in a["evidenceFrames"]}
    out = []
    for t in a["timestamps"][:MAX_TIMESTAMPS]:
        ev = stills.get(round(t, 1))
        out.append({"t": t, "at": round(a["clipStartSec"] + t, 1),
                    "image": ev["image"] if ev else None})
    return out


def combine(angles_in: list[dict], limit: int = 6) -> dict:
    """Merge one or two analysed clips into the single result the UI renders."""
    if not isinstance(angles_in, list) or not 1 <= len(angles_in) <= 2:
        raise CombineError("Send one or two analysed clips.")

    angles, seen = [], set()
    for item in angles_in:
        slot = item.get("slot") if isinstance(item, dict) else None
        if slot not in SLOTS or slot in seen:
            raise CombineError("Each clip needs a distinct slot: side or front.")
        seen.add(slot)
        angles.append(_clean_angle(slot, item.get("result")))
    angles.sort(key=lambda a: SLOTS.index(a["slot"]))

    thresholds = [a["reportThreshold"] for a in angles if a["reportThreshold"] is not None]
    threshold = thresholds[0] if thresholds else 0.2

    visible = [a for a in angles if a["swimmerVisible"]]
    warnings = []
    viewpoints = []
    for a in angles:
        mismatch = a["swimmerVisible"] and a["viewpoint"] != a["slot"] and a["viewpoint"] in SLOTS
        unclear = a["swimmerVisible"] and a["viewpoint"] not in SLOTS
        viewpoints.append({"slot": a["slot"], "read": a["viewpoint"], "mismatch": bool(mismatch),
                           "swimmerVisible": a["swimmerVisible"], "strokeCount": a["strokeCount"],
                           "durationSec": a["durationSec"]})
        if not a["swimmerVisible"]:
            warnings.append({"slot": a["slot"], "kind": "no_swimmer", "message":
                             f"No swimmer was clearly visible in the {a['slot']} clip."})
        elif mismatch:
            warnings.append({"slot": a["slot"], "kind": "viewpoint_mismatch", "message":
                             f"You filed this as the {a['slot']} view, but it reads as the "
                             f"{a['viewpoint']} view. Each fault was judged from the clip whose "
                             "angle suits it, so check the clips are in the right slots."})
        elif unclear:
            warnings.append({"slot": a["slot"], "kind": "viewpoint_unclear", "message":
                             f"The camera angle of the {a['slot']} clip was unclear, so it counts "
                             "for less when the two clips disagree."})

    merged, unassessed = merge_angles(visible)

    planes = {f["id"]: f["plane"] for f in taxonomy.faults()}
    assessments = []
    for a in merged:
        plane = planes.get(a["faultId"], "side")
        assessments.append({
            **{k: v for k, v in a.items() if k != "evidenceFrames"},
            "faultName": taxonomy.fault_name(a["faultId"]),
            "plane": plane,
            "severity": wording.severity(a["deviation"]),
            "clarity": wording.clarity(a["confidence"], plane),
            "moments": _moments(a),
        })

    reported = [a for a in assessments if a["deviation"] >= threshold]
    if not visible:
        headline = "No swimmer was clearly visible in the footage."
    elif reported:
        top = reported[0]
        headline = f"{top['faultName']} is the biggest thing to work on ({top['severity']['label'].lower()})."
    else:
        headline = "Nothing stands out above the reporting threshold in this footage."

    summaries = {a["slot"]: a["summary"] for a in angles if a["summary"]}
    drills = [s.as_dict() for s in recommend.recommend(assessments, limit=limit, threshold=threshold)]
    stroke = next((a["strokeCount"] for a in visible if a["strokeCount"]), None)

    return {
        "swimmerVisible": bool(visible),
        "provider": next((a["provider"] for a in angles if a["provider"]), None),
        "mode": next((a["mode"] for a in angles if a["mode"]), None),
        "headline": headline,
        "summary": " ".join(summaries[s] for s in SLOTS if s in summaries),
        "summaries": summaries,
        "viewpoint": " + ".join(a["slot"] for a in angles) if len(angles) > 1 else angles[0]["viewpoint"],
        "viewpoints": viewpoints,
        "warnings": warnings,
        "reportThreshold": threshold,
        "strokeCount": stroke,
        "durationSec": max((a["durationSec"] for a in angles), default=0.0),
        "assessments": assessments,
        "notAssessable": unassessed,
        "drills": drills,
        "clips": [{"slot": a["slot"], "startSec": a["startSec"], "durationSec": a["durationSec"]}
                  for a in angles],
    }
