// Film from two angles, analyse each, read the merged verdict.

import { el, clear, mmss, bytes, toast } from "../dom.js";
import * as api from "../api.js";
import state from "../state.js";
import { ensureConsent } from "../consent.js";
import { addHistory, getKey } from "../store.js";
import { createPlayer } from "../player.js";

const MAX_BYTES = 512 * 1024 * 1024;
const SLOTS = {
  side: {
    title: "Side view",
    rules: ["From the pool edge, level with the water", "Whole body in frame, close enough to read an elbow",
            "10–20 seconds of steady swimming"],
  },
  front: {
    title: "Front view",
    rules: ["From the end of the lane, as the swimmer comes towards you", "Head to feet in frame",
            "10–20 seconds; this view judges crossover, kick and rotation"],
  },
};

let ui = null;       // elements of the mounted view
let players = {};    // slot -> player
let timers = {};

export function mount(root, ctx) {
  ui = { root, ctx };
  const intro = [
    el("h1", { class: "page-title", text: "Analyse your stroke" }),
    el("p", { class: "lede", text:
      "Add a clip from the side, from the front, or both. Two angles beat one: half of the faults " +
      "can only be judged from the front, and a side-only analysis has to say \"can't tell\" about them." }),
  ];
  ui.notice = el("div");
  ui.slots = el("div", { class: "grid2" }, Object.keys(SLOTS).map(slotCard));
  ui.go = el("button", { class: "btn primary", type: "button", text: "Analyse", onclick: run });
  ui.bar = el("div", { class: "row center" }, [
    ui.go,
    el("span", { class: "small muted", text: "Clips are trimmed and sent to Google Gemini with your key." }),
  ]);
  ui.results = el("div", { id: "results" });
  root.append(...intro, ui.notice, ui.slots, ui.bar, ui.results);
  refreshButtons();
  if (state.combined) renderResults();
}

export function unmount() {
  for (const t of Object.values(timers)) clearInterval(t);
  timers = {};
  // Players hold blob URLs for the clips; the clips themselves stay in state.
  Object.values(players).forEach(p => p.destroy());
  players = {};
}

// -- the two clip slots ----------------------------------------------------

function slotCard(slot) {
  const spec = SLOTS[slot];
  const input = el("input", { type: "file", accept: "video/*,.mov,.mp4,.m4v", hidden: true });
  const title = el("div", { class: "big" });
  const sub = el("div", { class: "small muted" });
  const drop = el("div", { class: "drop", tabindex: "0", role: "button",
                           "aria-label": `Choose the ${spec.title.toLowerCase()} clip` }, [title, sub]);
  const start = el("input", { type: "number", min: "0", step: "1", placeholder: "0", "aria-label": `${spec.title} start seconds` });
  const end = el("input", { type: "number", min: "0", step: "1", placeholder: "auto", "aria-label": `${spec.title} end seconds` });
  const status = el("div", { class: "run-state" });
  const remove = el("button", { class: "btn quiet small", type: "button", text: "Remove", hidden: true });

  const paint = () => {
    const c = state.clips[slot];
    drop.classList.toggle("has", !!c);
    title.textContent = c ? c.file.name : "Drop a video here, or click to choose";
    sub.textContent = c ? `${bytes(c.file.size)} — click to change` : "mp4, mov, m4v";
    remove.hidden = !c;
    start.value = c && c.start != null ? c.start : "";
    end.value = c && c.end != null ? c.end : "";
    start.disabled = end.disabled = !c;
    paintStatus(slot, status);
  };

  const pick = f => {
    if (!f) return;
    if (!f.type.startsWith("video/") && !/\.(mp4|mov|m4v|avi|mkv)$/i.test(f.name)) {
      return fail("That doesn't look like a video file.");
    }
    if (f.size > MAX_BYTES) {
      return fail(`That file is ${bytes(f.size)}; the limit is 512 MB. Trim it on your phone first — 10–20 seconds is plenty.`);
    }
    state.clips[slot] = { file: f, start: null, end: null };
    state.runs[slot] = null;
    state.combined = null;
    clear(ui.results);
    ui.notice.replaceChildren();
    paint(); refreshButtons();
  };

  drop.addEventListener("click", () => input.click());
  drop.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => pick(input.files[0]));
  ["dragenter", "dragover"].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => pick(e.dataTransfer.files[0]));
  start.addEventListener("input", () => { if (state.clips[slot]) state.clips[slot].start = num(start.value); });
  end.addEventListener("input", () => { if (state.clips[slot]) state.clips[slot].end = num(end.value); });
  remove.addEventListener("click", () => {
    state.clips[slot] = null; state.runs[slot] = null; state.combined = null;
    clear(ui.results); paint(); refreshButtons();
  });

  const card = el("section", { class: "slot", "aria-label": spec.title }, [
    el("h3", { text: spec.title }),
    el("ul", { class: "rules" }, spec.rules.map(r => el("li", { text: r }))),
    drop, input,
    el("div", { class: "row" }, [
      el("div", { class: "field" }, [el("label", { class: "label", text: "Start (s)" }), start]),
      el("div", { class: "field" }, [el("label", { class: "label", text: "End (s)" }), end]),
      el("div", { class: "spacer" }), remove,
    ]),
    status,
  ]);
  card._paint = paint;
  paint();
  return card;
}

