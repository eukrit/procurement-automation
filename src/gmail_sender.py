"""
gmail_sender.py — Gmail send client for procurement automation.

Uses domain-wide delegation via service account to send as eukrit@goco.bz.
Supports: RFQ dispatch, auto-replies in thread, reminders, and generic email.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────

GCP_PROJECT = os.environ.get("GCP_PROJECT", "ai-agents-go")
IMPERSONATE_USER = os.environ.get("IMPERSONATE_USER", "eukrit@goco.bz")

# Service account key — local dev uses file, Cloud Functions uses default creds
SA_KEY_FILE = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "ai-agents-go-4c81b70995db.json",
    ),
)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

# Project root for resolving attachment paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── Gmail Service ─────────────────────────────────────────────


def get_gmail_send_service(impersonate_user: str | None = None):
    """Build Gmail API service with domain-wide delegation.

    Args:
        impersonate_user: Email to impersonate. Defaults to IMPERSONATE_USER env var.

    Returns:
        Gmail API service resource.
    """
    user = impersonate_user or IMPERSONATE_USER

    if os.path.exists(SA_KEY_FILE):
        credentials = service_account.Credentials.from_service_account_file(
            SA_KEY_FILE, scopes=GMAIL_SCOPES
        )
    else:
        # On Cloud Functions, use default credentials
        import google.auth

        credentials, _ = google.auth.default(scopes=GMAIL_SCOPES)

    delegated = credentials.with_subject(user)
    return build("gmail", "v1", credentials=delegated, cache_discovery=False)


# ── Core Send ─────────────────────────────────────────────────


def send_email(
    to: str | list[str],
    subject: str,
    body_html: str,
    reply_to: str | None = None,
    cc: str | list[str] | None = None,
    attachments: list[str] | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    thread_id: str | None = None,
    service=None,
) -> dict:
    """Send an email via Gmail API.

    Args:
        to: Recipient email(s).
        subject: Email subject line.
        body_html: HTML body content.
        reply_to: Reply-To header address.
        cc: CC recipient(s).
        attachments: List of file paths to attach.
        in_reply_to: Message-ID to reply to (for threading).
        references: References header (for threading).
        thread_id: Gmail thread ID to place message in.
        service: Pre-built Gmail service (optional).

    Returns:
        dict with 'message_id', 'thread_id', 'label_ids'.
    """
    service = service or get_gmail_send_service()

    # Normalize recipients
    if isinstance(to, str):
        to = [to]
    if isinstance(cc, str):
        cc = [cc]

    # Build message
    if attachments:
        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        for filepath in attachments:
            _attach_file(msg, filepath)
    else:
        msg = MIMEText(body_html, "html", "utf-8")

    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["From"] = IMPERSONATE_USER

    if reply_to:
        msg["Reply-To"] = reply_to
    if cc:
        msg["Cc"] = ", ".join(cc)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    # Encode
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    body: dict = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id

    # Send
    result = service.users().messages().send(userId="me", body=body).execute()

    logger.info(
        "Email sent: to=%s subject=%s message_id=%s thread_id=%s",
        to,
        subject,
        result.get("id"),
        result.get("threadId"),
    )

    return {
        "message_id": result.get("id"),
        "thread_id": result.get("threadId"),
        "label_ids": result.get("labelIds", []),
    }


def _attach_file(msg: MIMEMultipart, filepath: str) -> None:
    """Attach a file to a MIME message."""
    path = Path(filepath)
    if not path.is_absolute():
        path = PROJECT_ROOT / path

    if not path.exists():
        raise FileNotFoundError(f"Attachment not found: {path}")

    content_type, _ = mimetypes.guess_type(str(path))
    if content_type is None:
        content_type = "application/octet-stream"
    main_type, sub_type = content_type.split("/", 1)

    with open(path, "rb") as f:
        attachment = MIMEBase(main_type, sub_type)
        attachment.set_payload(f.read())
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition", "attachment", filename=path.name
    )
    msg.attach(attachment)


# ── RFQ Dispatch ──────────────────────────────────────────────


_SIGNATURE_HTML = """\
<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">

