import { el, toast } from "../dom.js";
import * as api from "../api.js";
import state from "../state.js";
import { ensureConsent } from "../consent.js";
import { clearKey, describeStored, forgetEverything, getKey, keyIsRemembered, setKey, withdrawConsent } from "../store.js";

const ping = () => document.dispatchEvent(new Event("swimform:status"));

export async function mount(root) {
  const cfg = await api.get("/config");
  root.append(
    el("h1", { class: "page-title", text: "Settings" }),
    el("p", { class: "lede", text: "Your key, the model, and what swimform keeps." }),
    keyPanel(),
    modelPanel(cfg),
    analysisPanel(cfg),
    privacyPanel(),
  );
}

function keyPanel() {
  const input = el("input", { type: "password", autocomplete: "off", spellcheck: "false",
    placeholder: getKey() ? "A key is saved — paste a new one to replace it" : "Paste your Gemini API key",
    "aria-label": "Gemini API key" });
  const remember = el("input", { type: "checkbox", checked: keyIsRemembered() });
  const result = el("div", { "aria-live": "polite" });
  const where = el("p", { class: "small muted" });
  const paintWhere = () => {
    const s = describeStored().key;
    where.textContent = s === "none"
      ? (state.health && state.health.serverKey
          ? "No key in this browser. A key set on this computer's environment will be used."
          : "No key saved yet.")
      : `A key is held: ${s}.`;
  };
  paintWhere();

  const save = el("button", { class: "btn primary", type: "button", text: "Save and check" });
  const remove = el("button", { class: "btn quiet", type: "button", text: "Remove key" });

  save.addEventListener("click", async () => {
    if (!(await ensureConsent())) return;
    const typed = input.value.trim();
    if (typed) setKey(typed, remember.checked);
    else if (getKey()) setKey(getKey(), remember.checked);   // only the remember choice changed
    if (!getKey()) { result.replaceChildren(el("p", { class: "notice bad", text: "Paste a key first." })); return; }
    input.value = "";
    save.disabled = true;
    result.replaceChildren(el("p", { class: "muted", text: "Checking with Google…" }));
    try {
      const r = await api.checkKey();
      if (r.valid === true) {
        state.models = r.models;
        result.replaceChildren(el("p", { class: "notice ok" }, [el("b", { text: "The key works. " }), `${r.models.length} models can be used with it.`]));
      } else if (r.valid === false) {
        result.replaceChildren(el("p", { class: "notice bad", role: "alert", text: r.error }));
      } else {
        result.replaceChildren(el("p", { class: "notice bad", role: "alert", text: `Couldn't check the key: ${r.error}` }));
      }
    } catch (err) {
      result.replaceChildren(el("p", { class: "notice bad", role: "alert", text: err.message }));
    } finally {
      save.disabled = false;
      input.placeholder = "A key is saved — paste a new one to replace it";
      paintWhere(); ping();
    }
  });
  remove.addEventListener("click", () => {
    clearKey(); state.models = null; input.value = "";
    input.placeholder = "Paste your Gemini API key";
    result.replaceChildren(); paintWhere(); ping(); toast("Key removed from this browser");
  });

  return el("section", { class: "card", "aria-label": "Gemini API key" }, [
    el("h2", { text: "Your Gemini API key" }),
    el("p", { class: "muted", text:
      "swimform has no account and no server of its own. Each analysis runs on Google's Gemini service using " +
      "your key, so the usage is yours — and so is the bill, if your key has billing on." }),
    el("ol", {}, [
      el("li", {}, ["Get a key at ", el("a", { href: "https://aistudio.google.com/apikey", target: "_blank", rel: "noopener noreferrer", text: "aistudio.google.com/apikey" }), "."]),
      el("li", { text: "Paste it below. It is kept in this browser tab, and sent only to this computer's swimform server and on to Google." }),
      el("li", { text: "Never share it, never put it in a screenshot, and never commit it to a repository." }),
    ]),
    el("p", { class: "notice", text:
      "A free key works for trying this out, but Google may use what you send on the free tier, and its terms say " +
      "not to submit personal information there. If you film anyone but yourself, use a key with billing enabled." }),
    input,
    el("label", { class: "check" }, [remember, el("span", { text: "Remember it on this browser (otherwise it is forgotten when you close the tab)" })]),
    el("div", { class: "row center" }, [save, remove]),
    where, result,
  ]);
}

