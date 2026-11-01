#!/usr/bin/env python3
"""ClassPrep Autopilot — Day 1 skeleton.

One page: session input form + outputs checklist, Run button, stage
run-log panel, results panel. Pipeline: Planner + Curator, Builders,
Verifier (Kevin's verifier.py wired in, plus bundle-level checks),
Instructor Review gate (one Approve Bundle unlocks exports), and the
Canvas + Kahoot Platform Agents behind that gate.
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
import bundle_verifier
import meta_api
import platform_agents
import review as review_gate
import studio_agents

BUNDLES = {}

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

    bank = None
    if plan and items and "question_bank" in session["outputs"]:
        bank = run_stage("Question Bank Builder",
                         lambda: builders.build_question_bank(
                             session, plan, items), log)

    outputs = {"deck": deck, "reference_card": card,
               "prep_podcast": podcast, "notebooklm_pack": nlm_pack}
    verifier_report = None
    bundle = None
    if plan and items:
        verifier_report = run_stage(
            "Verifier", lambda: bundle_verifier.verify_bundle(
                builders._items_list(items), outputs, bank), log)
        bundle = review_gate.new_bundle(
            session, plan=plan, curator_items=items, outputs=outputs,
            verifier_report=verifier_report, question_bank=bank)
        BUNDLES[bundle["bundle_id"]] = bundle

    return jsonify({
        "log": log,
        "plan": plan,
        "curator_items": items,
        "deck": deck,
        "reference_card": card,
        "prep_podcast": podcast,
        "notebooklm_pack": nlm_pack,
        "question_bank": bank,
        "verifier": verifier_report,
        "bundle_id": bundle["bundle_id"] if bundle else None,
        "review": {"status": bundle["status"],
                   "exports_locked": bundle["exports_locked"],
                   "watermark": bundle["watermark"]} if bundle else None,
        "note": "Full pipeline live: Planner + Curator + Builders + "
                "Question Bank, then the Verifier. Exports stay locked "
                "until you review the bundle and choose Approve Bundle.",
    })


@app.route("/api/bundles/<bundle_id>")
def get_bundle(bundle_id):
    bundle = BUNDLES.get(bundle_id)
    if not bundle:
        return jsonify({"error": "bundle not found"}), 404
    return jsonify({
        "bundle_id": bundle["bundle_id"], "status": bundle["status"],
        "approved": bundle["approved"],
        "exports_locked": bundle["exports_locked"],
        "watermark": bundle["watermark"],
        "verifier": bundle["verifier_report"],
        "question_bank": bundle["question_bank"],
        "outputs": bundle["outputs"],
        "studio_imports": bundle.get("studio_imports", []),
        "flow_pack": ({"choices": bundle["flow_pack"]["choices"],
                       "mode": bundle["flow_pack"]["mode"],
                       "pilot_slide":
                           bundle["flow_pack"]["pilot_slide"],
                       "pilot_approved":
                           bundle.get("flow_pilot_approved", False),
                       "files": bundle["flow_pack"]["files"]}
                      if bundle.get("flow_pack") else None),
    })


@app.route("/api/bundles/<bundle_id>/approve", methods=["POST"])
def approve(bundle_id):
    bundle = BUNDLES.get(bundle_id)
    if not bundle:
        return jsonify({"error": "bundle not found"}), 404
    review_gate.approve_bundle(bundle)
    return jsonify({"bundle_id": bundle_id, "status": bundle["status"],
                    "approved": True, "exports_locked": False,
                    "note": "Bundle approved. Canvas and Kahoot exports "
                            "are now unlocked."})


@app.route("/api/bundles/<bundle_id>/studio-import", methods=["POST"])
def studio_import(bundle_id):
    """Studio return-import: a downloaded Studio artifact (NotebookLM
    deck PDF, audio overview, quiz export, Flow clip...) is dropped
    back into the bundle's Review tray. Labeled 'Studio handoff',
    checked by the Verifier, and behind the same Approve Bundle gate
    as native outputs — importing never unlocks anything."""
    bundle = BUNDLES.get(bundle_id)
    if not bundle:
        return jsonify({"error": "bundle not found"}), 404
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify({"error": "no file uploaded (form field "
                                 "'file')"}), 400
    kind = request.form.get("kind", "other")
    item = studio_agents.import_artifact(
        bundle, upload.filename, upload.read(), kind)
    return jsonify({
        "import": item,
        "download": f"/outputs/{item['file']}",
        "review": {"status": bundle["status"],
                   "exports_locked": bundle["exports_locked"]},
        "note": "Studio handoff — imported into the Review tray and "
                "checked by the Verifier. It ships only with the "
                "bundle, after Approve Bundle, like any native output.",
    })


@app.route("/api/bundles/<bundle_id>/flow-pack", methods=["POST"])
def flow_pack(bundle_id):
    """Flow Agent, pilot first: storyboard + assets + assembly
    checklist for the whole deck, animation cards for ONE pilot
    slide. Batching waits for pilot approval (see flow_pack_batch)."""
    bundle = BUNDLES.get(bundle_id)
    if not bundle:
        return jsonify({"error": "bundle not found"}), 404
    choices = request.get_json(silent=True) or {}
    try:
        pack = studio_agents.build_flow_pack(bundle, choices,
                                             full=False)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    bundle["flow_pack"] = pack
    bundle["flow_pilot_approved"] = False
    return jsonify({"flow_pack": pack,
                    "downloads": {k: f"/outputs/{v}" for k, v in
                                  pack["files"].items()},
                    "note": "Pilot first: cards for one pilot slide "
                            "only. Approve the pilot to batch the "
                            "rest of the deck."})


@app.route("/api/bundles/<bundle_id>/flow-pack/approve-pilot",
           methods=["POST"])
def flow_pack_approve_pilot(bundle_id):
    bundle = BUNDLES.get(bundle_id)
    if not bundle:
        return jsonify({"error": "bundle not found"}), 404
    if not bundle.get("flow_pack"):
        return jsonify({"error": "no Flow pilot pack yet; generate "
                                 "one first"}), 400
    bundle["flow_pilot_approved"] = True
    return jsonify({"bundle_id": bundle_id, "pilot_approved": True,
                    "pilot_slide": bundle["flow_pack"]["pilot_slide"],
                    "note": "Pilot approved. The Flow Agent can now "
                            "batch cards for the rest of the deck."})


@app.route("/api/bundles/<bundle_id>/flow-pack/batch", methods=["POST"])
def flow_pack_batch(bundle_id):
    """Batch the Flow animation cards for every slide in scope. 403
    until the instructor approves the pilot slide's cards."""
    bundle = BUNDLES.get(bundle_id)
    if not bundle:
        return jsonify({"error": "bundle not found"}), 404
    if not bundle.get("flow_pack"):
        return jsonify({"error": "no Flow pilot pack yet; generate "
                                 "one first"}), 400
    if not bundle.get("flow_pilot_approved"):
        return jsonify({
            "error": "Pilot first: approve the pilot slide's cards "
                     "before batching the rest of the deck.",
            "pilot_approved": False}), 403
    choices = dict(bundle["flow_pack"]["choices"])
    choices.update({k: v for k, v in
                    (request.get_json(silent=True) or {}).items()
                    if v is not None})
    try:
        pack = studio_agents.build_flow_pack(bundle, choices,
                                             full=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    bundle["flow_pack"] = pack
    return jsonify({"flow_pack": pack,
                    "downloads": {k: f"/outputs/{v}" for k, v in
                                  pack["files"].items()},
                    "note": "Full batch generated for every slide "
                            "in scope."})


@app.route("/api/bundles/<bundle_id>/export/<platform>", methods=["POST", "GET"])
def export(bundle_id, platform):
    bundle = BUNDLES.get(bundle_id)
    if not bundle:
        return jsonify({"error": "bundle not found"}), 404
    try:
        review_gate.assert_exports_unlocked(bundle)
    except review_gate.ExportLockedError as e:
        return jsonify({"error": str(e), "exports_locked": True}), 403
    if not bundle.get("question_bank"):
        return jsonify({"error": "this bundle has no question bank; "
                                 "re-run with Question bank selected"}), 400
    if platform == "canvas":
        report = platform_agents.export_canvas(
            bundle["question_bank"], bundle["session"])
    elif platform == "kahoot":
        report = platform_agents.export_kahoot(
            bundle["question_bank"], bundle["session"])
    else:
        return jsonify({"error": f"unknown platform: {platform}"}), 404
    return jsonify({"export": report,
                    "download": f"/outputs/{report['file']}"})


@app.route("/outputs/<path:filename>")
def download(filename):
    from flask import send_from_directory
    return send_from_directory(builders.OUTPUT_DIR, filename,
                               as_attachment=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port,
            debug=False)
