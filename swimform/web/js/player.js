// A clip player that can be told to jump to a moment. The video is the user's
// own file, played straight from the browser — it never goes back to a server.

import { el, mmss } from "./dom.js";

export function createPlayer({ label, file, mismatch }) {
  const url = URL.createObjectURL(file);
  const time = el("span", { class: "time num", text: "0:00" });
  const video = el("video", {
    controls: true, preload: "metadata", playsinline: true, muted: true,
    "aria-label": `${label} footage`, src: url,
  });
  const stage = el("div", {}, [video]);
  const node = el("div", { class: "player" }, [
    el("div", { class: "head" }, [el("b", { text: label }), time]),
    stage,
    mismatch ? el("p", { class: "notice bad small", text: mismatch }) : null,
  ]);

  video.addEventListener("timeupdate", () => {
    time.textContent = `${mmss(video.currentTime)}${isFinite(video.duration) ? " / " + mmss(video.duration) : ""}`;
  });
  video.addEventListener("error", () => {
    stage.replaceChildren(el("div", { class: "failed" }, [
      el("b", { text: "This browser can't play that clip." }),
      el("p", { class: "small muted", text:
        "Phone clips in HEVC (.mov) play in Safari and Chrome on a Mac but not everywhere. " +
        "The stills under each finding were cut from the clip and still apply." }),
    ]));
  });

  return {
    node,
    seek(at) {
      if (!node.isConnected || !video.isConnected) return;
      video.currentTime = Math.max(0, at);
      video.play().catch(() => { /* needs a gesture on some browsers; the seek still happened */ });
      node.scrollIntoView({ behavior: "smooth", block: "nearest" });
    },
    destroy() { URL.revokeObjectURL(url); },
  };
}
