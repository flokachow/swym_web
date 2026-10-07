import { el, richText } from "../dom.js";
import * as api from "../api.js";
import state from "../state.js";
import { ensureConsent } from "../consent.js";
import { getKey } from "../store.js";

const EXAMPLES = [
  "My legs sink as soon as I breathe",
  "I feel like I'm pulling but going nowhere",
  "How do I stop snaking down the lane?",
  "What should I work on first?",
];

export function mount(root) {
  const thread = el("div", { class: "thread", "aria-live": "polite" });
  const input = el("input", { type: "text", placeholder: "My legs sink as soon as I breathe — why?",
                              "aria-label": "Your question", maxlength: "2000" });
  const send = el("button", { class: "btn primary", type: "button", text: "Ask" });
  const ctx = state.combined && state.combined.swimmerVisible;

  root.append(
    el("h1", { class: "page-title", text: "Ask about your technique" }),
    el("p", { class: "lede", text:
      "Questions are answered from the ten faults and the drill library, so any drill it names is a real one. " +
      "Ask about technique; for pain or injury, see a physio." }),
    el("p", { class: "notice" + (ctx ? " ok" : ""), text: ctx
      ? "Answering against the swim you just analysed — your own scores are taken into account."
      : "Answers are based on your description alone. Analyse a swim first and they will be written against what your footage showed." }),
    el("div", { class: "card" }, [
      thread,
      el("div", { class: "row" }, [el("div", { class: "grow" }, [input]), send]),
      el("div", { class: "chips" }, EXAMPLES.map(t => el("button", { class: "chip", type: "button", text: t, onclick: () => ask(t) }))),
    ]),
  );
  state.chat.forEach(t => addTurn(thread, t));

  async function ask(question) {
    question = question.trim();
    if (!question) return;
    if (!(await ensureConsent())) return;
    if (!getKey() && !(state.health && state.health.serverKey)) {
      return addTurn(thread, { role: "coach", error: "Add your Gemini key in Settings first.", link: true });
    }
    input.value = "";
    send.disabled = true;
    const you = { role: "swimmer", text: question };
    addTurn(thread, you);
    const pending = addTurn(thread, { role: "coach", text: "thinking…" });
    try {
      const analysis = ctx ? {
        summary: state.combined.summary,
        assessments: state.combined.assessments.map(a => ({
          faultId: a.faultId, deviation: a.deviation, confidence: a.confidence, evidence: a.evidence })),
      } : null;
      const history = state.chat.filter(t => t.text).slice(-6).map(t => ({ role: t.role, text: t.text }));
      const res = await api.ask(question, analysis, history);
      const turn = { role: "coach", text: res.answer, drills: res.drills, faults: res.faults };
      state.chat.push(you, turn);
      pending.replaceWith(turnNode(turn));
    } catch (err) {
      pending.replaceWith(turnNode({ role: "coach", error: err.message, link: err.needsKey }));
    } finally {
      send.disabled = false;
      input.focus();
    }
  }

  send.addEventListener("click", () => ask(input.value));
  input.addEventListener("keydown", e => { if (e.key === "Enter") ask(input.value); });
}

function addTurn(thread, turn) {
  const node = turnNode(turn);
  thread.append(node);
  node.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return node;
}

function turnNode(t) {
  const you = t.role === "swimmer";
  const body = el("div", { class: "msg" });
  if (t.error) {
    body.append(el("p", { class: "notice bad", text: t.error }));
    if (t.link) body.append(el("a", { href: "#/settings", text: "Open Settings" }));
  } else if (you) {
    body.append(el("p", { text: t.text }));
  } else {
    body.append(richText(t.text));
  }
  if (t.drills && t.drills.length) {
    body.append(el("div", { class: "chips" }, t.drills.map(d =>
      el("a", { class: "chip", href: `#/drills/${d.id}`, text: d.title }))));
  }
  return el("div", { class: you ? "you" : "coach" }, [el("div", { class: "who", text: you ? "you" : "coach" }), body]);
}
