"""
main.py — Cloud Function entry points for procurement automation.

Entry points:
  send_rfq              — HTTP trigger: dispatch RFQ emails to vendors
  process_procurement_email — Pub/Sub trigger: handle inbound emails (Phase 3)
  rfq_reminder_cron     — HTTP trigger: daily reminder cron (Phase 4)
"""

from __future__ import annotations

import json
import logging

import functions_framework
from google.cloud import firestore
from flask import Request

from src.rfq_store import (
    get_db,
    get_inquiry,
    get_inquiry_vendors,
    get_vendor,
    add_vendor_to_inquiry,
    log_message,
    update_vendor_status,
    update_vendor_rates,
    match_sender_to_vendor,
    get_template,
)
from src.gmail_sender import (
    get_gmail_send_service,
    send_rfq_to_vendor,
    send_auto_reply,
)
from src.gmail_reader import (
    get_new_messages,
    strip_html,
)
from src.parsers.rfq_gemini import (
    classify_vendor_response,
    extract_vendor_rates,
    generate_auto_reply,
)
from src.rfq_workflow import (
    should_auto_reply,
    check_rate_anomaly,
    process_reminders,
)
from src.slack_notifier import (
    notify_new_response,
    notify_escalation,
    notify_auto_reply_sent,
    notify_draft_for_approval,
    notify_rate_anomaly,
    notify_reminder_summary,
    notify_rfq_dispatched,
)
from src.rfq_store import list_inquiries

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _slack_channel_for(inquiry: dict | None) -> str | None:
    """Per-inquiry Slack channel override. Falls back to env SLACK_CHANNEL
    when not set on the inquiry.
    """
    if not inquiry:
        return None
    return inquiry.get("automation_config", {}).get("slack_channel")


