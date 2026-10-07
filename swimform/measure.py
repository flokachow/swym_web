#!/usr/bin/env python3
"""Geometry and overlay rendering from vision-model keypoints.

The model supplies POINTS; every number here is computed from them. Nothing in
this file asks a model for an angle — a model's "about 45 degrees" is a guess,
whereas an angle between three located points is arithmetic.

Coordinates arrive normalised to 0-1000 with the origin top-left.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

KEYPOINTS = [
    "head_top", "ear",
    "shoulder_near", "elbow_near", "wrist_near",
    "hip_top", "hip_rear",
    "knee_near", "ankle_near",
]

# Drawn as a skeleton when both ends are available.
BONES = [
    ("shoulder_near", "elbow_near"),
    ("elbow_near", "wrist_near"),
    ("shoulder_near", "hip_top"),
    ("hip_top", "hip_rear"),
    ("hip_top", "knee_near"),
    ("knee_near", "ankle_near"),
]

# Which measurement means something for which fault, and from which camera.
# Computing every measurement on every frame (the old behaviour) attached a
# head-height reading to a crossover-entry finding, which is noise dressed as
# evidence. A measurement is only shown beside the fault it actually bears on.
MEASURES_FOR_FAULT = {
    "dropped_elbow_catch": ({"elbow_angle"}, {"side", "front", "mixed"}),
    "low_elbow_recovery": ({"elbow_angle"}, {"side", "front", "mixed"}),
    "low_body_position": ({"body_line_angle"}, {"side", "mixed"}),
    "head_position_high": ({"head_height"}, {"side", "mixed"}),
    "breathing_head_lift": ({"head_height"}, {"side", "mixed"}),
}


def relevant(fault_id: str, viewpoint: str, measurements: list) -> list:
    """The subset of `measurements` that bears on `fault_id` from this camera."""
    ids, views = MEASURES_FOR_FAULT.get(fault_id, (set(), set()))
    if viewpoint not in views:
        return []
    return [m for m in measurements if m.id in ids]


# Outside this range the head-height ratio is a landmark failure, not a
# measurement. Swimming with your head a full torso clear of the water is
# not a technique fault anyone needs telling about.
HEAD_RISE_FLOOR = -0.5
HEAD_RISE_CEILING = 1.0

BRAND = (104, 182, 218)
GOOD = (63, 158, 119)
WARN = (224, 138, 60)
BAD = (217, 84, 77)
INK = (20, 38, 47)
PAPER = (255, 255, 255)


@dataclass
class Measurement:
    id: str
    label: str
    value: float
    unit: str
    reference: str
    from_points: list[str]
    confident: bool           # False when any source point was flagged invisible
    verdict: str = "unknown"  # good | mild | pronounced | unknown

    def as_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "value": round(self.value, 1),
            "unit": self.unit, "reference": self.reference,
            "from": self.from_points, "confident": self.confident,
            "verdict": self.verdict,
        }


def _pt(points: dict, name: str) -> tuple[float, float] | None:
    p = points.get(name)
    return (p["x"], p["y"]) if p else None


def _angle_at(a: tuple, b: tuple, c: tuple) -> float:
    """Interior angle at b, in degrees."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    n1 = math.hypot(*v1) or 1e-9
    n2 = math.hypot(*v2) or 1e-9
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / (n1 * n2)))))


def _slope_deg(a: tuple, b: tuple) -> float:
    """Angle of line a->b from horizontal, in [0, 90].

    A line is the same line whichever end you start from, and a swimmer can
    travel left-to-right or right-to-left. Without folding, a perfectly flat
    body heading left read as ~180 degrees and was scored "pronounced".
    """
    ang = abs(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])))
    return min(ang, 180.0 - ang)


def _confident(points: dict, names: list[str]) -> bool:
    return all(points.get(n, {}).get("visible") for n in names)


def compute(points_list: list[dict], waterline_y: float | None) -> list[Measurement]:
    """Derive every measurement the visible landmarks support.

    A measurement is emitted whenever its points exist; `confident` records
    whether the model called them visible. The visibility flag runs
    conservative — it marked a usable hip position as invisible in testing —
    so it lowers confidence rather than suppressing the result.
    """
    pts = {p["name"]: p for p in points_list}
    out: list[Measurement] = []

    sh, el, wr = _pt(pts, "shoulder_near"), _pt(pts, "elbow_near"), _pt(pts, "wrist_near")
    if sh and el and wr:
        ang = _angle_at(sh, el, wr)
        out.append(Measurement(
            id="elbow_angle", label="Elbow angle (recovery)", value=ang, unit="deg",
            reference="elite ~90-120° with the elbow leading",
            from_points=["shoulder_near", "elbow_near", "wrist_near"],
            confident=_confident(pts, ["shoulder_near", "elbow_near", "wrist_near"]),
            verdict="good" if 85 <= ang <= 125 else "mild" if 70 <= ang <= 145 else "pronounced",
        ))

    hip = _pt(pts, "hip_top")
    if sh and hip:
        slope = _slope_deg(sh, hip)
        out.append(Measurement(
            id="body_line_angle", label="Body line (shoulder to hip)", value=slope, unit="deg",
            reference="elite 0-5° from horizontal; 8°+ means the hips are dropping",
            from_points=["shoulder_near", "hip_top"],
            confident=_confident(pts, ["shoulder_near", "hip_top"]),
            verdict="good" if slope <= 5 else "mild" if slope <= 10 else "pronounced",
        ))

    head = _pt(pts, "head_top")
    if head and waterline_y is not None and sh and hip:
        # Scale-free: express head height above the surface as a fraction of
        # torso length, so it does not depend on framing or distance.
        torso = math.hypot(hip[0] - sh[0], hip[1] - sh[1]) or 1e-9
        rise = (waterline_y - head[1]) / torso
        # A head more than half a torso below the surface, or a full torso
        # above it, is not a swimmer — it is a failed waterline or head
        # landmark. Reporting that as "good" because the arithmetic came out
        # negative is worse than reporting nothing, so it is marked unknown.
        plausible = HEAD_RISE_FLOOR <= rise <= HEAD_RISE_CEILING
        if not plausible:
            verdict = "unknown"
        elif rise <= 0.08:
            verdict = "good"          # crown at or just under the surface
        elif rise <= 0.18:
            verdict = "mild"
        else:
            verdict = "pronounced"
        out.append(Measurement(
            id="head_height", label="Head above waterline", value=rise, unit="ratio",
            reference="elite ≈0 (crown at the surface); 0.15+ means the head is riding high",
            from_points=["head_top", "shoulder_near", "hip_top"],
            confident=_confident(pts, ["head_top"]) and plausible,
            verdict=verdict,
        ))

    return out


