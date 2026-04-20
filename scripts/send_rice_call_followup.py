#!/usr/bin/env python3
"""
send_rice_call_followup.py — Send a simple Thai follow-up to every silent vendor
on the Rice Export RFQ asking them to call Eukrit at 061-491-6393.

Replies in the existing Gmail thread (threadId + In-Reply-To). Logs each
outbound message to Firestore and bumps the vendor's reminder count.

Usage:
    python scripts/send_rice_call_followup.py          # send for real
    python scripts/send_rice_call_followup.py --dry    # preview only
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.rfq_store import (
    get_db,
    get_inquiry,
    get_inquiry_vendors,
    log_message,
    update_vendor_status,
)
from src.gmail_sender import get_gmail_send_service, send_email

INQUIRY_ID = "RFQ-GO-2026-04-RICE-EXPORT"
REPLY_TO = "shipping@goco.bz"
CC = ["shipping@goco.bz"]
PHONE_TH = "061-491-6393"

ORIG_SUBJECT = "RFQ: Thai White Rice 5% Broken — 200,000 MT Export to China | GO Corporation Co., Ltd."
SUBJECT = f"Re: {ORIG_SUBJECT}"


def build_body(vendor_name_th: str | None, vendor_name_en: str) -> str:
    greeting_th = f"เรียน {vendor_name_th}," if vendor_name_th else f"เรียน {vendor_name_en},"
    return f"""\
<div style="font-family: 'Segoe UI', 'Sarabun', Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #333;">

<p>{greeting_th}</p>

<p>ก่อนหน้านี้ทางบริษัท จีโอ คอร์ปอเรชั่น จำกัด (GO Corporation Co., Ltd.)
ได้ส่งอีเมลสอบถามราคา (RFQ) ข้าวขาวไทย 5% ปริมาณ 200,000 เมตริกตัน
สำหรับส่งออกไปยังประเทศจีน แต่ยังไม่ได้รับการตอบกลับจากท่าน</p>

<p>หากท่านสนใจเสนอราคา กรุณาโทรกลับมาหาผมโดยตรงที่
<strong>{PHONE_TH}</strong> เพื่อพูดคุยรายละเอียดเพิ่มเติมครับ</p>

<p>ขอบคุณครับ</p>

<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">

<p style="font-size: 13px; color: #666;">
<strong>Eukrit Kraikosol | เอกฤทธิ์ ไกรโกศล</strong><br>
GO Corporation Co., Ltd. | บริษัท จีโอ คอร์ปอเรชั่น จำกัด<br>
Email: eukrit@goco.bz | Reply-To: shipping@goco.bz<br>
Tel: {PHONE_TH} (+66 61 491 6393)<br>
11/2 P23 Tower, Unit 8A, Sukhumvit 23, Bangkok 10110, Thailand
</p>
</div>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="Preview, do not send")
    args = ap.parse_args()

    db = get_db()
    inquiry = get_inquiry(INQUIRY_ID, db=db)
    if not inquiry:
        print(f"ERROR: Inquiry {INQUIRY_ID} not found")
        sys.exit(1)

    vendors = get_inquiry_vendors(INQUIRY_ID, db=db)
    silent = [
        v for v in vendors
        if v.get("status") == "sent" and v.get("contact_email")
    ]
    print(f"Rice RFQ silent vendors: {len(silent)} / {len(vendors)}")
    print(f"Phone being shared: {PHONE_TH}")
    print(f"Mode: {'DRY RUN' if args.dry else 'LIVE SEND'}")
    print("=" * 70)

    service = None if args.dry else get_gmail_send_service()

    sent_count = 0
    for v in silent:
        vid = v["vendor_id"]
        email = v["contact_email"]
        name_en = v.get("company_en", "Sir/Madam")
        name_th = v.get("company_th")

        tracking = v.get("email_tracking", {}) or {}
        thread_id = tracking.get("thread_id")
        msg_ids = tracking.get("message_ids") or []
        in_reply_to = msg_ids[-1] if msg_ids else None

        body = build_body(name_th, name_en)

        if args.dry:
            print(f"[DRY] {vid:40s} -> {email}  (thread={thread_id})")
            continue

        result = send_email(
            to=email,
            subject=SUBJECT,
            body_html=body,
            reply_to=REPLY_TO,
            cc=CC,
            in_reply_to=in_reply_to,
            references=in_reply_to,
            thread_id=thread_id,
            service=service,
        )

        log_message(INQUIRY_ID, vid, {
            "direction": "outbound",
            "type": "follow_up_call",
            "subject": SUBJECT,
            "sender": "eukrit@goco.bz",
            "recipients": [email],
            "message_id": result.get("message_id"),
            "thread_id": result.get("thread_id"),
            "body_preview": f"Thai follow-up asking vendor to call {PHONE_TH}",
        }, db=db)

        update_vendor_status(
            INQUIRY_ID, vid, "reminder_1",
            note=f"Thai call-me follow-up sent ({PHONE_TH})", db=db,
        )
        # Bump reminder count
        (
            db.collection("rfq_inquiries").document(INQUIRY_ID)
              .collection("vendors").document(vid)
              .update({"reminders.count": (v.get("reminders", {}).get("count", 0) or 0) + 1})
        )
        sent_count += 1
        print(f"SENT  {vid:40s} -> {email}")

    print("=" * 70)
    print(f"DONE. {'Would send' if args.dry else 'Sent'} {sent_count if not args.dry else len(silent)} emails.")


if __name__ == "__main__":
    main()
