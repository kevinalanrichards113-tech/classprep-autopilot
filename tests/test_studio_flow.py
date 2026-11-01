#!/usr/bin/env python3
"""Saturday Oct 31 preflight: Studio return-import + Flow pilot pack.

Builds a bundle in-memory from the Dataveillance demo pack already in
outputs/ (no model calls — bundles are in-memory, so this exercises
the same one-sitting flow: assemble -> import -> verify -> gate ->
approve -> export), then:

1. Export before approval -> 403 (the Oct 29 gate behavior, unchanged).
2. Import one artifact from the demo pack's NotebookLM Source Pack
   (02-deck-source.md out of the pack zip) as a Studio handoff item:
   it must land in the Review tray data with a Verifier result, and
   exporting must STILL be 403 — the import unlocks nothing.
3. Approve Bundle -> Canvas and Kahoot exports return 200.
4. Flow pack: storyboard covers all 9 deck slides; animation cards
   cover the pilot slide ONLY; batch before pilot approval -> 403;
   approve pilot -> batch yields a card for every slide in scope.
5. The served page carries the Studio handoff UI (label + tray +
   Flow controls) so the import's Verifier result renders.

Run: .venv/bin/python tests/test_studio_flow.py
"""
import io
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module          # noqa: E402
import review as review_gate      # noqa: E402

OUT = app_module.builders.OUTPUT_DIR
STEM = "dataveillance-the-watched-data-double"

