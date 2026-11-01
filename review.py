#!/usr/bin/env python3
"""ClassPrep Autopilot — Instructor Review gate.

The review step is a hard pipeline stage, not a courtesy screen: a
bundle starts as a DRAFT, its Platform Agent exports are locked, and
one Approve Bundle action unlocks them. Reviewing happens once, on the
master bundle, so a fix propagates to every export.

This module is the gate logic only (no Flask, no API calls) so it can
be unit-tested directly and reused by the app.
"""
import time
import uuid


class ExportLockedError(PermissionError):
    """Raised when an export is attempted before Approve Bundle."""


def new_bundle(session, plan=None, curator_items=None, outputs=None,
               verifier_report=None, question_bank=None):
    return {
        "bundle_id": uuid.uuid4().hex[:12],
        "session": session,
        "plan": plan,
        "curator_items": curator_items,
        "outputs": outputs or {},
        "verifier_report": verifier_report,
        "question_bank": question_bank,
        "status": "draft",
        "approved": False,
        "approved_at": None,
        "watermark": "DRAFT — awaiting instructor review",
        "exports_locked": True,
        "created_at": time.time(),
    }


def approve_bundle(bundle):
    """The single Approve Bundle action. Idempotent in effect: approving
    an already-approved bundle keeps its original approval time."""
    if not bundle.get("approved"):
        bundle["approved"] = True
        bundle["status"] = "approved"
        bundle["approved_at"] = time.time()
        bundle["watermark"] = None
        bundle["exports_locked"] = False
    return bundle


def assert_exports_unlocked(bundle):
    if not bundle or not bundle.get("approved"):
        raise ExportLockedError(
            "Exports are locked until the instructor approves the bundle "
            "(Approve Bundle). Review the master bundle once, then export.")
    return True
