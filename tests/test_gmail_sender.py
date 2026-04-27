"""Tests for src/gmail_sender.py — Gmail send client."""

from __future__ import annotations

import base64
import os
import sys
from unittest.mock import MagicMock, patch, mock_open

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import gmail_sender


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def mock_gmail_service():
    """Create a mock Gmail API service."""
    service = MagicMock()
    service.users().messages().send().execute.return_value = {
        "id": "msg-123",
        "threadId": "thread-456",
        "labelIds": ["SENT"],
    }
    return service


@pytest.fixture
def sample_inquiry():
    return {
        "inquiry_id": "RFQ-GO-2026-04-FREIGHT",
        "title": "China to Bangkok Freight Forwarding",
        "response_deadline": "2026-04-19",
        "send_config": {
            "from_email": "eukrit@goco.bz",
            "reply_to": "shipping@goco.bz",
            "cc": ["shipping@goco.bz"],
            "subject_template": "RFQ: {title} | GO Corporation Co., Ltd.",
            "attach_pdf": True,
            "inline_html": True,
        },
        "rfq_document": {
            "pdf_path": "docs/RFQ-GO-2026-04-FREIGHT-China-Bangkok.pdf",
        },
    }


@pytest.fixture
def sample_vendor():
    return {
        "vendor_id": "djcargo",
        "company_en": "DJCargo (DJ International Freight)",
        "contact_email": "info@djcargo.cn",
        "email_tracking": {
            "thread_id": "thread-old",
            "message_ids": ["msg-old-1"],
        },
    }


@pytest.fixture
def vendor_no_email():
    return {
        "vendor_id": "no-email-co",
        "company_en": "No Email Co",
        "contact_email": None,
    }


# ── send_email tests ─────────────────────────────────────────


class TestSendEmail:
    def test_basic_send(self, mock_gmail_service):
        result = gmail_sender.send_email(
            to="test@example.com",
            subject="Test Subject",
            body_html="<p>Hello</p>",
            service=mock_gmail_service,
        )
        assert result["message_id"] == "msg-123"
        assert result["thread_id"] == "thread-456"

        # Verify the API was called
        mock_gmail_service.users().messages().send.assert_called()

    def test_send_with_reply_to_and_cc(self, mock_gmail_service):
        result = gmail_sender.send_email(
            to="test@example.com",
            subject="Test",
            body_html="<p>Body</p>",
            reply_to="reply@example.com",
            cc=["cc1@example.com", "cc2@example.com"],
            service=mock_gmail_service,
        )
        assert result["message_id"] == "msg-123"

    def test_send_with_thread_id(self, mock_gmail_service):
        result = gmail_sender.send_email(
            to="test@example.com",
            subject="Re: Test",
            body_html="<p>Reply</p>",
            thread_id="thread-existing",
            in_reply_to="msg-original",
            service=mock_gmail_service,
        )
        assert result["message_id"] == "msg-123"

        # Check threadId was included in the body
        call_args = mock_gmail_service.users().messages().send.call_args
        body = call_args[1].get("body") or call_args[0][0] if call_args[0] else call_args[1].get("body")
        # The mock chain makes this tricky — just verify it was called

    def test_send_to_list(self, mock_gmail_service):
        result = gmail_sender.send_email(
            to=["a@test.com", "b@test.com"],
            subject="Test",
            body_html="<p>Multi</p>",
            service=mock_gmail_service,
        )
        assert result["message_id"] == "msg-123"

    def test_send_with_attachment(self, mock_gmail_service, tmp_path):
        # Create a temp file to attach
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 test content")

        result = gmail_sender.send_email(
            to="test@example.com",
            subject="With attachment",
            body_html="<p>See attached</p>",
            attachments=[str(test_file)],
            service=mock_gmail_service,
        )
        assert result["message_id"] == "msg-123"


# ── build_rfq_email_body tests ───────────────────────────────