<p style="font-size: 13px; color: #666;">
<strong>Eukrit Kraikosol | 尤克里</strong><br>
GO Corporation Co., Ltd.<br>
Email: eukrit@goco.bz | Reply-To: shipping@goco.bz<br>
WeChat: eukrit | Tel: +66 61 491 6393<br>
11/2 P23 Tower, Unit 8A, Sukhumvit 23, Bangkok 10110, Thailand
</p>
"""


def _paragraphs_to_html(text: str) -> str:
    """Convert plain text with blank-line paragraph breaks to <p> tags."""
    chunks = [chunk.strip() for chunk in text.split("\n\n") if chunk.strip()]
    return "\n".join(
        f"<p>{chunk.replace(chr(10), '<br>')}</p>" for chunk in chunks
    )


def build_rfq_email_body(
    inquiry: dict,
    vendor: dict,
    template: dict | None = None,
) -> str:
    """Build bilingual HTML email body for RFQ dispatch.

    If `template` has `email_template.body_cn` / `body_en`, renders from
    those (with `{vendor_name}`, `{deadline}`, `{title}` substitutions).
    Otherwise falls back to the default freight RFQ body.
    """
    deadline = inquiry.get("response_deadline", "TBD")
    vendor_name = vendor.get("company_en", "Sir/Madam")
    title = inquiry.get("title", "RFQ")

    email_template = (template or {}).get("email_template") or {}
    body_cn_src = email_template.get("body_cn")
    body_en_src = email_template.get("body_en")

    if body_cn_src and body_en_src:
        substitutions = {
            "vendor_name": vendor_name,
            "deadline": deadline,
            "title": title,
        }
        body_cn = body_cn_src.format(**substitutions)
        body_en = body_en_src.format(**substitutions)
        return f"""\
<div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #333;">

{_paragraphs_to_html(body_cn)}

<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">

{_paragraphs_to_html(body_en)}

{_SIGNATURE_HTML}
</div>"""

    html = f"""\
<div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #333;">

<p>您好，</p>

<p>GO Corporation Co., Ltd.（บริษัท จีโอ คอร์ปอเรชั่น จำกัด）是泰国一家专注于
酒店、商业及住宅室内装修项目的设计和采购公司。我们从中国74家供应商处采购家具、
灯具、游乐设备及建筑材料，年运输量约200-400立方米。</p>

<p>我们目前正在寻找新的中国至曼谷物流合作伙伴。随函附上我们的询价书（RFQ），
涵盖海运拼箱/整箱、陆运、门到门及EXW条款的报价要求。</p>

<p>请在<strong>{deadline}</strong>前回复此邮件提供报价。如有任何问题，欢迎通过以下方式联系。</p>

<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">

<p>Dear {vendor_name},</p>

<p>GO Corporation Co., Ltd. is a Thai-based procurement and project delivery company.
We import furniture, lighting, playground equipment, and construction materials from
74 vendors across China (primarily Guangdong, Zhejiang, and central China).</p>

<p>Please find attached our Request for Quotation (RFQ) for China to Bangkok freight
forwarding services covering sea LCL/FCL, land transport, door-to-door and EXW terms.</p>

<p>Kindly submit your quotation by <strong>{deadline}</strong> by replying to this email.</p>

{_SIGNATURE_HTML}
</div>"""
    return html


def send_rfq_to_vendor(
    inquiry: dict,
    vendor: dict,
    service=None,
    dry_run: bool = False,
    template: dict | None = None,
) -> dict:
    """Send RFQ email to a single vendor.

    Args:
        inquiry: Inquiry document from Firestore.
        vendor: Vendor document from Firestore.
        service: Pre-built Gmail service (optional).
        dry_run: If True, build the email but don't send it.
        template: Optional template dict (from procurement_templates). If
            provided and it contains email_template.body_cn/body_en, the
            RFQ body is rendered from the template; otherwise the default
            freight body is used.

    Returns:
        dict with send result or dry_run preview.
    """
    send_config = inquiry.get("send_config", {})
    vendor_email = vendor.get("contact_email")

    if not vendor_email:
        logger.warning(
            "Vendor %s has no contact_email — skipping",
            vendor.get("vendor_id"),
        )
        return {"skipped": True, "reason": "no_contact_email"}

    # Subject
    subject_template = send_config.get(
        "subject_template", "RFQ: {title} | GO Corporation Co., Ltd."
    )
    subject = subject_template.format(
        title=inquiry.get("title", "RFQ"),
    )

    # Body
    body_html = build_rfq_email_body(inquiry, vendor, template=template)

    # Attachments
    attachments = []
    if send_config.get("attach_pdf"):
        pdf_path = inquiry.get("rfq_document", {}).get("pdf_path")
        if pdf_path:
            attachments.append(pdf_path)

    # CC and Reply-To
    reply_to = send_config.get("reply_to")
    cc = send_config.get("cc")

    if dry_run:
        return {
            "dry_run": True,
            "to": vendor_email,
            "subject": subject,
            "reply_to": reply_to,
            "cc": cc,
            "attachments": attachments,
            "body_preview": body_html[:500],
        }

    result = send_email(
        to=vendor_email,
        subject=subject,
        body_html=body_html,
        reply_to=reply_to,
        cc=cc,
        attachments=attachments,
        service=service,
    )

    logger.info(
        "RFQ sent to %s (%s) — message_id=%s",
        vendor.get("vendor_id"),
        vendor_email,
        result.get("message_id"),
    )

    return result


# ── Auto-Reply ────────────────────────────────────────────────


def send_auto_reply(
    vendor: dict,
    subject: str,
    body_html: str,
    thread_id: str,
    in_reply_to: str | None = None,
    service=None,
) -> dict:
    """Send an auto-reply in an existing email thread.

    Args:
        vendor: Vendor document.
        subject: Reply subject (usually "Re: ...").
        body_html: HTML body of the reply.
        thread_id: Gmail thread ID to reply in.
        in_reply_to: Message-ID of the message being replied to.
        service: Pre-built Gmail service (optional).

    Returns:
        Send result dict.
    """
    vendor_email = vendor.get("contact_email")
    if not vendor_email:
        return {"skipped": True, "reason": "no_contact_email"}

    return send_email(
        to=vendor_email,
        subject=subject,
        body_html=body_html,
        reply_to="shipping@goco.bz",
        cc=["shipping@goco.bz"],
        in_reply_to=in_reply_to,
        references=in_reply_to,
        thread_id=thread_id,
        service=service,
    )


# ── Reminders ─────────────────────────────────────────────────


def send_reminder(
    vendor: dict,
    inquiry: dict,
    reminder_number: int,
    service=None,
) -> dict:
    """Send a follow-up reminder to a vendor.

    Args:
        vendor: Vendor document.
        inquiry: Inquiry document.
        reminder_number: 1 or 2 (affects tone).
        service: Pre-built Gmail service (optional).

    Returns:
        Send result dict.
    """
    vendor_email = vendor.get("contact_email")
    if not vendor_email:
        return {"skipped": True, "reason": "no_contact_email"}

    vendor_name = vendor.get("company_en", "Sir/Madam")
    deadline = inquiry.get("response_deadline", "TBD")
    thread_id = vendor.get("email_tracking", {}).get("thread_id")

    if reminder_number == 1:
        subject = f"Friendly Reminder: RFQ — {inquiry.get('title', 'RFQ')} | GO Corporation"
        body_html = f"""\
