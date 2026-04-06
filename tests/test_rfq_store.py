"""Tests for src/rfq_store.py — Firestore CRUD for procurement automation."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import rfq_store


# ── Helpers ───────────────────────────────────────────────────


class FakeDocSnapshot:
    """Minimal Firestore document snapshot stub."""

    def __init__(self, doc_id: str, data: dict | None = None):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return self._data


class FakeDocRef:
    """Minimal Firestore document reference stub with nested collections."""

    def __init__(self, doc_id: str = "test-doc"):
        self.id = doc_id
        self._data = None
        self._collections: dict[str, FakeCollectionRef] = {}

    def set(self, data, merge=False):
        self._data = data

    def get(self):
        return FakeDocSnapshot(self.id, self._data)

    def update(self, data):
        if self._data is None:
            self._data = {}
        self._data.update(data)

    def collection(self, name):
        if name not in self._collections:
            self._collections[name] = FakeCollectionRef(name)
        return self._collections[name]


class FakeCollectionRef:
    """Minimal Firestore collection reference stub."""

    def __init__(self, name: str = "test-collection"):
        self.name = name
        self._docs: dict[str, FakeDocRef] = {}
        self._where_filters = []

    def document(self, doc_id: str) -> FakeDocRef:
        if doc_id not in self._docs:
            self._docs[doc_id] = FakeDocRef(doc_id)
        return self._docs[doc_id]

    def where(self, field=None, op=None, value=None, *, filter=None):
        # Return self for chaining — stream will return all docs
        return self

    def stream(self):
        for doc_id, doc_ref in self._docs.items():
            if doc_ref._data is not None:
                yield FakeDocSnapshot(doc_id, doc_ref._data)

    def add(self, data):
        doc_id = f"auto-{len(self._docs)}"
        ref = self.document(doc_id)
        ref.set(data)
        return (datetime.now(timezone.utc), ref)


class FakeFirestoreClient:
    """Minimal Firestore client stub."""

    def __init__(self):
        self._collections: dict[str, FakeCollectionRef] = {}

    def collection(self, name: str) -> FakeCollectionRef:
        if name not in self._collections:
            self._collections[name] = FakeCollectionRef(name)
        return self._collections[name]


@pytest.fixture
def db():
    return FakeFirestoreClient()


# ── Slugify ───────────────────────────────────────────────────


class TestSlugify:
    def test_simple(self):
        assert rfq_store._slugify("Canton Cargo") == "canton-cargo"

    def test_parenthetical(self):
        assert rfq_store._slugify("DJCargo (DJ International Freight)") == "djcargo"

    def test_special_chars(self):
        assert rfq_store._slugify("CSC Logistics (Cargo Speeds Co.)") == "csc-logistics"

    def test_chinese_stripped(self):
        assert rfq_store._slugify("中泰物流") == ""


# ── Inquiry CRUD ──────────────────────────────────────────────


class TestInquiryCRUD:
    def test_create_inquiry(self, db):
        inquiry_id = rfq_store.create_inquiry(
            {"inquiry_id": "TEST-001", "title": "Test", "category": "freight"},
            db=db,
        )
        assert inquiry_id == "TEST-001"

        doc = db.collection("rfq_inquiries").document("TEST-001").get()
        assert doc.exists
        data = doc.to_dict()
        assert data["title"] == "Test"
        assert data["status"] == "draft"
        assert data["responded_count"] == 0
        assert data["awarded_vendor_id"] is None

    def test_create_inquiry_missing_id(self, db):
        with pytest.raises(ValueError, match="inquiry_id"):
            rfq_store.create_inquiry({"title": "No ID"}, db=db)

    def test_get_inquiry(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "TEST-002", "title": "Get Test"}, db=db
        )
        result = rfq_store.get_inquiry("TEST-002", db=db)
        assert result is not None
        assert result["title"] == "Get Test"

    def test_get_inquiry_not_found(self, db):
        result = rfq_store.get_inquiry("NONEXISTENT", db=db)
        assert result is None

    def test_list_inquiries(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "A", "title": "A", "status": "draft"}, db=db
        )
        rfq_store.create_inquiry(
            {"inquiry_id": "B", "title": "B", "status": "active"}, db=db
        )
        results = rfq_store.list_inquiries(db=db)
        assert len(results) == 2


# ── Vendor CRUD ───────────────────────────────────────────────


class TestVendorCRUD:
    def test_add_vendor(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "INQ-1", "title": "Test"}, db=db
        )
        vendor_id = rfq_store.add_vendor_to_inquiry(
            "INQ-1",
            {"vendor_id": "test-vendor", "company_en": "Test Vendor Co"},
            db=db,
        )
        assert vendor_id == "test-vendor"

        vendor = rfq_store.get_vendor("INQ-1", "test-vendor", db=db)
        assert vendor is not None
        assert vendor["company_en"] == "Test Vendor Co"
        assert vendor["status"] == "draft"
        assert vendor["email_tracking"]["outbound_count"] == 0

    def test_add_vendor_slug_from_name(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "INQ-2", "title": "Test"}, db=db
        )
        vendor_id = rfq_store.add_vendor_to_inquiry(
            "INQ-2",
            {"company_en": "Canton Cargo"},
            db=db,
        )
        assert vendor_id == "canton-cargo"

    def test_get_vendor_not_found(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "INQ-3", "title": "Test"}, db=db
        )
        result = rfq_store.get_vendor("INQ-3", "nonexistent", db=db)
        assert result is None

    def test_get_inquiry_vendors(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "INQ-4", "title": "Test"}, db=db
        )
        rfq_store.add_vendor_to_inquiry(
            "INQ-4", {"vendor_id": "v1", "company_en": "V1"}, db=db
        )
        rfq_store.add_vendor_to_inquiry(
            "INQ-4", {"vendor_id": "v2", "company_en": "V2"}, db=db
        )
        vendors = rfq_store.get_inquiry_vendors("INQ-4", db=db)
        assert len(vendors) == 2

    def test_update_vendor_status(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "INQ-5", "title": "Test"}, db=db
        )
        rfq_store.add_vendor_to_inquiry(
            "INQ-5", {"vendor_id": "v1", "company_en": "V1"}, db=db
        )
        rfq_store.update_vendor_status("INQ-5", "v1", "sent", note="email sent", db=db)
        vendor = rfq_store.get_vendor("INQ-5", "v1", db=db)
        assert vendor["status"] == "sent"

    def test_update_vendor_rates(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "INQ-6", "title": "Test"}, db=db
        )
        rfq_store.add_vendor_to_inquiry(
            "INQ-6", {"vendor_id": "v1", "company_en": "V1"}, db=db
        )
        rfq_store.update_vendor_rates(
            "INQ-6",
            "v1",
            rates={"sea_per_cbm": 4200},
            benchmark={"sea_total": 10000},
            capabilities={"warehouse_china": True},
            db=db,
        )
        vendor = rfq_store.get_vendor("INQ-6", "v1", db=db)
        assert vendor["rates"] == {"sea_per_cbm": 4200}


# ── Messages ──────────────────────────────────────────────────


class TestMessages:
    def test_log_outbound_message(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "INQ-7", "title": "Test"}, db=db
        )
        rfq_store.add_vendor_to_inquiry(
            "INQ-7", {"vendor_id": "v1", "company_en": "V1"}, db=db
        )
        msg_id = rfq_store.log_message(
            "INQ-7",
            "v1",
            {
                "direction": "outbound",
                "type": "rfq_initial",
                "subject": "RFQ: Test",
                "message_id": "gmail-123",
                "thread_id": "thread-456",
            },
            db=db,
        )
        assert msg_id is not None

    def test_log_inbound_message(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "INQ-8", "title": "Test"}, db=db
        )
        rfq_store.add_vendor_to_inquiry(
            "INQ-8", {"vendor_id": "v1", "company_en": "V1"}, db=db
        )
        rfq_store.log_message(
            "INQ-8",
            "v1",
            {
                "direction": "inbound",
                "type": "response",
                "subject": "Re: RFQ",
                "message_id": "gmail-789",
                "thread_id": "thread-456",
            },
            db=db,
        )
        vendor = rfq_store.get_vendor("INQ-8", "v1", db=db)
        assert vendor is not None


# ── Vendor Directory ──────────────────────────────────────────


class TestVendorDirectory:
    def test_upsert(self, db):
        vendor_id = rfq_store.upsert_vendor_directory(
            {
                "vendor_id": "test-co",
                "company_en": "Test Co",
                "categories": ["freight"],
            },
            db=db,
        )
        assert vendor_id == "test-co"

        doc = db.collection("vendor_directory").document("test-co").get()
        assert doc.exists
        assert doc.to_dict()["company_en"] == "Test Co"

    def test_upsert_slug_from_name(self, db):
        vendor_id = rfq_store.upsert_vendor_directory(
            {"company_en": "DJCargo (DJ International Freight)"},
            db=db,
        )
        assert vendor_id == "djcargo"

    def test_upsert_no_id_or_name(self, db):
        with pytest.raises(ValueError):
            rfq_store.upsert_vendor_directory({}, db=db)


# ── Templates & Config ────────────────────────────────────────


class TestTemplatesAndConfig:
    def test_set_and_get_template(self, db):
        rfq_store.set_template(
            "test-tmpl",
            {"name": "Test Template", "category": "freight"},
            db=db,
        )
        result = rfq_store.get_template("test-tmpl", db=db)
        assert result is not None
        assert result["name"] == "Test Template"

    def test_get_template_not_found(self, db):
        assert rfq_store.get_template("nope", db=db) is None

    def test_set_and_get_workflow_config(self, db):
        rfq_store.set_workflow_config(
            "default",
            {"escalation_rules": {"max_auto_replies": 3}},
            db=db,
        )
        result = rfq_store.get_workflow_config("default", db=db)
        assert result is not None
        assert result["escalation_rules"]["max_auto_replies"] == 3

    def test_get_workflow_config_not_found(self, db):
        assert rfq_store.get_workflow_config("nope", db=db) is None


# ── Sender Matching ───────────────────────────────────────────


class TestSenderMatching:
    def test_match_found(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "INQ-M1", "title": "Test", "status": "active"},
            db=db,
        )
        rfq_store.add_vendor_to_inquiry(
            "INQ-M1",
            {"vendor_id": "v1", "company_en": "V1", "contact_email": "sales@v1.com"},
            db=db,
        )
        result = rfq_store.match_sender_to_vendor("sales@v1.com", db=db)
        assert result is not None
        assert result["inquiry_id"] == "INQ-M1"
        assert result["vendor_id"] == "v1"

    def test_match_not_found(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "INQ-M2", "title": "Test", "status": "active"},
            db=db,
        )
        result = rfq_store.match_sender_to_vendor("unknown@example.com", db=db)
        assert result is None

    def test_match_case_insensitive(self, db):
        rfq_store.create_inquiry(
            {"inquiry_id": "INQ-M3", "title": "Test", "status": "active"},
            db=db,
        )
        rfq_store.add_vendor_to_inquiry(
            "INQ-M3",
            {"vendor_id": "v1", "company_en": "V1", "contact_email": "Sales@V1.COM"},
            db=db,
        )
        result = rfq_store.match_sender_to_vendor("sales@v1.com", db=db)
        assert result is not None
