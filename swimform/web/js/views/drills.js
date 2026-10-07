import { el, clear, append } from "../dom.js";
import { get } from "../api.js";
import { createViewer } from "../viewer.js";

let viewer = null;

export async function mount(root, { param }) {
  const [{ drills }, { faults }] = await Promise.all([get("/drills"), get("/faults")]);
  if (param) {
    const drill = drills.find(d => d.id === param);
    return drill ? detail(root, drill) : root.append(
      el("p", { class: "notice bad", text: "There is no drill with that name." }),
      el("a", { href: "#/drills", text: "All drills" }));
  }
  list(root, drills, faults);
}

export function unmount() {
  if (viewer) viewer.destroy();
  viewer = null;
}

function list(root, drills, faults) {
  const state = { q: "", fault: null, kit: "" };
  const kits = [...new Set(drills.flatMap(d => d.equipment))].sort();

  const grid = el("div", { class: "drill-list" });
  const count = el("p", { class: "small muted" });
  const paint = () => {
    const q = state.q.trim().toLowerCase();
    const shown = drills.filter(d =>
      (!q || `${d.title} ${d.summary} ${d.why}`.toLowerCase().includes(q)) &&
      (!state.fault || d.corrects.some(c => c.faultId === state.fault)) &&
      (!state.kit || (state.kit === "none" ? d.equipment.length === 0 : d.equipment.includes(state.kit))));
    count.textContent = `${shown.length} of ${drills.length} drills`;
    clear(grid);
    if (!shown.length) grid.append(el("p", { class: "muted", text: "Nothing matches. Clear a filter." }));
    shown.forEach(d => grid.append(card(d)));
  };

  const search = el("input", { type: "search", placeholder: "Search drills", "aria-label": "Search drills",
                               oninput: e => { state.q = e.target.value; paint(); } });
  const kit = el("select", { "aria-label": "Equipment", onchange: e => { state.kit = e.target.value; paint(); } }, [
    el("option", { value: "", text: "Any equipment" }),
    el("option", { value: "none", text: "No equipment" }),
    ...kits.map(k => el("option", { value: k, text: k })),
  ]);
  const chips = faults.map(f => el("button", { class: "chip", type: "button", text: f.name, "aria-pressed": "false",
    onclick: e => {
      state.fault = state.fault === f.id ? null : f.id;
      chips.forEach((c, i) => c.setAttribute("aria-pressed", String(state.fault === faults[i].id)));
      paint();
    } }));

  root.append(
    el("h1", { class: "page-title", text: "Drills" }),
    el("p", { class: "lede", text:
      "Fifteen drills written for this project and mapped by hand to the ten faults. After an analysis the " +
      "list is ranked for you; here you can browse all of it." }),
    el("div", { class: "row" }, [el("div", { class: "grow" }, [search]), el("div", { class: "field wide" }, [kit])]),
    el("div", { class: "chips" }, chips), count, grid);
  paint();
}

function card(d) {
  const main = d.corrects.filter(c => c.strength === "primary").map(c => c.faultName);
  return el("a", { class: "drill", href: `#/drills/${d.id}` }, [
    el("h3", { text: d.title }),
    el("p", { text: d.summary }),
    main.length ? el("div", { class: "why-this", text: "Mainly for: " + main.join(", ") }) : null,
    el("div", { class: "chips" }, [
      ...(d.equipment.length ? d.equipment.map(e => el("span", { class: "tag", text: e })) : [el("span", { class: "tag", text: "no equipment" })]),
      d.demo ? el("span", { class: "tag", text: "3D demo" }) : null,
    ]),
  ]);
}

function detail(root, d) {
  const fixes = d.corrects.map(c => el("li", {}, [c.faultName, el("span", { class: "faint", text: c.strength === "primary" ? " — main target" : " — secondary" })]));
  append(root, [
    el("p", { class: "crumbs" }, [el("a", { href: "#/drills", text: "← All drills" })]),
    el("h1", { class: "page-title", text: d.title }),
    el("p", { class: "lede", text: d.summary }),
    d.caution ? el("div", { class: "callout", role: "note" }, [el("b", { text: "Careful. " }), d.caution]) : null,
    d.contraindicatedFor.length ? el("div", { class: "callout", role: "note" }, [
      el("b", { text: "Skip this one if your analysis shows: " }),
      d.contraindicatedFor.map(c => c.faultName).join(", "),
      ". It trains the opposite pattern and would make that worse."]) : null,
  ]);
  if (d.demo) {
    viewer = createViewer(d.demo);
    root.append(el("h2", { class: "section-title", text: "See it" }), viewer.node);
  }
  root.append(
    el("h2", { class: "section-title", text: "How to do it" }),
    el("ol", {}, d.howTo.map(s => el("li", { text: s }))),
    el("h2", { class: "section-title", text: "Why it helps" }),
    el("p", { text: d.why }),
    el("div", { class: "grid2" }, [
      el("div", { class: "card" }, [el("h3", { text: "Easier" }), el("p", { class: "muted", text: d.easier })]),
      el("div", { class: "card" }, [el("h3", { text: "Harder" }), el("p", { class: "muted", text: d.harder })]),
    ]),
    el("p", {}, [el("b", { text: "A starting set: " }), d.sets]),
    el("p", {}, [el("b", { text: "Kit: " }), d.equipment.length ? d.equipment.join(", ") + " (all optional)" : "none"]),
    el("h2", { class: "section-title", text: "What it fixes" }),
    el("ul", {}, fixes),
    el("p", { class: "callout draft small" }, ["Written for this project and not reviewed by a qualified coach. Treat it as a starting point."]),
  );
}
