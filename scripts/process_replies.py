#!/usr/bin/env python3
"""Process all inbound vendor replies through the Gemini pipeline."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.gmail_reader import get_gmail_readonly_service, _get_full_message, strip_html
from src.rfq_store import (
    get_db, get_inquiry, get_vendor, get_inquiry_vendors,
    match_sender_to_vendor, log_message, update_vendor_status, update_vendor_rates,
)
from src.parsers.rfq_gemini import classify_vendor_response, extract_vendor_rates
from src.rfq_workflow import check_rate_anomaly

INQUIRY_ID = "RFQ-GO-2026-04-FREIGHT"

# Domain-to-vendor fallback map (for senders not matching stored contact_email)
DOMAIN_MAP = {
    "csc.cc": "csc-logistics",
    "stusupplychain.com": "stu-supply-chain",
    "sdilogistics.com": "sdi-logistics",
    "szsdi.com": "sdi-logistics",
    "dfhfreight.com": "dfh-global-logistics",
    "djcargo.cn": "djcargo",
    "cantoncargo.com": "canton-cargo",
    "boruifeng.cn": "china-brf-logistics",
    "micocean.com": "micocean-international-logistics",
    "sino-shipping.com": "sino-shipping",
    "btshipping.com": "bt-shipping",
    "goodhopefreight.com": "goodhope-freight",
    "ddpchain.com": "ddpchain",
    "dimerco.com": "dimerco-express-group",
}


def match_sender(sender_email: str, db) -> dict | None:
    """Match sender email to vendor, with domain fallback."""
    match = match_sender_to_vendor(sender_email, db=db)
    if match:
        return match

    domain = sender_email.split("@")[1] if "@" in sender_email else ""
    if domain in DOMAIN_MAP:
        return {"inquiry_id": INQUIRY_ID, "vendor_id": DOMAIN_MAP[domain]}

    return None


def main():
    service = get_gmail_readonly_service()
    db = get_db()
    inquiry = get_inquiry(INQUIRY_ID, db=db)
    baseline = inquiry.get("scoring_config", {}).get("baseline", {})

    # Get all RFQ replies (not from us)
    results = service.users().messages().list(
        userId="me",
        q='subject:"RFQ: China to Bangkok Freight Forwarding" -from:eukrit@goco.bz newer_than:3d',
        maxResults=20,
    ).execute()

    msg_ids = [m["id"] for m in results.get("messages", [])]
    print(f"Processing {len(msg_ids)} replies...")
    print("=" * 70)

    processed = set()

    for msg_id in msg_ids:
        msg = _get_full_message(msg_id, service)
        if not msg:
            continue

        sender = msg["sender_email"]
        body_text = msg.get("body_text") or strip_html(msg.get("body_html", ""))

        print(f"\n--- {msg['sender'][:60]} ---")
        print(f"Subject: {msg['subject'][:70]}")

        match = match_sender(sender, db)
        if not match:
            print(f"  NO MATCH for {sender} - skipping")
            continue

        vendor_id = match["vendor_id"]
        vendor = get_vendor(INQUIRY_ID, vendor_id, db=db)
        if not vendor:
            print(f"  Vendor {vendor_id} not found in Firestore")
            continue

        print(f"  Matched: {vendor_id} ({vendor.get('company_en', '')})")

        # Skip if we already processed this vendor (take first/latest email only)
        if vendor_id in processed:
            print(f"  Already processed {vendor_id} - skipping duplicate")
            continue
        processed.add(vendor_id)

        # Classify
        classification = classify_vendor_response(
            sender=msg["sender"],
            subject=msg["subject"],
            body=body_text,
            inquiry_title=inquiry.get("title", ""),
        )
        print(f"  Intent: {classification['intent']}  Confidence: {classification['confidence']}")
        print(f"  Summary: {classification.get('summary', '')[:120]}")
        if classification.get("questions_from_vendor"):
            print(f"  Questions: {classification['questions_from_vendor']}")

        # Extract rates if applicable
        if classification.get("has_rate_data"):
            extraction = extract_vendor_rates(
                body=body_text,
                vendor_name=vendor.get("company_en", ""),
                vendor_company=vendor.get("company_en", ""),
            )
            rates = extraction.get("rates", {})
            sea = rates.get("d2d_sea_lcl_per_cbm")
            land = rates.get("d2d_land_per_cbm")
            print(f"  RATES: Sea={sea} THB/CBM  Land={land} THB/CBM")
            print(f"  Transit: Sea={rates.get('transit_sea_days')}d  Land={rates.get('transit_land_days')}d")
            print(f"  Payment: {rates.get('payment_terms', 'N/A')}")
            missing = extraction.get("missing_fields", [])
            if missing:
                print(f"  Missing: {missing[:5]}")
            print(f"  Extraction confidence: {extraction.get('confidence', 0)}")

            # Check anomalies
            anomalies = check_rate_anomaly(rates, baseline)
            if anomalies:
                print(f"  ANOMALIES: {anomalies}")
            else:
                print(f"  Rates vs baseline: OK")

            # Save to Firestore
            update_vendor_rates(INQUIRY_ID, vendor_id,
                rates=rates,
                capabilities=extraction.get("capabilities"),
                db=db)
            update_vendor_status(INQUIRY_ID, vendor_id,
                "response_received",
                note=classification.get("summary", ""),
                db=db)
        elif classification.get("intent") == "question":
            update_vendor_status(INQUIRY_ID, vendor_id,
                "question_received",
                note=classification.get("summary", ""),
                db=db)
        elif classification.get("intent") == "decline":
            update_vendor_status(INQUIRY_ID, vendor_id,
                "declined",
                note=classification.get("summary", ""),
                db=db)

        # Log message
        log_message(INQUIRY_ID, vendor_id, {
            "direction": "inbound",
            "type": "response",
            "subject": msg["subject"],
            "sender": msg["sender"],
            "body_preview": body_text[:3000],
            "message_id": msg_id,
            "thread_id": msg.get("threadId"),
            "gemini_analysis": {
                "intent": classification["intent"],
                "confidence": classification["confidence"],
                "summary": classification.get("summary", ""),
                "has_rate_data": classification.get("has_rate_data", False),
                "questions_from_vendor": classification.get("questions_from_vendor", []),
            },
        }, db=db)
        print(f"  SAVED to Firestore")

    # Update responded count
    vendors = get_inquiry_vendors(INQUIRY_ID, db=db)
    responded = sum(
        1 for v in vendors
        if v.get("status") in ("response_received", "complete_response", "partial_response", "question_received")
    )
    db.collection("rfq_inquiries").document(INQUIRY_ID).update({"responded_count": responded})

    print()
    print("=" * 70)
    print(f"DONE. Vendors responded: {responded} / {len(vendors)}")

    # Summary table
    print()
    print("RATE SUMMARY:")
    print(f"{'Vendor':<35} {'Sea/CBM':>10} {'Land/CBM':>10} {'Sea days':>10} {'Land days':>10}")
    print("-" * 80)
    print(f"{'Gift Somlak (baseline)':<35} {'4,600':>10} {'7,200':>10} {'':>10} {'':>10}")
    for v in sorted(vendors, key=lambda x: x.get("vendor_id", "")):
        rates = v.get("rates", {})
        if rates:
            sea = rates.get("d2d_sea_lcl_per_cbm")
            land = rates.get("d2d_land_per_cbm")
            sea_d = rates.get("transit_sea_days")
            land_d = rates.get("transit_land_days")
            sea_str = f"{sea:,.0f}" if sea else "-"
            land_str = f"{land:,.0f}" if land else "-"
            sea_d_str = f"{sea_d}" if sea_d else "-"
            land_d_str = f"{land_d}" if land_d else "-"
            print(f"{v.get('company_en', '')[:35]:<35} {sea_str:>10} {land_str:>10} {sea_d_str:>10} {land_d_str:>10}")


if __name__ == "__main__":
    main()
