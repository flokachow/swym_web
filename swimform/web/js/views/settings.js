import { el, toast } from "../dom.js";
import * as api from "../api.js";
import state from "../state.js";
import { ensureConsent } from "../consent.js";
import {
  PROVIDER_IDS, clearKey, describeStored, forgetEverything, getKey, getProvider, keyIsRemembered,
  setKey, setProvider, withdrawConsent,
} from "../store.js";

const ping = () => document.dispatchEvent(new Event("swimform:status"));

export async function mount(root) {
  const [cfg, list] = await Promise.all([api.get("/config"), state.providers ? null : api.get("/providers")]);
  if (list) state.providers = list.providers;
  draw(root, cfg);
}

function draw(root, cfg) {
  root.replaceChildren(
    el("h1", { class: "page-title", text: "Settings" }),
    el("p", { class: "lede", text: "Which AI service to use, your key, and what swimform keeps." }),
    keyPanel(root, cfg),
    modelPanel(cfg),
    privacyPanel(),
  );
}

const info = id => state.providers.find(p => p.id === id);

function keyPanel(root, cfg) {
  const provider = getProvider();
  const spec = info(provider);

  // -- which service ------------------------------------------------------
  const choose = el("select", { id: "provider", "aria-label": "AI service" },
    state.providers.map(p => el("option", { value: p.id, text: p.label + (p.recommended ? " (recommended)" : ""),
                                            selected: p.id === provider })));
  choose.addEventListener("change", () => {
    setProvider(choose.value);
    state.models = null;
    ping();
    draw(root, cfg);
  });

  const input = el("input", { type: "password", autocomplete: "off", spellcheck: "false",
    placeholder: getKey() ? "A key is saved — paste a new one to replace it" : "Paste your API key",
    "aria-label": "API key" });
  const remember = el("input", { type: "checkbox", checked: keyIsRemembered() });
  const result = el("div", { "aria-live": "polite" });
  const where = el("p", { class: "small muted" });
  const paintWhere = () => {
    const held = describeStored().keys[provider];
    where.textContent = held
      ? `A ${spec.label.replace(" (experimental)", "")} key is held: ${held}.`
      : (state.health && state.health.serverKeys && state.health.serverKeys[provider]
          ? "No key in this browser. A key set on this computer's environment will be used."
          : "No key saved yet.");
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
    result.replaceChildren(el("p", { class: "muted", text: "Checking the key…" }));
    try {
      const r = await api.checkKey();
      if (r.valid === true) {
        state.models = r.models;
        result.replaceChildren(el("p", { class: "notice ok" }, [el("b", { text: "The key works. " }), `${r.models.length} models can be used with it.`]));
        draw(root, cfg);   // refresh the model list below
        return;
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
    input.placeholder = "Paste your API key";
    result.replaceChildren(); paintWhere(); ping(); toast("Key removed from this browser");
  });

  const experimental = !spec.nativeVideo;
  return el("section", { class: "card", "aria-label": "AI service and API key" }, [
    el("h2", { text: "Your API key" }),
    el("p", { class: "muted", text:
      "swimform has no account and no server of its own. Each analysis runs on an AI service using your key, " +
      "so the usage is yours — and so is the bill, if your key has billing on." }),
    el("label", { class: "label", for: "provider", text: "AI service" }), choose,
    el("p", { class: "small muted", text: experimental
      ? "Experimental. This service cannot take video, so swimform sends it still frames cut from your clip. " +
        "Timing is coarser and results can differ from Gemini's, which is the better-tested choice."
      : "Recommended. Gemini takes the video directly, so it sees the whole stroke, and a key is freely available." }),
    el("ol", {}, [
      el("li", {}, ["Get a key at ", el("a", { href: spec.keyUrl, target: "_blank", rel: "noopener noreferrer", text: spec.keyUrl.replace("https://", "") }), "."]),
      el("li", { text: "Paste it below. It is kept in this browser tab, and sent only to this computer's swimform server and on to the AI service." }),
      el("li", { text: "Never share it, never put it in a screenshot, and never commit it to a repository." }),
    ]),
    el("p", { class: "notice", text:
      "A free key works for trying this out, but providers may use what you send on a free tier and generally say " +
      "not to submit personal information there. If you film anyone but yourself, use a paid key." }),
    input,
    el("label", { class: "check" }, [remember, el("span", { text: "Remember it on this browser (otherwise it is forgotten when you close the tab)" })]),
    el("div", { class: "row center" }, [save, remove]),
    where, result,
  ]);
}

function modelPanel(cfg) {
  const provider = getProvider();
  const spec = info(provider);
  const setting = spec.modelsSetting;
  const chain = cfg[setting];
  const current = chain[0];
  const select = el("select", { "aria-label": "Preferred model" });
  const names = state.models ? [...new Set([current, ...state.models])] : [current];
  select.replaceChildren(...names.map(n => el("option", { value: n, text: n, selected: n === current })));
  select.addEventListener("change", async () => {
    const chosen = select.value;
    const rest = chain.filter(m => m !== chosen);
    try {
      const saved = await api.saveConfig({ [setting]: [chosen, ...rest] });
      cfg[setting] = saved[setting];
      toast(`${chosen} will be tried first`);
    } catch (err) { toast(err.message); }
  });
  return el("section", { class: "card", "aria-label": "Model" }, [
    el("h2", { text: "Model" }),
    el("p", { class: "muted", text:
      "Which model is best changes faster than this code does. swimform tries the models below in order and uses " +
      "the first that answers. Check your key above to list what it can use. The default names are best guesses " +
      "and may be out of date; a name that no longer exists is skipped." }),
    el("label", { class: "label", text: `Try first (${spec.label.replace(" (experimental)", "")})` }), select,
    el("p", { class: "small faint num", text: "Order: " + chain.join(" → ") }),
  ]);
}

function privacyPanel() {
  const stored = describeStored();
  const held = PROVIDER_IDS.filter(p => stored.keys[p])
    .map(p => `${info(p).label.replace(" (experimental)", "")}: ${stored.keys[p]}`);
  return el("section", { class: "card", "aria-label": "Privacy and data" }, [
    el("h2", { text: "Privacy and data" }),
    el("ul", {}, [
      el("li", { text: `API keys held: ${held.length ? held.join("; ") : "none"}` }),
      el("li", { text: `Responsible-use notice accepted: ${stored.consent ? "yes" : "no"}` }),
      el("li", { text: `Saved swims in your progress history: ${stored.history}` }),
    ]),
    el("div", { class: "row" }, [
      el("button", { class: "btn quiet", type: "button", text: "Delete stored images now", onclick: async () => {
        try { const r = await api.purge(); toast(`Removed ${r.removed} stored item${r.removed === 1 ? "" : "s"}`); }
        catch (err) { toast(err.message); }
      } }),
      el("button", { class: "btn danger", type: "button", text: "Forget everything in this browser", onclick: () => {
        if (!confirm("Remove your keys, your history and your consent from this browser?")) return;
        forgetEverything(); location.reload();
      } }),
      el("button", { class: "btn quiet", type: "button", text: "Show the notice again", onclick: () => { withdrawConsent(); ensureConsent(); } }),
      el("a", { class: "btn quiet", href: "#/about", text: "Responsible use" }),
    ]),
  ]);
}
