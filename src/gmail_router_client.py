"""
gmail_router_client.py — HTTP client for the central Gmail Router.

Routes outbound email through `data-comms-send-email` (in the
`data-communications` repo) instead of building+sending the MIME locally.
Single Gmail DWD identity, single audit log (`email_sends` collection),
single chokepoint for retry/rate-limit/templating policy.

Authentication is handled by Google's metadata server (Cloud Run / Cloud
Functions runtime). No keys to manage — `fetch_id_token` returns a JWT
whose `aud` claim equals the target Cloud Function URL, signed by the
runtime service account. Gmail Router verifies that JWT and looks up the
SA in `email_sender_allowlist`.

Public surface mirrors the legacy `send_email()` return shape so
downstream code (rfq_workflow, send_followups, etc.) doesn't change.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from pathlib import Path

import requests
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

logger = logging.getLogger(__name__)

# Cloud Function URL — set at deploy time.
# data-comms-send-email lives in asia-southeast1. Override via env var if
# the URL changes (e.g. custom domain).
GMAIL_ROUTER_SEND_URL = os.environ.get(
    "GMAIL_ROUTER_SEND_URL",
    "https://data-comms-send-email-rg5gmtwrfa-as.a.run.app",
)

# Caller label baked into every request so the audit log shows where the
# send originated. Override per-call via the `caller` arg if needed.
DEFAULT_CALLER = os.environ.get(
    "GMAIL_ROUTER_CALLER", "procurement-automation/gmail_sender"
)

# Project root for resolving relative attachment paths.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Cached request adapter — fetch_id_token does an HTTP round-trip to
# Google each call; reusing the adapter keeps the urllib3 pool warm.
_REQUESTS_ADAPTER: google_requests.Request | None = None


def _adapter() -> google_requests.Request:
    global _REQUESTS_ADAPTER
    if _REQUESTS_ADAPTER is None:
        _REQUESTS_ADAPTER = google_requests.Request()
    return _REQUESTS_ADAPTER


def _file_to_attachment_dict(filepath: str) -> dict:
    """Read a local file and return Gmail Router's attachment shape."""
    path = Path(filepath)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        raise FileNotFoundError(f"Attachment not found: {path}")

    mime_type, _ = mimetypes.guess_type(str(path))
    if mime_type is None:
        mime_type = "application/octet-stream"

    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")

    return {
        "filename": path.name,
        "mimeType": mime_type,
        "contentBase64": encoded,
    }


def send_via_router(
    *,
    to: list[str],
    subject: str,
    body_html: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    reply_to: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    thread_id: str | None = None,
    attachments: list[str] | None = None,
    caller: str | None = None,
    template: str | None = None,
    idempotency_key: str | None = None,
    timeout: int = 60,
) -> dict:
    """POST to Gmail Router /send_email and return the legacy result shape.

    Legacy shape:
        { "message_id": str, "thread_id": str, "label_ids": list[str] }

    Raises:
        requests.HTTPError on non-2xx (after writing the failure to logs).
    """
    audience = GMAIL_ROUTER_SEND_URL
    token = id_token.fetch_id_token(_adapter(), audience)

    encoded_attachments: list[dict] = []
    for fp in attachments or []:
        encoded_attachments.append(_file_to_attachment_dict(fp))

    payload: dict = {
        "to": to,
        "subject": subject,
        "bodyHtml": body_html,
        "caller": caller or DEFAULT_CALLER,
    }
    if cc:
        payload["cc"] = cc
    if bcc:
        payload["bcc"] = bcc
    if reply_to:
        payload["replyTo"] = reply_to
    if in_reply_to:
        payload["inReplyTo"] = in_reply_to
    if references:
        payload["references"] = references
    if thread_id:
        payload["threadId"] = thread_id
    if encoded_attachments:
        payload["attachments"] = encoded_attachments
    if template:
        payload["template"] = template
    if idempotency_key:
        payload["idempotencyKey"] = idempotency_key

    logger.info(
        "gmail-router send: to=%s subject=%s thread_id=%s caller=%s",
        to, subject, thread_id, payload["caller"],
    )

    resp = requests.post(
        GMAIL_ROUTER_SEND_URL,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=timeout,
    )

    if resp.status_code >= 400:
        # Surface the Router's error JSON for easier debugging in caller logs.
        logger.warning(
            "gmail-router %d: %s", resp.status_code, resp.text[:500]
        )
        resp.raise_for_status()

    body = resp.json()
    if body.get("status") == "failed":
        # Router accepted the request but Gmail rejected — bubble up.
        raise RuntimeError(
            f"gmail-router send failed: {body.get('error') or 'unknown'}"
        )

    return {
        # Legacy callers expect snake_case. Map from Router's camelCase.
        "message_id": body.get("gmailMessageId"),
        "thread_id": body.get("gmailThreadId"),
        "label_ids": [],  # Router doesn't surface labels; legacy callers
                          # don't currently rely on this beyond logging.
        "_router": {
            "status": body.get("status"),       # "sent" | "skipped_duplicate"
            "idempotencyKey": body.get("idempotencyKey"),
        },
    }


def is_router_enabled() -> bool:
    """Check the feature flag. Default False — soft cutover.

    Set USE_GMAIL_ROUTER=true (Cloud Functions env var) to flip.
    """
    return os.environ.get("USE_GMAIL_ROUTER", "").lower() in (
        "true", "1", "yes", "on",
    )
