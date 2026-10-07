"""Video -> scored technique deviations, with annotated frames.

Gemini takes video natively and reasons over its own timeline, so returned
timestamps are grounded in the footage rather than stitched together from
frame filenames. The response is constrained by a JSON schema whose fault ids
are an enum built from the taxonomy, so the model cannot return a fault we
have no drills for.

Two design choices matter more than the rest:

  Scoring, not judging. Every fault comes back as a deviation 0-1 from an
  explicit elite reference, never present/absent. Asked to judge, the model
  compares against its own internal baseline — a competent club swimmer — and
  reports nothing on a swimmer a coach can fault in four places.

  Measurements are computed, not asked for. The model returns landmark
  coordinates; measure.py derives the angles. A model's "about 45 degrees" is
  a guess. An angle between three located points is arithmetic.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config, gemini, measure, recommend, taxonomy

# Per-call patience. A model that accepts a video and then goes silent used to
# hold a run for five minutes; now it is abandoned and the next model tried.
VIDEO_TIMEOUT_S = 240
KEYPOINT_TIMEOUT_S = 45

# Inline request data must stay under 100MB and base64 inflates by ~4/3, so we
# re-encode to a modest clip rather than shipping the original.
MAX_INLINE_BYTES = 60 * 1024 * 1024

KEYPOINT_NAMES = [
    "head_top", "ear", "shoulder_near", "elbow_near", "wrist_near",
    "hip_top", "hip_rear", "knee_near", "ankle_near",
]

VIEWPOINTS = ["side", "front", "rear", "above", "underwater", "mixed", "unclear"]


class AnalysisError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# video prep
# --------------------------------------------------------------------------

def ensure_ffmpeg() -> None:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        raise AnalysisError(
            "ffmpeg not found on PATH.\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu:  sudo apt install ffmpeg\n"
            "  Windows: winget install Gyan.FFmpeg"
        )


def probe_duration(video: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None


def prepare_clip(video: Path, start: float | None, end: float | None) -> bytes:
    """Trim to the window and downscale to at most 1280px wide.

    That is ample: the faults detectable at all are gross body-position cues,
    not fine detail. Keeping the upload small is what makes the analysis fast.
    """
    if not video.exists():
        raise AnalysisError(f"Video not found: {video}")

    cmd = ["ffmpeg", "-v", "error", "-y"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", str(video)]
    if end is not None:
        cmd += ["-t", str(end - (start or 0))]
    cmd += [
        "-vf", "scale='min(1280,iw)':-2",
        "-an",  # audio adds bytes and tells us nothing about technique
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
        "-movflags", "+faststart",
    ]

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        out = Path(tmp.name)
    cmd.append(str(out))

    try:
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise AnalysisError(f"ffmpeg could not read that video:\n{e.stderr.strip()[:400]}")
        data = out.read_bytes()
    finally:
        out.unlink(missing_ok=True)

    if not data:
        raise AnalysisError("That window contains no video. Check the start and end times.")
    if len(data) > MAX_INLINE_BYTES:
        raise AnalysisError(
            f"Clip is {len(data) // (1024 * 1024)}MB after re-encoding — too large to send. "
            "Analyse a shorter window; 10-20 seconds is plenty."
        )
    return data


def extract_frame(video: Path, t: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(video),
         "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "2", str(out)],
        check=True, capture_output=True,
    )
    return out


# --------------------------------------------------------------------------
# prompts and schemas
# --------------------------------------------------------------------------

def assessment_schema() -> dict:
    ids = taxonomy.fault_ids()
    return {
        "type": "object",
        "properties": {
            "viewpoint": {"type": "string", "enum": VIEWPOINTS},
            "swimmerVisible": {"type": "boolean"},
            "strokeCount": {"type": "integer"},
            "summary": {"type": "string"},
            "assessments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "faultId": {"type": "string", "enum": ids},
                        "deviation": {"type": "number"},
                        "confidence": {"type": "number"},
                        "timestamps": {"type": "array", "items": {"type": "number"}},
                        "evidence": {"type": "string"},
                    },
                    "required": ["faultId", "deviation", "confidence", "timestamps", "evidence"],
                },
            },
            "notAssessable": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "faultId": {"type": "string", "enum": ids},
                        "reason": {"type": "string"},
                    },
                    "required": ["faultId", "reason"],
                },
            },
        },
        "required": ["viewpoint", "swimmerVisible", "summary", "assessments", "notAssessable"],
    }


def assessment_prompt(duration: float = 0.0) -> str:
    span = f", which runs from 0.0 to {duration:.1f} seconds" if duration > 0 else ""
    lines = [
        "You are assessing freestyle (front crawl) swimming technique.",
        "",
        "You are NOT deciding whether something counts as a fault. You are measuring "
        "how far this swimmer's technique sits from an ELITE reference, for each item "
        "below. Score every item you can see on a continuous scale.",
        "",
        "deviation scale:",
        "  0.0      indistinguishable from the elite reference",
        "  0.1-0.25 slight — a coach would mention it in passing",
        "  0.3-0.5  clear — visible to any experienced swimmer watching",
        "  0.6-1.0  pronounced — the dominant thing wrong with this stroke",
        "",
        "Calibration — this matters. The reference is a technically excellent swimmer, "
        "NOT a competent club swimmer. Someone who swims well and would be graded highly "
        "in a normal squad still typically sits at 0.15-0.4 on several of these. Scoring "
        "everything near 0 means you have compared against an average swimmer instead of "
        "the reference, which is the most common way to get this wrong.",
        "",
        "ITEMS — each with the elite reference to score against:",
    ]
    for f in taxonomy.faults():
        lines.append(f"\n- {f['id']} ({f['name']}), best seen from the {f['plane']}:")
        lines.append(f"    ELITE: {f['elite']}")

    lines += [
        "",
        "RULES:",
        "1. Score every item the footage lets you see, in `assessments`. Include items "
        "you score near 0 — 'checked and clean' is a real result.",
        "2. Put an item in `notAssessable` ONLY when the camera angle, splash, refraction "
        "or cropping genuinely prevent judgement — not when the call is merely difficult. "
        "If you can see it partly, score it and lower `confidence` instead. The underwater "
        "catch phase is the usual honest exception from surface footage.",
        "3. `timestamps` are seconds measured in THIS clip" + span + ". They are used to "
        "pull the exact frames the swimmer is shown, so they carry real weight. Give one "
        "timestamp per DISTINCT occurrence, each at a different stroke cycle, and never "
        "repeat a value. Returning 0, or a value near it, for every item is the common "
        "failure mode: the opening frame is rarely the clearest example, and identical "
        "timestamps across several items means none of them were actually located. For "
        "each item, name the moment where that item specifically is most legible.",
        "4. `evidence` describes what is visible on screen and how it differs from the "
        "elite reference. Never restate the definition back.",
        "5. `summary` is two or three sentences to the swimmer, in plain language, naming "
        "the one thing that would most improve this stroke. No jargon they would have to "
        "look up, and no false encouragement.",
        "6. If no swimmer is clearly visible, set `swimmerVisible` false and return empty "
        "arrays.",
    ]
    return "\n".join(lines)


def keypoint_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "waterline_y": {"type": "integer"},
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": KEYPOINT_NAMES},
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "visible": {"type": "boolean"},
                    },
                    "required": ["name", "x", "y", "visible"],
                },
            },
        },
        "required": ["waterline_y", "points"],
    }


def keypoint_prompt() -> str:
    return (
        "One frame from a freestyle swimming video. Locate these anatomical landmarks "
        "on the swimmer nearest the camera.\n"
        "Return x and y as integers normalised to 0-1000, x=0 at the left edge, "
        "y=0 at the TOP edge.\n"
        "The hip is a region, not a point, so it has two landmarks: `hip_top` is the "
        "iliac crest / top of the hip at the lower back, `hip_rear` is the start of the "
        "buttock behind it.\n"
        "Set visible=false for a landmark hidden underwater, cropped or obscured, but "
        "still give your best estimate of where it is.\n"
        "waterline_y is the water surface height AT THE SWIMMER, not elsewhere in frame.\n"
        f"Landmarks: {', '.join(KEYPOINT_NAMES)}."
    )


# --------------------------------------------------------------------------
# pipeline
# --------------------------------------------------------------------------

def annotate(video: Path, t: float, key: str, out_dir: Path, caption: str,
             fault_id: str, viewpoint: str) -> dict | None:
    """Pull the frame at t, locate landmarks, measure, render an overlay.

    Only the measurements that bear on this fault from this camera are kept and
    drawn; the rest would be noise dressed as evidence.
    """
    try:
        frame = extract_frame(video, t, out_dir / f"frame_{t:.1f}.jpg")
    except (subprocess.CalledProcessError, OSError):
        return None  # a timestamp past the last frame; skip the overlay, keep the analysis
    try:
        try:
            kp = gemini.generate(
                [{"text": keypoint_prompt()}, gemini.image_part(frame)],
                keypoint_schema(), key, temperature=0.0, timeout=KEYPOINT_TIMEOUT_S,
            )
        except gemini.GeminiKeyError:
            raise  # a bad key is not a missing overlay
        except Exception as e:  # noqa: BLE001
            # An overlay is a nice-to-have. Losing a whole analysis — which has
            # already been paid for — because one frame would not annotate is
            # the worst possible trade, so nothing else is allowed to propagate.
            print(f"[swimform] no overlay at {t:.1f}s ({type(e).__name__}: {e})", file=sys.stderr)
            return None

        points = kp.get("points", [])
        if not points:
            return None

        waterline = kp.get("waterline_y")
        try:
            ms = measure.relevant(fault_id, viewpoint, measure.compute(points, waterline))
            overlay = out_dir / f"overlay_{t:.1f}.png"
            measure.render(frame, points, waterline, ms, overlay, caption)
        except Exception as e:  # noqa: BLE001
            print(f"[swimform] could not render overlay at {t:.1f}s "
                  f"({type(e).__name__}: {e})", file=sys.stderr)
            return None
    finally:
        # The raw frame was only needed to find landmarks. The annotated copy is
        # what the swimmer sees; no reason to keep a second picture of them.
        frame.unlink(missing_ok=True)

    return {
        "t": t,
        "image": str(overlay),
        "keypoints": points,
        "waterlineY": waterline,
        "measurements": [m.as_dict() for m in ms],
    }


def _distinct(stamps: list[float], duration: float, limit: int) -> list[float]:
    """Timestamps inside the clip, no two closer than half a second.

    The model does repeat timestamps, and it sometimes returns seconds beyond
    the clip. Showing the same moment twice as two pieces of evidence, or a
    frame that does not exist, would be worse than showing fewer.
    """
    out: list[float] = []
    for raw in stamps:
        t = round(float(raw), 1)
        if t < 0 or (duration and t > duration):
            continue
        if all(abs(t - kept) >= 0.5 for kept in out):
            out.append(t)
        if len(out) >= limit:
            break
    return out


def evidence_stills(video: Path, start: float, assessments: list[dict], out_dir: Path,
                    per_fault: int, threshold: float) -> None:
    """A plain still at every moment the model pointed at.

    ffmpeg only, no model call, so showing every reported moment costs disk and
    nothing else. This is the "show me exactly where" answer; the annotated
    overlays are the premium view layered on top, and they stay rationed
    because each one is a request.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for a in assessments:
        if a["deviation"] < threshold or not a["timestamps"] or per_fault <= 0:
            continue
        frames = []
        for i, t in enumerate(a["timestamps"][:per_fault]):
            out = out_dir / f"ev_{a['faultId']}_{i}.jpg"
            try:
                extract_frame(video, start + t, out)
            except (subprocess.CalledProcessError, OSError):
                continue  # one unreadable timestamp must not lose the others
            frames.append({"t": t, "at": round(start + t, 1), "image": str(out)})
        if frames:
            a["evidenceFrames"] = frames


