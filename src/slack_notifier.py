"""
slack_notifier.py — Slack notifications for procurement automation.

Sends structured notifications to #shipment-notifications (C08VD9PRSCU).
All messages prefixed with [Procurement] to distinguish from shipping-automation.
"""

from __future__ import annotations

import logging
import os

from google.cloud import secretmanager
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────

GCP_PROJECT = os.environ.get("GCP_PROJECT", "ai-agents-go")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "C08VD9PRSCU")
SOURCE_TAG = "Procurement"

_slack_client = None


def _get_slack_token() -> str:
    """Get Slack bot token from Secret Manager or env var."""
    token = os.environ.get("SLACK_BOT_TOKEN")
    if token:
        return token
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{GCP_PROJECT}/secrets/SLACK_BOT_TOKEN/versions/latest"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8").strip()
    except Exception as e:
        logger.error("Failed to get Slack token: %s", e)
        raise


def get_slack_client() -> WebClient:
    """Get or create a Slack WebClient."""
    global _slack_client
    if _slack_client is None:
        _slack_client = WebClient(token=_get_slack_token())
    return _slack_client


def _post_message(
    text: str,
    blocks: list[dict] | None = None,
    channel: str | None = None,
    client: WebClient | None = None,
) -> dict | None:
    """Post a message to Slack. Returns response or None on error."""
    client = client or get_slack_client()
    channel = channel or SLACK_CHANNEL
    try:
        response = client.chat_postMessage(
            channel=channel,
            text=f"[{SOURCE_TAG}] {text}",
            blocks=blocks,
        )
        return response.data
    except SlackApiError as e:
        logger.error("Slack error: %s", e.response["error"])
        return None
    except Exception as e:
        logger.error("Slack send failed: %s", e)
        return None


def _divider() -> dict:
    return {"type": "divider"}


def _context(text: str) -> dict:
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": text}],
    }


# ── Notification Types ────────────────────────────────────────


def notify_rfq_dispatched(
    inquiry_id: str,
    inquiry_title: str,
    sent: int,
    skipped: int,
    errors: int,
    vendor_details: list[dict] | None = None,
    channel: str | None = None,
    client: WebClient | None = None,
) -> dict | None:
    """Notify that RFQ emails were dispatched to vendors."""
    vendor_lines = ""
    if vendor_details:
        for v in vendor_details[:15]:
            status_icon = {"sent": ":white_check_mark:", "skipped": ":fast_forward:", "error": ":x:"}.get(v.get("status"), ":grey_question:")
            vendor_lines += f"\n{status_icon} {v.get('vendor_id', '')} — {v.get('to', v.get('reason', ''))}"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":outbox_tray: [{SOURCE_TAG}] RFQ Dispatched"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Inquiry:*\n`{inquiry_id}`"},
                {"type": "mrkdwn", "text": f"*Title:*\n{inquiry_title}"},
                {"type": "mrkdwn", "text": f"*Sent:* {sent}  |  *Skipped:* {skipped}  |  *Errors:* {errors}"},
            ],
        },
    ]
    if vendor_lines:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Vendors:*{vendor_lines}"},
        })
    blocks.append(_context(f"{SOURCE_TAG} Automation"))

    return _post_message(
        text=f"RFQ dispatched: {sent} sent, {skipped} skipped — {inquiry_id}",
        blocks=blocks,
        channel=channel,
        client=client,
    )


def notify_new_response(
    inquiry_id: str,
    vendor_id: str,
    vendor_name: str,
    intent: str,
    summary: str,
    confidence: float,
    has_rates: bool = False,
    channel: str | None = None,
    client: WebClient | None = None,
) -> dict | None:
    """Notify about a new vendor response."""
    emoji = {
        "rate_quote": ":chart_with_upwards_trend:",
        "question": ":speech_balloon:",
        "decline": ":no_entry_sign:",
        "partial_response": ":hourglass_flowing_sand:",
        "counter_offer": ":handshake:",
        "out_of_office": ":palm_tree:",
    }.get(intent, ":incoming_envelope:")

    intent_label = {
        "rate_quote": "Rate Quote",
        "question": "Question",
        "decline": "Declined",
        "partial_response": "Partial Response",
        "counter_offer": "Counter Offer",
        "out_of_office": "Out of Office",
    }.get(intent, intent)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} [{SOURCE_TAG}] {intent_label} from {vendor_name}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Vendor:*\n{vendor_name}"},
                {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.0%}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f">{summary[:300]}"},
        },
    ]
    if has_rates:
        blocks.append(_context(":white_check_mark: Rate data extracted — use `compare_rates` to view"))
    blocks.append(_context(f"`{inquiry_id}` / `{vendor_id}` | {SOURCE_TAG} Automation"))

    return _post_message(
        text=f"[{SOURCE_TAG}] {intent_label} from {vendor_name}",
        blocks=blocks,
        channel=channel,
        client=client,
    )


