import { el } from "../dom.js";
import { noticeBody, GOOGLE_TERMS } from "../consent.js";

export function mount(root) {
  root.append(
    el("h1", { class: "page-title", text: "Responsible use" }),
    el("p", { class: "lede", text:
      "swimform is a research and teaching tool. Read this before you film anyone." }),
    el("div", { class: "card" }, [noticeBody()]),
    el("h2", { class: "section-title", text: "What it can and cannot do" }),
    el("ul", {}, [
      el("li", { text: "It scores ten freestyle technique faults as a distance from an elite reference, not as pass or fail." }),
      el("li", { text: "None of the ten faults has been validated against real footage; every one is a candidate." }),
      el("li", { text: "The measurement bands (elbow angle, body line, head height) are estimates, not sourced thresholds." }),
      el("li", { text: "Calibration still runs soft: a low score is weaker evidence than a high one." }),
      el("li", { text: "A camera angle may genuinely be unable to judge a fault. Filming the second angle fixes most of that." }),
      el("li", { text: "The drills are written for this project and have not been reviewed by a qualified coach." }),
    ]),
    el("h2", { class: "section-title", text: "Your data" }),
    el("ul", {}, [
      el("li", { text: "Clips are re-encoded on your computer, sent to the AI service for the analysis, and deleted from this computer as soon as the analysis ends." }),
      el("li", { text: "Stills and annotated frames stay in swimform's folder on this computer for the retention time in Settings, then are deleted." }),
      el("li", { text: "Your key, your progress history and your consent are stored only in this browser, and can be removed from Settings." }),
      el("li", { text: "Nothing else leaves your computer: no analytics, no telemetry, no account." }),
    ]),
    el("p", { class: "small muted" }, [
      "The full text, with sources and a short note on data-protection law, is in ",
      el("code", { text: "docs/RESPONSIBLE_USE.md" }), " in the repository. Google's terms: ",
      el("a", { href: GOOGLE_TERMS, target: "_blank", rel: "noopener noreferrer", text: GOOGLE_TERMS }),
      ". This is a good-faith summary, not legal advice.",
    ]),
  );
}
