"""The fault taxonomy and drill library — the join between vision and coaching.

Fault ids are the only contract between the two halves of this project. The
model may only return ids that exist here (they are baked into the response
schema as an enum), and drills are mapped to the same ids by hand, so a
detected fault always resolves to drills that address it.
"""

from __future__ import annotations

import functools
import json

from .config import DATA_DIR

FAULTS_PATH = DATA_DIR / "faults.json"
DRILLS_PATH = DATA_DIR / "drills.json"

STRENGTHS = ("primary", "secondary")


class TaxonomyError(RuntimeError):
    """The data files are internally inconsistent."""


@functools.lru_cache(maxsize=1)
def faults() -> list[dict]:
    return json.loads(FAULTS_PATH.read_text())["faults"]


@functools.lru_cache(maxsize=1)
def fault_ids() -> list[str]:
    return [f["id"] for f in faults()]


@functools.lru_cache(maxsize=1)
def fault_by_id() -> dict[str, dict]:
    return {f["id"]: f for f in faults()}


@functools.lru_cache(maxsize=1)
def drills() -> list[dict]:
    records = json.loads(DRILLS_PATH.read_text())
    validate(records)
    return records


@functools.lru_cache(maxsize=1)
def drill_by_id() -> dict[str, dict]:
    return {d["id"]: d for d in drills()}


def validate(records: list[dict]) -> None:
    """Fail loudly at load time rather than quietly recommending nothing.

    A typo in a fault id would otherwise produce a drill that can never be
    prescribed, and nobody would notice.
    """
    valid = set(fault_ids())
    seen: set[str] = set()
    for d in records:
        did = d.get("id")
        if not did or did in seen:
            raise TaxonomyError(f"drill id missing or duplicated: {did!r}")
        seen.add(did)
        for link in d["corrects_faults"]:
            if link["faultId"] not in valid:
                raise TaxonomyError(f"{did}: unknown fault {link['faultId']!r}")
            if link["strength"] not in STRENGTHS:
                raise TaxonomyError(f"{did}: bad strength {link['strength']!r}")
        for f in d["contraindicated_for"]:
            if f not in valid:
                raise TaxonomyError(f"{did}: unknown contraindicated fault {f!r}")
        clash = {l["faultId"] for l in d["corrects_faults"]} & set(d["contraindicated_for"])
        if clash:
            raise TaxonomyError(f"{did}: both corrects and is contraindicated for {sorted(clash)}")


def fault_name(fault_id: str) -> str:
    return fault_by_id().get(fault_id, {}).get("name", fault_id)


def drills_for_fault(fault_id: str) -> list[dict]:
    """Every drill addressing a fault, primary links first."""
    def rank(d: dict) -> int:
        link = next(l for l in d["corrects_faults"] if l["faultId"] == fault_id)
        return 0 if link["strength"] == "primary" else 1

    matches = [d for d in drills() if any(l["faultId"] == fault_id for l in d["corrects_faults"])]
    return sorted(matches, key=rank)


def drill_public(d: dict) -> dict:
    """The camelCase shape handed to the web UI, CLI JSON and reports."""
    return {
        "id": d["id"],
        "title": d["title"],
        "summary": d["summary"],
        "howTo": d["how_to"],
        "why": d["why"],
        "easier": d["easier"],
        "harder": d["harder"],
        "sets": d["sets"],
        "equipment": d["equipment"],
        "caution": d.get("caution", ""),
        "demo": d.get("demo"),
        "status": d.get("status", "draft"),
        "relevance": d["triathlon_relevance"],
        "corrects": [
            {"faultId": l["faultId"], "faultName": fault_name(l["faultId"]),
             "strength": l["strength"]}
            for l in d["corrects_faults"]
        ],
        "contraindicatedFor": [
            {"faultId": f, "faultName": fault_name(f)} for f in d["contraindicated_for"]
        ],
    }
