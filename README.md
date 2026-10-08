# swimform

Film yourself swimming freestyle, from the side and from the front. swimform tells
you what your stroke is doing wrong, shows you the frames where it happens, and
suggests drills that fix it. Then you can ask it questions.

It runs on your own computer, against your own AI API key (Gemini recommended). There is no
account, no server of ours, and nothing that keeps your video. It is a tool you
run, not a service you join.

> **Read [docs/RESPONSIBLE_USE.md](docs/RESPONSIBLE_USE.md) before you film anyone.**
> Your video is sent to Google for analysis, adults only, and the results are
> not coaching or medical advice. The app asks you to accept a short notice
> before anything is sent.

```bash
python3 -m swimform serve --open     # then follow the steps below
```

---

## What it does

- **Scores ten freestyle faults against an elite reference.** A vision model
  watches your clip and scores how far you sit from a stated reference on each
  fault, as a continuous 0–1 deviation, never pass or fail.
- **Two camera angles.** Half of the faults can only be judged from the front.
  Give it a side clip and a front clip and each fault is judged from the camera
  that suits it; a clip filed in the wrong slot is flagged.
- **Shows where it happened.** Every finding links to the moments in your own
  footage: tap a time and the video jumps there, with a still cut from each
  moment.
- **Measurements are computed, not guessed.** The model locates landmarks; the
  angles are arithmetic on those points (elbow, body line, head height) and are
  drawn on an annotated frame.
- **Prescribes drills.** Fifteen drills, mapped by hand to the faults, ranked by
  arithmetic you can audit. Drills that would make a fault worse are withheld.
  Two have a 3D demonstration.
- **Answers questions.** Ask about a symptom ("my legs sink when I breathe").
  The answer is built from the same faults and drills, so any drill it names is
  real.
- **Tracks progress.** Scores (not images) are saved in your browser so you can
  see trends.

## Set up (macOS)

You need **Python 3.9+**, **ffmpeg**, and an **AI API key** (built for Gemini, which we recommend).

```bash
brew install ffmpeg
git clone https://github.com/flokachow/swym_web.git swimform
cd swimform
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m swimform serve --open
```

The app opens at <http://127.0.0.1:8787>. Then:

1. Read and accept the notice.
2. Open **Settings** and paste your API key (below), then **Save and check**.
3. Go to **Analyse**, add a side clip and a front clip (or one of them), and press **Analyse**.

Linux: `sudo apt install ffmpeg`. Windows: `winget install Gyan.FFmpeg`. These are
supported on a best-effort basis; the project is developed on macOS.

### Your API key

swimform is built for Google's Gemini API, which is the one we recommend: it takes
video directly and a key is freely available to anyone. (Keys from other AI providers
will not work without changing the code.) Get one free at
<https://aistudio.google.com/apikey> and paste it in **Settings**. It
is kept in your browser tab, or in browser storage if you tick *Remember it*, and
sent only to the swimform server on your own machine and on to Google. It is
never written to disk by swimform.

Two things to know:

- **A free key is fine for trying it on yourself, but** Google may use what you
  send on the free tier and says not to submit personal information there. If you
  film anyone else, or you are in the EEA, UK or Switzerland, use a key with
  billing enabled. Details and sources: [docs/RESPONSIBLE_USE.md](docs/RESPONSIBLE_USE.md).
- **The key is yours and so is the bill.** Keep it private; never commit it.

For the command line you can instead put it in the environment:

```bash
export GEMINI_API_KEY=your-key-here
```

or in `~/.config/swimform/.env` as `GEMINI_API_KEY=your-key-here`.

## Filming a clip that works

This matters more than any setting. Most disappointing results are footage
problems, not analysis problems.

- **Side view:** from the pool edge, level with the water, whole body in frame and
  close enough that an elbow is readable. Someone walking the edge, keeping pace.
- **Front view:** from the end of the lane as the swimmer comes towards you, head
  to feet in frame. This is the view that judges crossover entry, scissor kick and
  rotation.
