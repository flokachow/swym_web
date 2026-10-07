// Router and boot. Hash routes, one module per view, loaded on demand.

import { el, clear } from "./js/dom.js";
import { get } from "./js/api.js";
import { ensureConsent } from "./js/consent.js";
import { getKey, hasConsent } from "./js/store.js";
import state from "./js/state.js";

const VIEWS = {
  analyse: () => import("./js/views/analyse.js"),
  drills: () => import("./js/views/drills.js"),
  progress: () => import("./js/views/progress.js"),
  ask: () => import("./js/views/ask.js"),
  settings: () => import("./js/views/settings.js"),
  about: () => import("./js/views/about.js"),
};

const root = document.getElementById("view");
let current = null;

function parseHash() {
  const [, name = "analyse", ...rest] = location.hash.split("/");
  return { name: VIEWS[name] ? name : "analyse", param: rest.join("/") || null };
}

async function route() {
  const { name, param } = parseHash();
  if (current && current.unmount) current.unmount();
  document.querySelectorAll("#nav a").forEach(a => {
    if (a.dataset.route === name) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  clear(root);
  try {
    current = await VIEWS[name]();
    await current.mount(root, { param, navigate: h => { location.hash = h; }, refreshStatus });
  } catch (err) {
    console.error(err);
    root.replaceChildren(el("p", { class: "notice bad", text: `This page failed to load: ${err.message}` }));
  }
  window.scrollTo(0, 0);
}

export async function refreshStatus() {
  const box = document.getElementById("status");
  try { state.health = await get("/health"); } catch { state.health = null; }
  const h = state.health;
  const pills = [];
  if (!h) {
    pills.push(el("span", { class: "pill bad", text: "Can't reach the swimform server" }));
  } else {
    if (!h.ffmpeg || !h.ffprobe) pills.push(el("span", { class: "pill bad", text: "ffmpeg not found" }));
    if (getKey() || h.serverKey) pills.push(el("span", { class: "pill", text: "Gemini key ready" }));
    else pills.push(el("a", { class: "pill bad", href: "#/settings", text: "Add your Gemini key" }));
  }
  box.replaceChildren(...pills);
}

window.addEventListener("hashchange", route);
document.addEventListener("swimform:status", refreshStatus);

(async function boot() {
  await refreshStatus();
  await route();
  if (!hasConsent()) ensureConsent();
})();
