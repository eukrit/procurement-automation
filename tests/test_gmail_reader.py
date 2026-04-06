"""Tests for src/gmail_reader.py — Gmail watch and history fetch."""

from __future__ import annotations

import base64
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import gmail_reader


# ── strip_html tests ──────────────────────────────────────────


class TestStripHtml:
    def test_basic_tags(self):
        html = "<p>Hello <strong>world</strong></p>"
        text = gmail_reader.strip_html(html)
        assert "Hello" in text
        assert "world" in text
        assert "<" not in text

    def test_br_to_newline(self):
        html = "Line 1<br>Line 2<br/>Line 3"
        text = gmail_reader.strip_html(html)
        assert "Line 1" in text
        assert "Line 2" in text

    def test_entities(self):
        html = "&amp; &lt;tag&gt; &nbsp;"
        text = gmail_reader.strip_html(html)
        assert "& <tag>" in text

    def test_empty(self):
        assert gmail_reader.strip_html("") == ""

    def test_plain_text(self):
        assert gmail_reader.strip_html("no html here") == "no html here"


# ── _extract_body tests ──────────────────────────────────────


class TestExtractBody:
    def test_plain_text_body(self):
        payload = {
            "mimeType": "text/plain",
            "body": {
                "data": base64.urlsafe_b64encode(b"Hello plain text").decode(),
            },
        }
        text, html = gmail_reader._extract_body(payload)
        assert text == "Hello plain text"
        assert html == ""

    def test_html_body(self):
        payload = {
            "mimeType": "text/html",
            "body": {
                "data": base64.urlsafe_b64encode(b"<p>Hello HTML</p>").decode(),
            },
        }
        text, html = gmail_reader._extract_body(payload)
        assert text == ""
        assert "<p>Hello HTML</p>" in html

    def test_multipart_body(self):
        payload = {
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {
                        "data": base64.urlsafe_b64encode(b"Plain part").decode(),
                    },
                },
                {
                    "mimeType": "text/html",
                    "body": {
                        "data": base64.urlsafe_b64encode(b"<p>HTML part</p>").decode(),
                    },
                },
            ],
        }
        text, html = gmail_reader._extract_body(payload)
        assert text == "Plain part"
        assert "<p>HTML part</p>" in html

    def test_empty_body(self):
        payload = {"mimeType": "text/plain", "body": {}}
        text, html = gmail_reader._extract_body(payload)
        assert text == ""
        assert html == ""


# ── _extract_attachments tests ────────────────────────────────


class TestExtractAttachments:
    def test_no_attachments(self):
        payload = {"mimeType": "text/plain", "body": {"data": ""}}
        atts = gmail_reader._extract_attachments(payload, "msg-1")
        assert atts == []

    def test_single_attachment(self):
        payload = {
            "mimeType": "application/pdf",
            "filename": "rates.pdf",
            "body": {"attachmentId": "att-123", "size": 50000},
        }
        atts = gmail_reader._extract_attachments(payload, "msg-1")
        assert len(atts) == 1
        assert atts[0]["filename"] == "rates.pdf"
        assert atts[0]["gmail_attachment_id"] == "att-123"

    def test_multipart_with_attachment(self):
        payload = {
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "text/plain", "body": {"data": ""}},
                {
                    "mimeType": "application/pdf",
                    "filename": "quote.pdf",
                    "body": {"attachmentId": "att-456", "size": 100000},
                },
            ],
        }
        atts = gmail_reader._extract_attachments(payload, "msg-2")
        assert len(atts) == 1
        assert atts[0]["filename"] == "quote.pdf"


# ── History ID state tests ────────────────────────────────────


class TestHistoryIdState:
    @patch.object(gmail_reader, "_get_state_db")
    def test_get_last_history_id(self, mock_db):
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"history_id": "12345"}
        mock_db.return_value.collection.return_value.document.return_value.get.return_value = mock_doc

        result = gmail_reader.get_last_history_id()
        assert result == "12345"

    @patch.object(gmail_reader, "_get_state_db")
    def test_get_last_history_id_none(self, mock_db):
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_db.return_value.collection.return_value.document.return_value.get.return_value = mock_doc

        result = gmail_reader.get_last_history_id()
        assert result is None

    @patch.object(gmail_reader, "_get_state_db")
    def test_set_last_history_id(self, mock_db):
        gmail_reader.set_last_history_id("99999")
        mock_db.return_value.collection.return_value.document.return_value.set.assert_called_once()


# ── get_new_messages tests ────────────────────────────────────


class TestGetNewMessages:
    @patch.object(gmail_reader, "get_gmail_readonly_service")
    @patch.object(gmail_reader, "get_last_history_id", return_value=None)
    @patch.object(gmail_reader, "set_last_history_id")
    @patch.object(gmail_reader, "_get_state_db")
    def test_no_history_initializes(self, mock_db, mock_set, mock_get, mock_service):
        mock_svc = MagicMock()
        mock_service.return_value = mock_svc
        mock_svc.users().getProfile().execute.return_value = {
            "historyId": "50000",
        }

        messages = gmail_reader.get_new_messages(service=mock_svc, db=mock_db.return_value)
        assert messages == []
        mock_set.assert_called_with("50000", db=mock_db.return_value)

    @patch.object(gmail_reader, "get_gmail_readonly_service")
    @patch.object(gmail_reader, "set_last_history_id")
    @patch.object(gmail_reader, "_get_state_db")
    def test_no_new_messages(self, mock_db, mock_set, mock_service):
        mock_svc = MagicMock()
        mock_service.return_value = mock_svc
        mock_svc.users().history().list().execute.return_value = {
            "historyId": "50001",
            "history": [],
        }

        messages = gmail_reader.get_new_messages(
            history_id="50000", service=mock_svc, db=mock_db.return_value
        )
        assert messages == []