@functions_framework.http
def send_rfq(request: Request):
    """HTTP trigger to dispatch RFQ emails to vendors.

    Query params / JSON body:
        inquiry_id (required): The inquiry to send RFQs for.
        vendor_ids (optional): List of specific vendor IDs. If omitted, sends to
                               all vendors with status='draft'.
        dry_run (optional): If true, preview without sending.

    Examples:
        POST /send_rfq
        {"inquiry_id": "RFQ-GO-2026-04-FREIGHT"}

        POST /send_rfq
        {"inquiry_id": "RFQ-GO-2026-04-FREIGHT", "vendor_ids": ["djcargo"], "dry_run": true}
    """
    # Parse request
    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = {}

    inquiry_id = data.get("inquiry_id") or request.args.get("inquiry_id")
    vendor_ids = data.get("vendor_ids")
    dry_run = data.get("dry_run", False)

    if not inquiry_id:
        return {"error": "inquiry_id is required"}, 400

    db = get_db()
    inquiry = get_inquiry(inquiry_id, db=db)
    if not inquiry:
        return {"error": f"Inquiry {inquiry_id} not found"}, 404

    # Get target vendors
    if vendor_ids:
        vendors = [get_vendor(inquiry_id, vid, db=db) for vid in vendor_ids]
        vendors = [v for v in vendors if v is not None]
    else:
        vendors = get_inquiry_vendors(inquiry_id, status_filter="draft", db=db)

    if not vendors:
        return {"error": "No vendors to send to"}, 400

    # Build Gmail service once
    service = None if dry_run else get_gmail_send_service()

    # Load template once (same for every vendor in this inquiry)
    template = None
    template_id = inquiry.get("template_id")
    if template_id:
        template = get_template(template_id, db=db)
        if not template:
            logger.warning(
                "Template %s referenced by inquiry %s not found — falling back to default body",
                template_id, inquiry_id,
            )

    results = []
    sent_count = 0
    skipped_count = 0
    error_count = 0

    for vendor in vendors:
        vendor_id = vendor.get("vendor_id", "unknown")
        try:
            result = send_rfq_to_vendor(
                inquiry=inquiry,
                vendor=vendor,
                service=service,
                dry_run=dry_run,
                template=template,
            )

            if result.get("skipped"):
                skipped_count += 1
                results.append({
                    "vendor_id": vendor_id,
                    "status": "skipped",
                    "reason": result.get("reason"),
                })
                continue

            if dry_run:
                results.append({
                    "vendor_id": vendor_id,
                    "status": "dry_run",
                    "to": result.get("to"),
                    "subject": result.get("subject"),
                })
                continue

            # Log the outbound message and update vendor status
            log_message(
                inquiry_id,
                vendor_id,
                {
                    "direction": "outbound",
                    "type": "rfq_initial",
                    "subject": result.get("subject", ""),
                    "sender": "eukrit@goco.bz",
                    "recipients": [vendor.get("contact_email")],
                    "message_id": result.get("message_id"),
                    "thread_id": result.get("thread_id"),
                    "body_preview": "",
                },
                db=db,
            )

            update_vendor_status(
                inquiry_id, vendor_id, "sent", note="RFQ email sent", db=db
            )

            sent_count += 1
            results.append({
                "vendor_id": vendor_id,
                "status": "sent",
                "message_id": result.get("message_id"),
                "thread_id": result.get("thread_id"),
            })

        except Exception as e:
            error_count += 1
            logger.error("Failed to send to %s: %s", vendor_id, str(e))
            results.append({
                "vendor_id": vendor_id,
                "status": "error",
                "error": str(e),
            })

    # Update inquiry status if we actually sent
    if sent_count > 0 and not dry_run:
        inquiry_status = inquiry.get("status")
        if inquiry_status == "draft":
            db.collection("rfq_inquiries").document(inquiry_id).update(
                {"status": "sending"}
            )

    # Slack dispatch notification (honors per-inquiry channel override)
    if not dry_run and (sent_count or skipped_count or error_count):
        try:
            notify_rfq_dispatched(
                inquiry_id=inquiry_id,
                inquiry_title=inquiry.get("title", ""),
                sent=sent_count,
                skipped=skipped_count,
                errors=error_count,
                vendor_details=results,
                channel=_slack_channel_for(inquiry),
            )
        except Exception as e:
            logger.error("Slack notify_rfq_dispatched failed: %s", e)

    response = {
        "inquiry_id": inquiry_id,
        "dry_run": dry_run,
        "total_vendors": len(vendors),
        "sent": sent_count,
        "skipped": skipped_count,
        "errors": error_count,
        "results": results,
    }

    logger.info(
        "send_rfq complete: inquiry=%s sent=%d skipped=%d errors=%d dry_run=%s",
        inquiry_id,
        sent_count,
        skipped_count,
        error_count,
        dry_run,
    )

    return response, 200


@functions_framework.cloud_event
def process_procurement_email(cloud_event):
    """Pub/Sub trigger from Gmail watch — processes inbound vendor emails.

    Flow:
    1. Fetch new messages from Gmail History API
    2. For each message, match sender to an active inquiry vendor
    3. Classify with Gemini (intent, questions, rate data)
    4. Route by intent: extract rates, flag for auto-reply, escalate, etc.
    5. Log everything to Firestore
    """
    logger.info("process_procurement_email triggered")

    db = get_db()

    # 1. Get new messages
    try:
        messages = get_new_messages(db=db)
    except Exception as e:
        logger.error("Failed to fetch Gmail messages: %s", e)
        return

    if not messages:
        logger.info("No new messages")
        return

    logger.info("Processing %d new messages", len(messages))

    for msg in messages:
        try:
            _process_single_message(msg, db)
        except Exception as e:
            logger.error(
                "Error processing message %s from %s: %s",
                msg.get("id"),
                msg.get("sender_email"),
                e,
            )


