#!/usr/bin/env python3
"""
setup_gmail_watch.py — Set up Gmail push notifications for procurement automation.

Prerequisites:
  1. Pub/Sub topic 'gmail-procurement-watch' exists in ai-agents-go
  2. Service account has gmail.readonly domain-wide delegation for eukrit@goco.bz
  3. Gmail API Pub/Sub publish permission granted to gmail-api-push@system.gserviceaccount.com

Usage:
    python scripts/setup_gmail_watch.py

Must be re-run every 7 days to refresh the watch.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.gmail_reader import setup_watch, get_gmail_readonly_service, get_last_history_id


def main():
    print("=" * 60)
    print("  GMAIL WATCH SETUP — PROCUREMENT AUTOMATION")
    print("=" * 60)
    print()

    # Test Gmail access first
    print("[1/2] Testing Gmail readonly access...")
    service = get_gmail_readonly_service()
    profile = service.users().getProfile(userId="me").execute()
    print(f"  Email: {profile['emailAddress']}")
    print(f"  Messages: {profile['messagesTotal']:,}")
    print(f"  Current historyId: {profile['historyId']}")
    print()

    # Set up watch
    print("[2/2] Setting up Gmail watch...")
    result = setup_watch(service=service)
    print(f"  historyId: {result.get('historyId')}")
    print(f"  expiration: {result.get('expiration')}")
    print()

    # Verify state
    stored_id = get_last_history_id()
    print(f"  Stored historyId in Firestore: {stored_id}")
    print()

    print("=" * 60)
    print("  WATCH ACTIVE — expires in ~7 days")
    print("  Re-run this script to refresh before expiration.")
    print("=" * 60)


if __name__ == "__main__":
    main()
