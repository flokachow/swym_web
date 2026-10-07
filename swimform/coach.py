"""Ask a question about technique and get a grounded answer.

The naive version of this feature is to hand a model the question and let it
free-associate about swimming. It answers fluently and invents drills. This
runs in two phases instead, so the drills in an answer are always real ones:

  1. TRIAGE   the question is mapped onto fault ids from the taxonomy. The
              response schema is an enum, so the model physically cannot name
              a problem the drill library has no answer for.
  2. ANSWER   the deterministic recommender picks drills for those faults, and
              the model writes prose *from that list*. It is given the drill
              titles and told to use only those.

The recommender in step 2 is the same one the video analysis uses, so asking
"what do I do about sinking legs?" and having a video find sinking legs give
consistent advice rather than two different opinions.
"""

from __future__ import annotations

import json

from . import config, gemini, recommend, taxonomy

MAX_HISTORY = 6  # turns kept for follow-ups; beyond this the thread has drifted


class CoachError(RuntimeError):
    pass


def triage_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "onTopic": {"type": "boolean"},
            "faults": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "faultId": {"type": "string", "enum": taxonomy.fault_ids()},
                        "likelihood": {"type": "number"},
                        "why": {"type": "string"},
                    },
                    "required": ["faultId", "likelihood", "why"],
                },
            },
            "clarifyingQuestion": {"type": "string"},
        },
        "required": ["onTopic", "faults"],
    }


def triage_prompt(question: str, analysis: dict | None) -> str:
    lines = [
        "A swimmer has described a problem with their freestyle. Map it onto the "
        "technique faults below — which of these, if any, would produce what they "
        "describe?",
        "",
        "FAULTS:",
    ]
    for f in taxonomy.faults():
        lines.append(f"- {f['id']} ({f['name']}): {f['short']}")
        lines.append(f"    why it matters: {f['why']}")

    if analysis:
        lines += ["", "This swimmer has had a video analysed. Their scored deviations:"]
        for a in analysis.get("assessments", []):
            lines.append(
                f"- {a['faultId']}: deviation {a['deviation']:.2f}, "
                f"confidence {a['confidence']:.2f} — {a['evidence']}"
            )
        lines.append(
            "Weight your answer towards what their own footage actually showed. If what "
            "they describe matches a fault their video scored high, say so."
        )

    lines += [
        "",
        f'THEIR QUESTION: "{question}"',
        "",
        "RULES:",
        "1. `likelihood` 0-1 is how strongly their description points at that fault. "
        "Return the two or three best matches, not all ten.",
        "2. A symptom usually has several plausible causes. Sinking legs can be body "
        "position, head position or a scissor kick — return all of them rather than "
        "guessing one.",
        "3. Set `onTopic` false if the question is not about swimming technique at all. "
        "General swimming questions — training, pacing, equipment, open water — are "
        "still on topic; just return no faults if none apply.",
        "4. Fill `clarifyingQuestion` only when the description is too vague to map at "
        "all, and make it a question a swimmer can answer without a coach present.",
    ]
    return "\n".join(lines)


