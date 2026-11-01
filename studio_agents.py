#!/usr/bin/env python3
"""ClassPrep Autopilot — Studio Agents (guided handoff).

NotebookLM and Google Flow have no public consumer API this app can
call, so Studio Agents work as an honest guided handoff (see
classprep-studio-integrations-oct28.md): the app prepares the packs
and recipes, the instructor runs the studio step, and whatever comes
back re-enters here.

Two jobs live in this module:

1. **Studio return-import** — an artifact the instructor downloaded
   from a studio (NotebookLM deck PDF, audio overview, quiz export, a
   Flow clip, ...) is dropped back into a bundle's Review tray. It is
   labeled "Studio handoff" everywhere, it is checked by the Verifier
   (file/format checks plus a grounding check against the session's
   own sources), and it sits behind the same Approve Bundle gate as
   every native output. Nothing bypasses review because a studio made
   it.

2. **Flow Agent prompt packs** — from the bundle's deck: a storyboard
   (which slides animate, which get a cutaway, a one-line visual brief
   per shot), an assets/ingredients list with consistent prompts,
   animation cards in the instructor's pattern (slide as start AND
   end frame, "Animate this image," ~8-second seamless loop; cutaway
   prompts of 10-15 seconds from the narration), and an assembly
   checklist. Pilot-first: only ONE pilot slide's cards are generated
   until the instructor approves the pilot; then the rest batch.

This module never touches the Review gate itself: imports are stored
on the bundle dict, exports still go through review.assert_exports_
unlocked in app.py, unchanged.
"""
import io
import json
import os
import re
import time
import uuid
import zlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
IMPORTS_DIR = os.path.join(OUTPUT_DIR, "imports")

HANDOFF_LABEL = "Studio handoff"

# kind -> (human label, allowed extensions)
IMPORT_KINDS = {
    "notebooklm_deck": ("NotebookLM slide deck", {".pdf", ".pptx", ".md", ".txt"}),
    "audio_overview": ("NotebookLM audio overview", {".mp3", ".wav", ".m4a"}),
    "quiz_export": ("Studio quiz export", {".json", ".csv", ".xlsx"}),
    "flashcards": ("Studio flashcards", {".json", ".csv", ".xlsx", ".md", ".txt"}),
    "mind_map": ("NotebookLM mind map", {".png", ".pdf", ".md"}),
    "report": ("Studio report / briefing doc", {".pdf", ".md", ".txt", ".docx"}),
    "flow_clip": ("Google Flow clip", {".mp4", ".mov"}),
    "other": ("Other studio artifact", set()),
}

_TEXT_EXTS = {".md", ".txt", ".json", ".csv", ".html", ".htm"}

_STOPWORDS = {
    "about", "above", "after", "again", "against", "before", "below",
    "between", "could", "their", "there", "these", "those", "through",
    "under", "until", "using", "which", "while", "would", "should",
    "students", "student", "session", "class", "slide", "slides",
    "visual", "source", "sources", "question", "questions",
}


def _check(name, ok, detail, item=None):
    """Same check shape as bundle_verifier so the UI renders both the
    same way."""
    return {"name": name, "item": item,
            "status": "pass" if ok else "flag", "detail": detail}


def _safe_name(filename):
    name = os.path.basename(filename or "artifact")
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    return name or "artifact"


# ---------------------------------------------------------------------
# Text extraction (best effort, stdlib + python-pptx only)
# ---------------------------------------------------------------------

def _pdf_text(data):
    """Pull text out of simple PDFs: decompress FlateDecode streams and
    collect the string operands of Tj/TJ operators. Best effort — a
    PDF whose text cannot be extracted returns "" and the verifier
    says so honestly instead of pretending it read the file."""
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        chunk = m.group(1)
        try:
            chunk = zlib.decompress(chunk)
        except zlib.error:
            pass
        for s in re.findall(rb"\((?:[^()\\]|\\.)*\)", chunk):
            try:
                txt = s[1:-1].decode("utf-8", "ignore")
                txt = txt.replace("\\(", "(").replace("\\)", ")")
                if txt.strip():
                    out.append(txt)
            except Exception:
                continue
    return " ".join(out)


