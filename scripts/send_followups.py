#!/usr/bin/env python3
"""Send overdue follow-ups: reminders to silent vendors, replies to questions."""

from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.rfq_store import (
    get_db, get_inquiry, get_vendor, get_inquiry_vendors,
    log_message, update_vendor_status,
)
from src.gmail_sender import send_email, get_gmail_send_service

INQUIRY_ID = "RFQ-GO-2026-04-FREIGHT"
NEW_DEADLINE = "26 April 2026"
REPLY_TO = "shipping@goco.bz"
CC = ["shipping@goco.bz"]

SIGNATURE = """\
<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
<p style="font-size: 13px; color: #666;">
<strong>Eukrit Kraikosol | 尤克里</strong><br>
GO Corporation Co., Ltd.<br>
Email: eukrit@goco.bz | Reply-To: shipping@goco.bz<br>
WeChat: eukrit | Tel: +66 61 491 6393<br>
11/2 P23 Tower, Unit 8A, Sukhumvit 23, Bangkok 10110, Thailand
</p>"""


def send_and_log(vendor_id, to, subject, body_html, db, service, msg_type="reminder"):
    result = send_email(
        to=to, subject=subject, body_html=body_html,
        reply_to=REPLY_TO, cc=CC, service=service,
    )
    log_message(INQUIRY_ID, vendor_id, {
        "direction": "outbound", "type": msg_type,
        "subject": subject, "sender": "eukrit@goco.bz",
        "recipients": [to],
        "message_id": result.get("message_id"),
        "thread_id": result.get("thread_id"),
    }, db=db)
    return result


