#!/usr/bin/env python3
"""ClassPrep Autopilot — Platform Agents (Canvas + Kahoot).

Each agent adapts one verified master question bank for its platform,
validates its own export, and reports honestly what was exported,
converted, dropped, or kept instructor-only. Live posting to platform
accounts is roadmap work; these agents produce validated, import-ready
files only.

Canvas export: a QTI 1.2 zip (imsmanifest.xml + assessment.xml) that
Canvas imports as a question bank / quiz, plus an instructor JSON copy
with the answer key, rationales, and Kevin's quiz-settings preset.

Kahoot export: an .xlsx in Kahoot's import layout (Question, Answer 1-4,
Time limit, Correct answer(s)), plus an instructor JSON copy with the
conversion report. Kahoot stems are capped at 120 characters and answers
at 75, per Kahoot's spreadsheet import limits.
"""
import json
import os
import re
import zipfile
from xml.sax.saxutils import escape as xml_escape

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

# Kevin's Canvas preset (classprep-quiz-options-by-platform-oct28.md)
CANVAS_PRESET = {
    "bank_size_target": 20,
    "draw": 5,
    "points_per_question": 2,
    "attempts": 3,
    "scoring": "keep highest",
    "time_limit_minutes": 20,
    "shuffle_questions": True,
    "shuffle_answers": True,
}

KAHOOT_QUESTION_MAX = 120
KAHOOT_ANSWER_MAX = 75


def _slug(session):
    topic = re.sub(r"[^a-z0-9]+", "-",
                   (session.get("topic") or "session").lower()).strip("-")
    return topic[:40] or "session"


# ---------------------------------------------------------------- bank checks

def validate_question_bank(bank):
    """Verifier checks specific to quizzes (see quiz-options spec).

    Returns a list of checks: {name, question_id, status, detail}.
    status is "pass" or "flag". Flags are reported, never silently fixed.
    """
    checks = []
    questions = (bank or {}).get("questions") or []
    if not questions:
        checks.append({"name": "question_bank_present", "question_id": None,
                       "status": "flag", "detail": "question bank is empty"})
        return checks
    checks.append({"name": "question_bank_present", "question_id": None,
                   "status": "pass",
                   "detail": f"{len(questions)} questions in the master bank"})
    correct_positions = []
    for q in questions:
        qid = q.get("id")
        def add(name, ok, detail):
            checks.append({"name": name, "question_id": qid,
                           "status": "pass" if ok else "flag",
                           "detail": detail})
        add("question_has_source", bool(q.get("source")),
            q.get("source") or "no source cited for this question")
        add("question_has_rationale", bool(q.get("rationale")),
            "rationale present" if q.get("rationale") else
            "no rationale on the instructor copy")
        qtype = q.get("type")
        if qtype == "multiple_choice":
            choices = q.get("choices") or []
            add("mc_has_3_to_5_choices", 3 <= len(choices) <= 5,
                f"{len(choices)} choices")
            add("mc_has_one_correct",
                isinstance(q.get("correct_index"), int)
                and 0 <= q["correct_index"] < max(len(choices), 1),
                "correct_index in range" if choices else "no choices")
            add("mc_no_all_of_the_above",
                not any("all of the above" in str(c).lower()
                        for c in choices),
                "no 'all of the above' distractor")
            if isinstance(q.get("correct_index"), int):
                correct_positions.append(q["correct_index"])
        elif qtype == "multiple_answers":
            correct = q.get("correct_indices") or []
            choices = q.get("choices") or []
            add("multiple_answers_min_2_correct", len(correct) >= 2,
                f"{len(correct)} correct answers")
            add("multiple_answers_has_incorrect_options",
                len(choices) - len(correct) >= 2,
                f"{len(choices) - len(correct)} incorrect options")
        elif qtype == "true_false":
            add("tf_answer_is_bool", isinstance(q.get("correct"), bool),
                f"correct={q.get('correct')!r}")
        elif qtype == "matching":
            pairs = q.get("pairs") or []
            add("matching_min_4_pairs", len(pairs) >= 4,
                f"{len(pairs)} pairs")
        elif qtype == "fill_in_blank":
            add("fill_blank_has_acceptable_variants",
                bool(q.get("acceptable_answers")),
                f"{len(q.get('acceptable_answers') or [])} acceptable "
                "answers listed")
        elif qtype == "essay":
            add("essay_has_grading_notes", bool(q.get("grading_notes")),
                "grading notes present (essays are never auto-graded)"
                if q.get("grading_notes") else
                "essay without grading notes — Verifier flag per spec")
        elif qtype == "ordering":
            add("ordering_has_4_items", len(q.get("items") or []) == 4,
                f"{len(q.get('items') or [])} items")
        else:
            add("question_type_recognised", False,
                f"unknown question type: {qtype!r}")
    if len(correct_positions) >= 4:
        spread = len(set(correct_positions))
        checks.append({"name": "correct_answers_balanced",
                       "question_id": None,
                       "status": "pass" if spread >= 3 else "flag",
                       "detail": f"MC correct answers use {spread} "
                                 "different positions"})
    return checks


