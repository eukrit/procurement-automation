"""
rfq_workflow.py — State machine, auto-reply orchestration, escalation rules,
and reminder scheduling for RFQ inquiries.

Vendor status state machine:
  draft → sent → response_received → complete_response → evaluating → awarded
                                                                    → not_selected
         → reminder_1 (Day 5) → reminder_2 (Day 7) → escalated (Day 10) → closed
         → partial_response → (auto-reply) → awaiting_response → response_received
         → question_received → (auto-reply) → awaiting_response → response_received
         → declined → closed
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta

from src.rfq_store import (
    get_db,
    get_inquiry,
    get_inquiry_vendors,
    get_vendor,
    get_template,
    get_workflow_config,
    log_message,
    update_vendor_status,
    update_vendor_rates,
)
from src.gmail_sender import send_auto_reply, send_reminder
from src.parsers.rfq_gemini import (
    classify_vendor_response,
    extract_vendor_rates,
    generate_auto_reply as gemini_auto_reply,
)

logger = logging.getLogger(__name__)


# ── Valid state transitions ───────────────────────────────────

VALID_TRANSITIONS = {
    "draft": ["sent"],
    "sent": [
        "response_received", "partial_response", "question_received",
        "declined", "reminder_1", "escalated", "closed",
    ],
    "reminder_1": [
        "response_received", "partial_response", "question_received",
        "declined", "reminder_2", "escalated", "closed",
    ],
    "reminder_2": [
        "response_received", "partial_response", "question_received",
        "declined", "escalated", "closed",
    ],
    "response_received": ["complete_response", "partial_response", "evaluating", "escalated"],
    "partial_response": [
        "response_received", "complete_response", "awaiting_response",
        "escalated", "closed",
    ],
    "question_received": ["awaiting_response", "response_received", "escalated", "closed"],
    "awaiting_response": [
        "response_received", "partial_response", "question_received",
        "escalated", "closed",
    ],
    "complete_response": ["evaluating", "escalated"],
    "evaluating": ["awarded", "not_selected"],
    "escalated": ["response_received", "closed", "awaiting_response"],
    "declined": ["closed"],
    "awarded": [],
    "not_selected": [],
    "closed": [],
}

# Escalation keywords — immediate escalation if found in email
ESCALATION_KEYWORDS = [
    "exclusive", "minimum commitment", "penalty", "contract",
    "NDA", "legal", "binding", "liability", "indemnity",
]


# ── Auto-Reply Decision Engine ────────────────────────────────


def should_auto_reply(
    classification: dict,
    vendor: dict,
    inquiry: dict,
    workflow_config: dict | None = None,
) -> dict:
    """Decide whether to auto-reply, escalate, or draft for approval.

    Returns: {
        "action": "auto_send" | "draft_approval" | "escalate" | "skip",
        "reason": str,
    }
    """
    wf = workflow_config or {}
    escalation_rules = wf.get("escalation_rules", {})
    auto_config = inquiry.get("automation_config", {})

    intent = classification.get("intent", "unrelated")
    confidence = classification.get("confidence", 0)
    questions = classification.get("questions_from_vendor", [])
    should_escalate = classification.get("should_escalate", False)
    language = classification.get("language", "en")

    # Auto-reply count check
    auto_reply_count = vendor.get("email_tracking", {}).get("auto_reply_count", 0)
    max_auto = auto_config.get("max_auto_replies_per_vendor",
                                escalation_rules.get("max_auto_replies", 3))
    if auto_reply_count >= max_auto:
        return {"action": "escalate", "reason": f"Auto-reply limit reached ({max_auto})"}

    # Gemini flagged for escalation
    if should_escalate:
        return {
            "action": "escalate",
            "reason": classification.get("escalation_reason", "Gemini flagged"),
        }

    # Check escalation keywords in questions
    for q in questions:
        q_lower = q.lower()
        for kw in ESCALATION_KEYWORDS:
            if kw.lower() in q_lower:
                return {"action": "escalate", "reason": f"Escalation keyword: {kw}"}

    # No questions and no missing data — skip
    if not questions and not classification.get("missing_fields"):
        return {"action": "skip", "reason": "No questions or missing fields to address"}

    # Confidence-based routing
    min_confidence = auto_config.get("auto_reply_min_confidence",
                                      escalation_rules.get("auto_reply_min_confidence", 0.8))
    low_threshold = escalation_rules.get("low_confidence_threshold", 0.6)

    if confidence >= min_confidence:
        return {"action": "auto_send", "reason": f"High confidence ({confidence:.2f})"}
    elif confidence >= low_threshold:
        return {"action": "draft_approval", "reason": f"Medium confidence ({confidence:.2f})"}
    else:
        return {"action": "escalate", "reason": f"Low confidence ({confidence:.2f})"}


def check_rate_anomaly(
    rates: dict,
    baseline: dict,
    anomaly_factor: float = 2.0,
) -> list[str]:
    """Check if extracted rates are anomalous vs baseline.

    Returns list of anomaly descriptions.
    """
    anomalies = []
    checks = [
        ("d2d_sea_lcl_per_cbm", "sea_per_cbm", "Sea LCL/CBM"),
        ("d2d_sea_lcl_per_kg", "sea_per_kg", "Sea LCL/KG"),
        ("d2d_land_per_cbm", "land_per_cbm", "Land/CBM"),
        ("d2d_land_per_kg", "land_per_kg", "Land/KG"),
    ]
    for rate_key, baseline_key, label in checks:
        vendor_rate = rates.get(rate_key)
        base_rate = baseline.get(baseline_key)
        if vendor_rate and base_rate and base_rate > 0:
            ratio = vendor_rate / base_rate
            if ratio > anomaly_factor:
                anomalies.append(
                    f"{label}: {vendor_rate:,.0f} is {ratio:.1f}x baseline ({base_rate:,.0f})"
                )
            elif ratio < (1 / anomaly_factor):
                anomalies.append(
                    f"{label}: {vendor_rate:,.0f} is only {ratio:.2f}x baseline ({base_rate:,.0f}) — suspiciously low"
                )
    return anomalies


# ── Reminder Logic ────────────────────────────────────────────


def get_vendors_needing_reminders(
    inquiry_id: str,
    db=None,
) -> dict:
    """Check all vendors in an inquiry and determine who needs reminders.

    Returns: {
        "reminder_1": [vendor_docs...],
        "reminder_2": [vendor_docs...],
        "escalate": [vendor_docs...],
        "close": [vendor_docs...],
    }
    """
    db = db or get_db()
    inquiry = get_inquiry(inquiry_id, db=db)
    if not inquiry:
        return {"reminder_1": [], "reminder_2": [], "escalate": [], "close": []}

    workflow = get_workflow_config("default", db=db) or {}
    schedule = workflow.get("reminder_schedule", {})
    day_1 = schedule.get("day_1", 5)
    day_2 = schedule.get("day_2", 7)
    escalate_day = schedule.get("escalate_day", 10)
    grace_days = schedule.get("close_after_deadline_grace_days", 3)

    deadline_str = inquiry.get("response_deadline")
    now = datetime.now(timezone.utc)

    result = {"reminder_1": [], "reminder_2": [], "escalate": [], "close": []}

    vendors = get_inquiry_vendors(inquiry_id, db=db)
    for vendor in vendors:
        status = vendor.get("status", "draft")
        if status in ("draft", "declined", "closed", "complete_response",
                       "evaluating", "awarded", "not_selected"):
            continue

        # Calculate days since RFQ was sent
        last_outbound = vendor.get("email_tracking", {}).get("last_outbound_at")
        if not last_outbound:
            continue

        if isinstance(last_outbound, str):
            try:
                last_outbound = datetime.fromisoformat(last_outbound)
            except (ValueError, TypeError):
                continue

        # Ensure timezone aware
        if last_outbound.tzinfo is None:
            last_outbound = last_outbound.replace(tzinfo=timezone.utc)

        days_since_sent = (now - last_outbound).days

        reminder_count = vendor.get("reminders", {}).get("count", 0)

        # Check deadline + grace
        if deadline_str:
            try:
                deadline = datetime.fromisoformat(deadline_str)
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                if now > deadline + timedelta(days=grace_days):
                    if status in ("sent", "reminder_1", "reminder_2"):
                        result["close"].append(vendor)
                        continue
            except (ValueError, TypeError):
                pass

        # Escalation
        if days_since_sent >= escalate_day and status in ("sent", "reminder_1", "reminder_2"):
            result["escalate"].append(vendor)
        # Reminder 2
        elif days_since_sent >= day_2 and reminder_count < 2 and status in ("sent", "reminder_1"):
            result["reminder_2"].append(vendor)
        # Reminder 1
        elif days_since_sent >= day_1 and reminder_count < 1 and status == "sent":
            result["reminder_1"].append(vendor)

    return result


def process_reminders(
    inquiry_id: str,
    dry_run: bool = False,
    db=None,
) -> dict:
    """Process all reminders for an inquiry.

    Returns summary of actions taken.
    """
    db = db or get_db()
    inquiry = get_inquiry(inquiry_id, db=db)
    if not inquiry:
        return {"error": f"Inquiry {inquiry_id} not found"}

    needs = get_vendors_needing_reminders(inquiry_id, db=db)
    summary = {
        "inquiry_id": inquiry_id,
        "reminder_1_sent": 0,
        "reminder_2_sent": 0,
        "escalated": 0,
        "closed": 0,
        "details": [],
    }

    # Send reminder 1
    for vendor in needs["reminder_1"]:
        vid = vendor.get("vendor_id", "")
        if dry_run:
            summary["details"].append({"vendor_id": vid, "action": "reminder_1", "dry_run": True})
            summary["reminder_1_sent"] += 1
            continue
        try:
            send_reminder(vendor, inquiry, reminder_number=1)
            update_vendor_status(inquiry_id, vid, "reminder_1", note="Day 5 reminder sent", db=db)
            _update_reminder_count(inquiry_id, vid, 1, db)
            log_message(inquiry_id, vid, {
                "direction": "outbound", "type": "reminder",
                "subject": f"Reminder: {inquiry.get('title', 'RFQ')}",
                "sender": "eukrit@goco.bz",
            }, db=db)
            summary["reminder_1_sent"] += 1
            summary["details"].append({"vendor_id": vid, "action": "reminder_1", "status": "sent"})
        except Exception as e:
            logger.error("Failed reminder 1 for %s: %s", vid, e)
            summary["details"].append({"vendor_id": vid, "action": "reminder_1", "error": str(e)})

    # Send reminder 2
    for vendor in needs["reminder_2"]:
        vid = vendor.get("vendor_id", "")
        if dry_run:
            summary["details"].append({"vendor_id": vid, "action": "reminder_2", "dry_run": True})
            summary["reminder_2_sent"] += 1
            continue
        try:
            send_reminder(vendor, inquiry, reminder_number=2)
            update_vendor_status(inquiry_id, vid, "reminder_2", note="Day 7 reminder sent (WeChat mention)", db=db)
            _update_reminder_count(inquiry_id, vid, 2, db)
            log_message(inquiry_id, vid, {
                "direction": "outbound", "type": "reminder",
                "subject": f"2nd Reminder: {inquiry.get('title', 'RFQ')}",
                "sender": "eukrit@goco.bz",
            }, db=db)
            summary["reminder_2_sent"] += 1
            summary["details"].append({"vendor_id": vid, "action": "reminder_2", "status": "sent"})
        except Exception as e:
            logger.error("Failed reminder 2 for %s: %s", vid, e)
            summary["details"].append({"vendor_id": vid, "action": "reminder_2", "error": str(e)})

    # Escalate
    for vendor in needs["escalate"]:
        vid = vendor.get("vendor_id", "")
        if dry_run:
            summary["details"].append({"vendor_id": vid, "action": "escalate", "dry_run": True})
            summary["escalated"] += 1
            continue
        update_vendor_status(inquiry_id, vid, "escalated", note="Day 10 — no response", db=db)
        summary["escalated"] += 1
        summary["details"].append({"vendor_id": vid, "action": "escalated"})

    # Close non-responsive past deadline
    for vendor in needs["close"]:
        vid = vendor.get("vendor_id", "")
        if dry_run:
            summary["details"].append({"vendor_id": vid, "action": "close", "dry_run": True})
            summary["closed"] += 1
            continue
        update_vendor_status(inquiry_id, vid, "closed", note="Past deadline + grace period", db=db)
        summary["closed"] += 1
        summary["details"].append({"vendor_id": vid, "action": "closed"})

    return summary


def _update_reminder_count(inquiry_id: str, vendor_id: str, count: int, db) -> None:
    """Update the reminder count for a vendor."""
    from google.cloud import firestore as fs
    ref = (
        db.collection("rfq_inquiries")
        .document(inquiry_id)
        .collection("vendors")
        .document(vendor_id)
    )
    ref.update({"reminders.count": count})