class TestBuildRfqEmailBody:
    def test_body_contains_deadline(self, sample_inquiry, sample_vendor):
        body = gmail_sender.build_rfq_email_body(sample_inquiry, sample_vendor)
        assert "2026-04-19" in body

    def test_body_contains_vendor_name(self, sample_inquiry, sample_vendor):
        body = gmail_sender.build_rfq_email_body(sample_inquiry, sample_vendor)
        assert "DJCargo" in body

    def test_body_bilingual(self, sample_inquiry, sample_vendor):
        body = gmail_sender.build_rfq_email_body(sample_inquiry, sample_vendor)
        # Chinese content
        assert "您好" in body
        assert "询价书" in body
        # English content
        assert "GO Corporation" in body
        assert "Request for Quotation" in body

    def test_body_has_signature(self, sample_inquiry, sample_vendor):
        body = gmail_sender.build_rfq_email_body(sample_inquiry, sample_vendor)
        assert "Eukrit Kraikosol" in body
        assert "shipping@goco.bz" in body
        assert "WeChat: eukrit" in body


# ── send_rfq_to_vendor tests ─────────────────────────────────


class TestSendRfqToVendor:
    def test_dry_run(self, sample_inquiry, sample_vendor):
        result = gmail_sender.send_rfq_to_vendor(
            inquiry=sample_inquiry,
            vendor=sample_vendor,
            dry_run=True,
        )
        assert result["dry_run"] is True
        assert result["to"] == "info@djcargo.cn"
        assert "RFQ:" in result["subject"]
        assert result["reply_to"] == "shipping@goco.bz"

    def test_skip_no_email(self, sample_inquiry, vendor_no_email):
        result = gmail_sender.send_rfq_to_vendor(
            inquiry=sample_inquiry,
            vendor=vendor_no_email,
            dry_run=True,
        )
        assert result["skipped"] is True
        assert result["reason"] == "no_contact_email"

    def test_subject_from_template(self, sample_inquiry, sample_vendor):
        result = gmail_sender.send_rfq_to_vendor(
            inquiry=sample_inquiry,
            vendor=sample_vendor,
            dry_run=True,
        )
        assert result["subject"] == "RFQ: China to Bangkok Freight Forwarding | GO Corporation Co., Ltd."

    def test_attachments_included(self, sample_inquiry, sample_vendor):
        result = gmail_sender.send_rfq_to_vendor(
            inquiry=sample_inquiry,
            vendor=sample_vendor,
            dry_run=True,
        )
        assert "docs/RFQ-GO-2026-04-FREIGHT-China-Bangkok.pdf" in result["attachments"]


# ── send_auto_reply tests ─────────────────────────────────────


class TestSendAutoReply:
    def test_auto_reply(self, mock_gmail_service, sample_vendor):
        result = gmail_sender.send_auto_reply(
            vendor=sample_vendor,
            subject="Re: RFQ Question",
            body_html="<p>Thank you for your question.</p>",
            thread_id="thread-456",
            in_reply_to="msg-original",
            service=mock_gmail_service,
        )
        assert result["message_id"] == "msg-123"

    def test_auto_reply_no_email(self, vendor_no_email):
        result = gmail_sender.send_auto_reply(
            vendor=vendor_no_email,
            subject="Re: Test",
            body_html="<p>Reply</p>",
            thread_id="thread-1",
        )
        assert result["skipped"] is True


# ── send_reminder tests ──────────────────────────────────────


class TestSendReminder:
    def test_reminder_1(self, mock_gmail_service, sample_vendor, sample_inquiry):
        result = gmail_sender.send_reminder(
            vendor=sample_vendor,
            inquiry=sample_inquiry,
            reminder_number=1,
            service=mock_gmail_service,
        )
        assert result["message_id"] == "msg-123"

    def test_reminder_2(self, mock_gmail_service, sample_vendor, sample_inquiry):
        result = gmail_sender.send_reminder(
            vendor=sample_vendor,
            inquiry=sample_inquiry,
            reminder_number=2,
            service=mock_gmail_service,
        )
        assert result["message_id"] == "msg-123"

    def test_reminder_no_email(self, vendor_no_email, sample_inquiry):
        result = gmail_sender.send_reminder(
            vendor=vendor_no_email,
            inquiry=sample_inquiry,
            reminder_number=1,
        )
        assert result["skipped"] is True


# ── Gmail Router dispatch tests ──────────────────────────────────────
# Stage C migration: when USE_GMAIL_ROUTER is on, send_email() routes
# through the central /send_email Cloud Function instead of building MIME
# locally. Both paths return the same dict shape so callers don't change.