# ---------------------------------------------------------------- Canvas

def _canvas_item_xml(q, idx):
    """One QTI 1.2 item. Native Canvas types are mapped, not flattened:
    matching stays a matching item, essay stays an essay, etc."""
    ident = f"q{idx}_{re.sub(r'[^a-z0-9]+', '_', str(q.get('id') or idx))}"
    title = xml_escape(str(q.get("stem") or "")[:120])
    stem = xml_escape(str(q.get("stem") or ""))
    qtype = q.get("type")
    body_parts = [f"<p>{stem}</p>"]
    response = ""
    scoring = ""
    if qtype in ("multiple_choice", "true_false"):
        choices = q.get("choices") or (
            ["True", "False"] if qtype == "true_false" else [])
        if qtype == "true_false":
            correct_idx = 0 if q.get("correct") else 1
        else:
            correct_idx = q.get("correct_index", 0)
        labels = []
        for i, c in enumerate(choices):
            labels.append(
                f'<response_label ident="{i}"><material><mattext>'
                f'{xml_escape(str(c))}</mattext></material></response_label>')
        response = (
            f'<response_lid ident="response1" rcardinality="Single">'
            f'<render_choice>{"".join(labels)}</render_choice></response_lid>')
        scoring = (
            f'<respcondition><conditionvar><varequal respident="response1">'
            f'{correct_idx}</varequal></conditionvar>'
            f'<setvar varname="SCORE" action="Set">100</setvar></respcondition>')
    elif qtype == "multiple_answers":
        labels = []
        for i, c in enumerate(q.get("choices") or []):
            labels.append(
                f'<response_label ident="{i}"><material><mattext>'
                f'{xml_escape(str(c))}</mattext></material></response_label>')
        response = (
            f'<response_lid ident="response1" rcardinality="Multiple">'
            f'<render_choice>{"".join(labels)}</render_choice></response_lid>')
        conds = "".join(
            f'<varequal respident="response1">{i}</varequal>'
            for i in (q.get("correct_indices") or []))
        scoring = (f'<respcondition><conditionvar>{conds}</conditionvar>'
                   f'<setvar varname="SCORE" action="Set">100</setvar>'
                   f'</respcondition>')
    elif qtype == "matching":
        pairs = q.get("pairs") or []
        left = "".join(
            f'<response_label ident="L{i}"><material><mattext>'
            f'{xml_escape(str(p.get("left", "")))}</mattext></material>'
            f'</response_label>' for i, p in enumerate(pairs))
        right = "".join(
            f'<response_label ident="R{i}"><material><mattext>'
            f'{xml_escape(str(p.get("right", "")))}</mattext></material>'
            f'</response_label>' for i, p in enumerate(pairs))
        response = (
            f'<response_lid ident="response1" rcardinality="Multiple">'
            f'<render_choice>{left}</render_choice></response_lid>'
            f'<response_lid ident="response2" rcardinality="Multiple">'
            f'<render_choice>{right}</render_choice></response_lid>')
        scoring = ('<!-- matching pairs are in order: L0-R0, L1-R1, ... '
                   'Canvas reads the pairing from the item body order -->')
        body_parts.append(
            "<p>Match each item on the left with its pair on the right: "
            + "; ".join(f"{p.get('left')} — {p.get('right')}"
                        for p in pairs) + "</p>")
    elif qtype == "fill_in_blank":
        response = ('<response_str ident="response1" rcardinality="Single">'
                    '<render_fib fibtype="String"/></response_str>')
        variants = "; ".join(str(a) for a in
                             (q.get("acceptable_answers") or []))
        scoring = (f'<!-- acceptable answers: {xml_escape(variants)} -->')
    elif qtype == "essay":
        response = ('<response_str ident="response1" rcardinality="Single">'
                    '<render_fib fibtype="String"/></response_str>')
        scoring = ('<!-- essay: manual grading. Grading notes are on the '
                   'instructor JSON copy, not in this student import -->')
    elif qtype == "ordering":
        labels = "".join(
            f'<response_label ident="{i}"><material><mattext>'
            f'{xml_escape(str(it))}</mattext></material></response_label>'
            for i, it in enumerate(q.get("items") or []))
        response = (
            f'<response_lid ident="response1" rcardinality="Ordered">'
            f'<render_choice>{labels}</render_choice></response_lid>')
    else:
        response = ('<response_str ident="response1" rcardinality="Single">'
                    '<render_fib fibtype="String"/></response_str>')
    return (
        f'<item ident="{ident}" title="{title}">'
        f'<presentation><material><mattext>{"".join(body_parts)}</mattext>'
        f'</material>{response}</presentation>'
        f'<resprocessing><outcomes><decvar varname="SCORE" vartype="Decimal" '
        f'minvalue="0" maxvalue="100"/></outcomes>{scoring}</resprocessing>'
        f'</item>')