- **10–20 seconds** each. Longer is slower, costs more and is not more accurate.
  Use the start and end boxes to trim instead of uploading a whole session.
- Steady beats high resolution; clips are scaled down to 1280 px wide anyway.
- Adults who have agreed, only. Never children.

## Using the app

| Page | What it does |
|---|---|
| **Analyse** | Two clip slots, trim, analyse, then the merged verdict with video and stills |
| **Drills** | Browse the fifteen drills by fault or kit; open one for how-to, easier/harder variants, and a 3D demo where there is one |
| **Progress** | Score history and trends, kept in your browser |
| **Ask** | Questions about technique, answered against your latest analysis |
| **Settings** | Your key, the model order, frame rate, thresholds, and deleting stored data |

## The command line

Everything except the multi-angle view also works without the browser:

```bash
python3 -m swimform analyze swim.mp4 --start 10 --end 25
python3 -m swimform analyze swim.mp4 --out report.md
python3 -m swimform ask "my legs sink as soon as I breathe"
python3 -m swimform ask "what about my hips?" --context result.json
python3 -m swimform faults
python3 -m swimform drills --fault low_body_position
python3 -m swimform config --set fps=3
```

`pip install -e .` also installs a `swimform` command.

## How it works

**Scoring, not judging.** Asked to judge whether something "is a fault", a model
compares against its own internal baseline, which turns out to be a competent club
swimmer, and reports nothing wrong with a swimmer a coach can fault in four
places. So each fault has an explicit elite reference in
[`swimform/data/faults.json`](swimform/data/faults.json), the model scores the
distance from it, and swimform applies the threshold.

**Two angles.** Each clip is analysed separately, then merged
(`swimform/merge.py`): a fault is taken from the clip whose camera angle matches
the fault's plane, otherwise from the more confident clip, and is reported as
"not judgeable" only if neither could see it.

**Measurements are computed.** The model returns landmark coordinates;
`swimform/measure.py` computes the angles. Landmarks the model flags as obscured
lower a measurement's confidence rather than hiding it. A measurement is shown
only beside the fault it bears on, from a camera that can see it.

**Drills come from arithmetic, not a model.** Each drill is mapped by hand to the
faults it corrects (primary or secondary). Ranking weights `deviation ×
confidence`, honours contraindications (a drill that trains the opposite pattern is
withheld, not just ranked low), and spreads results across your faults.

**Questions are grounded.** Your question is mapped onto fault ids (an enum, so the
model cannot name a problem the library has no answer for); the same recommender
picks the drills; the model writes prose from that list only.

## Configuration

Settings page, or `python3 -m swimform config`. Stored in
`~/.config/swimform/config.json` (set `SWIMFORM_HOME` to move it).

| key | default | |
|---|---|---|
| `models` | four Gemini models | tried in order; the first that answers wins |
| `fps` | `2.0` | frames per second the model samples |
| `overlays` | `3` | annotated frames to render (each costs a request) |
| `evidencePerFault` | `4` | stills per finding (free, no model call) |
| `reportThreshold` | `0.2` | below this a deviation is "clean" |
| `temperature` | `0.2` | |
| `retentionHours` | `24` | stored images are deleted after this |

**The model is not hardcoded.** Which model is best changes faster than this code
does, so `models` is a list you edit; **Settings → Check key** lists what your key can
use. A model that no longer exists is skipped, not fatal.

`fps` defaults to 2 for a real reason: a freestyle stroke cycle takes about 1.2
seconds, so sampling at 1 fps aliases the stroke phases and the model never sees the
catch.

## Known limitations

An honest list, not a disclaimer.

- **None of the ten faults has been validated against real footage.** Every one is
  `status: candidate`. `dropped_elbow_catch` is the likeliest casualty, since the
  catch happens underwater.
- **The reference bands in `measure.py` are estimates, not sourced.** The elbow
  band in particular will flag a correct high-elbow recovery as "pronounced". They
  need setting by someone who actually coaches the stroke.
- **Measurements are phase-blind.** Body-line angle sampled during a breath measures
  rotation, not sustained hip position.
