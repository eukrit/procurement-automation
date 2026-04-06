"""
rfq_store.py — Firestore CRUD for procurement automation.

Collections:
  rfq_inquiries/{inquiry_id}                           — RFQ inquiries
  rfq_inquiries/{id}/vendors/{vendor_id}               — Vendors per inquiry
  rfq_inquiries/{id}/vendors/{vid}/messages/{msg_id}   — Email thread
  vendor_directory/{vendor_id}                         — Master vendor registry
  procurement_templates/{template_id}                  — Reusable RFQ templates
  workflow_config/{config_id}                          — Automation rules
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

GCP_PROJECT = os.environ.get("GCP_PROJECT", "ai-agents-go")
FIRESTORE_DATABASE = os.environ.get("FIRESTORE_DATABASE", "procurement-automation")

# Collection names
INQUIRIES = "rfq_inquiries"
VENDOR_DIRECTORY = "vendor_directory"
TEMPLATES = "procurement_templates"
WORKFLOW_CONFIG = "workflow_config"


def get_db() -> firestore.Client:
    return firestore.Client(project=GCP_PROJECT, database=FIRESTORE_DATABASE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(name: str) -> str:
    """Convert company name to a URL-friendly slug for use as vendor_id."""
    slug = name.lower()
    # Remove parenthetical content
    slug = re.sub(r"\s*\(.*?\)\s*", " ", slug)
    # Keep only alphanumeric and spaces
    slug = re.sub(r"[^a-z0-9\s]", "", slug)
    # Replace spaces with hyphens, collapse multiples
    slug = re.sub(r"\s+", "-", slug.strip())
    # Remove trailing hyphens
    slug = slug.strip("-")
    return slug


# ── Inquiry CRUD ──────────────────────────────────────────────


def create_inquiry(config: dict, db: firestore.Client | None = None) -> str:
    """Create an RFQ inquiry. Returns inquiry_id."""
    db = db or get_db()
    inquiry_id = config.get("inquiry_id")
    if not inquiry_id:
        raise ValueError("config must include 'inquiry_id'")

    now = _now()
    doc = {
        **config,
        "status": config.get("status", "draft"),
        "vendor_count": config.get("vendor_count", 0),
        "responded_count": 0,
        "awarded_vendor_id": None,
        "created_at": now,
        "last_updated": now,
    }
    db.collection(INQUIRIES).document(inquiry_id).set(doc)
    return inquiry_id


def get_inquiry(inquiry_id: str, db: firestore.Client | None = None) -> dict | None:
    """Get an inquiry by ID. Returns dict or None."""
    db = db or get_db()
    doc = db.collection(INQUIRIES).document(inquiry_id).get()
    return doc.to_dict() if doc.exists else None


def list_inquiries(
    status: str | None = None, db: firestore.Client | None = None
) -> list[dict]:
    """List all inquiries, optionally filtered by status."""
    db = db or get_db()
    query = db.collection(INQUIRIES)
    if status:
        query = query.where(filter=FieldFilter("status", "==", status))
    return [doc.to_dict() for doc in query.stream()]


# ── Vendor (per-inquiry) CRUD ─────────────────────────────────


def add_vendor_to_inquiry(
    inquiry_id: str, vendor_data: dict, db: firestore.Client | None = None
) -> str:
    """Add a vendor to an inquiry. Returns vendor_id."""
    db = db or get_db()
    vendor_id = vendor_data.get("vendor_id")
    if not vendor_id:
        vendor_id = _slugify(vendor_data.get("company_en", ""))
    if not vendor_id:
        raise ValueError("vendor_data must include 'vendor_id' or 'company_en'")

    now = _now()
    doc = {
        "vendor_id": vendor_id,
        **vendor_data,
        "status": vendor_data.get("status", "draft"),
        "status_history": [
            {"status": "draft", "at": now, "by": "system", "note": "seeded"}
        ],
        "email_tracking": {
            "thread_id": None,
            "message_ids": [],
            "outbound_count": 0,
            "inbound_count": 0,
            "auto_reply_count": 0,
            "last_outbound_at": None,
            "last_inbound_at": None,
        },
        "rates": vendor_data.get("rates", {}),
        "benchmark": vendor_data.get("benchmark", {}),
        "capabilities": vendor_data.get("capabilities", {}),
        "attachments": [],
        "score": {
            "price_score": None,
            "transit_score": None,
            "capability_score": None,
            "communication_score": None,
            "overall": None,
        },
        "escalation": {
            "escalated": False,
            "reason": None,
            "requires_human": False,
            "human_reason": None,
        },
        "reminders": {
            "count": 0,
            "next_at": None,
            "wechat_reminder_sent": False,
            "whatsapp_reminder_sent": False,
        },
        "created_at": now,
        "last_updated": now,
    }

    (
        db.collection(INQUIRIES)
        .document(inquiry_id)
        .collection("vendors")
        .document(vendor_id)
        .set(doc)
    )

    # Increment vendor_count on the inquiry
    db.collection(INQUIRIES).document(inquiry_id).update(
        {"vendor_count": firestore.Increment(1), "last_updated": now}
    )

    return vendor_id


def get_vendor(
    inquiry_id: str, vendor_id: str, db: firestore.Client | None = None
) -> dict | None:
    """Get a vendor document within an inquiry."""
    db = db or get_db()
    doc = (
        db.collection(INQUIRIES)
        .document(inquiry_id)
        .collection("vendors")
        .document(vendor_id)
        .get()
    )
    return doc.to_dict() if doc.exists else None


def get_inquiry_vendors(
    inquiry_id: str,
    status_filter: str | None = None,
    db: firestore.Client | None = None,
) -> list[dict]:
    """Get all vendors for an inquiry, optionally filtered by status."""
    db = db or get_db()
    query = (
        db.collection(INQUIRIES).document(inquiry_id).collection("vendors")
    )
    if status_filter:
        query = query.where(filter=FieldFilter("status", "==", status_filter))
    return [doc.to_dict() for doc in query.stream()]


def update_vendor_status(
    inquiry_id: str,
    vendor_id: str,
    status: str,
    note: str = "",
    db: firestore.Client | None = None,
) -> None:
    """Update a vendor's status and append to status_history."""
    db = db or get_db()
    now = _now()
    ref = (
        db.collection(INQUIRIES)
        .document(inquiry_id)
        .collection("vendors")
        .document(vendor_id)
    )
    ref.update(
        {
            "status": status,
            "status_history": firestore.ArrayUnion(
                [{"status": status, "at": now, "by": "system", "note": note}]
            ),
            "last_updated": now,
        }
    )