def _process_single_message(msg: dict, db) -> None:
    """Process a single inbound Gmail message."""
    sender_email = msg.get("sender_email", "")
    subject = msg.get("subject", "")
    msg_id = msg.get("id", "")

    logger.info("Processing message %s from %s: %s", msg_id, sender_email, subject)

    # 2. Match sender to a vendor in an active inquiry
    match = match_sender_to_vendor(sender_email, db=db)
    if not match:
        logger.info("No vendor match for sender %s — skipping", sender_email)
        return

    inquiry_id = match["inquiry_id"]
    vendor_id = match["vendor_id"]

    inquiry = get_inquiry(inquiry_id, db=db)
    vendor = get_vendor(inquiry_id, vendor_id, db=db)
    if not inquiry or not vendor:
        logger.warning("Inquiry or vendor not found: %s / %s", inquiry_id, vendor_id)
        return

    logger.info("Matched: inquiry=%s vendor=%s", inquiry_id, vendor_id)

    # Get email body text for Gemini
    body_text = msg.get("body_text") or strip_html(msg.get("body_html", ""))

    # 3. Classify with Gemini
    classification = classify_vendor_response(
        sender=msg.get("sender", ""),
        subject=subject,
        body=body_text,
        inquiry_title=inquiry.get("title", ""),
    )

    # 4. Log the inbound message with Gemini analysis
    message_data = {
        "message_id": msg_id,
        "direction": "inbound",
        "type": _intent_to_message_type(classification.get("intent", "unrelated")),
        "subject": subject,
        "sender": msg.get("sender", ""),
        "recipients": [msg.get("headers", {}).get("to", "")],
        "body_preview": msg.get("body_preview", "")[:5000],
        "gmail_link": f"https://mail.google.com/mail/u/0/#inbox/{msg_id}",
        "thread_id": msg.get("threadId"),
        "attachments": msg.get("attachments", []),
        "gemini_analysis": {
            "intent": classification.get("intent"),
            "confidence": classification.get("confidence", 0),
            "summary": classification.get("summary", ""),
            "extracted_data": {},
            "questions_from_vendor": classification.get("questions_from_vendor", []),
            "missing_fields": classification.get("missing_fields", []),
            "auto_reply_draft": None,
            "auto_reply_confidence": None,
            "should_escalate": classification.get("should_escalate", False),
            "escalation_reason": classification.get("escalation_reason"),
            "language": classification.get("language", "en"),
        },
    }

    log_message(inquiry_id, vendor_id, message_data, db=db)

    # 5. Route by intent
    intent = classification.get("intent", "unrelated")

    if not classification.get("is_rfq_response", False):
        logger.info("Not an RFQ response — logged and done")
        return

    # Update vendor status based on intent
    if intent == "rate_quote":
        _handle_rate_quote(inquiry_id, vendor_id, inquiry, vendor, body_text, msg, classification, db)
    elif intent == "partial_response":
        update_vendor_status(inquiry_id, vendor_id, "partial_response", note=classification.get("summary", ""), db=db)
        _handle_questions_or_missing(inquiry_id, vendor_id, inquiry, vendor, body_text, msg, classification, db)
    elif intent == "question":
        update_vendor_status(inquiry_id, vendor_id, "question_received", note=classification.get("summary", ""), db=db)
        _handle_questions_or_missing(inquiry_id, vendor_id, inquiry, vendor, body_text, msg, classification, db)
    elif intent == "decline":
        update_vendor_status(inquiry_id, vendor_id, "declined", note=classification.get("summary", ""), db=db)
        logger.info("Vendor %s declined", vendor_id)
    elif intent == "out_of_office" or intent == "auto_reply_bounce":
        logger.info("Out of office / auto-reply from %s — no action", vendor_id)
    elif intent == "counter_offer":
        update_vendor_status(inquiry_id, vendor_id, "response_received", note="Counter offer", db=db)
        _handle_rate_quote(inquiry_id, vendor_id, inquiry, vendor, body_text, msg, classification, db)
    else:
        logger.info("Unhandled intent '%s' from %s", intent, vendor_id)


