"""Tests for src/rfq_workflow.py — state machine, auto-reply decisions, reminders."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import rfq_workflow


# ── should_auto_reply tests ───────────────────────────────────


class TestShouldAutoReply:
    def _make_classification(self, **overrides):
        base = {
            "intent": "question",
            "confidence": 0.9,
            "questions_from_vendor": ["What is your annual volume?"],
            "missing_fields": [],
            "should_escalate": False,
            "escalation_reason": None,
            "language": "en",
        }
        base.update(overrides)
        return base

    def _make_vendor(self, auto_reply_count=0):
        return {
            "vendor_id": "test-vendor",
            "email_tracking": {"auto_reply_count": auto_reply_count},
        }

    def _make_inquiry(self, min_confidence=0.8, max_auto=3):
        return {
            "automation_config": {
                "auto_reply_min_confidence": min_confidence,
                "max_auto_replies_per_vendor": max_auto,
            },
        }

    def test_high_confidence_auto_send(self):
        result = rfq_workflow.should_auto_reply(
            classification=self._make_classification(confidence=0.92),
            vendor=self._make_vendor(),
            inquiry=self._make_inquiry(),
        )
        assert result["action"] == "auto_send"

    def test_medium_confidence_draft_approval(self):
        result = rfq_workflow.should_auto_reply(
            classification=self._make_classification(confidence=0.7),
            vendor=self._make_vendor(),
            inquiry=self._make_inquiry(),
        )
        assert result["action"] == "draft_approval"

    def test_low_confidence_escalate(self):
        result = rfq_workflow.should_auto_reply(
            classification=self._make_classification(confidence=0.4),
            vendor=self._make_vendor(),
            inquiry=self._make_inquiry(),
        )
        assert result["action"] == "escalate"

    def test_auto_reply_limit_reached(self):
        result = rfq_workflow.should_auto_reply(
            classification=self._make_classification(confidence=0.95),
            vendor=self._make_vendor(auto_reply_count=3),
            inquiry=self._make_inquiry(max_auto=3),
        )
        assert result["action"] == "escalate"
        assert "limit" in result["reason"].lower()

    def test_gemini_flagged_escalation(self):
        result = rfq_workflow.should_auto_reply(
            classification=self._make_classification(
                should_escalate=True,
                escalation_reason="Legal terms detected",
            ),
            vendor=self._make_vendor(),
            inquiry=self._make_inquiry(),
        )
        assert result["action"] == "escalate"

    def test_escalation_keyword_in_question(self):
        result = rfq_workflow.should_auto_reply(
            classification=self._make_classification(
                questions_from_vendor=["Do you require an exclusive contract?"],
            ),
            vendor=self._make_vendor(),
            inquiry=self._make_inquiry(),
        )
        assert result["action"] == "escalate"
        assert "exclusive" in result["reason"].lower()

    def test_no_questions_skip(self):
        result = rfq_workflow.should_auto_reply(
            classification=self._make_classification(
                questions_from_vendor=[],
                missing_fields=[],
            ),
            vendor=self._make_vendor(),
            inquiry=self._make_inquiry(),
        )
        assert result["action"] == "skip"

    def test_missing_fields_triggers_reply(self):
        result = rfq_workflow.should_auto_reply(
            classification=self._make_classification(
                questions_from_vendor=[],
                missing_fields=["payment_terms"],
                confidence=0.85,
            ),
            vendor=self._make_vendor(),
            inquiry=self._make_inquiry(),
        )
        assert result["action"] == "auto_send"


# ── check_rate_anomaly tests ─────────────────────────────────


class TestCheckRateAnomaly:
    def test_no_anomaly(self):
        rates = {"d2d_sea_lcl_per_cbm": 4500}
        baseline = {"sea_per_cbm": 4600}
        anomalies = rfq_workflow.check_rate_anomaly(rates, baseline)
        assert anomalies == []

    def test_high_anomaly(self):
        rates = {"d2d_sea_lcl_per_cbm": 15000}
        baseline = {"sea_per_cbm": 4600}
        anomalies = rfq_workflow.check_rate_anomaly(rates, baseline)
        assert len(anomalies) == 1
        assert "3.3x" in anomalies[0]

    def test_low_anomaly(self):
        rates = {"d2d_sea_lcl_per_cbm": 1000}
        baseline = {"sea_per_cbm": 4600}
        anomalies = rfq_workflow.check_rate_anomaly(rates, baseline)
        assert len(anomalies) == 1
        assert "suspiciously low" in anomalies[0]

    def test_missing_rate_no_error(self):
        rates = {"d2d_sea_lcl_per_cbm": None}
        baseline = {"sea_per_cbm": 4600}
        anomalies = rfq_workflow.check_rate_anomaly(rates, baseline)
        assert anomalies == []

    def test_multiple_anomalies(self):
        rates = {
            "d2d_sea_lcl_per_cbm": 20000,
            "d2d_land_per_cbm": 500,
        }
        baseline = {"sea_per_cbm": 4600, "land_per_cbm": 7200}
        anomalies = rfq_workflow.check_rate_anomaly(rates, baseline)
        assert len(anomalies) == 2


# ── get_vendors_needing_reminders tests ───────────────────────


class TestGetVendorsNeedingReminders:
    @patch("src.rfq_workflow.get_inquiry_vendors")
    @patch("src.rfq_workflow.get_workflow_config")
    @patch("src.rfq_workflow.get_inquiry")
    @patch("src.rfq_workflow.get_db")
    def test_day5_reminder(self, mock_db, mock_inq, mock_wf, mock_vendors):
        mock_inq.return_value = {
            "inquiry_id": "TEST",
            "response_deadline": "2099-12-31",
        }
        mock_wf.return_value = {
            "reminder_schedule": {
                "day_1": 5, "day_2": 7, "escalate_day": 10,
                "close_after_deadline_grace_days": 3,
            },
        }
        now = datetime.now(timezone.utc)
        mock_vendors.return_value = [
            {
                "vendor_id": "v1",
                "status": "sent",
                "email_tracking": {
                    "last_outbound_at": now - timedelta(days=6),
                },
                "reminders": {"count": 0},
            },
        ]

        result = rfq_workflow.get_vendors_needing_reminders("TEST", db=mock_db.return_value)
        assert len(result["reminder_1"]) == 1
        assert result["reminder_1"][0]["vendor_id"] == "v1"

    @patch("src.rfq_workflow.get_inquiry_vendors")
    @patch("src.rfq_workflow.get_workflow_config")
    @patch("src.rfq_workflow.get_inquiry")
    @patch("src.rfq_workflow.get_db")
    def test_day10_escalation(self, mock_db, mock_inq, mock_wf, mock_vendors):
        mock_inq.return_value = {
            "inquiry_id": "TEST",
            "response_deadline": "2099-12-31",
        }
        mock_wf.return_value = {
            "reminder_schedule": {
                "day_1": 5, "day_2": 7, "escalate_day": 10,
                "close_after_deadline_grace_days": 3,
            },
        }
        now = datetime.now(timezone.utc)
        mock_vendors.return_value = [
            {
                "vendor_id": "v2",
                "status": "reminder_2",
                "email_tracking": {
                    "last_outbound_at": now - timedelta(days=11),
                },
                "reminders": {"count": 2},
            },
        ]

        result = rfq_workflow.get_vendors_needing_reminders("TEST", db=mock_db.return_value)
        assert len(result["escalate"]) == 1

    @patch("src.rfq_workflow.get_inquiry_vendors")
    @patch("src.rfq_workflow.get_workflow_config")
    @patch("src.rfq_workflow.get_inquiry")
    @patch("src.rfq_workflow.get_db")
    def test_responded_vendor_skipped(self, mock_db, mock_inq, mock_wf, mock_vendors):
        mock_inq.return_value = {
            "inquiry_id": "TEST",
            "response_deadline": "2099-12-31",
        }
        mock_wf.return_value = {
            "reminder_schedule": {
                "day_1": 5, "day_2": 7, "escalate_day": 10,
                "close_after_deadline_grace_days": 3,
            },
        }
        now = datetime.now(timezone.utc)
        mock_vendors.return_value = [
            {
                "vendor_id": "v3",
                "status": "complete_response",
                "email_tracking": {
                    "last_outbound_at": now - timedelta(days=15),
                },
                "reminders": {"count": 0},
            },
        ]

        result = rfq_workflow.get_vendors_needing_reminders("TEST", db=mock_db.return_value)
        assert all(len(v) == 0 for v in result.values())


# ── VALID_TRANSITIONS tests ──────────────────────────────────


class TestValidTransitions:
    def test_draft_can_go_to_sent(self):
        assert "sent" in rfq_workflow.VALID_TRANSITIONS["draft"]

    def test_sent_can_go_to_response(self):
        assert "response_received" in rfq_workflow.VALID_TRANSITIONS["sent"]

    def test_awarded_is_terminal(self):
        assert rfq_workflow.VALID_TRANSITIONS["awarded"] == []

    def test_closed_is_terminal(self):
        assert rfq_workflow.VALID_TRANSITIONS["closed"] == []

    def test_all_states_defined(self):
        expected_states = {
            "draft", "sent", "reminder_1", "reminder_2",
            "response_received", "partial_response", "question_received",
            "awaiting_response", "complete_response", "evaluating",
            "escalated", "declined", "awarded", "not_selected", "closed",
        }
        assert set(rfq_workflow.VALID_TRANSITIONS.keys()) == expected_states
