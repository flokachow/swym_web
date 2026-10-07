// Talking to the local swimform server. Every call carries the custom header
// that proves it came from this page, and the Gemini key when there is one.

import { getKey } from "./store.js";

export class ApiError extends Error {
  constructor(message, status, body = {}) {
    super(message);
    this.status = status;
    this.needsKey = !!body.needsKey;
  }
}

function headers(extra = {}) {
  const h = { "X-Swimform": "1", ...extra };
  const key = getKey();
  if (key) h["X-Gemini-Key"] = key;
  return h;
}

async function parse(res) {
  let body = {};
  try { body = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) throw new ApiError(body.error || res.statusText || "Request failed", res.status, body);
  return body;
}

export const get = path => fetch(path).then(parse);

export const post = (path, obj) =>
  fetch(path, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(obj ?? {}),
  }).then(parse);

// One clip, as raw bytes. `slot` is the angle the user filed it under.
export function analyse(file, slot, startSec, endSec) {
  const h = headers({ "Content-Type": "application/octet-stream", "X-Viewpoint": slot });
  if (startSec != null) h["X-Start-Sec"] = String(startSec);
  if (endSec != null) h["X-End-Sec"] = String(endSec);
  return fetch("/analyze", { method: "POST", headers: h, body: file }).then(parse);
}

export const checkKey = () => post("/key/check", {});
export const combine = angles => post("/combine", { angles });
export const ask = (question, analysis, history) => post("/ask", { question, analysis, history });
export const saveConfig = patch => post("/config", patch);
export const purge = () => post("/purge", {});
