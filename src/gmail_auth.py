"""
gmail_auth.py — Build a domain-wide-delegated Gmail API service.

Credential resolution (in priority order):
1. Local dev: `GOOGLE_APPLICATION_CREDENTIALS` env var points at an SA key
   FILE on disk. Used only when the value looks like a path, not JSON.
2. Cloud Run / production: fetch the SA key JSON from Secret Manager at
   runtime via the runtime service account's `roles/secretmanager.secretAccessor`.
   Secret name configurable via env `GMAIL_SA_SECRET` (default `gmail-service-account`).

We deliberately do NOT support `GOOGLE_APPLICATION_CREDENTIALS` containing
JSON content — Cloud Run's `--set-secrets` injects the secret VALUE into the
env var, and any google-auth error then echoes the entire private key into
Cloud Logging. See SECURITY.md / CHANGELOG v1.6.0 for the incident.
"""

from __future__ import annotations

import json
import logging
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

IMPERSONATE_USER = os.environ.get("IMPERSONATE_USER", "eukrit@goco.bz")
GMAIL_SA_SECRET = os.environ.get("GMAIL_SA_SECRET", "gmail-service-account")
GCP_PROJECT = os.environ.get("GCP_PROJECT", "ai-agents-go")


def _scrub_bad_gac_env() -> None:
    """If GOOGLE_APPLICATION_CREDENTIALS holds JSON content (not a path), drop it.

    See module docstring + SECURITY.md for context.
    """
    raw = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if raw.lstrip().startswith("{"):
        # Never log the value — that's exactly the bug we're preventing.
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        logger.warning(
            "GOOGLE_APPLICATION_CREDENTIALS contained JSON content; unset to "
            "prevent SA key leak via google-auth error messages. Falling back "
            "to Secret Manager fetch."
        )


_scrub_bad_gac_env()


def _fetch_sa_key_from_secret_manager() -> dict | None:
    """Fetch the Gmail SA key JSON from Secret Manager.

    Returns the parsed JSON dict on success, or None if the SM call fails
    (caller should fall through to ADC). Errors are logged with sanitized
    summaries only — never the secret payload.
    """
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{GCP_PROJECT}/secrets/{GMAIL_SA_SECRET}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        payload = response.payload.data.decode("utf-8")
        return json.loads(payload)
    except Exception as exc:
        # Sanitized: type + a short message, no secret payload.
        logger.error(
            "Secret Manager fetch failed for %s: %s",
            GMAIL_SA_SECRET, type(exc).__name__,
        )
        return None


def _load_service_account_credentials(scopes: list[str]):
    # 1) Local dev: GAC env points at a file on disk.
    gac_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if gac_path and not gac_path.lstrip().startswith("{") and os.path.exists(gac_path):
        return service_account.Credentials.from_service_account_file(
            gac_path, scopes=scopes
        )

    # 2) Production: fetch SA key from Secret Manager at runtime.
    info = _fetch_sa_key_from_secret_manager()
    if info:
        return service_account.Credentials.from_service_account_info(
            info, scopes=scopes
        )

    # 3) Last-resort: ADC. Will not support DWD impersonation but lets callers
    #    discover the misconfig early via a clear error from the impersonation
    #    step rather than a silent leak.
    import google.auth
    credentials, _ = google.auth.default(scopes=scopes)
    return credentials


def build_gmail_service(scopes: list[str], impersonate_user: str | None = None):
    """Build a Gmail API service impersonating `impersonate_user`."""
    user = impersonate_user or IMPERSONATE_USER
    credentials = _load_service_account_credentials(scopes)
    delegated = credentials.with_subject(user)
    return build("gmail", "v1", credentials=delegated, cache_discovery=False)
