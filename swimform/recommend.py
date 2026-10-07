"""Rank drills against detected faults.

This is the deterministic half of the coaching side: no model runs here. The
scores come from the hand-authored drill/fault mapping, so the same analysis
always yields the same prescription, and you can audit why a drill was chosen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import taxonomy

STRENGTH_WEIGHT = {"primary": 1.0, "secondary": 0.55}
RELEVANCE_WEIGHT = {"high": 1.0, "medium": 0.8, "low": 0.45}


@dataclass
class ScoredDrill:
    drill: dict
    score: float
    addresses: list[str] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> dict:
        d = self.drill
        return {
            "id": d["id"],
            "title": d["title"],
            "summary": d["summary"],
            "equipment": d.get("equipment", []),
            "caution": d.get("caution", ""),
            "demo": d.get("demo"),
            "score": round(self.score, 3),
            "addresses": self.addresses,
            "addressesNames": [taxonomy.fault_name(f) for f in self.addresses],
            "reason": self.reason,
            "why": d["why"],
        }


def _reason(drill: dict, addresses: list[str]) -> str:
    """'Works on X (main target) and Y (secondary)' — generated, so it can never
    drift from the mapping it describes."""
    strength = {l["faultId"]: l["strength"] for l in drill["corrects_faults"]}
    parts = [
        f"{taxonomy.fault_name(f)} ({'main target' if strength[f] == 'primary' else 'secondary'})"
        for f in addresses
    ]
    return "Works on " + ", ".join(parts) + "." if parts else ""


def recommend(assessments: list[dict], limit: int = 6,
              threshold: float = 0.2, focus: set[str] | None = None) -> list[ScoredDrill]:
    """Score every drill against the assessed faults and return the best spread.

    `assessments` are the analyzer's output: faultId, deviation, confidence.
    Weighting by deviation * confidence means a pronounced fault the model is
    unsure about does not outrank a clear one.
    """
    focus = focus or set()
    weight_by_fault = {
        a["faultId"]: a["deviation"] * a["confidence"]
        for a in assessments
        if a["deviation"] >= threshold
    }
    if not weight_by_fault:
        return []

    scored: list[ScoredDrill] = []

    for drill in taxonomy.drills():
        # A drill that deliberately trains the opposite pattern is withheld,
        # not merely ranked low. Prescribing a rotation drill to someone who
        # already over-rotates makes them worse.
        if any(f in weight_by_fault for f in drill["contraindicated_for"]):
            continue

        score = 0.0
        addresses: list[str] = []
        for link in drill["corrects_faults"]:
            weight = weight_by_fault.get(link["faultId"])
            if weight is None:
                continue
            contribution = weight * STRENGTH_WEIGHT[link["strength"]]
            if link["faultId"] in focus:
                contribution *= 1.3  # the swimmer asked about this one
            score += contribution
            addresses.append(link["faultId"])

        if score == 0:
            continue

        score *= RELEVANCE_WEIGHT.get(drill["triathlon_relevance"], 0.8)
        addresses.sort(key=lambda f: weight_by_fault.get(f, 0), reverse=True)
        scored.append(ScoredDrill(drill, score, addresses, _reason(drill, addresses)))

    scored.sort(key=lambda s: s.score, reverse=True)

    # Spread across faults: don't return six drills for one problem. The cap
    # scales with how many faults were actually found, so a single-fault
    # analysis still fills the requested limit.
    per_fault = max(2, -(-limit // max(1, len(weight_by_fault))))

    out: list[ScoredDrill] = []
    covered: dict[str, int] = {}

    for s in scored:
        lead = s.addresses[0]
        if covered.get(lead, 0) >= per_fault:
            continue
        covered[lead] = covered.get(lead, 0) + 1
        out.append(s)
        if len(out) >= limit:
            break

    return out