def notify_escalation(
    inquiry_id: str,
    vendor_id: str,
    vendor_name: str,
    reason: str,
    vendor_contacts: dict | None = None,
    channel: str | None = None,
    client: WebClient | None = None,
) -> dict | None:
    """Notify about an escalation requiring human attention."""
    contacts = vendor_contacts or {}
    contact_parts = []
    if contacts.get("contact_email"):
        contact_parts.append(f":email: {contacts['contact_email']}")
    if contacts.get("contact_wechat"):
        contact_parts.append(f":speech_balloon: WeChat: {contacts['contact_wechat']}")
    if contacts.get("contact_whatsapp"):
        contact_parts.append(f":iphone: WhatsApp: {contacts['contact_whatsapp']}")
    if contacts.get("contact_phone"):
        contact_parts.append(f":telephone_receiver: {contacts['contact_phone']}")
    contact_text = "\n".join(contact_parts) if contact_parts else "_No contact info on file_"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":rotating_light: [{SOURCE_TAG}] Escalation — {vendor_name}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Reason:* {reason}"},
        },
        _divider(),
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Contact vendor directly:*\n{contact_text}"},
        },
        _context(f"`{inquiry_id}` / `{vendor_id}` | {SOURCE_TAG} Automation"),
    ]

    return _post_message(
        text=f"[{SOURCE_TAG}] Escalation: {vendor_name} — {reason}",
        blocks=blocks,
        channel=channel,
        client=client,
    )


def notify_auto_reply_sent(
    inquiry_id: str,
    vendor_id: str,
    vendor_name: str,
    confidence: float,
    answers: list[str] | None = None,
    channel: str | None = None,
    client: WebClient | None = None,
) -> dict | None:
    """Notify that an auto-reply was sent."""
    answers_text = "\n".join(f"  • {a}" for a in (answers or [])) or "  General response"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":robot_face: *[{SOURCE_TAG}] Auto-reply sent* to *{vendor_name}* ({confidence:.0%})\n"
                    f"{answers_text}"
                ),
            },
        },
        _context(f"`{inquiry_id}` / `{vendor_id}` | {SOURCE_TAG} Automation"),
    ]

    return _post_message(
        text=f"[{SOURCE_TAG}] Auto-reply sent to {vendor_name}",
        blocks=blocks,
        channel=channel,
        client=client,
    )


