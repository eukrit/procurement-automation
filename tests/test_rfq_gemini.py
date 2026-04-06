"""Tests for src/parsers/rfq_gemini.py — Gemini classification and extraction."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.parsers import rfq_gemini


# ── Helpers ───────────────────────────────────────────────────


def _mock_gemini_response(json_data: dict) -> MagicMock:
    """Create a mock Gemini response with .text returning JSON string."""
    response = MagicMock()
    response.text = json.dumps(json_data)
    return response


# ── classify_vendor_response tests ────────────────────────────


class TestClassifyVendorResponse:
    @patch.object(rfq_gemini, "GEMINI_ENABLED", False)
    def test_disabled_returns_default(self):
        result = rfq_gemini.classify_vendor_response(
            sender="test@test.com",
            subject="Test",
            body="Test body",
        )
        assert result["is_rfq_response"] is False
        assert result["intent"] == "unrelated"
        assert result["confidence"] == 0.0

    @patch.object(rfq_gemini, "_get_client")
    @patch.object(rfq_gemini, "GEMINI_ENABLED", True)
    def test_rate_quote_classification(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.return_value = _mock_gemini_response({
            "is_rfq_response": True,
            "intent": "rate_quote",
            "confidence": 0.95,
            "summary": "Vendor provided sea and land freight rates",
            "questions_from_vendor": [],
            "has_rate_data": True,
            "has_attachment": False,
            "missing_fields": ["payment_terms"],
            "language": "en",
            "urgency": "normal",
            "should_escalate": False,
            "escalation_reason": None,
        })

        result = rfq_gemini.classify_vendor_response(
            sender="sales@djcargo.cn",
            subject="Re: RFQ: China to Bangkok Freight",
            body="Dear Eukrit, here are our rates: Sea LCL 4200 THB/CBM...",
        )
        assert result["is_rfq_response"] is True
        assert result["intent"] == "rate_quote"
        assert result["confidence"] == 0.95
        assert result["has_rate_data"] is True

    @patch.object(rfq_gemini, "_get_client")
    @patch.object(rfq_gemini, "GEMINI_ENABLED", True)
    def test_question_classification(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.return_value = _mock_gemini_response({
            "is_rfq_response": True,
            "intent": "question",
            "confidence": 0.88,
            "summary": "Vendor asking about annual volume and HS codes",
            "questions_from_vendor": [
                "What is your annual shipping volume?",
                "What HS codes do your products fall under?",
            ],
            "has_rate_data": False,
            "has_attachment": False,
            "missing_fields": [],
            "language": "zh",
            "urgency": "normal",
            "should_escalate": False,
            "escalation_reason": None,
        })

        result = rfq_gemini.classify_vendor_response(
            sender="info@csc.cc",
            subject="Re: RFQ",
            body="您好，请问贵司的年运输量大概多少？",
        )
        assert result["intent"] == "question"
        assert len(result["questions_from_vendor"]) == 2
        assert result["language"] == "zh"

    @patch.object(rfq_gemini, "_get_client")
    @patch.object(rfq_gemini, "GEMINI_ENABLED", True)
    def test_decline_classification(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.return_value = _mock_gemini_response({
            "is_rfq_response": True,
            "intent": "decline",
            "confidence": 0.92,
            "summary": "Vendor declined, does not service Thailand route",
            "questions_from_vendor": [],
            "has_rate_data": False,
            "has_attachment": False,
            "missing_fields": [],
            "language": "en",
            "urgency": "normal",
            "should_escalate": False,
            "escalation_reason": None,
        })

        result = rfq_gemini.classify_vendor_response(
            sender="info@example.com",
            subject="Re: RFQ",
            body="Sorry, we don't service Thailand.",
        )
        assert result["intent"] == "decline"

    @patch.object(rfq_gemini, "_get_client")
    @patch.object(rfq_gemini, "GEMINI_ENABLED", True)
    def test_gemini_error_returns_safe_default(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("API quota exceeded")

        result = rfq_gemini.classify_vendor_response(
            sender="test@test.com",
            subject="Test",
            body="Test",
        )
        assert result["is_rfq_response"] is False
        assert result["should_escalate"] is True
        assert "quota" in result["escalation_reason"].lower()


# ── extract_vendor_rates tests ────────────────────────────────


class TestExtractVendorRates:
    @patch.object(rfq_gemini, "GEMINI_ENABLED", False)
    def test_disabled_returns_empty(self):
        result = rfq_gemini.extract_vendor_rates(body="Some rates here")
        assert result["rates"] == {}
        assert result["confidence"] == 0.0

    @patch.object(rfq_gemini, "_get_client")
    @patch.object(rfq_gemini, "GEMINI_ENABLED", True)
    def test_full_extraction(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.return_value = _mock_gemini_response({
            "rates": {
                "d2d_sea_lcl_per_cbm": 4200,
                "d2d_sea_lcl_per_kg": 32,
                "d2d_land_per_cbm": 6800,
                "d2d_land_per_kg": 45,
                "transit_sea_days": 15,
                "transit_land_days": 8,
                "billing_rule": "charge the higher of CBM or KG",
                "payment_terms": "30 days after delivery",
                "currency": "THB",
            },
            "capabilities": {
                "warehouse_china": True,
                "customs_clearance": True,
                "wechat_support": True,
            },
            "missing_fields": ["last_mile_standard", "insurance_rate"],
            "notes": "Rates valid until end of Q2 2026",
            "confidence": 0.88,
        })

        result = rfq_gemini.extract_vendor_rates(
            body="Sea LCL: 4200 THB/CBM, Land: 6800 THB/CBM...",
            vendor_name="DJCargo",
            vendor_company="DJ International Freight",
        )
        assert result["rates"]["d2d_sea_lcl_per_cbm"] == 4200
        assert result["rates"]["d2d_land_per_cbm"] == 6800
        assert result["capabilities"]["warehouse_china"] is True
        assert "last_mile_standard" in result["missing_fields"]
        assert result["confidence"] == 0.88

    @patch.object(rfq_gemini, "_get_client")
    @patch.object(rfq_gemini, "GEMINI_ENABLED", True)
    def test_extraction_with_attachment(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.return_value = _mock_gemini_response({
            "rates": {"d2d_sea_lcl_per_cbm": 3900},
            "capabilities": {},
            "missing_fields": [],
            "notes": "Extracted from attached PDF rate card",
            "confidence": 0.75,
        })

        result = rfq_gemini.extract_vendor_rates(
            body="Please see attached rate card.",
            attachment_text="Rate Card 2026: Sea LCL Guangzhou-Bangkok 3900 THB/CBM",
        )
        assert result["rates"]["d2d_sea_lcl_per_cbm"] == 3900

    @patch.object(rfq_gemini, "_get_client")
    @patch.object(rfq_gemini, "GEMINI_ENABLED", True)
    def test_extraction_error(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("timeout")

        result = rfq_gemini.extract_vendor_rates(body="test")
        assert result["rates"] == {}
        assert result["confidence"] == 0.0


# ── generate_auto_reply tests ─────────────────────────────────


class TestGenerateAutoReply:
    @patch.object(rfq_gemini, "GEMINI_ENABLED", False)
    def test_disabled_returns_escalation(self):
        result = rfq_gemini.generate_auto_reply(
            vendor_name="Test",
            vendor_company="Test Co",
            vendor_email_body="Question?",
        )
        assert result["should_escalate"] is True
        assert result["confidence"] == 0.0

    @patch.object(rfq_gemini, "_get_client")
    @patch.object(rfq_gemini, "GEMINI_ENABLED", True)
    def test_high_confidence_reply(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.return_value = _mock_gemini_response({
            "subject": "Re: RFQ Question",
            "body_html": "<div><p>Thank you for your question. Our annual volume is 200-400 CBM.</p></div>",
            "body_language": "en",
            "confidence": 0.92,
            "should_escalate": False,
            "escalation_reason": None,
            "answers_given": ["Annual volume: 200-400 CBM"],
            "info_requested": [],
        })

        result = rfq_gemini.generate_auto_reply(
            vendor_name="CSC Logistics",
            vendor_company="Cargo Speeds Co.",
            vendor_email_body="What is your annual shipping volume?",
            questions=["What is your annual shipping volume?"],
            auto_reply_context="Annual volume: 200-400 CBM across 30-50 POs.",
        )
        assert result["confidence"] == 0.92
        assert result["should_escalate"] is False
        assert "200-400 CBM" in result["body_html"]

    @patch.object(rfq_gemini, "_get_client")
    @patch.object(rfq_gemini, "GEMINI_ENABLED", True)
    def test_escalation_reply(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.return_value = _mock_gemini_response({
            "subject": "Re: Contract Terms",
            "body_html": "",
            "body_language": "en",
            "confidence": 0.3,
            "should_escalate": True,
            "escalation_reason": "Vendor asking about exclusive contract and minimum commitment",
            "answers_given": [],
            "info_requested": [],
        })

        result = rfq_gemini.generate_auto_reply(
            vendor_name="Test",
            vendor_company="Test Co",
            vendor_email_body="We require a minimum 3-year exclusive contract.",
            questions=["Will you sign an exclusive contract?"],
        )
        assert result["should_escalate"] is True
        assert "exclusive" in result["escalation_reason"].lower()

    @patch.object(rfq_gemini, "_get_client")
    @patch.object(rfq_gemini, "GEMINI_ENABLED", True)
    def test_error_returns_escalation(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.models.generate_content.side_effect = Exception("API error")

        result = rfq_gemini.generate_auto_reply(
            vendor_name="Test",
            vendor_company="Test Co",
            vendor_email_body="Question",
        )
        assert result["should_escalate"] is True
        assert result["confidence"] == 0.0
