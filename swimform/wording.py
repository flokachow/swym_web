"""The words used to describe a score — one source for the web app, the CLI and
the reports, so the same number never reads two different ways."""

from __future__ import annotations


def severity(deviation: float) -> dict:
    """A deviation 0-1 from the elite reference, in plain words."""
    if deviation >= 0.66:
        return {"key": "high", "label": "Costing you time"}
    if deviation >= 0.4:
        return {"key": "mid", "label": "Worth fixing"}
    return {"key": "low", "label": "Minor"}


def clarity(confidence: float, plane: str = "side") -> str:
    """How clear the evidence is, in words. A percentage next to a severity bar
    reads as the same quantity; it is not."""
    if confidence >= 0.8:
        return "Clear in the video"
    if confidence >= 0.6:
        return "Fairly clear"
    other = "front" if plane == "side" else "side"
    return f"Hard to see — worth filming from the {other}"
