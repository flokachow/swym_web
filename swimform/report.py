"""Render an analysis result as something a swimmer can read.

The JSON is the interface; this is the human view of it. Kept separate so the
CLI, the web UI and anything anyone builds on top share one idea of what a
result means.
"""

from __future__ import annotations

from . import wording

BAR_WIDTH = 20


def _bar(value: float) -> str:
    filled = round(max(0.0, min(1.0, value)) * BAR_WIDTH)
    return "█" * filled + "·" * (BAR_WIDTH - filled)


def _band(deviation: float, threshold: float = 0.2) -> str:
    if deviation < threshold:
        return "clean"
    return wording.severity(deviation)["label"].lower()


def text(result: dict, verbose: bool = False) -> str:
    """Plain-text report for the terminal."""
    out: list[str] = []
    threshold = result.get("reportThreshold", 0.2)

    if not result.get("swimmerVisible", True):
        return ("No swimmer was clearly visible in that clip.\n"
                "Film side-on, the whole body in frame, and keep the swimmer large enough "
                "to see an elbow.")

    out.append("=" * 62)
    out.append("SWIMFORM — freestyle technique analysis")
    out.append("=" * 62)
    meta = [f"viewpoint: {result.get('viewpoint', 'unclear')}"]
    if result.get("durationSec"):
        meta.append(f"{result['durationSec']:.0f}s analysed")
    if result.get("strokeCount"):
        meta.append(f"~{result['strokeCount']} strokes")
    out.append("  ".join(meta))

    if result.get("summary"):
        out += ["", result["summary"]]

    reported = [a for a in result.get("assessments", []) if a["deviation"] >= threshold]
    clean = [a for a in result.get("assessments", []) if a["deviation"] < threshold]

    if reported:
        out += ["", "-" * 62, "WHAT TO WORK ON", "-" * 62]
        for a in reported:
            out.append("")
            out.append(f"{a['faultName']}   {_bar(a['deviation'])} "
                       f"{a['deviation']:.2f} ({_band(a['deviation'], threshold)})")
            if a["confidence"] < 0.6:
                out.append(f"  low confidence ({a['confidence']:.2f}) — treat as a hint")
            out.append(f"  {a['evidence']}")
            if a.get("timestamps"):
                stamps = ", ".join(f"{t:.1f}s" for t in a["timestamps"][:4])
                out.append(f"  seen at: {stamps}")
            for m in a.get("measurements", []):
                val = f"{m['value']:.2f}" if m["unit"] == "ratio" else f"{m['value']:.0f}°"
                est = "" if m["confident"] else "  (estimated — landmark obscured)"
                out.append(f"  measured  {m['label']}: {val}  [{m['verdict']}]{est}")
                out.append(f"            reference: {m['reference']}")
            if a.get("frame"):
                out.append(f"  annotated frame: {a['frame']['image']}")

    if clean:
        out += ["", "-" * 62, "CHECKED AND CLEAN", "-" * 62]
        for a in clean:
            out.append(f"  {a['faultName']}  ({a['deviation']:.2f})"
                       + (f" — {a['evidence']}" if verbose else ""))

    if result.get("notAssessable"):
        out += ["", "-" * 62, "COULD NOT BE JUDGED FROM THIS FOOTAGE", "-" * 62]
        for n in result["notAssessable"]:
            out.append(f"  {n['faultName']}: {n['reason']}")

    if result.get("drills"):
        out += ["", "-" * 62, "DRILLS TO DO ABOUT IT", "-" * 62]
        for i, d in enumerate(result["drills"], 1):
            kit = ", ".join(d["equipment"]) or "no equipment"
            out.append("")
            out.append(f"{i}. {d['title']}  ({kit})")
            out.append(f"   targets: {', '.join(d['addressesNames'])}")
            if d.get("summary"):
                out.append(f"   what: {d['summary']}")
            if d.get("reason"):
                out.append(f"   why: {d['reason']}")
            if d.get("caution"):
                out.append(f"   caution: {d['caution']}")

    out += ["", "-" * 62,
            "Scores are deviation from an elite reference, not a pass/fail. A good",
            "swimmer still sits at 0.15-0.4 on several items. This is software, not",
            "a coach — see the calibration caveats in the README before trusting a",
            "number.", ""]
    return "\n".join(out)


def markdown(result: dict) -> str:
    """Markdown report, for saving or sharing."""
    threshold = result.get("reportThreshold", 0.2)
    out = ["# Freestyle technique analysis", ""]

    if not result.get("swimmerVisible", True):
        return "# Freestyle technique analysis\n\nNo swimmer was clearly visible in that clip.\n"

    meta = [f"**Viewpoint:** {result.get('viewpoint', 'unclear')}"]
    if result.get("durationSec"):
        meta.append(f"**Analysed:** {result['durationSec']:.0f}s")
    if result.get("strokeCount"):
        meta.append(f"**Strokes:** ~{result['strokeCount']}")
    out += [" · ".join(meta), ""]

    if result.get("summary"):
        out += ["> " + result["summary"], ""]

    reported = [a for a in result.get("assessments", []) if a["deviation"] >= threshold]
    if reported:
        out += ["## What to work on", ""]
        for a in reported:
            out.append(f"### {a['faultName']} — {a['deviation']:.2f} ({_band(a['deviation'], threshold)})")
            out.append("")
            out.append(a["evidence"])
            out.append("")
            for m in a.get("measurements", []):
                val = f"{m['value']:.2f}" if m["unit"] == "ratio" else f"{m['value']:.0f}°"
                out.append(f"- **{m['label']}:** {val} ({m['verdict']}) — {m['reference']}")
            if a.get("measurements"):
                out.append("")

    clean = [a for a in result.get("assessments", []) if a["deviation"] < threshold]
    if clean:
        out += ["## Checked and clean", ""]
        out += [f"- {a['faultName']} ({a['deviation']:.2f})" for a in clean] + [""]

    if result.get("notAssessable"):
        out += ["## Not judgeable from this footage", ""]
        out += [f"- **{n['faultName']}:** {n['reason']}" for n in result["notAssessable"]] + [""]

    if result.get("drills"):
        out += ["## Drills", ""]
        for d in result["drills"]:
            kit = ", ".join(d["equipment"]) or "no equipment"
            out.append(f"**{d['title']}** ({kit})")
            out.append(f"Targets: {', '.join(d['addressesNames'])}")
            if d.get("summary"):
                out.append(d["summary"])
            if d.get("caution"):
                out.append(f"*Caution: {d['caution']}*")
            out.append("")

    out += ["---", "",
            "*Deviation from an elite reference, not a pass/fail — a good swimmer still "
            "sits at 0.15–0.4 on several items. Software, not a coach.*", ""]
    return "\n".join(out)