def main():
    db = get_db()
    inquiry = get_inquiry(INQUIRY_ID, db=db)
    service = get_gmail_send_service()
    vendors = get_inquiry_vendors(INQUIRY_ID, db=db)

    # === 1. Reminder to silent vendors (status=sent, no reply for 11 days) ===
    silent_vendors = [
        v for v in vendors
        if v.get("status") == "sent" and v.get("contact_email")
    ]

    print(f"=== REMINDERS TO SILENT VENDORS ({len(silent_vendors)}) ===")
    for v in silent_vendors:
        vid = v["vendor_id"]
        email = v["contact_email"]
        name = v.get("company_en", "Sir/Madam")

        subject = f"Follow-up: RFQ China to Bangkok Freight | GO Corporation Co., Ltd."
        body = f"""\
<div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #333;">

<p>您好，</p>

<p>我们于4月6日发送了关于中国至曼谷货运代理服务的询价函（RFQ）。
由于我们方面的沟通延迟，我们已将截止日期延长至 <strong>{NEW_DEADLINE}</strong>。</p>

<p>如您有意参与报价，请回复此邮件。如有任何问题，欢迎随时联系。</p>

<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">

<p>Dear {name},</p>

<p>We sent you our RFQ for China to Bangkok freight forwarding services on April 6th.
Due to a delay on our end in following up, we have extended the deadline to
<strong>{NEW_DEADLINE}</strong>.</p>

<p>If you are interested in quoting, please reply to this email. We would appreciate
your rates for sea LCL, land transport, and door-to-door services from
Guangdong (Guangzhou/Foshan/Shenzhen) to Bangkok.</p>

<p>Please don't hesitate to reach out if you have any questions.</p>

{SIGNATURE}
</div>"""

        result = send_and_log(vid, email, subject, body, db, service, "reminder")
        update_vendor_status(INQUIRY_ID, vid, "reminder_1", note="Follow-up sent (extended deadline)", db=db)
        # Update reminder count
        db.collection("rfq_inquiries").document(INQUIRY_ID).collection("vendors").document(vid).update({
            "reminders.count": 1,
        })
        print(f"  SENT  {vid:35s} -> {email}")

    # === 2. Reply to STU Supply Chain (question about dimensions) ===
    print()
    print("=== REPLY TO STU SUPPLY CHAIN ===")
    stu = get_vendor(INQUIRY_ID, "stu-supply-chain", db=db)
    if stu and stu.get("status") == "question_received":
        subject = f"Re: RFQ: China to Bangkok Freight Forwarding | GO Corporation Co., Ltd."
        body = f"""\
<div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #333;">

<p>您好 Maggie，</p>

<p>感谢您的回复。关于尺寸问题的说明：</p>

<p>285×30×280cm 是我们在询价书中作为示例产品列出的铝合金折叠门（ED 70）的尺寸。
这只是一个示例，用于基准成本计算，并不代表我们所有的货物都是这个尺寸。</p>

<p>我们的实际货物种类包括：家具、灯具、游乐设备和建筑材料。
典型单件货物尺寸在1-3立方米之间。年运输总量约200-400立方米，分30-50个订单。</p>

<p>我们主要需要您提供以下报价：<br>
- 海运拼箱 (LCL) 和陆运的立方米单价<br>
- 运输时间<br>
- 付款条件</p>

<p>截止日期已延长至 <strong>{NEW_DEADLINE}</strong>。期待您的报价。</p>

<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">

<p>Dear Maggie,</p>

<p>Thank you for your reply. Regarding the dimension question:</p>

<p>The 285×30×280cm is the dimension of an ED 70 Aluminum Folding Door, which was
listed in our RFQ as a sample product for cost benchmarking. It does not represent
all our cargo — our shipments include furniture, lighting, playground equipment,
and construction materials with typical per-item sizes of 1-3 CBM.</p>

<p>Our annual volume is approximately 200-400 CBM across 30-50 purchase orders,
primarily from Guangdong (Guangzhou, Foshan, Shenzhen).</p>

<p>We would appreciate your quotation for:<br>
- Sea LCL and land transport rates per CBM<br>
- Transit times<br>
- Payment terms</p>

<p>The deadline has been extended to <strong>{NEW_DEADLINE}</strong>.</p>

{SIGNATURE}
</div>"""

        result = send_and_log("stu-supply-chain", "maggie@stusupplychain.com", subject, body, db, service, "auto_reply")
        update_vendor_status(INQUIRY_ID, "stu-supply-chain", "awaiting_response", note="Answered dimension question, requested rates", db=db)
        print(f"  SENT  stu-supply-chain -> maggie@stusupplychain.com")

    # === 3. Reply to SDI Logistics (DDU/DDP question) ===
    print()
    print("=== REPLY TO SDI LOGISTICS ===")
    sdi = get_vendor(INQUIRY_ID, "sdi-logistics", db=db)
    if sdi and sdi.get("status") == "question_received":
        subject = f"Re: RFQ: China to Bangkok Freight Forwarding | GO Corporation Co., Ltd."
        body = f"""\
<div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #333;">

<p>您好 Lucy，</p>

<p>感谢您的回复。以下是您所需的信息：</p>

<p><strong>运输方式偏好：</strong>我们对 DDP（含税到门）和 DDU 都持开放态度。
请提供您最具竞争力的方案。如果您能同时提供 DDP 和 DDU 的报价供我们比较，那就更好了。</p>

<p><strong>货物信息：</strong><br>
- 货物类型：家具、灯具、游乐设备、建筑材料（铝门窗、钢结构）<br>
- 年运输量：200-400立方米，分30-50个订单<br>
- 单次运输量：通常5-15立方米<br>
- 贸易条款：工厂交货 (EXW)<br>
- 产地：广东省（广州、佛山、深圳）</p>

<p>截止日期已延长至 <strong>{NEW_DEADLINE}</strong>。</p>

<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">

<p>Dear Lucy,</p>

<p>Thank you for your response. Here is the information you requested:</p>

<p><strong>Shipping method:</strong> We are open to both DDP and DDU. Please provide
your most competitive option. If you can quote both DDP and DDU for comparison,
that would be ideal.</p>

<p><strong>Cargo information:</strong><br>
- Products: Furniture, lighting, playground equipment, construction materials
  (aluminum doors/windows, steel structures)<br>
- Annual volume: 200-400 CBM across 30-50 purchase orders<br>
- Per-shipment: Typically 5-15 CBM<br>
- Trade term: EXW from factory<br>
- Origin: Guangdong province (Guangzhou, Foshan, Shenzhen)<br>
- HS codes: 9403 (furniture), 7610 (aluminum), 9405 (lighting), 7308 (steel)</p>

<p>Deadline extended to <strong>{NEW_DEADLINE}</strong>.</p>

{SIGNATURE}
</div>"""

        result = send_and_log("sdi-logistics", "lucy@sdilogistics.com", subject, body, db, service, "auto_reply")
        update_vendor_status(INQUIRY_ID, "sdi-logistics", "awaiting_response", note="Answered DDU/DDP and cargo info questions", db=db)
        print(f"  SENT  sdi-logistics -> lucy@sdilogistics.com")

    # === 4. Nudge DFH Global (Joya was supposed to follow up) ===
    print()
    print("=== NUDGE DFH GLOBAL ===")
    dfh = get_vendor(INQUIRY_ID, "dfh-global-logistics", db=db)
    if dfh:
        subject = f"Follow-up: RFQ China to Bangkok Freight | GO Corporation Co., Ltd."
        body = f"""\
<div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #333;">

<p>您好，</p>

<p>感谢您之前回复说会安排服务经理 Joya 与我们联系。想跟进一下我们的询价进展。</p>

<p>截止日期已延长至 <strong>{NEW_DEADLINE}</strong>。期待收到您的报价。</p>

<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">

<p>Dear DFH Logistics Team,</p>

<p>Thank you for your earlier reply indicating that your service manager Joya would
follow up with us. We wanted to check on the status of our RFQ for China to
Bangkok freight forwarding services.</p>

<p>The deadline has been extended to <strong>{NEW_DEADLINE}</strong>.
We look forward to receiving your quotation.</p>

{SIGNATURE}
</div>"""

        result = send_and_log("dfh-global-logistics", "info@dfhfreight.com", subject, body, db, service, "follow_up")
        update_vendor_status(INQUIRY_ID, "dfh-global-logistics", "reminder_1", note="Follow-up on Joya's promised quote", db=db)
        print(f"  SENT  dfh-global-logistics -> info@dfhfreight.com")

    # Summary
    print()
    print("=" * 60)
    total = len(silent_vendors) + 3  # + STU + SDI + DFH
    print(f"DONE. {total} emails sent. Deadline: {NEW_DEADLINE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
