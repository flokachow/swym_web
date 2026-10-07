// Everything the browser remembers. All of it is optional and all of it can
// fail (private windows, blocked storage), so every access is guarded and the
// app works without any of it.

export const CONSENT_VERSION = "2026-10-07.1";
const K = {
  key: "swimform.geminiKey",
  consent: "swimform.consent",
  history: "swimform.history",
  historyOn: "swimform.historyOn",
};

const safe = (fn, fallback) => { try { return fn(); } catch { return fallback; } };
const local = () => window.localStorage;
const session = () => window.sessionStorage;

// -- Gemini key ----------------------------------------------------------
// Held in this tab only unless the user opts in to remembering it on this
// browser. It is sent to this computer's swimform server per request and on
// to Google; it is never written anywhere else.

export function getKey() {
  return safe(() => session().getItem(K.key), null) || safe(() => local().getItem(K.key), null) || "";
}
export function keyIsRemembered() {
  return !!safe(() => local().getItem(K.key), null);
}
export function setKey(key, remember) {
  clearKey();
  const store = remember ? local() : session();
  safe(() => store.setItem(K.key, key.trim()));
}
export function clearKey() {
  safe(() => session().removeItem(K.key));
  safe(() => local().removeItem(K.key));
}

// -- consent -------------------------------------------------------------

export function hasConsent() {
  return safe(() => local().getItem(K.consent), null) === CONSENT_VERSION
      || safe(() => session().getItem(K.consent), null) === CONSENT_VERSION;
}
export function giveConsent() {
  // If local storage is unavailable, fall back to this tab so the app still works.
  try { local().setItem(K.consent, CONSENT_VERSION); }
  catch { safe(() => session().setItem(K.consent, CONSENT_VERSION)); }
}
export function withdrawConsent() {
  safe(() => local().removeItem(K.consent));
  safe(() => session().removeItem(K.consent));
}

// -- progress history ------------------------------------------------------
// Scores only — dates, per-fault deviations, a headline. No images, no video.

export function historyEnabled() {
  return safe(() => local().getItem(K.historyOn), null) !== "0";
}
export function setHistoryEnabled(on) {
  safe(() => local().setItem(K.historyOn, on ? "1" : "0"));
}
export function getHistory() {
  const raw = safe(() => JSON.parse(local().getItem(K.history) || "[]"), []);
  return Array.isArray(raw) ? raw : [];
}
export function addHistory(entry) {
  if (!historyEnabled()) return;
  const all = getHistory();
  all.push(entry);
  safe(() => local().setItem(K.history, JSON.stringify(all.slice(-100))));
}
export function clearHistory() {
  safe(() => local().removeItem(K.history));
}

export function forgetEverything() {
  for (const k of Object.values(K)) {
    safe(() => local().removeItem(k));
    safe(() => session().removeItem(k));
  }
}

export function describeStored() {
  return {
    key: getKey() ? (keyIsRemembered() ? "remembered on this browser" : "this tab only") : "none",
    consent: hasConsent(),
    history: getHistory().length,
  };
}