def _handle_rate_quote(
    inquiry_id: str, vendor_id: str, inquiry: dict, vendor: dict,
    body_text: str, msg: dict, classification: dict, db
) -> None:
    """Handle a vendor that sent rate/pricing data."""
    update_vendor_status(inquiry_id, vendor_id, "response_received", note="Rate quote received", db=db)

    # Extract structured rates with Gemini
    extraction = extract_vendor_rates(
        body=body_text,
        vendor_name=vendor.get("company_en", ""),
        vendor_company=vendor.get("company_en", ""),
    )

    if extraction.get("rates"):
        update_vendor_rates(
            inquiry_id, vendor_id,
            rates=extraction.get("rates", {}),
            benchmark=None,
            capabilities=extraction.get("capabilities"),
            db=db,
        )

    # Check completeness
    missing = extraction.get("missing_fields", [])
    if not missing:
        update_vendor_status(inquiry_id, vendor_id, "complete_response", note="All fields received", db=db)
    else:
        logger.info("Vendor %s has missing fields: %s", vendor_id, missing)

    # Update inquiry responded_count
    db.collection("rfq_inquiries").document(inquiry_id).update({
        "responded_count": _count_responded(inquiry_id, db),
    })

    # Slack notification for new response
    slack_channel = _slack_channel_for(inquiry)
    try:
        notify_new_response(
            inquiry_id=inquiry_id,
            vendor_id=vendor_id,
            vendor_name=vendor.get("company_en", vendor_id),
            intent=classification.get("intent", "rate_quote"),
            summary=classification.get("summary", ""),
            confidence=classification.get("confidence", 0),
            channel=slack_channel,
        )
    except Exception as e:
        logger.error("Slack notify_new_response failed: %s", e)

    # Check rate anomalies vs baseline
    if extraction.get("rates"):
        baseline = inquiry.get("scoring_config", {}).get("baseline", {})
        if baseline:
            anomalies = check_rate_anomaly(extraction["rates"], baseline)
            if anomalies:
                logger.warning("Rate anomalies for %s: %s", vendor_id, anomalies)
                try:
                    notify_rate_anomaly(
                        inquiry_id,
                        vendor_id,
                        vendor.get("company_en", ""),
                        anomalies,
                        channel=slack_channel,
                    )
                except Exception as e:
                    logger.error("Slack rate anomaly notify failed: %s", e)

    # If there are still questions or missing fields, optionally auto-reply
    if missing or classification.get("questions_from_vendor"):
        _handle_questions_or_missing(inquiry_id, vendor_id, inquiry, vendor, body_text, msg, classification, db)