const num = v => (v === "" || isNaN(Number(v)) ? null : Number(v));

function fail(message) {
  ui.notice.replaceChildren(el("p", { class: "notice bad", role: "alert" }, [el("b", { text: "Didn't work. " }), message]));
}

function refreshButtons() {
  const any = Object.values(state.clips).some(Boolean);
  const busy = Object.values(state.runs).some(r => r && r.status === "running");
  ui.go.disabled = !any || busy;
  ui.go.textContent = busy ? "Analysing…" : (any ? "Analyse" : "Add a clip to start");
}

function paintStatus(slot, box) {
  const r = state.runs[slot];
  box.replaceChildren();
  if (!r) return;
  if (r.status === "running") {
    const label = el("span", { text: "Uploading…" });
    box.append(el("div", { class: "bar working bar-wrap" }, [el("i")]), label);
    const tick = () => {
      const s = Math.round((Date.now() - r.startedAt) / 1000);
      label.textContent = `${s < 5 ? "Preparing" : s < 40 ? "Watching the clip" : "Scoring against the reference"} · ${mmss(s)}`;
    };
    tick();
    clearInterval(timers[slot]);
    timers[slot] = setInterval(tick, 500);
  } else if (r.status === "error") {
    clearInterval(timers[slot]);
    box.append(el("span", { class: "sev high", text: `Failed: ${r.error}` }),
      el("button", { class: "btn quiet small", type: "button", text: "Try this clip again", onclick: () => run(slot) }));
  } else {
    clearInterval(timers[slot]);
    box.append(el("span", { class: "muted", text: `Analysed${r.result.viewpoint ? " — reads as a " + r.result.viewpoint + " view" : ""}.` }));
  }
}

function repaintSlots() {
  [...ui.slots.children].forEach(c => c._paint && c._paint());
  refreshButtons();
}

// -- running an analysis ---------------------------------------------------

async function run(only) {
  if (!(await ensureConsent())) {
    return fail("Read and accept the responsible-use notice first — it explains where your video goes.");
  }
  if (!getKey() && !(state.health && state.health.serverKey)) {
    ui.notice.replaceChildren(el("p", { class: "notice bad", role: "alert" }, [
      el("b", { text: "A Gemini API key is needed. " }),
      "Paste yours in ", el("a", { href: "#/settings", text: "Settings" }),
      " — it takes a minute. Settings also explains what a free key means for your video.",
    ]));
    return;
  }
  ui.notice.replaceChildren();

  const slots = typeof only === "string" ? [only]
    : Object.keys(SLOTS).filter(s => state.clips[s] && !(state.runs[s] && state.runs[s].status === "done"));
  if (!slots.length) slots.push(...Object.keys(SLOTS).filter(s => state.clips[s]));

  clear(ui.results);
  state.combined = null;
  slots.forEach(s => { state.runs[s] = { status: "running", startedAt: Date.now() }; });
  repaintSlots();

  await Promise.all(slots.map(async slot => {
    const c = state.clips[slot];
    try {
      const result = await api.analyse(c.file, slot, c.start, c.end);
      state.runs[slot] = { status: "done", result };
    } catch (err) {
      state.runs[slot] = { status: "error", error: err.message };
      if (err.needsKey) {
        ui.notice.replaceChildren(el("p", { class: "notice bad", role: "alert" }, [
          el("b", { text: "Google rejected the key. " }), "Check it in ", el("a", { href: "#/settings", text: "Settings" }), "."]));
      }
    }
  }));
  repaintSlots();
  document.dispatchEvent(new Event("swimform:status"));
  await showCombined();
}