<div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #333;">
<p>您好，</p>
<p>此为友好提醒。我们之前发送的关于中国至曼谷货运代理服务的询价函（RFQ），
截止日期为 <strong>{deadline}</strong>。如您已回复，请忽略此消息。</p>
<p>如有任何疑问，欢迎直接回复此邮件。</p>
<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
<p>Dear {vendor_name},</p>
<p>This is a gentle reminder about our RFQ for China to Bangkok freight forwarding services.
The deadline for submission is <strong>{deadline}</strong>.</p>
<p>If you have already responded, please disregard this message.
Should you have any questions, feel free to reply to this email.</p>
<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
<p style="font-size: 13px; color: #666;">
<strong>Eukrit Kraikosol | 尤克里</strong><br>
GO Corporation Co., Ltd.<br>
Email: eukrit@goco.bz | Reply-To: shipping@goco.bz<br>
WeChat: eukrit | Tel: +66 61 491 6393
</p>
</div>"""
    else:
        subject = f"2nd Reminder: RFQ — {inquiry.get('title', 'RFQ')} | GO Corporation"
        body_html = f"""\
<div style="font-family: 'Segoe UI', Arial, sans-serif; font-size: 14px; line-height: 1.8; color: #333;">
<p>您好，</p>
<p>这是我们关于中国至曼谷货运代理的第二次提醒。截止日期为 <strong>{deadline}</strong>。</p>
<p>如果您更方便使用微信沟通，我的微信号是：<strong>eukrit</strong>。
也可以通过WhatsApp联系：+66 61 491 6393。</p>
<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
<p>Dear {vendor_name},</p>
<p>This is our second reminder regarding the RFQ for China-Bangkok freight services.
The deadline is <strong>{deadline}</strong>.</p>
<p>If you prefer to communicate via WeChat, my ID is: <strong>eukrit</strong>.
You can also reach me on WhatsApp: +66 61 491 6393.</p>
<hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
<p style="font-size: 13px; color: #666;">
<strong>Eukrit Kraikosol | 尤克里</strong><br>
GO Corporation Co., Ltd.<br>
Email: eukrit@goco.bz | Reply-To: shipping@goco.bz<br>
WeChat: eukrit | Tel: +66 61 491 6393
</p>
</div>"""

    # Get last message_id for threading
    last_msg_ids = vendor.get("email_tracking", {}).get("message_ids", [])
    in_reply_to = last_msg_ids[-1] if last_msg_ids else None

    return send_email(
        to=vendor_email,
        subject=subject,
        body_html=body_html,
        reply_to="shipping@goco.bz",
        cc=["shipping@goco.bz"],
        in_reply_to=in_reply_to,
        thread_id=thread_id,
        service=service,
    )