function modelPanel(cfg) {
  const current = cfg.models[0];
  const select = el("select", { "aria-label": "Preferred model" });
  const fill = () => {
    const names = state.models ? [...new Set([current, ...state.models])] : [current];
    select.replaceChildren(...names.map(n => el("option", { value: n, text: n, selected: n === current })));
  };
  fill();
  select.addEventListener("change", async () => {
    const chosen = select.value;
    const rest = cfg.models.filter(m => m !== chosen);
    try {
      const saved = await api.saveConfig({ models: [chosen, ...rest] });
      cfg.models = saved.models;
      toast(`${chosen} will be tried first`);
    } catch (err) { toast(err.message); }
  });
  return el("section", { class: "card", "aria-label": "Model" }, [
    el("h2", { text: "Model" }),
    el("p", { class: "muted", text:
      "Which model is best changes faster than this code does. swimform tries the models below in order and uses " +
      "the first that answers. Check your key above to list what it can use." }),
    el("label", { class: "label", text: "Try first" }), select,
    el("p", { class: "small faint num", text: "Fallback order: " + cfg.models.join(" → ") }),
  ]);
}

function analysisPanel(cfg) {
  const field = (id, label, hint, attrs) => {
    const input = el("input", { type: "number", id, value: cfg[id], ...attrs });
    return { id, input, node: el("div", { class: "field" }, [el("label", { class: "label", for: id, text: label }), input, el("div", { class: "small faint", text: hint })]) };
  };
  const fields = [
    field("fps", "Frames per second", "2 sees the catch", { min: "0.5", max: "10", step: "0.5" }),
    field("overlays", "Annotated frames", "0–6, each costs a request", { min: "0", max: "6", step: "1" }),
    field("evidencePerFault", "Stills per fault", "free, no model call", { min: "0", max: "6", step: "1" }),
    field("reportThreshold", "Report threshold", "below this is “clean”", { min: "0", max: "1", step: "0.05" }),
    field("retentionHours", "Keep images (hours)", "then deleted", { min: "1", max: "720", step: "1" }),
  ];
  const msg = el("span", { class: "small muted", "aria-live": "polite" });
  const save = el("button", { class: "btn", type: "button", text: "Save settings", onclick: async () => {
    const patch = Object.fromEntries(fields.map(f => [f.id, Number(f.input.value)]));
    try { Object.assign(cfg, await api.saveConfig(patch)); msg.textContent = "Saved."; }
    catch (err) { msg.textContent = err.message; }
  } });
  return el("section", { class: "card", "aria-label": "Analysis settings" }, [
    el("h2", { text: "Analysis" }),
    el("div", { class: "row" }, fields.map(f => f.node)),
    el("div", { class: "row center" }, [save, msg]),
  ]);
}

function privacyPanel() {
  const stored = describeStored();
  return el("section", { class: "card", "aria-label": "Privacy and data" }, [
    el("h2", { text: "Privacy and data" }),
    el("ul", {}, [
      el("li", { text: `Gemini key: ${stored.key}` }),
      el("li", { text: `Responsible-use notice accepted: ${stored.consent ? "yes" : "no"}` }),
      el("li", { text: `Saved swims in your progress history: ${stored.history}` }),
    ]),
    el("div", { class: "row" }, [
      el("button", { class: "btn quiet", type: "button", text: "Delete stored images now", onclick: async () => {
        try { const r = await api.purge(); toast(`Removed ${r.removed} stored item${r.removed === 1 ? "" : "s"}`); }
        catch (err) { toast(err.message); }
      } }),
      el("button", { class: "btn danger", type: "button", text: "Forget everything in this browser", onclick: () => {
        if (!confirm("Remove your key, your history and your consent from this browser?")) return;
        forgetEverything(); location.reload();
      } }),
      el("button", { class: "btn quiet", type: "button", text: "Show the notice again", onclick: () => { withdrawConsent(); ensureConsent(); } }),
      el("a", { class: "btn quiet", href: "#/about", text: "Responsible use" }),
    ]),
  ]);
}