async function showCombined() {
  const done = Object.keys(SLOTS).filter(s => state.runs[s] && state.runs[s].status === "done");
  if (!done.length) return;
  try {
    const combined = await api.combine(done.map(slot => ({ slot, result: state.runs[slot].result })));
    state.combined = combined;
    record(combined);
    renderResults();
  } catch (err) {
    fail(err.message);
  }
}

function record(c) {
  if (!c.swimmerVisible) return;
  const scores = {};
  c.assessments.forEach(a => { scores[a.faultId] = a.deviation; });
  addHistory({ date: new Date().toISOString(), clips: c.clips.length, headline: c.headline, scores });
}

// -- results -----------------------------------------------------------------

function renderResults() {
  const c = state.combined;
  const box = ui.results;
  clear(box);
  Object.values(players).forEach(p => p.destroy());
  players = {};

  if (!c.swimmerVisible) {
    box.append(el("div", { class: "card" }, [
      el("h2", { text: "No swimmer found" }),
      el("p", { class: "muted", text: "No swimmer was clearly visible. Film with the whole body in frame, keep the swimmer large enough that an elbow is readable, and avoid glare." }),
      ...c.warnings.map(w => el("p", { class: "notice bad", text: w.message })),
    ]));
    return;
  }

  const threshold = c.reportThreshold;
  const reported = c.assessments.filter(a => a.deviation >= threshold);
  const clean = c.assessments.filter(a => a.deviation < threshold);
  const single = c.clips.length === 1;

  // verdict
  const verdict = el("section", { class: "card", "aria-label": "Verdict" }, [
    el("div", { class: "verdict", text: c.headline }),
    ...Object.entries(c.summaries).map(([slot, text]) =>
      el("div", { class: "summ" }, [el("div", { class: "who", text: `${SLOTS[slot].title} clip` }), el("div", { text }) ])),
    ...c.warnings.map(w => el("p", { class: "notice bad", role: "alert", text: w.message })),
    el("div", { class: "meta num" }, [
      meta("viewpoint", c.viewpoint),
      c.strokeCount ? meta("strokes", "~" + c.strokeCount) : null,
      meta("scored", String(c.assessments.length)),
      meta("report threshold", c.reportThreshold.toFixed(2)),
    ]),
  ]);
  box.append(el("h2", { class: "section-title", text: "Your result" }), verdict);

  // footage
  const footage = el("section", { "aria-label": "Your footage" });
  c.clips.forEach(clip => {
    const file = state.clips[clip.slot] && state.clips[clip.slot].file;
    if (!file) return;
    const vp = c.viewpoints.find(v => v.slot === clip.slot);
    const p = createPlayer({
      label: `${SLOTS[clip.slot].title} clip`, file,
      mismatch: vp && vp.mismatch ? `You filed this as the ${clip.slot} view, but it reads as the ${vp.read} view.` : null,
    });
    players[clip.slot] = p;
    footage.append(p.node);
  });
  if (footage.children.length) {
    box.append(el("h2", { class: "section-title", text: "Your footage" }), footage);
  }

  // what to work on
  if (reported.length) {
    const list = el("section", { class: "card", "aria-label": "What to work on" });
    reported.forEach(a => list.append(faultCard(a, single)));
    box.append(el("h2", { class: "section-title", text: "What to work on" }), list);
  } else {
    box.append(el("p", { class: "notice ok", text: "Nothing in this footage rose above the reporting threshold." }));
  }

  if (clean.length) {
    box.append(el("h2", { class: "section-title", text: "Checked and clean" }),
      el("div", { class: "chips" }, clean.map(a =>
        el("span", { class: "chip", title: a.evidence }, [a.faultName, el("span", { class: "faint num", text: a.deviation.toFixed(2) })]))));
  }

  if (c.notAssessable.length) {
    const unjudged = el("section", { class: "card" }, c.notAssessable.map(n =>
      el("div", { class: "fault" }, [
        el("div", { class: "fault-name", text: n.faultName }),
        el("p", { text: n.reason }),
      ])));
    box.append(el("h2", { class: "section-title", text: single ? "Not judgeable from this angle" : "Neither angle could show these" }),
      unjudged);
    if (single) {
      box.append(el("p", { class: "notice", text: "Film the other angle and run both together — what a side camera cannot see, a front camera usually can, and the other way round." }));
    }
  }

  if (c.drills.length) {
    box.append(el("h2", { class: "section-title", text: "Do this next" }),
      el("div", { class: "drill-list" }, c.drills.map(d =>
        el("a", { class: "drill", href: `#/drills/${d.id}` }, [
          el("h3", { text: d.title }),
          el("p", { text: d.summary }),
          el("div", { class: "why-this", text: d.reason }),
          el("div", { class: "chips" }, d.equipment.length ? d.equipment.map(e => el("span", { class: "tag", text: e })) : [el("span", { class: "tag", text: "no equipment" })]),
        ]))));
  }

  box.append(el("div", { class: "row", }, [
    el("button", { class: "btn quiet", type: "button", text: "Download report (.md)", onclick: () => download(c) }),
    el("a", { class: "btn quiet", href: "#/ask", text: "Ask about this result" }),
  ]));
  box.firstChild.scrollIntoView({ behavior: "smooth", block: "start" });
}

