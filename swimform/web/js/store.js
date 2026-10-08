// Everything the browser remembers. All of it is optional and all of it can
// fail (private windows, blocked storage), so every access is guarded and the
// app works without any of it.

export const CONSENT_VERSION = "2026-10-08.1";
const K = {
  keyPrefix: "swimform.key.",       // one key per provider: swimform.key.gemini, ...
  legacyKey: "swimform.geminiKey",  // an earlier build stored the one key here
  provider: "swimform.provider",
  consent: "swimform.consent",
  history: "swimform.history",
  historyOn: "swimform.historyOn",
};
export const PROVIDER_IDS = ["gemini", "openai", "anthropic"];

const safe = (fn, fallback) => { try { return fn(); } catch { return fallback; } };
const local = () => window.localStorage;
const session = () => window.sessionStorage;

// -- which AI service ----------------------------------------------------

export function getProvider() {
  const p = safe(() => local().getItem(K.provider), null);
  return PROVIDER_IDS.includes(p) ? p : "gemini";
}
export function setProvider(p) {
  if (PROVIDER_IDS.includes(p)) safe(() => local().setItem(K.provider, p));
}

// -- API key -------------------------------------------------------------
// Held in this tab only unless the user opts in to remembering it on this
// browser. It is sent to this computer's swimform server per request and on to
// the AI service; it is never written anywhere else. One key per provider, so
// switching provider does not lose the others.

export function getKey(provider = getProvider()) {
  const name = K.keyPrefix + provider;
  return safe(() => session().getItem(name), null) || safe(() => local().getItem(name), null) || "";
}
export function keyIsRemembered(provider = getProvider()) {
  return !!safe(() => local().getItem(K.keyPrefix + provider), null);
}
export function setKey(key, remember, provider = getProvider()) {
  clearKey(provider);
  const store = remember ? local() : session();
  safe(() => store.setItem(K.keyPrefix + provider, key.trim()));
}
export function clearKey(provider = getProvider()) {
  safe(() => session().removeItem(K.keyPrefix + provider));
  safe(() => local().removeItem(K.keyPrefix + provider));
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
  const names = [...Object.values(K).filter(k => k !== K.keyPrefix),
                 ...PROVIDER_IDS.map(p => K.keyPrefix + p)];
  for (const k of names) {
    safe(() => local().removeItem(k));
    safe(() => session().removeItem(k));
  }
}

// Where each provider's key is held, for the privacy panel.
export function describeStored() {
  const keys = {};
  for (const p of PROVIDER_IDS) {
    keys[p] = getKey(p) ? (keyIsRemembered(p) ? "remembered on this browser" : "this tab only") : null;
  }
  return { keys, consent: hasConsent(), history: getHistory().length };
}