failures = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} — {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def load_demo_bundle():
    with open(os.path.join(OUT, f"{STEM}-question-bank.json")) as f:
        saved = json.load(f)
    session, bank = saved["session"], saved["question_bank"]
    # Curator items parsed from the NotebookLM Source Pack's sources
    # file — the same items the preflight run curated.
    with zipfile.ZipFile(os.path.join(OUT, f"{STEM}-notebooklm.zip")) as z:
        sources_md = z.read("01-sources.md").decode()
        deck_source = z.read("02-deck-source.md")
    items = []
    for m in re.finditer(
            r"- \*\*(.+?)\*\* \((.+?)\) — (.+?): (https?://\S+)\n"
            r"\s+Why it fits: (.+)", sources_md):
        items.append({"title": m.group(1), "type": m.group(2),
                      "source_name": m.group(3),
                      "source_url": m.group(4),
                      "why_it_fits": m.group(5)})
    assert items, "no curator items parsed from the source pack"
    outputs = {
        "deck": {"file": f"{STEM}-deck.pptx", "slides": 9},
        "reference_card": {"file": f"{STEM}-card.html"},
        "prep_podcast": {"file": f"{STEM}-podcast.md", "words": 800},
        "notebooklm_pack": {"file": f"{STEM}-notebooklm.zip"},
    }
    bundle = review_gate.new_bundle(
        session, plan=None, curator_items=items, outputs=outputs,
        verifier_report=None, question_bank=bank)
    app_module.BUNDLES[bundle["bundle_id"]] = bundle
    return bundle, deck_source


def main():
    client = app_module.app.test_client()
    bundle, deck_source = load_demo_bundle()
    bid = bundle["bundle_id"]
    print(f"Demo bundle {bid}: {bundle['session']['topic']}")

    # 1. Gate: export before approval -> 403.
    r = client.post(f"/api/bundles/{bid}/export/canvas")
    check("export locked before approval", r.status_code == 403,
          f"got {r.status_code}")

    # 2. Studio return-import from the NotebookLM Source Pack.
    r = client.post(
        f"/api/bundles/{bid}/studio-import",
        data={"kind": "notebooklm_deck",
              "file": (io.BytesIO(deck_source), "02-deck-source.md")},
        content_type="multipart/form-data")
    check("studio import accepted", r.status_code == 200,
          f"got {r.status_code}: {r.get_data(as_text=True)[:200]}")
    d = r.get_json() or {}
    item = d.get("import") or {}
    check("import labeled 'Studio handoff'",
          item.get("origin") == "Studio handoff", item.get("origin", ""))
    check("import sits in the review tray (status in_review)",
          item.get("status") == "in_review", item.get("status", ""))
    v = item.get("verifier") or {}
    check("import carries a Verifier result",
          bool(v.get("checks")) and bool(v.get("summary")),
          f"summary={v.get('summary')}")
    by_name = {c["name"]: c for c in v.get("checks", [])}
    check("grounding check passed for the pack's own deck source",
          by_name.get("studio_import_grounded_in_session_sources", {})
          .get("status") == "pass",
          (by_name.get("studio_import_grounded_in_session_sources") or {})
          .get("detail", ""))
    r = client.get(d.get("download", ""))
    check("imported file downloads back", r.status_code == 200
          and len(r.data) == len(deck_source), f"got {r.status_code}")
    r = client.get(f"/api/bundles/{bid}")
    tray = (r.get_json() or {}).get("studio_imports") or []
    check("GET bundle shows the import in the tray", len(tray) == 1
          and tray[0]["id"] == item.get("id"), f"tray size {len(tray)}")

    # Importing must not weaken the gate.
    r = client.post(f"/api/bundles/{bid}/export/kahoot")
    check("export STILL locked after import", r.status_code == 403,
          f"got {r.status_code}")

    # 3. Approve -> exports open (Oct 29 behavior preserved).
    r = client.post(f"/api/bundles/{bid}/approve")
    check("Approve Bundle works", r.status_code == 200
          and (r.get_json() or {}).get("approved") is True)
    for platform in ("canvas", "kahoot"):
        r = client.post(f"/api/bundles/{bid}/export/{platform}")
        check(f"{platform} export unlocked after approval",
              r.status_code == 200, f"got {r.status_code}")

    # 4. Flow pack — pilot first.
    choices = {"scope": "key_slides", "clip_seconds": 8,
               "aspect": "16:9", "cutaways": True}
    r = client.post(f"/api/bundles/{bid}/flow-pack", json=choices)
    check("flow pilot pack generated", r.status_code == 200,
          f"got {r.status_code}: {r.get_data(as_text=True)[:200]}")
    pack = (r.get_json() or {}).get("flow_pack") or {}
    check("storyboard covers all 9 slides",
          len(pack.get("storyboard", [])) == 9,
          f"{len(pack.get('storyboard', []))} entries")
    cards = pack.get("cards", [])
    check("pilot generates ONE slide's cards only", len(cards) == 1,
          f"{len(cards)} cards")
    pilot = pack.get("pilot_slide")
    card = cards[0] if cards else {}
    check("pilot card is the pilot slide", card.get("slide") == pilot,
          f"pilot={pilot}, card slide={card.get('slide')}")
    check("pilot slide is the first content slide (slide 2, the hook)",
          pilot == 2 and "Watching You" in (card.get("title") or ""),
          f"pilot={pilot}, title={card.get('title')}")
    prompt = card.get("prompt") or ""
    check("card uses Kevin's pattern (Animate this image, start=end frame, loop)",
          prompt.startswith("Animate this image")
          and card.get("start_frame") is not None
          and "same slide image" in (card.get("end_frame") or "")
          and "loops seamlessly" in prompt)
    check("card honors choices (8s, 16:9)",
          card.get("duration_seconds") == 8
          and card.get("aspect") == "16:9")
    check("assets list + assembly checklist present",
          len(pack.get("assets", [])) >= 3
          and len(pack.get("assembly_checklist", [])) >= 5)
    check("assembly sends clips back through the Studio handoff",
          any("Studio handoff" in s
              for s in pack.get("assembly_checklist", [])))
    for suffix in ("flow-storyboard", "flow-assets",
                   "flow-cards-pilot", "flow-assembly"):
        path = os.path.join(OUT, (pack.get("files") or {}).get(suffix, ""))
        check(f"pack file written: {suffix}",
              os.path.exists(path) and os.path.getsize(path) > 0, path)

    r = client.post(f"/api/bundles/{bid}/flow-pack/batch", json={})
    check("batch blocked before pilot approval", r.status_code == 403,
          f"got {r.status_code}")
    r = client.post(f"/api/bundles/{bid}/flow-pack/approve-pilot")
    check("pilot approval recorded", r.status_code == 200
          and (r.get_json() or {}).get("pilot_approved") is True)
    r = client.post(f"/api/bundles/{bid}/flow-pack/batch", json={})
    pack2 = (r.get_json() or {}).get("flow_pack") or {}
    expected = len(app_module.studio_agents.slides_in_scope(
        pack2.get("storyboard", []), "key_slides"))
    check("batch cards cover every slide in scope",
          len(pack2.get("cards", [])) == expected and expected > 1,
          f"{len(pack2.get('cards', []))} cards, scope size {expected}")

    # 5. The page itself carries the Studio handoff UI.
    html = client.get("/").get_data(as_text=True)
    for needle in ("Studio handoff", "studio-import-btn", "studio-tray",
                   "flow-scope", "flow-cutaways", "Generate pilot pack",
                   "Verifier"):
        check(f"page renders: {needle}", needle in html)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