def update_vendor_rates(
    inquiry_id: str,
    vendor_id: str,
    rates: dict,
    benchmark: dict | None = None,
    capabilities: dict | None = None,
    db: firestore.Client | None = None,
) -> None:
    """Update extracted rate data for a vendor."""
    db = db or get_db()
    now = _now()
    updates: dict = {"rates": rates, "last_updated": now}
    if benchmark is not None:
        updates["benchmark"] = benchmark
    if capabilities is not None:
        updates["capabilities"] = capabilities

    (
        db.collection(INQUIRIES)
        .document(inquiry_id)
        .collection("vendors")
        .document(vendor_id)
        .update(updates)
    )


# ── Messages ──────────────────────────────────────────────────


def log_message(
    inquiry_id: str,
    vendor_id: str,
    message_data: dict,
    db: firestore.Client | None = None,
) -> str:
    """Log an email message in the vendor's message subcollection.
    Returns the Firestore document ID.
    """
    db = db or get_db()
    now = _now()
    msg = {**message_data, "timestamp": now}
    ref = (
        db.collection(INQUIRIES)
        .document(inquiry_id)
        .collection("vendors")
        .document(vendor_id)
        .collection("messages")
        .add(msg)
    )
    # .add() returns a tuple (timestamp, doc_ref)
    doc_ref = ref[1]

    # Update email_tracking counters
    direction = message_data.get("direction", "outbound")
    tracking_updates: dict = {"last_updated": now}
    if direction == "outbound":
        tracking_updates["email_tracking.outbound_count"] = firestore.Increment(1)
        tracking_updates["email_tracking.last_outbound_at"] = now
    else:
        tracking_updates["email_tracking.inbound_count"] = firestore.Increment(1)
        tracking_updates["email_tracking.last_inbound_at"] = now

    if message_data.get("message_id"):
        tracking_updates["email_tracking.message_ids"] = firestore.ArrayUnion(
            [message_data["message_id"]]
        )
    if message_data.get("thread_id"):
        tracking_updates["email_tracking.thread_id"] = message_data["thread_id"]

    (
        db.collection(INQUIRIES)
        .document(inquiry_id)
        .collection("vendors")
        .document(vendor_id)
        .update(tracking_updates)
    )

    return doc_ref.id


