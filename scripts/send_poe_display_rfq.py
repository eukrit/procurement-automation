#!/usr/bin/env python3
"""
send_poe_display_rfq.py — Dispatch initial RFQ emails for the 10.1" PoE
Android multi-touch display sourcing round (RFQ-GO-2026-04-POE-DISPLAY).

Sends bilingual (EN + CN) emails to all 6 shortlisted vendors:
  - Shenzhen Electron Technology / ELC Sign
  - Shenzhen Mio Industrial / MIO-LCD
  - Shenzhen Raypodo Technology
  - AIYOS Technology Co., Ltd.
  - Shenzhen HDFocus Technology
  - Qbic Technology Co., Ltd. (Taiwan — English only)

Logs every outbound message to Firestore and sets vendor status → "sent".

Usage:
    python scripts/send_poe_display_rfq.py --dry   # preview without sending
    python scripts/send_poe_display_rfq.py          # live send
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
from src.slack_notifier import notify_rfq_dispatched, notify_new_response

SLACK_CHANNEL = "C0AC8GK12N6"  # #areda-mike

INQUIRY_ID = "RFQ-GO-2026-04-POE-DISPLAY"
SUBJECT = "RFQ: 10.1\" Android PoE+ Multi-Touch Signage Display — 12 pcs | GO Corporation Co., Ltd."
REPLY_TO = "shipping@goco.bz"
CC = ["shipping@goco.bz"]
DEADLINE = "6 May 2026"
DEADLINE_CN = "2026年5月6日"
TARGET_QTY = 12
WHATSAPP = "+66 61 491 6393"
WECHAT = "eukrit"

SIGNATURE = """\
<hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
<p style="font-size: 13px; color: #555; line-height: 1.7;">
<strong>Eukrit Kraikosol | เอกฤทธิ์ ไกรโกศล</strong><br>
GO Corporation Co., Ltd. | บริษัท จีโอ คอร์ปอเรชั่น จำกัด<br>
Email: eukrit@goco.bz &nbsp;|&nbsp; Reply-To: shipping@goco.bz<br>
WhatsApp: <strong>+66 61 491 6393</strong> &nbsp;|&nbsp; WeChat ID: <strong>eukrit</strong><br>
11/2 P23 Tower, Unit 8A, Sukhumvit 23, Bangkok 10110, Thailand
</p>"""


def build_body_bilingual(vendor_name: str) -> str:
    return f"""\
<div style="font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif; font-size: 14px; line-height: 1.9; color: #222;">

<p>Dear {vendor_name},</p>

<p>
GO Corporation Co., Ltd. is a Thailand-based procurement and project delivery company.<br>
We are sourcing <strong>{TARGET_QTY} units</strong> of a
<strong>10.1&quot; Android PoE+ capacitive multi-touch wall-mount display</strong>
to replace the discontinued Philips Signage Solutions 10BDL3051T/00
(successor model: 10BDL4551T/00).
</p>

<p>We found your product to be a strong match for our requirements.
Please provide a formal quotation for your equivalent 10&quot; PoE touch display model.</p>

<p><strong>Minimum required specification:</strong></p>
<ul>
  <li>Screen: 10.1&quot;, IPS, &ge;1280&times;800, &ge;250 nits</li>
  <li>Touch: Projected capacitive (PCAP), &ge;5-point multi-touch</li>
  <li>Power: IEEE 802.3at PoE+ (single RJ45 cable for power + data)</li>
  <li>OS: Android 8.1 or newer</li>
  <li>Wireless: WiFi, Bluetooth</li>
  <li>Wall-mount bracket included</li>
  <li>Certifications: CE + FCC + RoHS (minimum)</li>
</ul>

<p><strong>Please quote the following for your closest matching model(s):</strong></p>
<ul>
  <li>Unit price FOB Shenzhen and DDP Bangkok, in USD</li>
  <li>MOQ and price at {TARGET_QTY} pcs</li>
  <li>Lead time from deposit to delivery in Bangkok</li>
  <li>Warranty: period and scope</li>
  <li>Payment terms (we propose 30% deposit / 70% against B/L)</li>
  <li>Full technical datasheet</li>
  <li>Certifications in hand (CE, FCC, RoHS — list any additional)</li>
  <li>Sample unit availability and sample pricing</li>
  <li>Android MDM / CMS compatibility (Android Enterprise DPC, third-party MDM, or vendor CMS?)</li>
</ul>

<p>
Kindly submit your quotation by <strong>{DEADLINE}</strong> by replying to this email.
Please keep <strong>shipping@goco.bz</strong> on all replies.
</p>

<p>
For questions, please reach me on:<br>
&bull; WhatsApp: <strong>{WHATSAPP}</strong><br>
&bull; WeChat ID: <strong>{WECHAT}</strong><br>
&bull; Email: eukrit@goco.bz
</p>

<p>We look forward to your response.</p>

<hr style="border: none; border-top: 1px solid #eee; margin: 28px 0;">