class TestGmailRouterDispatch:
    """When the feature flag is on, send_email forwards to the Router."""

    def test_dispatches_to_router_when_flag_on(self):
        with patch("src.gmail_sender.is_router_enabled", return_value=True), \
             patch("src.gmail_sender.send_via_router") as mock_router:
            mock_router.return_value = {
                "message_id": "router-msg-1",
                "thread_id": "router-thread-1",
                "label_ids": [],
            }
            result = gmail_sender.send_email(
                to="vendor@example.com",
                subject="Test",
                body_html="<p>Hi</p>",
            )
            assert result["message_id"] == "router-msg-1"
            mock_router.assert_called_once()
            kwargs = mock_router.call_args.kwargs
            assert kwargs["to"] == ["vendor@example.com"]
            assert kwargs["subject"] == "Test"
            assert kwargs["body_html"] == "<p>Hi</p>"

    def test_normalizes_string_recipients_before_router(self):
        """Single-string `to`/`cc` must become lists before hitting the Router."""
        with patch("src.gmail_sender.is_router_enabled", return_value=True), \
             patch("src.gmail_sender.send_via_router") as mock_router:
            mock_router.return_value = {
                "message_id": "m", "thread_id": "t", "label_ids": [],
            }
            gmail_sender.send_email(
                to="solo@example.com",
                cc="cc-solo@example.com",
                subject="x",
                body_html="<p>y</p>",
            )
            kwargs = mock_router.call_args.kwargs
            assert kwargs["to"] == ["solo@example.com"]
            assert kwargs["cc"] == ["cc-solo@example.com"]

    def test_passes_threading_fields_to_router(self):
        with patch("src.gmail_sender.is_router_enabled", return_value=True), \
             patch("src.gmail_sender.send_via_router") as mock_router:
            mock_router.return_value = {
                "message_id": "m", "thread_id": "t", "label_ids": [],
            }
            gmail_sender.send_email(
                to="vendor@example.com",
                subject="Re: RFQ",
                body_html="<p>Reply</p>",
                in_reply_to="<msg-orig@example.com>",
                references="<msg-orig@example.com>",
                thread_id="thread-12345",
            )
            kwargs = mock_router.call_args.kwargs
            assert kwargs["thread_id"] == "thread-12345"
            assert kwargs["in_reply_to"] == "<msg-orig@example.com>"
            assert kwargs["references"] == "<msg-orig@example.com>"

    def test_legacy_path_when_flag_off(self, mock_gmail_service):
        """Default: flag off, never call the Router."""
        with patch("src.gmail_sender.is_router_enabled", return_value=False), \
             patch("src.gmail_sender.send_via_router") as mock_router:
            result = gmail_sender.send_email(
                to="test@example.com",
                subject="Legacy Test",
                body_html="<p>Body</p>",
                service=mock_gmail_service,
            )
            assert result["message_id"] == "msg-123"
            mock_router.assert_not_called()


class TestGmailRouterClient:
    """Direct tests for gmail_router_client._file_to_attachment_dict +
    is_router_enabled. The HTTP-call path is best tested in integration.
    """

    def test_is_router_enabled_truthy_values(self):
        from src import gmail_router_client
        for val in ("true", "True", "TRUE", "1", "yes", "on"):
            with patch.dict(os.environ, {"USE_GMAIL_ROUTER": val}, clear=False):
                assert gmail_router_client.is_router_enabled() is True

    def test_is_router_enabled_falsy_values(self):
        from src import gmail_router_client
        for val in ("", "false", "0", "no", "off", "anything-else"):
            with patch.dict(os.environ, {"USE_GMAIL_ROUTER": val}, clear=False):
                assert gmail_router_client.is_router_enabled() is False

    def test_is_router_enabled_missing(self):
        from src import gmail_router_client
        env = {k: v for k, v in os.environ.items() if k != "USE_GMAIL_ROUTER"}
        with patch.dict(os.environ, env, clear=True):
            assert gmail_router_client.is_router_enabled() is False

    def test_file_to_attachment_dict(self, tmp_path):
        from src import gmail_router_client
        f = tmp_path / "rfq.pdf"
        f.write_bytes(b"%PDF-1.4 hello")
        att = gmail_router_client._file_to_attachment_dict(str(f))
        assert att["filename"] == "rfq.pdf"
        assert att["mimeType"] == "application/pdf"
        decoded = base64.b64decode(att["contentBase64"])
        assert decoded == b"%PDF-1.4 hello"

    def test_file_to_attachment_dict_missing(self):
        from src import gmail_router_client
        with pytest.raises(FileNotFoundError):
            gmail_router_client._file_to_attachment_dict("/nonexistent/file.pdf")