def analyze(video: str | Path, start: float | None = None, end: float | None = None,
            fps: float | None = None, model: str | None = None,
            overlays: int | None = None, out_dir: Path | None = None,
            limit: int = 6, key: str | None = None, viewpoint: str | None = None,
            evidence_per_fault: int | None = None) -> dict:
    """Run the full pipeline for one clip: clip -> assessment -> stills -> overlays -> drills.

    `key` is the caller's own Gemini key (the web app sends it per request); the
    command line leaves it unset and the environment supplies it. `viewpoint` is
    the slot the swimmer filed this clip under. It is deliberately NOT shown to
    the model: letting the model read the angle for itself is what lets us catch
    a front clip filed as a side clip.
    """
    ensure_ffmpeg()
    cfg = config.load()
    fps = cfg["fps"] if fps is None else fps
    overlays = cfg["overlays"] if overlays is None else overlays
    evidence_per_fault = cfg["evidencePerFault"] if evidence_per_fault is None else evidence_per_fault
    threshold = cfg["reportThreshold"]

    start = max(0.0, start or 0.0)
    if end is not None and end <= start:
        raise AnalysisError("The end time must be after the start time.")

    video = Path(video).expanduser().resolve()
    key = key or config.api_key()

    total = probe_duration(video)
    window_end = end if end is not None else total
    if total is not None and start >= total:
        raise AnalysisError(f"The start time ({start:g}s) is past the end of the video ({total:.1f}s).")
    if total is not None and window_end is not None:
        window_end = min(window_end, total)
    duration = round(max(0.0, (window_end or 0.0) - start), 1)

    clip = prepare_clip(video, start, end)
    raw = gemini.generate(
        [{"text": assessment_prompt(duration)}, gemini.video_part(clip, fps)],
        assessment_schema(), key, model=model, timeout=VIDEO_TIMEOUT_S,
    )

    assessments = sorted(
        (
            {
                "faultId": a["faultId"],
                "faultName": taxonomy.fault_name(a["faultId"]),
                "deviation": round(min(1.0, max(0.0, float(a["deviation"]))), 2),
                "confidence": round(min(1.0, max(0.0, float(a["confidence"]))), 2),
                "timestamps": _distinct(a.get("timestamps", []), duration, 6),
                "evidence": a["evidence"],
                "measurements": [],
            }
            for a in raw.get("assessments", [])
        ),
        key=lambda a: a["deviation"] * a["confidence"],
        reverse=True,
    )

    read_viewpoint = raw.get("viewpoint", "unclear")
    result = {
        "durationSec": duration,
        "window": {"startSec": start, "endSec": window_end},
        "engine": "gemini",
        "viewpoint": read_viewpoint,
        "requestedViewpoint": viewpoint,
        "swimmerVisible": raw.get("swimmerVisible", False),
        "strokeCount": raw.get("strokeCount"),
        "summary": raw.get("summary", ""),
        "reportThreshold": threshold,
        "assessments": assessments,
        "notAssessable": [
            {**n, "faultName": taxonomy.fault_name(n["faultId"])}
            for n in raw.get("notAssessable", [])
        ],
    }

    if assessments:
        out_dir = out_dir or Path(tempfile.mkdtemp(prefix="swimform-"))
        out_dir.mkdir(parents=True, exist_ok=True)
        evidence_stills(video, start, assessments, out_dir, evidence_per_fault, threshold)

        # Annotate the worst offenders — one frame each, only where the model
        # gave a timestamp to pull from. Each overlay costs an extra request.
        done = 0
        for a in assessments:
            if done >= overlays or not a["timestamps"] or a["deviation"] < threshold:
                continue
            # timestamps are relative to the trimmed clip, not the source file
            t_abs = start + a["timestamps"][0]
            caption = f"{a['faultName']} — deviation {a['deviation']:.2f}"
            frame = annotate(video, t_abs, key, out_dir, caption, a["faultId"], read_viewpoint)
            if frame:
                a["measurements"] = frame.pop("measurements", [])
                a["frame"] = frame
                done += 1
        result["overlayDir"] = str(out_dir)

    result["drills"] = [
        s.as_dict() for s in recommend.recommend(assessments, limit=limit, threshold=threshold)
    ]
    return result


def save(result: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return path