<p style="color: #888; font-size: 13px;">——— 中文版 / Chinese Version ———</p>

<p>您好，{vendor_name}，</p>

<p>
GO Corporation Co., Ltd.（บริษัท จีโอ คอร์ปอเรชั่น จำกัด）是一家总部位于泰国曼谷的采购与项目执行公司。<br>
我们正在采购 <strong>{TARGET_QTY} 台</strong> 10.1英寸 Android PoE+ 电容触控壁挂式显示屏，
用于替换已停产的飞利浦 Signage Solutions 10BDL3051T/00（后续型号：10BDL4551T/00）。
</p>

<p>我们认为贵司产品与我们的需求高度匹配，诚邀您提供正式报价。</p>

<p><strong>基本规格要求：</strong></p>
<ul>
  <li>屏幕：10.1英寸 IPS，分辨率 ≥1280×800，亮度 ≥250 nits</li>
  <li>触摸：投射式电容（PCAP），≥5点同时触控</li>
  <li>供电：IEEE 802.3at PoE+（单网线同时传输电力和数据）</li>
  <li>系统：Android 8.1 或更新版本</li>
  <li>无线：WiFi、蓝牙</li>
  <li>含壁挂支架</li>
  <li>认证：CE + FCC + RoHS（最低要求）</li>
</ul>

<p><strong>请针对您最接近的对应型号，提供以下报价信息：</strong></p>
<ul>
  <li>含税出厂价（FOB 深圳）及 DDP 曼谷到门价，单位：美元</li>
  <li>最小起订量（MOQ）及 {TARGET_QTY} 台的批量价格</li>
  <li>从支付定金到货抵曼谷的交期</li>
  <li>质保期及质保范围</li>
  <li>付款条件（建议：30% 定金 / 70% 见提单）</li>
  <li>完整产品技术规格书</li>
  <li>已取得的认证（CE、FCC、RoHS，以及其他认证）</li>
  <li>样机供货情况及样机价格</li>
  <li>设备管理（MDM）兼容性：支持 Android Enterprise DPC、第三方 MDM 还是厂商自带 CMS？</li>
</ul>

<p>
请于 <strong>{DEADLINE_CN}</strong> 前回复本邮件。
请将 <strong>shipping@goco.bz</strong> 保留在所有回复的收件人列表中。
</p>

<p>
如有问题，欢迎通过以下方式联系我：<br>
&bull; WhatsApp：<strong>{WHATSAPP}</strong><br>
&bull; 微信（WeChat）：<strong>{WECHAT}</strong><br>
&bull; 邮箱：eukrit@goco.bz
</p>

<p>期待贵司回复，谢谢！</p>

{SIGNATURE}
</div>"""


def build_body_english_only(vendor_name: str) -> str:
    return f"""\
<div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; line-height: 1.9; color: #222;">

<p>Dear {vendor_name},</p>

<p>
GO Corporation Co., Ltd. is a Thailand-based procurement and project delivery company.<br>
We are sourcing <strong>{TARGET_QTY} units</strong> of a
<strong>10.1&quot; Android PoE+ capacitive multi-touch wall-mount display</strong>
to replace the discontinued Philips Signage Solutions 10BDL3051T/00
(successor model: 10BDL4551T/00).
</p>

<p>We came across the <strong>TD-1060 Slim</strong> on your website and believe it is a strong
match for our requirements. Please provide a formal quotation.</p>

<p><strong>Minimum required specification (for reference — your TD-1060 Slim already meets or
exceeds most of these):</strong></p>
<ul>
  <li>Screen: 10.1&quot;, IPS, &ge;1280&times;800, &ge;250 nits</li>
  <li>Touch: Projected capacitive (PCAP), &ge;5-point multi-touch</li>
  <li>Power: IEEE 802.3at PoE+ (single RJ45 cable for power + data)</li>
  <li>OS: Android 8.1 or newer</li>
  <li>Wireless: WiFi, Bluetooth</li>
  <li>Wall-mount bracket included</li>
  <li>Certifications: CE + FCC + RoHS (minimum)</li>
</ul>

<p><strong>Please provide the following for the TD-1060 Slim (and any comparable models you
recommend):</strong></p>
<ul>
  <li>Unit price delivered DDP Bangkok, Thailand (in USD)</li>
  <li>MOQ and price break at {TARGET_QTY} pcs</li>
  <li>Lead time from order to delivery in Bangkok</li>
  <li>Warranty: period and scope</li>
  <li>Payment terms (we propose 30% deposit / 70% against B/L)</li>
  <li>Full technical datasheet (if not on website)</li>
  <li>Certifications in hand (CE, FCC, RoHS — list any additional)</li>
  <li>Sample unit availability and pricing</li>
  <li>Android MDM / CMS compatibility (Android Enterprise DPC, SOTI, or other MDM?)</li>
  <li>Any Thailand / Southeast Asia reseller or distributor we should know of</li>
