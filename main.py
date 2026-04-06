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
from flask import Request

from src.rfq_store import (
    get_db,
    get_inquiry,
    get_inquiry_vendors,
    get_vendor,
    add_vendor_to_inquiry,
    log_message,
    update_vendor_status,
)
from src.gmail_sender import (
    get_gmail_send_service,
    send_rfq_to_vendor,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

    Phase 3 implementation. Currently a stub.
    """
    logger.info("process_procurement_email triggered — Phase 3 stub")
    return


@functions_framework.http
def rfq_reminder_cron(request: Request):
    """HTTP trigger from Cloud Scheduler — daily reminder check.

    Phase 4 implementation. Currently a stub.
    """
    logger.info("rfq_reminder_cron triggered — Phase 4 stub")
    return {"status": "ok", "message": "Phase 4 stub"}, 200