def notify_draft_for_approval(
    inquiry_id: str,
    vendor_id: str,
    vendor_name: str,
    draft_subject: str,
    draft_body_preview: str,
    confidence: float,
    channel: str | None = None,
    client: WebClient | None = None,
) -> dict | None:
    """Post a draft reply to Slack for human approval."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":pencil: [{SOURCE_TAG}] Draft Reply — Needs Approval"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Vendor:*\n{vendor_name}"},
                {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.0%}"},
            ],
        },
        _divider(),
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Subject:* {draft_subject}\n\n>{draft_body_preview[:400]}",
            },
        },
        _context(f"`{inquiry_id}` / `{vendor_id}` | Reply via MCP `approve_reply` tool | {SOURCE_TAG} Automation"),
    ]

    return _post_message(
        text=f"[{SOURCE_TAG}] Draft reply for {vendor_name} needs approval",
        blocks=blocks,
        channel=channel,
        client=client,
    )


def notify_rate_anomaly(
    inquiry_id: str,
    vendor_id: str,
    vendor_name: str,
    anomalies: list[str],
    channel: str | None = None,
    client: WebClient | None = None,
) -> dict | None:
    """Notify about rate anomalies vs baseline."""
    anomaly_text = "\n".join(f"  :small_red_triangle: {a}" for a in anomalies)

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":triangular_flag_on_post: *[{SOURCE_TAG}] Rate Anomaly — {vendor_name}*\n\n"
                    f"{anomaly_text}"
                ),
            },
        },
        _context(f"`{inquiry_id}` / `{vendor_id}` | vs Gift Somlak baseline | {SOURCE_TAG} Automation"),
    ]

    return _post_message(
        text=f"[{SOURCE_TAG}] Rate anomaly: {vendor_name}",
        blocks=blocks,
        channel=channel,
        client=client,
    )


def notify_reminder_summary(
    inquiry_id: str,
    summary: dict,
    channel: str | None = None,
    client: WebClient | None = None,
) -> dict | None:
    """Post daily reminder processing summary."""
    r1 = summary.get("reminder_1_sent", 0)
    r2 = summary.get("reminder_2_sent", 0)
    esc = summary.get("escalated", 0)
    closed = summary.get("closed", 0)
    total = r1 + r2 + esc + closed

    if total == 0:
        return None

    lines = []
    if r1:
        lines.append(f":one: Reminder 1 sent: *{r1}*")
    if r2:
        lines.append(f":two: Reminder 2 sent: *{r2}*")
    if esc:
        lines.append(f":rotating_light: Escalated: *{esc}*")
    if closed:
        lines.append(f":lock: Closed (past deadline): *{closed}*")

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":bell: *[{SOURCE_TAG}] Daily Reminder Summary*\n\n" + "\n".join(lines),
            },
        },
        _context(f"`{inquiry_id}` | {SOURCE_TAG} Automation"),
    ]

    return _post_message(
        text=f"[{SOURCE_TAG}] Reminders: {r1}+{r2} sent, {esc} escalated, {closed} closed",
        blocks=blocks,
        channel=channel,
        client=client,
    )


def notify_daily_digest(
    inquiry_id: str,
    inquiry_title: str,
    status: str,
    vendor_count: int,
    responded: int,
    status_breakdown: dict,
    deadline: str,
    days_remaining: int,
    channel: str | None = None,
    client: WebClient | None = None,
) -> dict | None:
    """Post daily inquiry status digest."""
    breakdown_lines = []
    for s, count in sorted(status_breakdown.items(), key=lambda x: -x[1]):
        icon = {
            "sent": ":outbox_tray:", "draft": ":memo:",
            "response_received": ":white_check_mark:", "complete_response": ":star:",
            "partial_response": ":hourglass_flowing_sand:", "question_received": ":speech_balloon:",
            "reminder_1": ":one:", "reminder_2": ":two:",
            "escalated": ":rotating_light:", "declined": ":no_entry_sign:",
            "closed": ":lock:", "awarded": ":trophy:",
        }.get(s, ":grey_question:")
        breakdown_lines.append(f"  {icon} {s}: *{count}*")

    deadline_warning = ""
    if days_remaining <= 3:
        deadline_warning = f"\n:warning: *{days_remaining} days until deadline!*"
    elif days_remaining <= 0:
        deadline_warning = "\n:x: *Deadline has passed!*"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":clipboard: [{SOURCE_TAG}] Daily Digest"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Inquiry:*\n{inquiry_title}"},
                {"type": "mrkdwn", "text": f"*Deadline:*\n{deadline} ({days_remaining}d left)"},
                {"type": "mrkdwn", "text": f"*Responses:*\n{responded} / {vendor_count}"},
                {"type": "mrkdwn", "text": f"*Status:*\n{status}"},
            ],
        },
        _divider(),
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Vendor Breakdown:*\n" + "\n".join(breakdown_lines) + deadline_warning},
        },
        _context(f"`{inquiry_id}` | {SOURCE_TAG} Automation"),
    ]

    return _post_message(
        text=f"[{SOURCE_TAG}] Daily digest: {responded}/{vendor_count} responses — {inquiry_id}",
        blocks=blocks,
        channel=channel,
        client=client,
    )