# Pillow's default font is a 6px bitmap — unreadable on a 1280px frame. Try the
# usual system faces first and only fall back if none of them exist.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",                          # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",              # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",                       # Fedora
    "C:\\Windows\\Fonts\\arial.ttf",                                # Windows
]


def _fonts():
    for path in FONT_CANDIDATES:
        try:
            return (ImageFont.truetype(path, 17), ImageFont.truetype(path, 14))
        except OSError:
            continue
    default = ImageFont.load_default()
    return default, default


def _verdict_color(v: str) -> tuple:
    return {"good": GOOD, "mild": WARN, "pronounced": BAD}.get(v, BRAND)


def render(frame_path: Path, points_list: list[dict], waterline_y: float | None,
           measurements: list[Measurement], out_path: Path, caption: str = "") -> Path:
    """Draw the skeleton, the measured angles and a readout panel."""
    img = Image.open(frame_path).convert("RGB")
    W, H = img.size
    d = ImageDraw.Draw(img, "RGBA")
    pts = {p["name"]: p for p in points_list}

    def px(name: str) -> tuple[float, float] | None:
        p = pts.get(name)
        return (p["x"] / 1000 * W, p["y"] / 1000 * H) if p else None

    font, small = _fonts()

    # Waterline only where it is physically meaningful — at the swimmer's head.
    # Extending it across the frame implies a flat plane that perspective and
    # refraction make false for anything below the surface.
    if waterline_y is not None:
        y = waterline_y / 1000 * H
        head = px("head_top")
        x0 = max(0, (head[0] - W * 0.22)) if head else 0
        x1 = min(W, (head[0] + W * 0.22)) if head else W
        d.line([(x0, y), (x1, y)], fill=BRAND + (220,), width=3)
        d.text((x0, y + 6), "waterline", fill=BRAND, font=small)

    for a, b in BONES:
        pa, pb = px(a), px(b)
        if pa and pb:
            dashed = not (pts[a].get("visible") and pts[b].get("visible"))
            d.line([pa, pb], fill=(255, 255, 255, 120 if dashed else 230), width=3)

    for name, p in pts.items():
        xy = px(name)
        if not xy:
            continue
        x, y = xy
        col = PAPER if p.get("visible") else (255, 255, 255, 140)
        r = 7
        d.ellipse([x - r, y - r, x + r, y + r], outline=col, width=3)

    # Highlight the measured angle vertices
    for m in measurements:
        if m.id == "elbow_angle" and px("elbow_near"):
            x, y = px("elbow_near")
            col = _verdict_color(m.verdict)
            d.ellipse([x - 15, y - 15, x + 15, y + 15], outline=col, width=5)
            d.text((x + 20, y - 10), f"{m.value:.0f}°", fill=col, font=font)
        if m.id == "body_line_angle" and px("hip_top") and px("shoulder_near"):
            sx, sy = px("shoulder_near")
            hx, hy = px("hip_top")
            col = _verdict_color(m.verdict)
            d.line([(sx, sy), (hx, hy)], fill=col + (255,), width=4)
            d.line([(sx, sy), (hx, sy)], fill=col + (110,), width=2)  # horizontal ref
            d.text(((sx + hx) / 2, (sy + hy) / 2 + 10), f"{m.value:.0f}°", fill=col, font=font)

    # Readout panel
    rows = [m for m in measurements]
    if rows or caption:
        pad = 12
        line_h = 24
        panel_h = pad * 2 + line_h * (len(rows) + (1 if caption else 0))
        d.rectangle([0, H - panel_h, W, H], fill=(20, 38, 47, 205))
        ty = H - panel_h + pad
        if caption:
            d.text((pad, ty), caption, fill=PAPER, font=font)
            ty += line_h
        for m in rows:
            col = _verdict_color(m.verdict)
            val = f"{m.value:.2f}" if m.unit == "ratio" else f"{m.value:.0f}°"
            suffix = "" if m.confident else "  (estimated — landmark partly obscured)"
            d.text((pad, ty), f"{m.label}: {val}{suffix}", fill=col, font=small)
            ty += line_h

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