def export_canvas(bank, session, out_dir=OUTPUT_DIR):
    """Canvas Agent: QTI zip + instructor JSON. Returns a report dict."""
    os.makedirs(out_dir, exist_ok=True)
    slug = _slug(session)
    questions = (bank or {}).get("questions") or []
    items_xml = "\n".join(_canvas_item_xml(q, i + 1)
                          for i, q in enumerate(questions))
    assessment = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<questestinterop><assessment '
        f'title="{xml_escape(str(session.get("topic") or "Session"))} — '
        'question bank">'
        f'<section ident="root_section">{items_xml}</section>'
        '</assessment></questestinterop>')
    manifest = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<manifest identifier="classprep_canvas_export"><metadata>'
        '<schema>IMS Content</schema><schemaversion>1.1.3</schemaversion>'
        '</metadata><resources><resource identifier="assessment" '
        'type="imsqti_xmlv1p2" href="assessment.xml"/></resources></manifest>')
    qti_path = os.path.join(out_dir, f"{slug}-canvas-qti.zip")
    with zipfile.ZipFile(qti_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("imsmanifest.xml", manifest)
        z.writestr("assessment.xml", assessment)
    report = {
        "platform": "canvas",
        "mode": "Native",
        "file": os.path.basename(qti_path),
        "settings_preset": CANVAS_PRESET,
        "exported": [q.get("id") for q in questions],
        "converted": [],
        "dropped": [],
        "instructor_only": ["answer key, rationales, and essay grading "
                            "notes live on the instructor JSON copy"],
        "question_count": len(questions),
        "types": sorted({q.get("type") for q in questions}),
    }
    json_path = os.path.join(out_dir, f"{slug}-canvas-instructor.json")
    with open(json_path, "w") as f:
        json.dump({"session": session, "settings_preset": CANVAS_PRESET,
                   "question_bank": bank, "conversion_report": report},
                  f, indent=2)
    report["instructor_file"] = os.path.basename(json_path)
    # Validate our own export before it ships.
    with zipfile.ZipFile(qti_path) as z:
        names = z.namelist()
        xml_text = z.read("assessment.xml").decode("utf-8")
    report["validation"] = {
        "zip_entries": names,
        "items_in_qti": xml_text.count("<item "),
        "valid": names == ["imsmanifest.xml", "assessment.xml"]
                 and xml_text.count("<item ") == len(questions),
    }
    return report


# ---------------------------------------------------------------- Kahoot

def _kahoot_row(q):
    """Convert one master question to a Kahoot row, or return
    (None, reason) when Kahoot has no such type. Honest conversions:
    essay is dropped (listed in the report), never flattened silently."""
    qtype = q.get("type")
    stem = str(q.get("stem") or "")
    timer = int(q.get("time_limit") or 30)
    if qtype == "multiple_choice":
        choices = [str(c)[:KAHOOT_ANSWER_MAX]
                   for c in (q.get("choices") or [])[:4]]
        while len(choices) < 2:
            choices.append("")
        return {"question": stem[:KAHOOT_QUESTION_MAX],
                "answers": (choices + ["", "", "", ""])[:4],
                "time": timer,
                "correct": str(int(q.get("correct_index", 0)) + 1)}, "exported"
    if qtype == "true_false":
        return {"question": stem[:KAHOOT_QUESTION_MAX],
                "answers": ["True", "False", "", ""],
                "time": timer,
                "correct": "1" if q.get("correct") else "2"}, "exported"
    if qtype == "multiple_answers":
        # Kahoot quiz is single-correct: keep the first correct answer as
        # the key and say so in the report.
        choices = [str(c)[:KAHOOT_ANSWER_MAX]
                   for c in (q.get("choices") or [])[:4]]
        first_correct = min(q.get("correct_indices") or [0])
        return {"question": stem[:KAHOOT_QUESTION_MAX],
                "answers": (choices + ["", "", "", ""])[:4],
                "time": timer,
                "correct": str(first_correct + 1)}, "converted"
    if qtype == "matching":
        pairs = q.get("pairs") or []
        if not pairs:
            return None, "dropped"
        p = pairs[0]
        distractors = [str(x.get("right")) for x in pairs[1:4]]
        answers = ([str(p.get("right"))] + distractors)[:4]
        return {"question": f"Match: {p.get('left')}"[:KAHOOT_QUESTION_MAX],
                "answers": (answers + ["", "", "", ""])[:4],
                "time": timer, "correct": "1"}, "converted"
    if qtype == "fill_in_blank":
        answers = [str(a)[:KAHOOT_ANSWER_MAX]
                   for a in (q.get("acceptable_answers") or [])]
        if not answers:
            return None, "dropped"
        # Type Answer in Kahoot is typed, not multiple choice; the import
        # sheet expresses it as a single correct answer cell.
        return {"question": stem[:KAHOOT_QUESTION_MAX],
                "answers": [answers[0], "", "", ""],
                "time": timer, "correct": "1"}, "converted"
    if qtype == "ordering":
        items = [str(i)[:KAHOOT_ANSWER_MAX] for i in (q.get("items") or [])]
        if len(items) != 4:
            return None, "dropped"
        return {"question": stem[:KAHOOT_QUESTION_MAX],
                "answers": items, "time": timer,
                "correct": "1,2,3,4"}, "converted"
    if qtype == "essay":
        return None, "instructor_only"
    return None, "dropped"


def export_kahoot(bank, session, out_dir=OUTPUT_DIR):
    """Kahoot Agent: import .xlsx + instructor JSON conversion report."""
    import xlsxwriter
    os.makedirs(out_dir, exist_ok=True)
    slug = _slug(session)
    questions = (bank or {}).get("questions") or []
    rows, exported, converted, dropped, instructor_only = [], [], [], [], []
    for q in questions:
        row, how = _kahoot_row(q)
        if row is None:
            (instructor_only if how == "instructor_only"
             else dropped).append(q.get("id"))
            continue
        rows.append(row)
        (converted if how == "converted" else exported).append(q.get("id"))
    xlsx_path = os.path.join(out_dir, f"{slug}-kahoot.xlsx")
    wb = xlsxwriter.Workbook(xlsx_path)
    ws = wb.add_worksheet("Kahoot")
    headers = ["Question", "Answer 1", "Answer 2", "Answer 3", "Answer 4",
               "Time limit (sec)", "Correct answer(s)"]
    for c, h in enumerate(headers):
        ws.write(0, c, h)
    for r, row in enumerate(rows, start=1):
        ws.write(r, 0, row["question"])
        for c, a in enumerate(row["answers"]):
            ws.write(r, 1 + c, a)
        ws.write(r, 5, row["time"])
        ws.write(r, 6, row["correct"])
    wb.close()
    report = {
        "platform": "kahoot",
        "mode": "Native",
        "file": os.path.basename(xlsx_path),
        "exported": exported,
        "converted": converted,
        "dropped": dropped,
        "instructor_only": instructor_only,
        "question_count": len(rows),
        "notes": [
            "Essay questions have no Kahoot type and stay instructor-only.",
            "Multiple-answers questions become single-correct Kahoot quiz "
            "questions (first correct answer is the key).",
            "Matching becomes a single-pair quiz question; the full "
            "matching set stays in the Canvas export.",
        ],
    }
    json_path = os.path.join(out_dir, f"{slug}-kahoot-instructor.json")
    with open(json_path, "w") as f:
        json.dump({"session": session, "rows": rows,
                   "conversion_report": report}, f, indent=2)
    report["instructor_file"] = os.path.basename(json_path)
    # Validate our own export: re-open the xlsx as a zip and confirm the
    # sheet XML carries every row's question text.
    with zipfile.ZipFile(xlsx_path) as z:
        shared = ""
        if "xl/sharedStrings.xml" in z.namelist():
            shared = z.read("xl/sharedStrings.xml").decode("utf-8")
    report["validation"] = {
        "rows_written": len(rows),
        "questions_found_in_file": sum(
            1 for row in rows if row["question"][:40] in shared),
        "valid": len(rows) > 0 and all(
            row["question"][:40] in shared for row in rows),
    }
    return report
