"""
slack_notifier.py — Slack notifications for procurement automation.

Sends structured notifications to #shipment-notifications (C08VD9PRSCU)
for escalations, approval requests, status updates, and daily digests.
"""

from __future__ import annotations

import json
import logging
import os

from google.cloud import secretmanager
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────

GCP_PROJECT = os.environ.get("GCP_PROJECT", "ai-agents-go")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "C08VD9PRSCU")

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
            text=text,
            blocks=blocks,
        )
        return response.data
    except SlackApiError as e:
        logger.error("Slack error: %s", e.response["error"])
        return None
    except Exception as e:
        logger.error("Slack send failed: %s", e)
        return None


# ── Notification Types ────────────────────────────────────────


def notify_new_response(
    inquiry_id: str,
    vendor_id: str,
    vendor_name: str,
    intent: str,
    summary: str,
    confidence: float,
    channel: str | None = None,
    client: WebClient | None = None,
) -> dict | None:
    """Notify Slack about a new vendor response."""
    emoji = {
        "rate_quote": ":chart_with_upwards_trend:",
        "question": ":question:",
        "decline": ":x:",
        "partial_response": ":hourglass:",
        "counter_offer": ":handshake:",
        "out_of_office": ":palm_tree:",
    }.get(intent, ":envelope:")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} New RFQ Response"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Vendor:*\n{vendor_name}"},
                {"type": "mrkdwn", "text": f"*Intent:*\n{intent}"},
                {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.0%}"},
                {"type": "mrkdwn", "text": f"*Inquiry:*\n{inquiry_id}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Summary:* {summary}"},
        },
    ]

    return _post_message(
        text=f"New response from {vendor_name}: {intent}",
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
    """Notify Slack about an escalation requiring human attention."""
    contacts = vendor_contacts or {}
    contact_lines = []
    if contacts.get("contact_email"):
        contact_lines.append(f"Email: {contacts['contact_email']}")
    if contacts.get("contact_wechat"):
        contact_lines.append(f"WeChat: {contacts['contact_wechat']}")
    if contacts.get("contact_whatsapp"):
        contact_lines.append(f"WhatsApp: {contacts['contact_whatsapp']}")
    if contacts.get("contact_phone"):
        contact_lines.append(f"Phone: {contacts['contact_phone']}")
    contact_text = "\n".join(contact_lines) if contact_lines else "No contact info"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": ":rotating_light: Escalation Required"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Vendor:*\n{vendor_name}"},
                {"type": "mrkdwn", "text": f"*Inquiry:*\n{inquiry_id}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Reason:*\n{reason}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Vendor Contacts:*\n{contact_text}"},
        },
    ]

    return _post_message(
        text=f"Escalation: {vendor_name} — {reason}",
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
    """Notify Slack that an auto-reply was sent."""
    answers_text = "\n".join(f"• {a}" for a in (answers or [])) or "General response"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":robot_face: *Auto-reply sent* to *{vendor_name}*\n"
                    f"Confidence: {confidence:.0%} | Inquiry: {inquiry_id}\n"
                    f"Answers given:\n{answers_text}"
                ),
            },
        },
    ]

    return _post_message(
        text=f"Auto-reply sent to {vendor_name}",
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
            "text": {"type": "plain_text", "text": ":pencil: Auto-Reply Draft — Needs Approval"},
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
            "text": {
                "type": "mrkdwn",
                "text": f"*Subject:* {draft_subject}\n\n*Preview:*\n>{draft_body_preview[:500]}",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Inquiry: `{inquiry_id}` | Vendor: `{vendor_id}` | Use MCP approve tool to send",
                },
            ],
        },
    ]

    return _post_message(
        text=f"Draft reply for {vendor_name} needs approval",
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
    anomaly_text = "\n".join(f"• {a}" for a in anomalies)

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":warning: *Rate Anomaly* — *{vendor_name}*\n"
                    f"Inquiry: {inquiry_id}\n\n{anomaly_text}"
                ),
            },
        },
    ]

    return _post_message(
        text=f"Rate anomaly from {vendor_name}",
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
        return None  # Nothing to report

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":bell: *Daily Reminder Summary* — `{inquiry_id}`\n"
                    f"• Reminder 1 sent: {r1}\n"
                    f"• Reminder 2 sent: {r2}\n"
                    f"• Escalated: {esc}\n"
                    f"• Closed (past deadline): {closed}"
                ),
            },
        },
    ]

    return _post_message(
        text=f"Reminder summary: {r1} R1, {r2} R2, {esc} escalated, {closed} closed",
        blocks=blocks,
        channel=channel,
        client=client,
    )
