// In-memory state shared between views. Nothing here is persisted: the clips
// are File objects the browser holds only while this tab is open.
export default {
  health: null,          // last /health response
  providers: null,       // the AI services on offer, from /providers
  clips: { side: null, front: null },   // { file, url, start, end }
  runs: { side: null, front: null },    // { status: "running"|"done"|"error", result?, error?, startedAt }
  combined: null,        // the merged result currently on screen
  chat: [],              // ask-view history
  models: null,          // usable models from the last key check
};
