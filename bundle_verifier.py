#!/usr/bin/env python3
"""ClassPrep Autopilot — bundle-level verification.

Wraps Kevin's verifier.py (curator URL checks, written in Muse
Code) and adds the checks the Verifier stage owes on the whole bundle:
builder output files exist and are non-empty, the deck carries
narration in its speaker notes, the podcast is a usable length, and the
question bank passes the quiz-specific rules in platform_agents.

Every check reports pass or flag with a plain reason. Flags are
reported, never silently fixed.
"""
import os

import platform_agents
import verifier

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")


def _check(name, ok, detail, item=None):
    return {"name": name, "item": item,
            "status": "pass" if ok else "flag", "detail": detail}


def _file_check(name, file_info):
    if not file_info or not file_info.get("file"):
        return _check(name, False, "builder produced no file")
    path = os.path.join(OUTPUT_DIR, file_info["file"])
    ok = os.path.exists(path) and os.path.getsize(path) > 0
    return _check(name, ok,
                  f"{file_info['file']} ({os.path.getsize(path) if ok else 0} "
                  "bytes)" if ok else f"{file_info['file']} missing or empty")


def verify_bundle(curator_items, outputs, question_bank=None):
    """outputs: the bundle's builder outputs dict (deck / reference_card
    / prep_podcast / notebooklm_pack entries as returned by builders)."""
    checks = []

    # 1. Curator source checks — Kevin's verifier.py, wired in.
    items = curator_items or []
    if isinstance(items, str):
        import builders as _b
        items = _b._items_list(items)
    report = verifier.verify_items(items)
    for r in report["items"]:
        checks.append(_check(
            "curator_source_url", r["status"] == "pass",
            (f"{r['source_name']}: HTTP {r['status_code']}"
             if r["status"] == "pass" else
             f"{r['source_name']}: {r['error']} ({r['source_url']})"),
            item=r["title"]))
    checks.append(_check(
        "curator_items_present", len(items) > 0,
        f"{len(items)} curated items, each with a source to check"))

    # 2. Builder output files.
    if outputs:
        if "deck" in outputs or outputs.get("deck"):
            checks.append(_file_check("deck_file", outputs.get("deck")))
            deck = outputs.get("deck") or {}
            if deck.get("file"):
                try:
                    from pptx import Presentation
                    prs = Presentation(os.path.join(OUTPUT_DIR,
                                                    deck["file"]))
                    narrated = 0
                    for slide in prs.slides:
                        if slide.has_notes_slide:
                            text = (slide.notes_slide.notes_text_frame
                                    .text or "").strip()
                            if len(text) > 40:
                                narrated += 1
                    checks.append(_check(
                        "deck_narration_in_speaker_notes", narrated >= 3,
                        f"{narrated} of {len(prs.slides)} slides carry "
                        "narration in speaker notes"))
                except Exception as e:
                    checks.append(_check(
                        "deck_narration_in_speaker_notes", False, str(e)))
        if outputs.get("reference_card"):
            checks.append(_file_check("reference_card_file",
                                      outputs.get("reference_card")))
        if outputs.get("prep_podcast"):
            checks.append(_file_check("podcast_file",
                                      outputs.get("prep_podcast")))
            words = (outputs.get("prep_podcast") or {}).get("words") or 0
            checks.append(_check(
                "podcast_usable_length", 400 <= words <= 1200,
                f"{words} words (~{round(words / 150.0, 1)} min at "
                "speaking pace)"))
        if outputs.get("notebooklm_pack"):
            checks.append(_file_check("notebooklm_pack_file",
                                      outputs.get("notebooklm_pack")))

    # 3. Question bank rules (only when a bank was requested / built).
    if question_bank is not None:
        for c in platform_agents.validate_question_bank(question_bank):
            checks.append(_check(c["name"], c["status"] == "pass",
                                 c["detail"], item=c.get("question_id")))

    passed = sum(1 for c in checks if c["status"] == "pass")
    return {
        "checks": checks,
        "summary": {"total": len(checks), "pass": passed,
                    "flag": len(checks) - passed},
        "curator_url_report": report,
        "overall": "pass" if passed == len(checks) and checks else "flag",
    }
