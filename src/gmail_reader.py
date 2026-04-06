"""
gmail_reader.py — Gmail watch + history fetch for procurement automation.

Sets up Gmail push notifications via Pub/Sub and retrieves new messages
using the History API. Pattern adapted from shipping-automation.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from email.utils import parseaddr

from google.cloud import firestore
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────

GCP_PROJECT = os.environ.get("GCP_PROJECT", "ai-agents-go")
FIRESTORE_DATABASE = os.environ.get("FIRESTORE_DATABASE", "procurement-automation")
IMPERSONATE_USER = os.environ.get("IMPERSONATE_USER", "eukrit@goco.bz")
PUBSUB_TOPIC = f"projects/{GCP_PROJECT}/topics/gmail-procurement-watch"

SA_KEY_FILE = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "..", "ai-agents-go-4c81b70995db.json"),
)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
]

# Firestore document for persisting Gmail state
STATE_DOC = "procurement_automation"
STATE_COLLECTION = "gmail_state"


# ── Gmail Service ─────────────────────────────────────────────


def get_gmail_readonly_service(impersonate_user: str | None = None):
    """Build Gmail API service with readonly scope."""
    user = impersonate_user or IMPERSONATE_USER

    if os.path.exists(SA_KEY_FILE):
        credentials = service_account.Credentials.from_service_account_file(
            SA_KEY_FILE, scopes=GMAIL_SCOPES
        )
    else:
        import google.auth
        credentials, _ = google.auth.default(scopes=GMAIL_SCOPES)

    delegated = credentials.with_subject(user)
    return build("gmail", "v1", credentials=delegated, cache_discovery=False)


# ── History ID State ──────────────────────────────────────────


def _get_state_db():
    return firestore.Client(project=GCP_PROJECT, database=FIRESTORE_DATABASE)


def get_last_history_id(db=None) -> str | None:
    """Get the last processed Gmail history ID from Firestore."""
    db = db or _get_state_db()
    doc = db.collection(STATE_COLLECTION).document(STATE_DOC).get()
    if doc.exists:
        return doc.to_dict().get("history_id")
    return None


def set_last_history_id(history_id: str, db=None) -> None:
    """Persist the latest Gmail history ID to Firestore."""
    db = db or _get_state_db()
    db.collection(STATE_COLLECTION).document(STATE_DOC).set(
        {"history_id": str(history_id)}, merge=True
    )
    logger.info("Updated history_id to %s", history_id)


# ── Gmail Watch ───────────────────────────────────────────────


def setup_watch(service=None) -> dict:
    """Set up Gmail push notifications via Pub/Sub.

    Must be called once initially and refreshed every 7 days.
    Returns: {'historyId': ..., 'expiration': ...}
    """
    service = service or get_gmail_readonly_service()
    result = service.users().watch(
        userId="me",
        body={
            "topicName": PUBSUB_TOPIC,
            "labelIds": ["INBOX"],
        },
    ).execute()

    history_id = result.get("historyId")
    if history_id:
        set_last_history_id(history_id)

    logger.info(
        "Gmail watch set up: historyId=%s expiration=%s",
        history_id,
        result.get("expiration"),
    )
    return result


# ── Fetch New Messages ────────────────────────────────────────


def get_new_messages(
    history_id: str | None = None,
    service=None,
    db=None,
) -> list[dict]:
    """Fetch new inbound messages since the given history ID.

    Returns list of message dicts with: id, threadId, sender, subject,
    body_text, body_html, attachments, internalDate.
    """
    service = service or get_gmail_readonly_service()
    db = db or _get_state_db()

    if not history_id:
        history_id = get_last_history_id(db=db)

    if not history_id:
        # No history — get current and return empty
        profile = service.users().getProfile(userId="me").execute()
        set_last_history_id(profile["historyId"], db=db)
        logger.info("No history_id found — initialized to %s", profile["historyId"])
        return []

    try:
        response = service.users().history().list(
            userId="me",
            startHistoryId=history_id,
            historyTypes=["messageAdded"],
            labelId="INBOX",
        ).execute()
    except HttpError as e:
        if e.resp.status == 404:
            # History ID expired — reset
            logger.warning("History ID %s expired — resetting", history_id)
            profile = service.users().getProfile(userId="me").execute()
            set_last_history_id(profile["historyId"], db=db)
            return []
        raise

    # Update history ID
    new_history_id = response.get("historyId")
    if new_history_id:
        set_last_history_id(new_history_id, db=db)

    # Collect unique message IDs from history
    message_ids = set()
    for history_record in response.get("history", []):
        for msg_added in history_record.get("messagesAdded", []):
            msg = msg_added.get("message", {})
            msg_id = msg.get("id")
            labels = msg.get("labelIds", [])
            # Only process inbox messages, skip sent/draft
            if msg_id and "INBOX" in labels:
                message_ids.add(msg_id)

    if not message_ids:
        return []

    # Fetch full message details
    messages = []
    for msg_id in message_ids:
        try:
            full_msg = _get_full_message(msg_id, service)
            if full_msg:
                messages.append(full_msg)
        except Exception as e:
            logger.error("Failed to fetch message %s: %s", msg_id, e)

    logger.info("Fetched %d new messages", len(messages))
    return messages


def _get_full_message(msg_id: str, service) -> dict | None:
    """Fetch and parse a single Gmail message."""
    try:
        msg = service.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()
    except HttpError as e:
        logger.error("Error fetching message %s: %s", msg_id, e)
        return None

    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    sender = headers.get("from", "")
    subject = headers.get("subject", "")

    # Parse sender email
    _, sender_email = parseaddr(sender)

    # Extract body
    body_text, body_html = _extract_body(msg.get("payload", {}))

    # Extract attachment info
    attachments = _extract_attachments(msg.get("payload", {}), msg_id)

    return {
        "id": msg_id,
        "threadId": msg.get("threadId"),
        "sender": sender,
        "sender_email": sender_email.lower().strip() if sender_email else "",
        "subject": subject,
        "body_text": body_text,
        "body_html": body_html,
        "body_preview": (body_text or body_html or "")[:5000],
        "attachments": attachments,
        "internalDate": msg.get("internalDate"),
        "labelIds": msg.get("labelIds", []),
        "headers": {
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "cc": headers.get("cc", ""),
            "date": headers.get("date", ""),
            "message-id": headers.get("message-id", ""),
            "in-reply-to": headers.get("in-reply-to", ""),
            "references": headers.get("references", ""),
        },
    }


def _extract_body(payload: dict) -> tuple[str, str]:
    """Extract text and HTML body from a Gmail message payload."""
    body_text = ""
    body_html = ""

    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    elif mime_type == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            body_html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    elif "parts" in payload:
        for part in payload["parts"]:
            t, h = _extract_body(part)
            if t and not body_text:
                body_text = t
            if h and not body_html:
                body_html = h

    return body_text, body_html


def _extract_attachments(payload: dict, msg_id: str) -> list[dict]:
    """Extract attachment metadata from a Gmail message payload."""
    attachments = []

    if payload.get("filename"):
        att_id = payload.get("body", {}).get("attachmentId")
        if att_id:
            attachments.append({
                "filename": payload["filename"],
                "mime_type": payload.get("mimeType", ""),
                "gmail_attachment_id": att_id,
                "gmail_message_id": msg_id,
                "size": payload.get("body", {}).get("size", 0),
            })

    for part in payload.get("parts", []):
        attachments.extend(_extract_attachments(part, msg_id))

    return attachments


def get_attachment_content(
    message_id: str, attachment_id: str, service=None
) -> bytes:
    """Download attachment content by ID."""
    service = service or get_gmail_readonly_service()
    att = service.users().messages().attachments().get(
        userId="me", messageId=message_id, id=attachment_id
    ).execute()
    data = att.get("data", "")
    return base64.urlsafe_b64decode(data)


def strip_html(html: str) -> str:
    """Simple HTML to text conversion for Gemini input."""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