def answer_prompt(question: str, faults: list[dict], drills: list[dict],
                  analysis: dict | None, history: list[dict]) -> str:
    lines = [
        "You are a swimming coach answering a question about freestyle technique. "
        "You are talking to an adult who trains on their own — likely a triathlete or "
        "a fitness swimmer, without a coach on deck.",
        "",
    ]

    if faults:
        lines.append("LIKELY CAUSES of what they describe, with the elite reference:")
        for f in faults:
            rec = taxonomy.fault_by_id()[f["faultId"]]
            lines.append(f"\n- {rec['name']} ({rec['id']}):")
            lines.append(f"    what it is: {rec['short']}")
            lines.append(f"    why it matters: {rec['why']}")
            lines.append(f"    elite reference: {rec['elite']}")
            lines.append(f"    how it shows up here: {f['why']}")
    else:
        lines.append(
            "None of the technique faults in our database clearly match this question. "
            "Answer from general swimming knowledge and say plainly that this is general "
            "advice rather than something tied to their stroke."
        )

    if drills:
        lines += ["", "DRILLS YOU MAY PRESCRIBE — these and no others:"]
        for d in drills:
            kit = ", ".join(d["equipment"]) or "no equipment"
            lines.append(f"\n- {d['title']} ({kit})")
            lines.append(f"    addresses: {', '.join(d['addressesNames'])}")
            lines.append(f"    what it is: {d['summary']}")
            lines.append(f"    why it helps: {d['why']}")
            if d.get("caution"):
                lines.append(f"    caution: {d['caution']}")

    if analysis:
        lines += [
            "",
            "THEIR OWN VIDEO ANALYSIS is available and summarised as: "
            + (analysis.get("summary") or "(no summary)"),
        ]

    if history:
        lines += ["", "EARLIER IN THIS CONVERSATION:"]
        for turn in history[-MAX_HISTORY:]:
            lines.append(f"  {turn['role']}: {turn['text']}")

    lines += [
        "",
        f'THEIR QUESTION: "{question}"',
        "",
        "HOW TO ANSWER:",
        "1. Lead with the likely cause in their own words — what is probably happening "
        "and why it produces what they feel. Two or three sentences.",
        "2. Then what to do about it. Name drills by title exactly as listed above. "
        "Never invent a drill or a name. If the list is empty, give general advice and "
        "say no specific drill is mapped to this.",
        "3. Say how to practise it: sets and distances an adult can do in a normal lane "
        "session, and what the drill should feel like when it is working.",
        "4. Plain language. No jargon without a short gloss — 'EVF' means nothing to "
        "most people, 'high elbow catch' does.",
        "5. Be honest about uncertainty. You are reading a description, not watching "
        "them swim; several of these faults look identical from the outside. Say so, "
        "and tell them what to film if they want a real answer.",
        "6. PAIN AND INJURY. If they mention pain, injury, numbness or anything that "
        "hurts, say plainly in your first sentence that this needs a physiotherapist or "
        "doctor who can examine them, and that you cannot tell a technique problem from "
        "a tissue problem through a description. You may still explain which technique "
        "faults are associated with that complaint, but never tell someone to train "
        "through pain, and never suggest a drill as a treatment for an injury.",
        "7. Under 300 words. Markdown, short paragraphs, no headings.",
    ]
    return "\n".join(lines)


def ask(question: str, analysis: dict | None = None, history: list[dict] | None = None,
        model: str | None = None, limit: int = 4, key: str | None = None) -> dict:
    """Answer a technique question. Returns the prose plus what grounded it.

    `key` is the caller's own Gemini key (the web UI sends it per request);
    without one it falls back to the environment, which is what the CLI uses.
    """
    question = (question or "").strip()
    if not question:
        raise CoachError("Ask a question.")

    key = key or config.api_key()
    history = history or []

    triaged = gemini.generate(
        [{"text": triage_prompt(question, analysis)}],
        triage_schema(), key, model=model, temperature=0.1, timeout=90,
    )

    if not triaged.get("onTopic", True):
        return {
            "question": question,
            "answer": "That is outside what this tool knows about — it only covers "
                      "freestyle swimming technique.",
            "faults": [],
            "drills": [],
            "clarifyingQuestion": "",
        }

    faults = sorted(triaged.get("faults", []), key=lambda f: -f["likelihood"])
    faults = [f for f in faults if f["likelihood"] >= 0.15][:3]

    # Feed the recommender the same shape the analyser produces. Likelihood
    # stands in for deviation: we do not know how bad it is, only how likely
    # this fault is to be the cause.
    pseudo = [
        {"faultId": f["faultId"], "deviation": f["likelihood"], "confidence": 1.0}
        for f in faults
    ]
    # If their video scored these faults, prefer that over a description.
    if analysis:
        scored = {a["faultId"]: a for a in analysis.get("assessments", [])}
        for p in pseudo:
            real = scored.get(p["faultId"])
            if real:
                p["deviation"] = max(p["deviation"], real["deviation"])
                p["confidence"] = real["confidence"]

    drills = [
        s.as_dict() for s in
        recommend.recommend(pseudo, limit=limit, threshold=0.1,
                            focus={f["faultId"] for f in faults})
    ]

    answer = gemini.generate(
        [{"text": answer_prompt(question, faults, drills, analysis, history)}],
        None, key, model=model, temperature=0.4, timeout=120,
    )

    return {
        "question": question,
        "answer": answer.strip() if isinstance(answer, str) else str(answer),
        "faults": [
            {
                "faultId": f["faultId"],
                "faultName": taxonomy.fault_name(f["faultId"]),
                "likelihood": round(f["likelihood"], 2),
                "why": f["why"],
            }
            for f in faults
        ],
        "drills": drills,
        "clarifyingQuestion": triaged.get("clarifyingQuestion", ""),
    }