- **Calibration still runs soft.** The model has been seen scoring a swimmer an
  expert faults in four places at 0.05–0.15 across the board. Treat a low score as
  weaker evidence than a high one, and scores as noisy: the same footage can move by
  about 0.1 between runs.
- **The drills are drafts.** They were written for this project and have not been
  reviewed by a qualified coach. Only two have a 3D demonstration, and the movement
  in it is hand-authored.
- **Thin coverage.** "Head too high" and "over-rotation" are each addressed by only
  one or two drills, all of them secondary.
- **Not tested with real footage in this repository.** The test suite runs the whole
  pipeline against a local stand-in for Gemini, so the real model's behaviour on real
  swims is exactly what is not covered.

## Privacy, and what leaves your machine

- **Your clip is sent to the AI service behind your key** (Google's Gemini API in this version). That is where the
  analysis happens; there is no way around it in this design.
- **Nothing else leaves.** No analytics, no telemetry, no account.
- The shortened copy of your clip is deleted when the analysis ends. Stills and
  annotated frames stay in `~/.config/swimform/overlays` for 24 hours (configurable)
  and can be deleted from Settings.
- The server binds to `127.0.0.1` and refuses requests that name another host or come
  from another website. `--host 0.0.0.0` exposes it to your whole network with no
  authentication; it warns you. Don't do it on a network you don't trust.

Full details, sources and a note on data-protection law:
[docs/RESPONSIBLE_USE.md](docs/RESPONSIBLE_USE.md).

## Troubleshooting

| Problem | Fix |
|---|---|
| "ffmpeg not found" | `brew install ffmpeg`, then restart `swimform serve` |
| "port 8787 is already in use" | an earlier swimform is running; use `--port 8788`, or `lsof -nP -iTCP:8787 -sTCP:LISTEN` |
| "The AI service rejected the key" | re-copy it whole from aistudio.google.com/apikey; check the Gemini API is enabled for it |
| "Could not verify Google's certificate" | with a python.org install on macOS, run the "Install Certificates.command" that ships with Python, or use the system Python |
| Every model is "unavailable" | the free tier saturates at peak times; wait a few minutes, or change the model list in Settings |
| The video won't play but stills work | the browser can't decode that codec (iPhone HEVC `.mov` outside Safari/Chrome); the stills still apply |

## Development

```bash
python3 -m unittest discover -s tests          # no network, no key
```

The tests start the real server and run the dual-angle flow against
`tests/support/fake_gemini_server.py`, a local stand-in for the Gemini API used for
testing only (the clips are test patterns generated by ffmpeg). The environment
variable `SWIMFORM_GEMINI_BASE` points the client at it; it is deliberately not a
setting, so a web page cannot redirect your key.

The 3D viewer is built from `drill3d/` and the output is committed, so running
swimform needs no Node. To change it:

```bash
cd drill3d && npm ci && npm run build
```

## Layout

```
swimform/
  analyze.py      one clip -> scored deviations, stills, annotated frames, drills
  merge.py        two angles -> one verdict per fault
  measure.py      geometry and overlay rendering from keypoints
  coach.py        grounded Q&A: triage to faults, then answer from real drills
  recommend.py    deterministic drill ranking
  taxonomy.py     faults + drills, the join between the two halves
  gemini.py       stdlib API client with model fallback
  server.py       local HTTP API and static files
  security.py     host / origin / key-shape checks
  wording.py      the words used for a score
  storage.py      stored images and their retention
  config.py       settings (never the key)
  cli.py          command line
  data/           faults.json, drills.json
  web/            the web app (plain modules, no build step)
    viewer/       the built 3D viewer
drill3d/          source of the 3D viewer
docs/             RESPONSIBLE_USE.md
tests/            unit and end-to-end tests
```

Fault ids are the only contract between the vision side and the coaching side.
Change the taxonomy and both halves follow.

## Licence

MIT, see [LICENSE](LICENSE); bundled and external components are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Not affiliated with or endorsed by
Google.

**Not medical or coaching advice.** It is software that looks at a video. If
something hurts, see a physio, not a language model.