def _handle_questions_or_missing(
    inquiry_id: str, vendor_id: str, inquiry: dict, vendor: dict,
    body_text: str, msg: dict, classification: dict, db
) -> None:
    """Generate auto-reply draft for vendor questions or missing fields."""
    questions = classification.get("questions_from_vendor", [])
    missing = classification.get("missing_fields", [])

    if not questions and not missing:
        return

    # Check auto-reply limits
    auto_reply_count = vendor.get("email_tracking", {}).get("auto_reply_count", 0)
    max_auto_replies = inquiry.get("automation_config", {}).get("max_auto_replies_per_vendor", 3)

    if auto_reply_count >= max_auto_replies:
        logger.info("Vendor %s hit auto-reply limit (%d) — escalating", vendor_id, max_auto_replies)
        update_vendor_status(inquiry_id, vendor_id, "escalated", note="Auto-reply limit reached", db=db)
        _send_slack_escalation(inquiry_id, vendor_id, vendor, "Auto-reply limit reached", db, inquiry=inquiry)
        return

    # Check for escalation keywords
    if classification.get("should_escalate"):
        reason = classification.get("escalation_reason", "Gemini flagged for escalation")
        update_vendor_status(inquiry_id, vendor_id, "escalated", note=reason, db=db)
        _send_slack_escalation(inquiry_id, vendor_id, vendor, reason, db, inquiry=inquiry)
        return

    # Get template context for auto-reply
    template = get_template(inquiry.get("template_id", ""), db=db)
    auto_reply_context = ""
    if template:
        auto_reply_context = template.get("auto_reply_context", "")

    # Generate auto-reply with Gemini
    reply = generate_auto_reply(
        vendor_name=vendor.get("company_en", ""),
        vendor_company=vendor.get("company_en", ""),
        vendor_email_body=body_text,
        questions=questions,
        missing_fields=missing,
        auto_reply_context=auto_reply_context,
    )

    reply_confidence = reply.get("confidence", 0)
    min_confidence = inquiry.get("automation_config", {}).get("auto_reply_min_confidence", 0.8)

    if reply.get("should_escalate"):
        reason = reply.get("escalation_reason", "Auto-reply flagged for escalation")
        logger.info("Auto-reply escalated for %s: %s", vendor_id, reason)
        _send_slack_escalation(inquiry_id, vendor_id, vendor, reason, db, inquiry=inquiry)
        return

    if reply_confidence >= min_confidence and reply.get("body_html"):
        # Auto-send the reply
        thread_id = vendor.get("email_tracking", {}).get("thread_id")
        last_msg_ids = vendor.get("email_tracking", {}).get("message_ids", [])
        in_reply_to = last_msg_ids[-1] if last_msg_ids else None

        try:
            send_result = send_auto_reply(
                vendor=vendor,
                subject=reply.get("subject", f"Re: {msg.get('subject', '')}"),
                body_html=reply["body_html"],
                thread_id=thread_id or msg.get("threadId", ""),
                in_reply_to=in_reply_to,
            )

            # Log the auto-reply
            log_message(
                inquiry_id, vendor_id,
                {
                    "direction": "outbound",
                    "type": "auto_reply",
                    "subject": reply.get("subject", ""),
                    "sender": "eukrit@goco.bz",
                    "recipients": [vendor.get("contact_email", "")],
                    "body_preview": reply.get("body_html", "")[:5000],
                    "message_id": send_result.get("message_id"),
                    "thread_id": send_result.get("thread_id"),
                },
                db=db,
            )

            # Increment auto-reply count
            vendor_ref = (
                db.collection("rfq_inquiries")
                .document(inquiry_id)
                .collection("vendors")
                .document(vendor_id)
            )
            vendor_ref.update({
                "email_tracking.auto_reply_count": firestore.Increment(1),
            })

            logger.info("Auto-reply sent to %s (confidence=%.2f)", vendor_id, reply_confidence)

            try:
                notify_auto_reply_sent(
                    inquiry_id=inquiry_id,
                    vendor_id=vendor_id,
                    vendor_name=vendor.get("company_en", vendor_id),
                    confidence=reply_confidence,
                    answers=reply.get("answers_given"),
                    channel=_slack_channel_for(inquiry),
                )
            except Exception as e:
                logger.error("Slack auto-reply notify failed: %s", e)

        except Exception as e:
            logger.error("Failed to send auto-reply to %s: %s", vendor_id, e)

    elif reply_confidence >= 0.6:
        # Draft for Slack approval
        logger.info("Auto-reply draft for %s (confidence=%.2f) — needs approval", vendor_id, reply_confidence)
        _send_slack_draft_approval(inquiry_id, vendor_id, vendor, reply, db, inquiry=inquiry)
    else:
        # Too low confidence — escalate
        logger.info("Auto-reply confidence too low (%.2f) for %s — escalating", reply_confidence, vendor_id)
        _send_slack_escalation(inquiry_id, vendor_id, vendor, f"Low confidence auto-reply ({reply_confidence:.2f})", db, inquiry=inquiry)


def _count_responded(inquiry_id: str, db) -> int:
    """Count vendors that have responded."""
    vendors = get_inquiry_vendors(inquiry_id, db=db)
    return sum(
        1 for v in vendors
        if v.get("status") in ("response_received", "complete_response", "partial_response")
    )


def _intent_to_message_type(intent: str) -> str:
    """Map Gemini intent to message type."""
    mapping = {
        "rate_quote": "response",
        "question": "response",
        "decline": "response",
        "partial_response": "response",
        "counter_offer": "response",
        "out_of_office": "response",
        "auto_reply_bounce": "response",
        "unrelated": "response",
    }
    return mapping.get(intent, "response")


