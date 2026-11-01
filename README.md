# ClassPrep Autopilot

**Give every teacher back their Sunday night.**

A multi-agent pipeline that turns one course session into a verified
prep bundle — slide deck, one-page reference card, prep podcast, and a
question bank exported natively to Canvas and Kahoot — with a
verification agent and an instructor review step before anything ships.

Built Oct 28 – Nov 4, 2026 for the Meta Global AI Developer Hackathon
(solo, Indie Developer track, "Build for Your World"). **All code in this
repo is new work from the hackathon window.**

**▶ Live demo: https://classprep-autopilot.onrender.com**
(Free hosting tier — the first load after a quiet stretch can take
about a minute while the instance wakes. Verified end to end on
Nov 1, 2026: full demo run, review gate, Canvas + Kahoot exports.)

## Pipeline

1. **Planner** — reads the session, outcomes, and instructor's chosen outputs
2. **Curator** — finds current supporting material; every item carries a real source
3. **Builders** — deck, reference card, podcast script, question bank (Thu)
4. **Verifier** — checks every item against the sources; flags, never silently fixes (Sat)
5. **Instructor Review** — approve / edit / regenerate / drop; one approval unlocks exports (Sat)
6. **Platform Agents** — Canvas Agent + Kahoot Agent export natively (Sat)
7. **Studio Agents** — NotebookLM source packs + recipes, Google Flow animation packs (guided handoff)

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add MODEL_API_KEY
python3 hello.py       # Day 1 gate: one live call to the Meta Model API
python3 app.py         # http://127.0.0.1:5000
```

API facts (Meta Model API quickstart):
- Console / keys: https://dev.meta.ai — add a payment method under
  **Billing** first (Create API key stays disabled until then), then
  **API keys → Create API key**. Hackathon credits appear in Billing.
- Base URL: `https://api.meta.ai/v1` (OpenAI-compatible, Responses API)
- Key env var: `MODEL_API_KEY`
- Model: **muse-spark-1.3** — verified live on this account Oct 28, 2026
  (hello-world answered "Hello, I am Muse Spark."). Muse Spark is a
  reasoning model: keep max_output_tokens >= 2000 or replies come back
  empty with status "incomplete".
- Never use a `-contributor` model variant (it opts prompts into training).

## Build log

- **Wed Oct 28 (Day 1):** repo + MIT LICENSE, app skeleton (Apple TV-style
  UI), Planner + Curator wired to the Meta Model API. API verified live
  (muse-spark-1.3 and muse-wonder-1.0 both answer on this account).
- **Wed Oct 28 (pulled forward):** Deck Builder live — Muse Spark writes a
  visual-first deck spec (full narration in speaker notes), python-pptx
  renders the .pptx; verified on the Dataveillance demo pack (9 slides).
- **Wed Oct 28 (Muse Code task):** `verifier.py` (URL well-formedness +
  reachability checks for curator items, `verify_items` report) written by
  **Muse Code** (Everyday tier, Muse Wonder) in a logged session and
  pushed by the author; wired into the pipeline Sat with the Verifier
  stage.
- **Wed Oct 28 (pulled forward):** Reference Card Builder (one-page,
  print-ready HTML: key terms, core ideas, comparison, try-it, discussion
  prompt, sources) and Podcast Builder (~5-min instructor prep script,
  markdown) live — all three Builders done a day early.
- **Sun Nov 1 (real run):** full bundle for the real Mon Nov 2 GERMAN
  3250 session (Week 11 Dataveillance live session + council trial) —
  8 stages in ~2 minutes, Verifier 43 pass / 2 flag (two FTC links
  corrected at review), bundle approved by the instructor, Canvas +
  Kahoot exports generated.
- Sun Nov 1 (deployed): live on Render at
  https://classprep-autopilot.onrender.com — verified end to end with
  the demo pack (Verifier 40 pass / 0 flag; exports 403 before
  approval, Canvas + Kahoot after).
- Mon Nov 2: teach with the real bundle.
- **Thu Oct 29 (Sat work pulled forward — preflight):** Verifier wired
  into the pipeline (`bundle_verifier.py`: Kevin's `verifier.py` URL
  checks + bundle-level and quiz-rule checks, reported per check);
  Review gate live (`review.py`: DRAFT bundle, exports locked, one
  Approve Bundle unlocks them — tested blocked-before / open-after
  through the app); Platform Agents live (`platform_agents.py`: Canvas
  QTI zip with native types + instructor copy on Kevin's preset, Kahoot
  import .xlsx with an honest conversion report); minimal Question Bank
  Builder added so exports have a real bank to test (model bank first,
  validated; a reported deterministic fallback). Full live run on the
  Dataveillance demo pack: all stages passed, Verifier 42 pass / 2 flag
  (both source-URL flags — see `PREFLIGHT-AUDIT-2026-10-29.md`).
- **Sat Oct 31:** Studio return-import + Flow Agent prompt packs live
  (`studio_agents.py`). Return-import: a downloaded Studio artifact
  (NotebookLM deck PDF, audio overview, quiz export, Flow clip) drops
  back into the bundle's Review tray labeled **"Studio handoff"** —
  the Verifier checks it (file saved, format matches the declared
  kind, text extraction, and a grounding check against the session's
  own sources) and it sits behind the same Approve Bundle gate as
  native outputs; importing unlocks nothing. Flow Agent: storyboard
  (animated vs. cutaway vs. static, one-line brief per shot),
  assets/ingredients list with a shared style anchor, animation cards
  in Kevin's pattern (slide as start AND end frame, "Animate this
  image," ~8s seamless loop; 10–15s cutaway prompts from the
  narration), and an assembly checklist that returns finished clips
  through the Studio handoff import. Pilot-first: cards generate for
  ONE pilot slide (demo deck: slide 2, "The Smart City Is Now
  Watching You") and batching returns 403 until the pilot is
  approved; instructor choices exposed (dividers only / key slides /
  all slides, loop length, aspect, cutaways on/off). Verified by
  `tests/test_studio_flow.py` (36 checks, all passing): import from
  the demo pack's NotebookLM Source Pack (deck source, Verifier 4/4
  pass, 33% grounding overlap), exports 403 before approval and
  still 403 after import, 200 after Approve Bundle, pilot/batch
  gating as designed. Push to GitHub remains a separate browser step
  (the connected integration cannot write to this repo).
- Mon Nov 2: live run prepping a real class; deploy to a public URL.
- Tue Nov 3: freeze, demo video, write-up.
- Wed Nov 4: submit (deadline 9:00 PM ET).