def extract_text(filename, data):
    """Return (text, method). method is None when no text could be
    extracted (e.g. an audio file)."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in _TEXT_EXTS:
        try:
            return data.decode("utf-8", "ignore"), "plain text"
        except Exception:
            return "", None
    if ext == ".pptx":
        try:
            from pptx import Presentation
            prs = Presentation(io.BytesIO(data))
            parts = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if shape.has_text_frame and shape.text_frame.text:
                        parts.append(shape.text_frame.text)
                if slide.has_notes_slide:
                    parts.append(slide.notes_slide.notes_text_frame.text)
            return "\n".join(parts), "pptx text"
        except Exception:
            return "", None
    if ext == ".pdf":
        text = _pdf_text(data)
        return (text, "pdf text") if len(text) >= 40 else ("", None)
    return "", None


def _magic_ok(ext, data):
    """Cheap signature check so a renamed file cannot pose as another
    format. Returns True/False, or None when there is no signature to
    check."""
    if ext == ".pdf":
        return data[:4] == b"%PDF"
    if ext in (".pptx", ".xlsx", ".docx"):
        return data[:2] == b"PK"
    if ext == ".mp3":
        return data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3",
                                                  b"\xff\xf2")
    if ext == ".wav":
        return data[:4] == b"RIFF"
    if ext in (".mp4", ".m4a", ".mov"):
        return len(data) > 8 and data[4:8] == b"ftyp"
    if ext == ".png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if ext == ".json":
        try:
            json.loads(data.decode("utf-8", "ignore"))
            return True
        except Exception:
            return False
    return None


# ---------------------------------------------------------------------
# Grounding check — is this artifact actually about THIS session?
# ---------------------------------------------------------------------

def _tokens(text):
    words = re.findall(r"[a-z][a-z0-9\-]{3,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def session_corpus(bundle):
    """The session's own words: the instructor's input, the curated
    items, the plan's concepts, and the question bank. An imported
    artifact is checked against this — and nothing else — so a deck
    from a different session flags instead of sailing through."""
    session = bundle.get("session") or {}
    parts = [session.get("topic") or "", session.get("assigned") or "",
             session.get("outcomes") or "", session.get("course") or "",
             session.get("context") or ""]
    items = bundle.get("curator_items")
    if isinstance(items, str):
        import builders
        items = builders._items_list(items)
    for it in items or []:
        if isinstance(it, dict):
            parts += [it.get("title") or "", it.get("why_it_fits") or "",
                      it.get("source_name") or ""]
    plan = bundle.get("plan")
    if isinstance(plan, str):
        import builders
        plan = builders._as_json(plan)
    if isinstance(plan, dict):
        for key in ("key_concepts", "objectives",
                    "likely_student_questions"):
            val = plan.get(key) or []
            parts += [str(v) for v in val] if isinstance(val, list) \
                else [str(val)]
    bank = bundle.get("question_bank") or {}
    for q in bank.get("questions") or []:
        parts += [q.get("stem") or "", q.get("rationale") or "",
                  q.get("source") or ""]
    return _tokens(" \n".join(parts))


def verify_import(bundle, meta, data):
    """Verifier checks for one imported studio artifact. Same report
    shape as bundle_verifier.verify_bundle: checks + summary +
    overall. Flags are reported, never silently fixed."""
    checks = []
    kind = meta.get("kind") or "other"
    label, allowed_exts = IMPORT_KINDS.get(kind, IMPORT_KINDS["other"])
    filename = meta.get("filename") or ""
    ext = os.path.splitext(filename)[1].lower()

    saved_ok = bool(meta.get("file")) and len(data) > 0
    checks.append(_check(
        "studio_import_file_saved", saved_ok,
        f"{filename} ({len(data)} bytes) stored in the bundle's "
        "review tray" if saved_ok else "no file was stored"))

    if allowed_exts:
        magic = _magic_ok(ext, data)
        fmt_ok = ext in allowed_exts and magic is not False
        detail = (f"{ext or 'no extension'} matches the declared kind "
                  f"({label})" if fmt_ok else
                  f"{ext or 'no extension'} does not match the declared "
                  f"kind ({label}); expected one of "
                  f"{', '.join(sorted(allowed_exts))}")
        if magic is True:
            detail += "; file signature verified"
        checks.append(_check("studio_import_format_matches_kind",
                             fmt_ok, detail))
    else:
        checks.append(_check(
            "studio_import_format_matches_kind", True,
            "kind 'other' carries no format expectation; checked "
            "structurally only"))

    text, method = extract_text(filename, data)
    if text and len(text) >= 200:
        checks.append(_check(
            "studio_import_text_extracted", True,
            f"{len(text)} characters extracted via {method} for the "
            "grounding check"))
    elif text:
        checks.append(_check(
            "studio_import_text_extracted", False,
            f"only {len(text)} characters extracted via {method} — "
            "too little to ground against the session sources"))
    else:
        checks.append(_check(
            "studio_import_text_extracted", False,
            "no readable text in this artifact (audio/video/image or "
            "unreadable PDF) — verified structurally only; the "
            "instructor reviews the content directly in the tray"))

    if text and len(text) >= 200:
        corpus = session_corpus(bundle)
        art_tokens = _tokens(text)
        overlap = (len(art_tokens & corpus) / len(art_tokens)
                   if art_tokens else 0.0)
        topic_words = _tokens((bundle.get("session") or {})
                              .get("topic") or "")
        topic_hits = len(art_tokens & topic_words)
        grounded = overlap >= 0.15 or topic_hits >= 2
        checks.append(_check(
            "studio_import_grounded_in_session_sources", grounded,
            f"{overlap:.0%} of the artifact's content words appear in "
            f"this session's sources; topic terms hit: {topic_hits}"
            + ("" if grounded else
               " — low overlap: confirm this artifact belongs to this "
               "session before approving")))
        meta["grounding_overlap"] = round(overlap, 3)
    else:
        checks.append(_check(
            "studio_import_grounded_in_session_sources", False,
            "grounding check skipped — no extractable text (see the "
            "text check above)"))

    passed = sum(1 for c in checks if c["status"] == "pass")
    return {"checks": checks,
            "summary": {"total": len(checks), "pass": passed,
                        "flag": len(checks) - passed},
            "overall": "pass" if passed == len(checks) else "flag"}


def import_artifact(bundle, filename, data, kind="other"):
    """Store one studio artifact on the bundle and run the Verifier on
    it. Returns the review-tray item. The item starts 'in_review' and
    the bundle's gate state is untouched: exports stay exactly as
    locked or unlocked as they already were."""
    if kind not in IMPORT_KINDS:
        kind = "other"
    safe = _safe_name(filename)
    bundle_dir = os.path.join(IMPORTS_DIR, bundle["bundle_id"])
    os.makedirs(bundle_dir, exist_ok=True)
    path = os.path.join(bundle_dir, safe)
    with open(path, "wb") as f:
        f.write(data)
    label, _ = IMPORT_KINDS[kind]
    item = {
        "id": uuid.uuid4().hex[:10],
        "origin": HANDOFF_LABEL,
        "kind": kind,
        "kind_label": label,
        "filename": safe,
        "file": f"imports/{bundle['bundle_id']}/{safe}",
        "bytes": len(data),
        "imported_at": time.time(),
        "status": "in_review",
    }
    item["verifier"] = verify_import(bundle, item, data)
    bundle.setdefault("studio_imports", []).append(item)
    return item


# ---------------------------------------------------------------------
# Flow Agent — storyboard, assets, animation cards, assembly
# ---------------------------------------------------------------------

STYLE_ANCHOR = ("dark cinematic classroom style, deep navy background "
                "(#0B0B12), soft blue accent light (#6EA8FF), clean "
                "minimal composition, no text overlays, consistent "
                "across every clip in the session")

DEFAULT_CHOICES = {"scope": "key_slides", "clip_seconds": 8,
                   "cutaway_seconds": 12, "aspect": "16:9",
                   "cutaways": True}

SCOPES = ("dividers_only", "key_slides", "all_slides")


def read_deck_slides(deck_path):
    """Slides of a ClassPrep deck as the Flow Agent sees them: kicker,
    title, the on-screen visual cue, and the narration from the
    speaker notes."""
    from pptx import Presentation
    prs = Presentation(deck_path)
    slides = []
    for i, slide in enumerate(prs.slides):
        texts = [sh.text_frame.text.strip() for sh in slide.shapes
                 if sh.has_text_frame and sh.text_frame.text.strip()]
        notes = ""
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
        if i == 0:
            role = "title"
            kicker = texts[0] if texts else ""
            title = texts[1] if len(texts) > 1 else "Title slide"
            visual = ""
        else:
            kicker = texts[0] if texts else ""
            role = "sources" if kicker.upper().startswith("SOURCES") \
                else "content"
            # The sources slide renders every source into one text
            # box; its title is simply "Sources".
            title = "Sources" if role == "sources" else (
                texts[1] if len(texts) > 1 else f"Slide {i + 1}")
            visual = ""
            for t in texts[2:]:
                if t.startswith("On screen:"):
                    visual = t[len("On screen:"):].strip()
        slides.append({"index": i, "number": i + 1, "role": role,
                       "kicker": kicker, "title": title,
                       "visual": visual, "narration": notes})
    return slides


def _first_sentence(text, limit=180):
    text = re.sub(r"\s+", " ", (text or "").strip())
    m = re.split(r"(?<=[.!?])\s+", text)
    sentence = m[0] if m else text
    return sentence[:limit].rstrip() + ("…" if len(sentence) > limit
                                        else "")


def build_storyboard(slides, choices):
    """Shot list for the whole deck. Director's rules: the title slide
    and every content slide get an animated loop; the sources slide
    stays static (it is a reference, not a shot); up to two content
    slides with substantial narration also get a cutaway scene, when
    cutaways are on."""
    board = []
    cutaways_left = 2 if choices.get("cutaways") else 0
    for s in slides:
        entry = {"slide": s["number"], "role": s["role"],
                 "title": s["title"], "treatment": "static",
                 "brief": "", "cutaway_brief": None}
        if s["role"] == "sources":
            entry["brief"] = ("Reference slide — stays static; "
                              "students read it, nothing moves.")
        elif s["role"] == "title":
            entry["treatment"] = "animated_loop"
            entry["brief"] = ("Cinematic opener: the session title "
                              "holds while light moves subtly behind "
                              "it — a living title card.")
        else:
            entry["treatment"] = "animated_loop"
            visual = s["visual"] or _first_sentence(s["narration"])
            entry["brief"] = (f"Animate the slide's visual — {visual}"
                              if visual else
                              "Animate the slide's visual with slow, "
                              "subtle motion.")
            if cutaways_left and len(s["narration"]) >= 450:
                entry["cutaway_brief"] = (
                    "Cutaway scene from the narration: "
                    + _first_sentence(s["narration"]))
                cutaways_left -= 1
        board.append(entry)
    return board


def slides_in_scope(board, scope):
    """Which storyboard entries get animation cards under a scope."""
    if scope == "all_slides":
        return [e for e in board if e["treatment"] == "animated_loop"]
    if scope == "dividers_only":
        return [e for e in board if e["role"] in ("title", "divider")]
    # key_slides: the title, the first content slide, and any slide
    # carrying a cutaway.
    out = []
    for e in board:
        if e["role"] == "title" or e["cutaway_brief"]:
            out.append(e)
        elif e["role"] == "content" and not any(
                x["role"] == "content" for x in out):
            out.append(e)
    return out


def pilot_entry(board):
    """The pilot is the first content slide: representative motion,
    real narration, small enough to judge the whole pack by."""
    for e in board:
        if e["role"] == "content":
            return e
    return board[0] if board else None


def animation_card(entry, slide, choices):
    clip = int(choices.get("clip_seconds") or 8)
    aspect = choices.get("aspect") or "16:9"
    visual = slide.get("visual") or entry["brief"]
    card = {
        "slide": entry["slide"], "title": entry["title"],
        "type": "animated_loop",
        "start_frame": "this slide, exported as an image",
        "end_frame": "the same slide image (seamless loop)",
        "prompt": (f"Animate this image: bring the scene to life "
                   f"with slow, subtle motion — {visual} Keep every "
                   f"word of text perfectly still and legible, no new "
                   f"text, and end exactly on the starting frame so "
                   f"the clip loops seamlessly."),
        "duration_seconds": clip, "aspect": aspect,
        "cutaway": None,
    }
    if entry.get("cutaway_brief"):
        cut_secs = int(choices.get("cutaway_seconds") or 12)
        cut_secs = max(10, min(15, cut_secs))
        card["cutaway"] = {
            "type": "cutaway_scene",
            "prompt": (f"{entry['cutaway_brief']} Render as a short "
                       f"cinematic scene, {STYLE_ANCHOR}."),
            "duration_seconds": cut_secs, "aspect": aspect,
            "placement": f"plays over slide {entry['slide']}'s "
                         "narration, then returns to the slide",
        }
    return card


def card_markdown(card):
    lines = [f"## Animation card — Slide {card['slide']}: "
             f"{card['title']}",
             f"- Start frame: {card['start_frame']}",
             f"- End frame: {card['end_frame']}",
             f"- Flow prompt: \"{card['prompt']}\"",
             f"- Duration: ~{card['duration_seconds']} seconds, "
             f"seamless loop · Aspect: {card['aspect']}"]
    if card.get("cutaway"):
        c = card["cutaway"]
        lines += [f"- Cutaway ({c['duration_seconds']}s, "
                  f"{c['aspect']}): \"{c['prompt']}\"",
                  f"  Placement: {c['placement']}"]
    return "\n".join(lines)


def build_assets(slides):
    """Ingredients list: one consistent image prompt per animated
    slide, all sharing the style anchor so clips match."""
    assets = [{"name": "Style anchor (applies to every asset)",
               "prompt": STYLE_ANCHOR}]
    for s in slides:
        if s["role"] in ("title", "sources"):
            continue
        visual = s["visual"] or s["title"]
        assets.append({
            "name": f"Slide {s['number']} — {s['title']}",
            "prompt": f"{visual} — {STYLE_ANCHOR}"})
    return assets


ASSEMBLY_CHECKLIST = [
    "Export each animated slide from the deck as a PNG image "
    "(slide size, full bleed).",
    "In Google Flow, create one project for the session; add the "
    "style anchor as the first ingredient so every clip matches.",
    "For each animation card: upload the slide image as BOTH the "
    "start and the end frame, paste the card's prompt, set the "
    "card's duration and aspect, generate.",
    "For each cutaway card: generate from the text prompt alone "
    "(no slide frame), at the card's duration.",
    "Download the finished clips and drop them back into ClassPrep "
    "through the Studio handoff import (kind: Flow clip) — they "
    "re-enter the Review tray like everything else.",
    "After approval, place each clip in the deck: animated loops "
    "full-bleed behind the slide's content; cutaways as a "
    "picture-in-picture inset over the slide, or full-bleed for "
    "the length of the narration beat.",
    "Play the deck once start to finish: every loop must return "
    "to the slide frame cleanly, and no clip may cover slide text.",
]


def _slug(bundle):
    topic = re.sub(r"[^a-z0-9]+", "-",
                   ((bundle.get("session") or {}).get("topic")
                    or "session").lower()).strip("-")
    return topic[:40] or "session"


def _write_pack_files(bundle, pack, full):
    slug = _slug(bundle)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    board_md = [f"# Flow storyboard — "
                f"{(bundle.get('session') or {}).get('topic', '')}",
                f"\nScope: {pack['choices']['scope']} · loop "
                f"{pack['choices']['clip_seconds']}s · aspect "
                f"{pack['choices']['aspect']} · cutaways "
                f"{'on' if pack['choices']['cutaways'] else 'off'}\n"]
    for e in pack["storyboard"]:
        board_md.append(f"- **Slide {e['slide']} — {e['title']}** "
                        f"[{e['treatment']}]: {e['brief']}")
        if e["cutaway_brief"]:
            board_md.append(f"  - Cutaway: {e['cutaway_brief']}")
    assets_md = ["# Flow assets / ingredients", ""]
    for a in pack["assets"]:
        assets_md.append(f"- **{a['name']}**: {a['prompt']}")
    cards_md = [f"# Flow animation cards — "
                f"{'full batch' if full else 'PILOT ONLY'}", ""]
    for c in pack["cards"]:
        cards_md.append(card_markdown(c))
        cards_md.append("")
    assembly_md = ["# Flow assembly checklist", ""] + \
        [f"{i + 1}. {step}" for i, step in
         enumerate(ASSEMBLY_CHECKLIST)]
    files = {}
    for suffix, lines in (("flow-storyboard", board_md),
                          ("flow-assets", assets_md),
                          ("flow-cards-full" if full
                           else "flow-cards-pilot", cards_md),
                          ("flow-assembly", assembly_md)):
        name = f"{slug}-{suffix}.md"
        with open(os.path.join(OUTPUT_DIR, name), "w") as f:
            f.write("\n".join(lines) + "\n")
        files[suffix] = name
    return files


def build_flow_pack(bundle, choices=None, full=False):
    """Build a Flow prompt pack for the bundle's deck.

    full=False is the pilot: the storyboard, assets and checklist
    cover the whole deck, but animation cards are generated for the
    pilot slide ONLY. full=True (after pilot approval) generates
    cards for every slide in the chosen scope.
    """
    deck = (bundle.get("outputs") or {}).get("deck") or {}
    if not deck.get("file"):
        raise ValueError("this bundle has no deck to storyboard; "
                         "re-run with Slide deck selected")
    deck_path = os.path.join(OUTPUT_DIR, deck["file"])
    if not os.path.exists(deck_path):
        raise ValueError(f"deck file missing: {deck['file']}")
    merged = dict(DEFAULT_CHOICES)
    for k, v in (choices or {}).items():
        if k in merged and v is not None:
            merged[k] = v
    if merged["scope"] not in SCOPES:
        merged["scope"] = "key_slides"
    merged["clip_seconds"] = int(merged["clip_seconds"])
    merged["cutaways"] = bool(merged["cutaways"])

    slides = read_deck_slides(deck_path)
    board = build_storyboard(slides, merged)
    by_number = {s["number"]: s for s in slides}
    if full:
        entries = slides_in_scope(board, merged["scope"])
    else:
        pilot = pilot_entry(board)
        entries = [pilot] if pilot else []
    cards = [animation_card(e, by_number[e["slide"]], merged)
             for e in entries]
    pack = {"choices": merged, "storyboard": board,
            "assets": build_assets(slides), "cards": cards,
            "assembly_checklist": ASSEMBLY_CHECKLIST,
            "pilot_slide": (pilot_entry(board) or {}).get("slide"),
            "mode": "full" if full else "pilot",
            "generated_at": time.time()}
    pack["files"] = _write_pack_files(bundle, pack, full)
    return pack