def _send_slack_escalation(
    inquiry_id: str, vendor_id: str, vendor: dict, reason: str, db,
    inquiry: dict | None = None,
) -> None:
    """Send a Slack notification for escalation."""
    logger.info(
        "SLACK ESCALATION: inquiry=%s vendor=%s (%s) reason=%s",
        inquiry_id, vendor_id, vendor.get("company_en", ""), reason,
    )
    try:
        notify_escalation(
            inquiry_id=inquiry_id,
            vendor_id=vendor_id,
            vendor_name=vendor.get("company_en", vendor_id),
            reason=reason,
            vendor_contacts={
                "contact_email": vendor.get("contact_email"),
                "contact_wechat": vendor.get("contact_wechat"),
                "contact_whatsapp": vendor.get("contact_whatsapp"),
                "contact_phone": vendor.get("contact_phone"),
            },
            channel=_slack_channel_for(inquiry),
        )
    except Exception as e:
        logger.error("Slack escalation failed: %s", e)


def _send_slack_draft_approval(
    inquiry_id: str, vendor_id: str, vendor: dict, reply: dict, db,
    inquiry: dict | None = None,
) -> None:
    """Send auto-reply draft to Slack for human approval."""
    logger.info(
        "SLACK APPROVAL NEEDED: inquiry=%s vendor=%s (%s) confidence=%.2f",
        inquiry_id, vendor_id, vendor.get("company_en", ""), reply.get("confidence", 0),
    )
    try:
        from src.gmail_reader import strip_html as _strip
        body_preview = _strip(reply.get("body_html", ""))[:500]
        notify_draft_for_approval(
            inquiry_id=inquiry_id,
            vendor_id=vendor_id,
            vendor_name=vendor.get("company_en", vendor_id),
            draft_subject=reply.get("subject", ""),
            draft_body_preview=body_preview,
            confidence=reply.get("confidence", 0),
            channel=_slack_channel_for(inquiry),
        )
    except Exception as e:
        logger.error("Slack draft approval failed: %s", e)


@functions_framework.http
def rfq_reminder_cron(request: Request):
    """HTTP trigger from Cloud Scheduler — daily reminder check.

    Runs daily at 09:00 Bangkok (02:00 UTC).
    For each active inquiry:
      - Day 5: Send reminder 1
      - Day 7: Send reminder 2 (mention WeChat/WhatsApp)
      - Day 10: Escalate to Slack
      - Post-deadline + 3 days: Close non-responsive vendors

    Query params / JSON body:
        inquiry_id (optional): Process a specific inquiry. If omitted, processes all active.
        dry_run (optional): If true, preview without sending.
    """
    logger.info("rfq_reminder_cron triggered")

    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = {}

    inquiry_id = data.get("inquiry_id") or request.args.get("inquiry_id")
    dry_run = data.get("dry_run", False)

    db = get_db()

    # Get target inquiries
    if inquiry_id:
        inquiry_ids = [inquiry_id]
    else:
        # Process all active/sending inquiries
        active = list_inquiries(status="active", db=db)
        sending = list_inquiries(status="sending", db=db)
        inquiry_ids = [
            inq.get("inquiry_id") for inq in active + sending
            if inq.get("inquiry_id")
        ]

    if not inquiry_ids:
        return {"status": "ok", "message": "No active inquiries"}, 200

    all_summaries = []
    for inq_id in inquiry_ids:
        summary = process_reminders(inq_id, dry_run=dry_run, db=db)
        all_summaries.append(summary)

        # Post Slack summary if any actions taken
        if not dry_run:
            try:
                notify_reminder_summary(inq_id, summary)
            except Exception as e:
                logger.error("Slack reminder summary failed for %s: %s", inq_id, e)

    total_actions = sum(
        s.get("reminder_1_sent", 0) + s.get("reminder_2_sent", 0) +
        s.get("escalated", 0) + s.get("closed", 0)
        for s in all_summaries
    )

    logger.info(
        "Reminder cron complete: %d inquiries processed, %d actions taken, dry_run=%s",
        len(inquiry_ids), total_actions, dry_run,
    )

    return {
        "status": "ok",
        "dry_run": dry_run,
        "inquiries_processed": len(inquiry_ids),
        "total_actions": total_actions,
        "summaries": all_summaries,
    }, 200