</ul>

<p>
Kindly submit your quotation by <strong>{DEADLINE}</strong> by replying to this email.
Please keep <strong>shipping@goco.bz</strong> on all replies.
</p>

<p>
For questions, please reach me on:<br>
&bull; WhatsApp: <strong>{WHATSAPP}</strong><br>
&bull; WeChat ID: <strong>{WECHAT}</strong><br>
&bull; Email: eukrit@goco.bz
</p>

<p>We look forward to hearing from you.</p>

{SIGNATURE}
</div>"""


ENGLISH_ONLY_VENDORS = {"qbic-technology-co-ltd"}

VENDOR_OVERRIDES = {
    "qbic-technology-co-ltd": {
        "display_name": "Qbic Technology",
        "body_builder": "english_only",
    }
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="Preview, do not send")
    args = ap.parse_args()

    db = get_db()
    inquiry = get_inquiry(INQUIRY_ID, db=db)
    if not inquiry:
        print(f"ERROR: Inquiry {INQUIRY_ID} not found in Firestore.")
        print(f"  Run first: python scripts/seed_poe_display_rfq.py")
        sys.exit(1)

    vendors = get_inquiry_vendors(INQUIRY_ID, db=db)
    pending = [
        v for v in vendors
        if v.get("status") in ("pending", None, "") and v.get("contact_email")
    ]

    print(f"Inquiry:  {INQUIRY_ID}")
    print(f"Vendors:  {len(vendors)} total, {len(pending)} pending dispatch")
    print(f"Subject:  {SUBJECT}")
    print(f"Mode:     {'DRY RUN' if args.dry else '*** LIVE SEND ***'}")
    print("=" * 70)

    if not pending:
        print("No pending vendors to dispatch. All may already be sent.")
        sys.exit(0)

    service = None if args.dry else get_gmail_send_service()
    sent_count = 0

    for v in pending:
        vid = v["vendor_id"]
        email = v["contact_email"]
        company_en = v.get("company_en", "Sir/Madam")
        languages = v.get("languages", ["English", "Chinese"])

        override = VENDOR_OVERRIDES.get(vid, {})
        display_name = override.get("display_name") or company_en
        body_type = override.get("body_builder", "bilingual")

        if body_type == "english_only" or "Chinese" not in languages:
            body = build_body_english_only(display_name)
        else:
            body = build_body_bilingual(display_name)

        email_verified = v.get("email_verified", False)
        verified_label = "✓ verified" if email_verified else "⚠ inferred"

        if args.dry:
            lang_label = "EN only" if body_type == "english_only" else "Bilingual EN+CN"
            print(f"[DRY] {vid:50s}")
            print(f"      To: {email}  ({verified_label})  [{lang_label}]")
            print()
            continue

        result = send_email(
            to=email,
            subject=SUBJECT,
            body_html=body,
            reply_to=REPLY_TO,
            cc=CC,
            service=service,
        )

        log_message(INQUIRY_ID, vid, {
            "direction": "outbound",
            "type": "rfq_initial",
            "subject": SUBJECT,
            "sender": "eukrit@goco.bz",
            "recipients": [email],
            "cc": CC,
            "message_id": result.get("message_id"),
            "thread_id": result.get("thread_id"),
            "email_verified": email_verified,
        }, db=db)

        update_vendor_status(INQUIRY_ID, vid, "sent",
                             note="Initial RFQ dispatched", db=db)

        notify_new_response(
            inquiry_id=INQUIRY_ID,
            vendor_id=vid,
            vendor_name=display_name,
            intent="rfq_sent",
            summary=f":outbox_tray: RFQ sent to {display_name} <{email}> — deadline {DEADLINE}",
            confidence=1.0,
            channel=SLACK_CHANNEL,
        )

        print(f"  SENT  {vid:50s} -> {email}  ({verified_label})")
        sent_count += 1

    print()
    print("=" * 70)
    if args.dry:
        print(f"  DRY RUN COMPLETE — {len(pending)} emails previewed, nothing sent.")
    else:
        print(f"  DISPATCHED: {sent_count}/{len(pending)} RFQ emails sent.")
        print(f"  Reply-To: {REPLY_TO}")
        print(f"  Deadline communicated to vendors: {DEADLINE}")
        vendor_details = [
            {"status": "sent", "vendor_id": v["vendor_id"], "to": v.get("contact_email", "")}
            for v in pending
            if v.get("status") == "sent" or True
        ]
        notify_rfq_dispatched(
            inquiry_id=INQUIRY_ID,
            inquiry_title=f"10.1\" Android PoE+ Multi-Touch Display — {TARGET_QTY} pcs",
            sent=sent_count,
            skipped=len(pending) - sent_count,
            errors=0,
            vendor_details=vendor_details[:sent_count],
            channel=SLACK_CHANNEL,
        )
        print(f"  Slack notification sent to #areda-mike")
    print("=" * 70)


if __name__ == "__main__":
    main()