const meta = (k, v) => el("span", {}, [k + " ", el("b", { text: v })]);

function faultCard(a, single) {
  const seek = at => { const p = players[a.fromClip]; if (p) p.seek(at); };
  const stills = a.moments.filter(m => m.image);
  const kids = [
    el("div", { class: "fault-head" }, [
      el("div", { class: "fault-name", text: a.faultName }),
      el("div", { class: "sev" + (a.severity.key === "high" ? " high" : ""), text: a.severity.label }),
    ]),
    el("div", { class: "bar" + (a.severity.key === "high" ? " high" : ""), role: "img",
                "aria-label": `Deviation ${a.deviation.toFixed(2)} out of 1` }, [
      el("i"),
    ]),
    el("p", { text: a.evidence }),
    el("div", { class: "src" }, [a.clarity + (single ? "" : ` · judged from the ${a.fromClip} clip`)]),
  ];
  kids[1].firstChild.style.width = `${Math.max(3, Math.round(a.deviation * 100))}%`;

  if (a.moments.length && players[a.fromClip]) {
    kids.push(el("div", { class: "moments" }, [
      el("span", { class: "label", text: "Jump to" }),
      ...a.moments.map(m => el("button", { class: "chip", type: "button", onclick: () => seek(m.at),
                                           "aria-label": `Jump to ${mmss(m.at)}`, text: mmss(m.at) })),
    ]));
  } else if (a.moments.length) {
    kids.push(el("div", { class: "src", text: "Seen at " + a.moments.map(m => mmss(m.at)).join("  ") }));
  }
  if (stills.length) {
    kids.push(el("div", { class: "stills" }, stills.map(m =>
      el("button", { class: "still", type: "button", onclick: () => seek(m.at), "aria-label": `Show ${mmss(m.at)} in the clip` }, [
        el("img", { src: m.image, alt: `${a.faultName} at ${mmss(m.at)}`, loading: "lazy" }),
        el("span", { text: mmss(m.at) }),
      ]))));
  }
  if (a.frame) {
    kids.push(el("figure", { class: "frame" }, [
      el("img", { src: a.frame.image, alt: `Annotated frame for ${a.faultName}`, loading: "lazy" }),
      el("figcaption", { text: "Skeleton and angles are computed from landmarks the model located — arithmetic, not a guess at an angle." }),
    ]));
  }
  if (a.measurements.length) {
    kids.push(el("div", {}, a.measurements.map(m =>
      el("div", { class: "measure" }, [
        el("div", { class: `v ${m.verdict}`, text: m.unit === "ratio" ? m.value.toFixed(2) : `${Math.round(m.value)}°` }),
        el("div", {}, [m.label, m.confident ? null : el("span", { class: "est", text: "  estimated — landmark partly hidden" })]),
        el("div", { class: "ref", text: m.reference }),
      ]))));
  }
  return el("div", { class: "fault" }, kids);
}

function download(c) {
  const url = URL.createObjectURL(new Blob([c.markdown], { type: "text/markdown" }));
  const a = el("a", { href: url, download: "swimform-report.md" });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("Report saved");
}
