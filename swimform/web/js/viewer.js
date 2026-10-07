// The 3D drill demonstration: a self-contained page in a sandboxed frame,
// driven by messages. The frame has no access to this page, its storage or the
// network; it can only draw and report that it is ready.

import { el } from "./dom.js";

const SPEEDS = [["0.25×", 0.25], ["0.5×", 0.5], ["1×", 1]];
const VIEWS = [["Side", "side"], ["Front", "front"], ["Above", "above"], ["Below", "below"], ["Reset", "default"]];

// Strictest first: no access to this page at all. Some browsers refuse to load a frame with
// an opaque origin, so if the viewer has not reported in after a few seconds it is retried with
// the same-origin sandbox — still script-only, and the page it loads is our own bundle.
const ISOLATED = "allow-scripts";
const SAME_ORIGIN = "allow-scripts allow-same-origin";

export function createViewer(demo) {
  let frame = null;
  let ready = false;
  let timer = null;
  const src = `/static/viewer/viewer.html#drill=${encodeURIComponent(demo)}&hud=0&speed=0.5`;
  const box = el("div", { class: "viewer-box" });

  const load = sandbox => {
    frame = el("iframe", { title: "3D demonstration of the drill", sandbox, src });
    box.replaceChildren(frame, tools);
    ready = false;
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (!ready && sandbox === ISOLATED) load(SAME_ORIGIN);
      else if (!ready) fail();
    }, 4000);
  };
  const fail = () => {
    node.replaceChildren(el("p", { class: "notice", text:
      "The 3D demonstration could not start in this browser (it needs WebGL)." }));
  };
  const send = (call, ...args) => {
    if (frame && frame.contentWindow) frame.contentWindow.postMessage({ swimform: "drill3d", call, args }, "*");
  };

  let playing = true;
  const play = el("button", { class: "btn small", type: "button", text: "Pause",
    onclick: () => { playing = !playing; send("setPlaying", playing); play.textContent = playing ? "Pause" : "Play"; } });

  const tools = el("div", { class: "viewer-tools" }, [
    play,
    el("span", { class: "label", text: "Speed" }),
    ...SPEEDS.map(([label, v]) => el("button", { class: "chip", type: "button", text: label, onclick: () => send("setSpeed", v) })),
    el("span", { class: "label", text: "View" }),
    ...VIEWS.map(([label, v]) => el("button", { class: "chip", type: "button", text: label, onclick: () => send("setView", v) })),
  ]);

  const note = el("p", { class: "small faint", text:
    "Drag to turn the swimmer. The movement is hand-authored for this project, not motion-captured from a coach." });
  const node = el("div", {}, [box, note]);

  const onMessage = e => {
    if (!frame || e.source !== frame.contentWindow || !e.data || e.data.swimform !== "drill3d") return;
    if (e.data.event === "ready") { ready = true; clearTimeout(timer); }
    if (e.data.event === "error") { clearTimeout(timer); fail(); }
  };
  window.addEventListener("message", onMessage);
  load(ISOLATED);

  return { node, destroy() { clearTimeout(timer); window.removeEventListener("message", onMessage); } };
}
