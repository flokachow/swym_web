// DOM helpers. Everything on the page is built with these — never from HTML
// strings — because the Gemini key sits in this origin's web storage and the page must
// stay immune to injected markup. Text goes in as text.

export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k === "value") node.value = v;
    else if (k === "checked" || k === "disabled" || k === "hidden") node[k] = !!v;
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  append(node, children);
  return node;
}

export function append(node, children) {
  for (const c of [].concat(children)) {
    if (c == null || c === false) continue;
    if (Array.isArray(c)) append(node, c);
    else node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

export const clear = node => { node.replaceChildren(); return node; };

export const mmss = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;

export const percent = v => `${Math.round(v * 100)}%`;

export function bytes(n) {
  return n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

// A short-lived message at the bottom of the screen.
export function toast(text) {
  const t = el("div", { class: "toast", role: "status", text });
  document.body.append(t);
  setTimeout(() => t.remove(), 3200);
}

// Model output is shown as text. Bold and `code` are the only markup honoured,
// and they are built as elements, not parsed as HTML.
export function richText(text) {
  const wrap = el("div", { class: "msg" });
  String(text).split(/\n{2,}/).forEach(para => {
    const p = el("p");
    para.split(/(\*\*[^*]+\*\*|`[^`]+`)/).forEach(chunk => {
      if (/^\*\*.+\*\*$/.test(chunk)) p.append(el("b", { text: chunk.slice(2, -2) }));
      else if (/^`.+`$/.test(chunk)) p.append(el("code", { text: chunk.slice(1, -1) }));
      else if (chunk) p.append(chunk);
    });
    wrap.append(p);
  });
  return wrap;
}

export function svg(tag, attrs = {}, children = []) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
  append(n, children);
  return n;
}
