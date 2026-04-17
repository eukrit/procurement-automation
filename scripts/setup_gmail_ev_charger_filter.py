#!/usr/bin/env python3
"""
setup_gmail_ev_charger_filter.py — Create Gmail label "Suppliers/EV Charger"
and a filter that applies it to incoming mail from the EV charger supplier
shortlist in data/china_ev_charger_suppliers.json.

Idempotent: safe to re-run. Existing label is reused; an existing filter
with the same "from:" criteria is left in place.

Prerequisites (domain-wide delegation on eukrit@goco.bz):
    https://www.googleapis.com/auth/gmail.labels
    https://www.googleapis.com/auth/gmail.settings.basic

If those scopes are not yet on the Workspace admin allow-list, the script
will fail with HttpError 403. Add them in:
    Google Workspace Admin > Security > Access and data control
    > API controls > Domain-wide Delegation > edit the service account.

Usage:
    python scripts/setup_gmail_ev_charger_filter.py
    python scripts/setup_gmail_ev_charger_filter.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

GCP_PROJECT = os.environ.get("GCP_PROJECT", "ai-agents-go")
IMPERSONATE_USER = os.environ.get("IMPERSONATE_USER", "eukrit@goco.bz")
SA_KEY_FILE = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(
        os.path.dirname(__file__), "..", "ai-agents-go-4c81b70995db.json"
    ),
)

LABEL_NAME = "Suppliers/EV Charger"
DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "china_ev_charger_suppliers.json"
)

SCOPES = [
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]


def get_gmail_admin_service():
    """Build Gmail service with labels + settings scopes."""
    if os.path.exists(SA_KEY_FILE):
        credentials = service_account.Credentials.from_service_account_file(
            SA_KEY_FILE, scopes=SCOPES
        )
    else:
        import google.auth
        credentials, _ = google.auth.default(scopes=SCOPES)
    delegated = credentials.with_subject(IMPERSONATE_USER)
    return build("gmail", "v1", credentials=delegated, cache_discovery=False)


def collect_vendor_emails() -> list[str]:
    """Return deduplicated list of vendor contact emails."""
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    emails: list[str] = []
    seen: set[str] = set()
    for company in data["companies"]:
        for key in ("contact_email", "contact_email_alt"):
            email = company.get(key)
            if email and email not in seen:
                emails.append(email)
                seen.add(email)
    return emails


def ensure_label(service, name: str, dry_run: bool) -> str | None:
    """Create the label if it does not exist; return its ID.

    Gmail treats "/" as a hierarchy separator, so a single create call with
    name "Suppliers/EV Charger" produces the nested structure.
    """
    existing = service.users().labels().list(userId="me").execute()
    for label in existing.get("labels", []):
        if label["name"] == name:
            logger.info("Label already exists: %s (id=%s)", name, label["id"])
            return label["id"]

    if dry_run:
        logger.info("[dry-run] Would create label: %s", name)
        return None

    body = {
        "name": name,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
    }
    created = service.users().labels().create(userId="me", body=body).execute()
    logger.info("Created label: %s (id=%s)", name, created["id"])
    return created["id"]


def _from_query(emails: list[str]) -> str:
    # Gmail filter "from" criterion accepts OR-joined list in parentheses.
    return "(" + " OR ".join(emails) + ")"


def ensure_filter(
    service, label_id: str | None, emails: list[str], dry_run: bool
) -> None:
    """Create the filter if one with matching "from" criteria does not exist."""
    from_query = _from_query(emails)

    existing = service.users().settings().filters().list(userId="me").execute()
    for f in existing.get("filter", []):
        criteria = f.get("criteria", {})
        if criteria.get("from") == from_query:
            logger.info("Filter already exists (id=%s) — skipping create", f["id"])
            return

    if dry_run or label_id is None:
        logger.info("[dry-run] Would create filter:")
        logger.info("         from: %s", from_query)
        logger.info("         action: addLabel %s", LABEL_NAME)
        return

    body = {
        "criteria": {"from": from_query},
        "action": {"addLabelIds": [label_id]},
    }
    created = service.users().settings().filters().create(
        userId="me", body=body
    ).execute()
    logger.info("Created filter (id=%s)", created["id"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    emails = collect_vendor_emails()
    logger.info("=" * 60)
    logger.info("  GMAIL LABEL + FILTER SETUP")
    logger.info("=" * 60)
    logger.info("Impersonating: %s", IMPERSONATE_USER)
    logger.info("Label:         %s", LABEL_NAME)
    logger.info("Vendor emails: %d", len(emails))
    for e in emails:
        logger.info("  - %s", e)
    logger.info("")

    try:
        service = get_gmail_admin_service()
    except FileNotFoundError:
        logger.error("Service account key not found at: %s", SA_KEY_FILE)
        sys.exit(1)

    try:
        label_id = ensure_label(service, LABEL_NAME, dry_run=args.dry_run)
        ensure_filter(service, label_id, emails, dry_run=args.dry_run)
    except HttpError as e:
        if e.resp.status == 403:
            logger.error("")
            logger.error("403 Forbidden from Gmail API.")
            logger.error("Likely cause: missing scopes on domain-wide delegation.")
            logger.error("Add these scopes in Workspace Admin > DWD:")
            for s in SCOPES:
                logger.error("  %s", s)
            sys.exit(2)
        raise

    logger.info("")
    logger.info("=" * 60)
    logger.info("  DONE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
