#!/usr/bin/env python3
"""ClassPrep Autopilot — Day 1 skeleton.

One page: session input form + outputs checklist, Run button, stage
run-log panel, results panel. Day 1 wires the Planner and Curator stages
to the Meta Model API; Builders arrive Thu, Verifier/Review/Platform
Agents Sat (see README for the build plan).
"""
import json
import os

from flask import Flask, jsonify, render_template, request

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import builders
import meta_api

app = Flask(__name__)

PLANNER_SYSTEM = (
    "You are the Planner stage of ClassPrep Autopilot, a teacher-prep "
    "pipeline. Given one class session, return a tight prep plan as JSON "
    "with keys: objectives (list), session_arc (list of segments with "
    "minutes), key_concepts (list), likely_student_questions (list), "
    "materials_needed (list). No prose outside the JSON."
)

CURATOR_SYSTEM = (
    "You are the Curator stage of ClassPrep Autopilot. Propose current, "
    "real supporting items for the session (news, explainers, primary "
    "sources, data). Every item MUST have a real source: return JSON list, "
    "each item {title, type, why_it_fits, source_name, source_url}. "
    "Only include items you are confident exist. No prose outside the JSON."
)


def run_stage(name, fn, log):
    try:
        result = fn()
        log.append({"stage": name, "status": "ok"})
        return result
    except Exception as e:  # a stage failure must never 500 the run
        log.append({"stage": name, "status": "error", "detail": str(e)})
        return None


@app.route("/")
def index():
    return render_template("index.html", api_ready=meta_api.api_ready(),
                           model=meta_api.get_model())


@app.route("/api/run", methods=["POST"])
def run():
    data = request.get_json(force=True)
    session = {
        "course": data.get("course", ""),
        "date": data.get("date", ""),
        "topic": data.get("topic", ""),
        "assigned": data.get("assigned", ""),
        "outcomes": data.get("outcomes", ""),
        "context": data.get("context", ""),
        "outputs": data.get("outputs", []),
    }
    log = []
    session_json = json.dumps(session, indent=2)

    plan = run_stage("Planner", lambda: meta_api.chat(
        PLANNER_SYSTEM,
        f"Plan this session:\n{session_json}", max_output_tokens=4000), log)
    items = None
    if plan:
        items = run_stage("Curator", lambda: meta_api.chat(
            CURATOR_SYSTEM,
            f"Session plan:\n{plan}\n\nSession input:\n{session_json}",
            max_output_tokens=4000), log)

    deck = None
    if plan and items and "deck" in session["outputs"]:
        deck = run_stage("Deck Builder", lambda: builders.build_deck(
            session, plan, items), log)
    card = None
    if plan and items and "reference_card" in session["outputs"]:
        card = run_stage("Reference Card Builder",
                         lambda: builders.build_card(session, plan, items),
                         log)
    podcast = None
    if plan and items and "prep_podcast" in session["outputs"]:
        podcast = run_stage("Podcast Builder",
                            lambda: builders.build_podcast(session, plan,
                                                           items), log)
    nlm_pack = None
    if plan and items and "notebooklm_pack" in session["outputs"]:
        nlm_pack = run_stage("NotebookLM Pack",
                             lambda: builders.build_notebooklm_pack(
                                 session, plan, items), log)

    return jsonify({
        "log": log,
        "plan": plan,
        "curator_items": items,
        "deck": deck,
        "reference_card": card,
        "prep_podcast": podcast,
        "notebooklm_pack": nlm_pack,
        "note": "Planner + Curator + all three Builders (deck, card, "
                "podcast) + NotebookLM Pack live. Verifier, Review gate "
                "and Platform Agents Sat.",
    })


@app.route("/outputs/<path:filename>")
def download(filename):
    from flask import send_from_directory
    return send_from_directory(builders.OUTPUT_DIR, filename,
                               as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=False)
