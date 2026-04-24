#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_poe_display_gmail_filter.py — Create Gmail label "Suppliers/LED" and
filter to auto-label all inbound emails from the 6 PoE display RFQ vendors.

Creates (if missing):
  • Label:  Suppliers/LED
  • Filter: FROM any vendor email -> apply label + skip inbox optional

Usage:
    python scripts/setup_poe_display_gmail_filter.py --dry   # preview only
    python scripts/setup_poe_display_gmail_filter.py          # create filter
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.gmail_auth import build_gmail_service

# Gmail label to apply (nested — parent "Suppliers" auto-created if absent)
LABEL_NAME = "Suppliers/LED"

# All vendor email addresses for this RFQ
VENDOR_EMAILS = [
    "sales@elcsign.com",
    "hello@mio-lcd.com",
    "sales@raypodo.com",
    "info@raypodotech.com",
    "sales@aiyostech.com",
    "info@hd-focus.com",
    "jack@hd-focus.com",
    "info@qbictechnology.com",
    "sales@qbictechnology.com",
]

IMPERSONATE_USER = os.environ.get("IMPERSONATE_USER", "eukrit@goco.bz")

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.labels",
]


def get_or_create_label(service, label_name: str, dry_run: bool = False) -> str | None:
    """Return label ID, creating the label if it doesn't exist."""
    result = service.users().labels().list(userId="me").execute()
    for label in result.get("labels", []):
        if label["name"] == label_name:
            print(f"  Label already exists: '{label_name}' (id={label['id']})")
            return label["id"]

    if dry_run:
        print(f"  [DRY] Would create label: '{label_name}'")
        return "DRY_RUN_LABEL_ID"

    created = service.users().labels().create(
        userId="me",
        body={
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    ).execute()
    print(f"  Created label: '{label_name}' (id={created['id']})")
    return created["id"]


def get_existing_filters(service) -> list[dict]:
    result = service.users().settings().filters().list(userId="me").execute()
    return result.get("filter", [])


def filter_already_covers(existing: list[dict], email: str, label_id: str) -> bool:
    """Return True if a filter already applies label_id to mail from email."""
    for f in existing:
        criteria = f.get("criteria", {})
        action = f.get("action", {})
        if (
            criteria.get("from", "").lower() == email.lower()
            and label_id in action.get("addLabelIds", [])
        ):
            return True
    return False


def create_filter(service, email: str, label_id: str, dry_run: bool = False) -> bool:
    """Create a Gmail filter: FROM email -> apply label. Returns True if created."""
    if dry_run:
        print(f"  [DRY] Would create filter: from:{email} -> label '{LABEL_NAME}'")
        return True

    body = {
        "criteria": {"from": email},
        "action": {
            "addLabelIds": [label_id],
            "removeLabelIds": [],
        },
    }
    service.users().settings().filters().create(userId="me", body=body).execute()
    print(f"  Filter created: from:{email} -> '{LABEL_NAME}'")
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="Preview without making changes")
    args = ap.parse_args()

    scopes = [
        "https://www.googleapis.com/auth/gmail.settings.basic",
        "https://www.googleapis.com/auth/gmail.labels",
    ]
    service = build_gmail_service(scopes, impersonate_user=IMPERSONATE_USER)

    print("=" * 60)
    print("  POE DISPLAY RFQ — Gmail Filter Setup")
    print(f"  Label:  {LABEL_NAME}")
    print(f"  Mode:   {'DRY RUN' if args.dry else '*** LIVE ***'}")
    print("=" * 60)
    print()

    print(f"[1/2] Ensuring label '{LABEL_NAME}' exists...")
    label_id = get_or_create_label(service, LABEL_NAME, dry_run=args.dry)
    print()

    print(f"[2/2] Creating per-vendor filters ({len(VENDOR_EMAILS)} emails)...")
    existing = [] if args.dry else get_existing_filters(service)
    created, skipped = 0, 0
    for email in VENDOR_EMAILS:
        if not args.dry and filter_already_covers(existing, email, label_id):
            print(f"  SKIP  {email}  (filter already exists)")
            skipped += 1
            continue
        create_filter(service, email, label_id, dry_run=args.dry)
        created += 1

    print()
    print("=" * 60)
    if args.dry:
        print(f"  DRY RUN — {len(VENDOR_EMAILS)} filters would be created for '{LABEL_NAME}'")
    else:
        print(f"  DONE — {created} filters created, {skipped} skipped (already existed)")
        print(f"  All mail from PoE display vendors -> '{LABEL_NAME}'")
    print("=" * 60)


if __name__ == "__main__":
    main()
