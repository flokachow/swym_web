import { el, svg } from "../dom.js";
import { clearHistory, getHistory, historyEnabled, setHistoryEnabled } from "../store.js";
import { get } from "../api.js";

export async function mount(root) {
  const { faults } = await get("/faults");
  const names = Object.fromEntries(faults.map(f => [f.id, f.name]));
  const history = getHistory();

  root.append(
    el("h1", { class: "page-title", text: "Progress" }),
    el("p", { class: "lede", text:
      "Scores from your past analyses, kept only in this browser — no images, no video. Scores move between " +
      "runs of the very same footage, so only changes of about 0.1 or more are worth reading as real." }),
  );

  const toggle = el("input", { type: "checkbox", checked: historyEnabled(),
    onchange: e => setHistoryEnabled(e.target.checked) });
  root.append(el("label", { class: "check" }, [toggle, el("span", { text: "Save a score history in this browser" })]));

  if (!history.length) {
    root.append(el("div", { class: "card" }, [
      el("h2", { text: "Nothing yet" }),
      el("p", { class: "muted", text: "Analyse a swim and its scores will appear here. Two or more swims show a trend per fault." }),
      el("a", { class: "btn primary", href: "#/analyse", text: "Analyse a swim" }),
    ]));
    return;
  }

  const seen = [...new Set(history.flatMap(h => Object.keys(h.scores)))];
  const trends = seen.map(id => {
    const pts = history.filter(h => id in h.scores).map(h => h.scores[id]);
    return { id, pts };
  }).filter(t => t.pts.length >= 2);

  if (trends.length) {
    root.append(el("h2", { class: "section-title", text: "Trends" }));
    const card = el("div", { class: "card" });
    trends.sort((a, b) => Math.abs(delta(b)) - Math.abs(delta(a))).forEach(t => {
      const d = delta(t);
      const word = Math.abs(d) < 0.1 ? "no clear change" : d < 0 ? `better by ${Math.abs(d).toFixed(2)}` : `worse by ${d.toFixed(2)}`;
      card.append(el("div", { class: "trend" }, [
        el("div", {}, [el("b", { text: names[t.id] || t.id }),
                       el("div", { class: "small muted num", text: `${t.pts[0].toFixed(2)} → ${t.pts[t.pts.length - 1].toFixed(2)} · ${word}` })]),
        spark(t.pts),
      ]));
    });
    root.append(card);
  } else {
    root.append(el("p", { class: "notice", text: "A single swim is saved so far. After a second analysis you will see trends here." }));
  }

  root.append(el("h2", { class: "section-title", text: "Swims" }));
  const list = el("div", { class: "card" });
  [...history].reverse().forEach(h => {
    const top = Object.entries(h.scores).sort((a, b) => b[1] - a[1]).slice(0, 3)
      .map(([id, v]) => `${names[id] || id} ${v.toFixed(2)}`).join(" · ");
    list.append(el("div", { class: "sess" }, [
      el("b", { text: new Date(h.date).toLocaleString() }),
      el("span", { class: "faint", text: ` · ${h.clips} clip${h.clips === 1 ? "" : "s"}` }),
      el("div", { text: h.headline }),
      el("div", { class: "small muted num", text: top }),
    ]));
  });
  root.append(list, el("div", { class: "row" }, [
    el("button", { class: "btn quiet", type: "button", text: "Export as JSON", onclick: () => exportJson(history) }),
    el("button", { class: "btn danger", type: "button", text: "Delete history", onclick: () => {
      if (confirm("Delete all saved scores from this browser?")) { clearHistory(); location.reload(); }
    } }),
  ]));
}

const delta = t => t.pts[t.pts.length - 1] - t.pts[0];

function spark(pts) {
  const w = 140, h = 36, pad = 4;
  const x = i => pad + (i * (w - 2 * pad)) / Math.max(1, pts.length - 1);
  const y = v => h - pad - v * (h - 2 * pad);
  const line = svg("polyline", { points: pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ") });
  const last = svg("circle", { cx: x(pts.length - 1).toFixed(1), cy: y(pts[pts.length - 1]).toFixed(1), r: 3 });
  return svg("svg", { viewBox: `0 0 ${w} ${h}`, role: "img", "aria-label": "Score trend, lower is better" }, [line, last]);
}

function exportJson(history) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(history, null, 2)], { type: "application/json" }));
  const a = el("a", { href: url, download: "swimform-history.json" });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
