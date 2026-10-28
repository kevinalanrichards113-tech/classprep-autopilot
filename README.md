# ClassPrep Autopilot

**Give every teacher back their Sunday night.**

A multi-agent pipeline that turns one course session into a verified
prep bundle — slide deck, one-page reference card, prep podcast, and a
question bank exported natively to Canvas and Kahoot — with a
verification agent and an instructor review step before anything ships.

Built Oct 28 – Nov 4, 2026 for the Meta Global AI Developer Hackathon
(solo, Indie Developer track, "Build for Your World"). **All code in this
repo is new work from the hackathon window.**

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
- Thu Oct 29: NotebookLM Source Pack; push + deploy prep.
- Sat Oct 31: Verifier, Review gate, Platform Agents, Studio return-import.
- Mon Nov 2: live run prepping a real class; deploy to a public URL.
- Tue Nov 3: freeze, demo video, write-up.
- Wed Nov 4: submit (deadline 9:00 PM ET).