# ── Sender matching ──────────────────────────────────────────


def match_sender_to_vendor(
    sender_email: str, db: firestore.Client | None = None
) -> dict | None:
    """Match an inbound sender email to a vendor in any active inquiry.
    Returns {'inquiry_id': ..., 'vendor_id': ...} or None.
    """
    db = db or get_db()
    sender_email = sender_email.lower().strip()

    # Search active inquiries
    inquiries = db.collection(INQUIRIES).where(
        filter=FieldFilter("status", "in", ["sending", "active"])
    ).stream()

    for inq_doc in inquiries:
        inquiry_id = inq_doc.id
        vendors = (
            db.collection(INQUIRIES)
            .document(inquiry_id)
            .collection("vendors")
            .stream()
        )
        for vendor_doc in vendors:
            v = vendor_doc.to_dict()
            # Check contact_email and contact_email_alt
            emails = []
            if v.get("contact_email"):
                emails.append(v["contact_email"].lower().strip())
            if v.get("contact_email_alt"):
                emails.append(v["contact_email_alt"].lower().strip())
            if sender_email in emails:
                return {"inquiry_id": inquiry_id, "vendor_id": vendor_doc.id}

    return None


# ── Vendor Directory (master registry) ────────────────────────


def upsert_vendor_directory(
    vendor_data: dict, db: firestore.Client | None = None
) -> str:
    """Upsert a vendor in the master vendor_directory collection.
    Returns vendor_id.
    """
    db = db or get_db()
    vendor_id = vendor_data.get("vendor_id")
    if not vendor_id:
        vendor_id = _slugify(vendor_data.get("company_en", ""))
    if not vendor_id:
        raise ValueError("vendor_data must include 'vendor_id' or 'company_en'")

    now = _now()
    doc = {
        "vendor_id": vendor_id,
        **vendor_data,
        "last_updated": now,
    }
    # Merge so we don't overwrite campaign_history etc. on re-seed
    db.collection(VENDOR_DIRECTORY).document(vendor_id).set(doc, merge=True)
    return vendor_id


# ── Templates & Config ────────────────────────────────────────


def set_template(
    template_id: str, template_data: dict, db: firestore.Client | None = None
) -> str:
    """Create or update a procurement template."""
    db = db or get_db()
    now = _now()
    doc = {
        "template_id": template_id,
        **template_data,
        "last_updated": now,
    }
    if "created_at" not in template_data:
        doc["created_at"] = now
    db.collection(TEMPLATES).document(template_id).set(doc, merge=True)
    return template_id


def get_template(
    template_id: str, db: firestore.Client | None = None
) -> dict | None:
    """Get a procurement template by ID."""
    db = db or get_db()
    doc = db.collection(TEMPLATES).document(template_id).get()
    return doc.to_dict() if doc.exists else None


def set_workflow_config(
    config_id: str, config_data: dict, db: firestore.Client | None = None
) -> str:
    """Create or update workflow config."""
    db = db or get_db()
    doc = {"config_id": config_id, **config_data}
    db.collection(WORKFLOW_CONFIG).document(config_id).set(doc, merge=True)
    return config_id


def get_workflow_config(
    config_id: str = "default", db: firestore.Client | None = None
) -> dict | None:
    """Get workflow config by ID."""
    db = db or get_db()
    doc = db.collection(WORKFLOW_CONFIG).document(config_id).get()
    return doc.to_dict() if doc.exists else None
