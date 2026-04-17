"""
gmail_auth.py — Build a domain-wide-delegated Gmail API service.

Handles three credential sources, in priority order:

1. GOOGLE_APPLICATION_CREDENTIALS env var contains the service-account
   JSON *as a string* (injected via `gcloud run --set-secrets` or
   Cloud Build `--set-secrets`). Detected by a leading `{`.
2. GOOGLE_APPLICATION_CREDENTIALS env var (or the legacy default path)
   points at a file on disk — used for local development.
3. Application Default Credentials — last-resort fallback.

Centralizing this lets gmail_sender, gmail_reader, and one-shot scripts
share the same logic instead of each re-implementing it.
"""

from __future__ import annotations

import json
import logging
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

IMPERSONATE_USER = os.environ.get("IMPERSONATE_USER", "eukrit@goco.bz")

_DEFAULT_KEY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "ai-agents-go-4c81b70995db.json"
)


def _load_service_account_credentials(scopes: list[str]):
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

    if raw.lstrip().startswith("{"):
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(
            info, scopes=scopes
        )

    path = raw or _DEFAULT_KEY_PATH
    if os.path.exists(path):
        return service_account.Credentials.from_service_account_file(
            path, scopes=scopes
        )

    import google.auth
    credentials, _ = google.auth.default(scopes=scopes)
    return credentials


def build_gmail_service(scopes: list[str], impersonate_user: str | None = None):
    """Build a Gmail API service impersonating `impersonate_user`."""
    user = impersonate_user or IMPERSONATE_USER
    credentials = _load_service_account_credentials(scopes)
    delegated = credentials.with_subject(user)
    return build("gmail", "v1", credentials=delegated, cache_discovery=False)
