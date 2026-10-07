# Responsible use

Consent notice version: 2026-10-07.1
Last checked against Google's published terms: 2026-10-07

swimform analyses video of a person. That raises questions about privacy,
consent, cost and what the results can be trusted for. This page is what you
should know before using it, and what you agree to when you accept the notice in
the app.

> This is a good-faith summary written by the authors of a student project. It
> is **not legal advice**. Rules differ by country, by institution and by pool.
> If you are unsure, ask your institution's data-protection officer or ethics
> board before you film anyone.

## 1. What happens to your video

- You choose a clip. swimform trims and shrinks it **on your computer** with ffmpeg.
- The shortened clip is sent to **Google's Gemini API**, using the API key you
  provide, to be analysed. This is the only place video leaves your machine.
- The copy swimform made is deleted from your computer as soon as the analysis
  ends.
- Still images cut from the clip (the evidence stills and annotated frames) are
  kept in swimform's folder so the results page can show them, then deleted
  after the retention time in Settings (24 hours by default). You can delete
  them at any time from Settings, or by deleting `~/.config/swimform/overlays`.
- There is no swimform server, no account, no analytics and no telemetry.
- Your progress history (scores only, no images) and your key live in your
  browser's storage, and nowhere else. Settings can remove them.

## 2. Google's terms and your key

swimform has no key of its own. Every analysis is made under **your** Gemini API
key, so Google's terms apply to you:
<https://ai.google.dev/gemini-api/terms>.

Points from those terms that matter here (read the original, they can change):

- **Free (unpaid) usage.** Google may use what you submit, and what comes back,
  to improve its products, and human reviewers may read it. The terms say: "Do
  not submit sensitive, confidential, or personal information to the Unpaid
  Services." A video of a person is personal information.
- **Paid usage.** When a Cloud Billing account is activated, Google says it does
  not use prompts or responses to improve its products and processes them under
  its data-processing terms.
- **Europe.** The terms say you may use only Paid Services when making API
  clients available to users in the EEA, Switzerland or the UK.
- **Age.** The terms say not to use the services in applications likely to be
  accessed by people under 18. swimform is for adults.

What follows in practice:

- To try swimform on yourself, a free key is fine as long as you accept the
  free-tier terms for your own video.
- If you film **anyone else**, or you are in Europe, use a key with billing
  enabled.
- You are responsible for your key, for what it costs, and for following
  Google's terms. Keep it private: never paste it into a screenshot, an issue or
  a repository. swimform sends it only to the swimform server on your own
  computer (in a request header) and from there to Google, and never writes it to
  disk. It is kept in your browser tab, or in browser storage if you tick
  "Remember it".

## 3. Filming people

- **Adults who have clearly agreed, only.** Tell them what the clip is for, where
  it goes (to Google, see above), how long it is kept, and that they can ask you
  to delete it.
- **Never film children**, or anyone who has not agreed. Swimwear footage of a
  child sent to a third-party service is a different decision from footage of
  yourself. Google scans uploads automatically, a false positive lands on *your*
  Google account, and you may not get a chance to explain the context first. If
  you coach juniors, review their technique on the deck with your own eyes.
- **Pools have rules.** Many ban filming altogether, and filming in or near
  changing areas is never acceptable. Ask the operator first.
- **Data-protection law.** Video of an identifiable person is personal data
  (under the GDPR and similar laws). Analysing only your own swimming for your
  own purposes is usually a personal matter. Analysing other people's footage can
  make you a *controller* of their data: you need a lawful basis (normally
  explicit consent), you must tell them what happens to the video, and you must
  be able to delete it on request.
- **Research and teaching.** If swimform is used in a course or study, the
  institution's rules on human participants apply, and an ethics review may be
  needed. Do not use swimform's output to make decisions about people (selection,
  grading, discipline). It is not validated for that.

## 4. What the results are, and are not

- The scores are an AI model's estimates of how far a stroke sits from a stated
  elite reference. None of the ten faults has been validated against real
  footage, and the measurement bands in `swimform/measure.py` are unsourced
  estimates. See "Known limitations" in the README.
- The drills were written for this project. They have not been reviewed by a
  qualified coach, and each is marked as a draft in the app.
- **It is not coaching, medical or physiotherapy advice.** If something hurts,
  stop and see a professional. The question box refers pain and injury questions
  to one, but it cannot examine you.

## 5. Your machine

| What | Where | How long | How to remove |
|---|---|---|---|
| Uploaded clip (shortened copy) | `~/.config/swimform/uploads` | until the analysis ends | automatic |
| Evidence stills, annotated frames | `~/.config/swimform/overlays` | 24 h (Settings) | Settings, "Delete stored images now" |
| Settings (models, fps…) | `~/.config/swimform/config.json` | until you delete it | delete the file |
| Gemini key | browser tab, or browser storage if you tick "Remember" | tab / until removed | Settings, "Remove key" |
| Score history | browser storage | until deleted | Progress or Settings |
| Notice accepted | browser storage | until deleted | Settings, "Forget everything" |

Set `SWIMFORM_HOME` to keep this folder elsewhere.

## 6. No warranty

swimform is provided as is, under the MIT licence (see `LICENSE`), without
warranty of any kind. It is not affiliated with or endorsed by Google. The
authors are not responsible for how it is used.

## Sources

- Gemini API Additional Terms of Service: <https://ai.google.dev/gemini-api/terms>
- Get a Gemini API key: <https://aistudio.google.com/apikey>
