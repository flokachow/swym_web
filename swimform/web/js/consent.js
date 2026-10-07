// The responsible-use notice. Shown on first load, and again before anything is
// sent to the AI service until it has been accepted. The wording mirrors
// docs/RESPONSIBLE_USE.md, which holds the full text and the sources.

import { el } from "./dom.js";
import { CONSENT_VERSION, giveConsent, hasConsent } from "./store.js";

export const GOOGLE_TERMS = "https://ai.google.dev/gemini-api/terms";

const POINTS = [
  ["Where your video goes.",
   "Each clip is shortened on your computer and then sent over the internet to the AI service behind the API key " +
   "you provide. This version is built for Google's Gemini API, which we recommend because a key is freely " +
   "available to anyone. There is no swimform server and no account. Stills made from your clips are stored " +
   "on this computer for a limited time and can be deleted in Settings."],
  ["Free keys and personal data.",
   "AI providers usually let themselves use what you send on a free tier to improve their products, and people " +
   "may review it. They generally say not to send personal information there, and video of a person is " +
   "personal information. Use a paid key, or film only yourself."],
  ["Other people.",
   "Only film adults who have clearly agreed. Never film children, or anyone who has not agreed. " +
   "This tool is for people aged 18 and over."],
  ["Your key and costs.",
   "You are responsible for your API key, for any usage costs, and for following your provider's terms. " +
   "Keep the key private."],
  ["What the results are.",
   "Scores are estimates from an AI model measured against a reference that has not been validated on real " +
   "footage. This is not coaching, medical or physiotherapy advice. If something hurts, see a professional."],
  ["No warranty.",
   "Provided as is under the MIT licence. Not affiliated with or endorsed by Google or any other provider."],
];

const CHECKS = [
  "I understand my video is sent to an outside AI service under my own API key, and what that means on a free key.",
  "I will only film myself or adults who have agreed, and never children.",
  "I understand the results are not coaching or medical advice, and I am responsible for my key and its costs.",
];

export function noticeBody() {
  return el("div", {}, [
    el("ul", { class: "notice-list" }, POINTS.map(([head, text]) =>
      el("li", {}, [el("b", { text: head + " " }), text]))),
    el("p", { class: "small muted" }, [
      "For Gemini, Google's terms: ",
      el("a", { href: GOOGLE_TERMS, target: "_blank", rel: "noopener noreferrer", text: GOOGLE_TERMS }),
      ". Consent notice version ", CONSENT_VERSION, ".",
    ]),
  ]);
}

let pending = null;

// Resolves true once the notice has been accepted, false if the user declined.
export function ensureConsent() {
  if (hasConsent()) return Promise.resolve(true);
  if (pending) return pending;

  const dialog = document.getElementById("consent");
  pending = new Promise(resolve => {
    const boxes = CHECKS.map(text => {
      const input = el("input", { type: "checkbox" });
      return { input, row: el("label", { class: "check" }, [input, el("span", { text })]) };
    });
    const agree = el("button", { class: "btn primary", type: "button", text: "I agree", disabled: true });
    const later = el("button", { class: "btn quiet", type: "button", text: "Not now, just browse" });
    const update = () => { agree.disabled = !boxes.every(b => b.input.checked); };
    boxes.forEach(b => b.input.addEventListener("change", update));

    const finish = ok => {
      if (ok) giveConsent();
      dialog.close();
      dialog.replaceChildren();
      pending = null;
      resolve(ok);
    };
    agree.addEventListener("click", () => finish(true));
    later.addEventListener("click", () => finish(false));
    dialog.addEventListener("cancel", e => { e.preventDefault(); finish(false); }, { once: true });

    dialog.replaceChildren(el("div", { class: "inner" }, [
      el("h2", { id: "consent-title", text: "Before you use swimform" }),
      el("p", { class: "muted", text:
        "swimform analyses a video of you swimming by sending it to an AI service. Please read this once." }),
      noticeBody(),
      boxes.map(b => b.row),
      el("div", { class: "actions" }, [agree, later]),
    ]));
    dialog.showModal();
  });
  return pending;
}
