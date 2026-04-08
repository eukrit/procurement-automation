"""Tests for src/slack_notifier.py — Slack notification functions."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import slack_notifier


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def mock_slack_client():
    client = MagicMock()
    client.chat_postMessage.return_value = MagicMock(data={"ok": True, "ts": "1234.5678"})
    return client


# ── Source tag prefix tests ──────────────────────────────────


class TestSourceTagPrefix:
    def test_all_messages_have_procurement_prefix(self, mock_slack_client):
        slack_notifier.notify_new_response(
            inquiry_id="RFQ-001", vendor_id="v1", vendor_name="Test",
            intent="rate_quote", summary="test", confidence=0.9,
            client=mock_slack_client,
        )
        call_kwargs = mock_slack_client.chat_postMessage.call_args[1]
        assert "[Procurement]" in call_kwargs["text"]


# ── notify_rfq_dispatched tests ──────────────────────────────


class TestNotifyRfqDispatched:
    def test_dispatch_summary(self, mock_slack_client):
        result = slack_notifier.notify_rfq_dispatched(
            inquiry_id="RFQ-001",
            inquiry_title="China to Bangkok Freight",
            sent=10, skipped=3, errors=0,
            vendor_details=[
                {"vendor_id": "djcargo", "status": "sent", "to": "info@djcargo.cn"},
                {"vendor_id": "no-email", "status": "skipped", "reason": "no_contact_email"},
            ],
            client=mock_slack_client,
        )
        assert result is not None

    def test_dispatch_no_details(self, mock_slack_client):
        result = slack_notifier.notify_rfq_dispatched(
            inquiry_id="RFQ-001", inquiry_title="Test",
            sent=5, skipped=0, errors=0,
            client=mock_slack_client,
        )
        assert result is not None


# ── notify_new_response tests ─────────────────────────────────


class TestNotifyNewResponse:
    def test_rate_quote(self, mock_slack_client):
        result = slack_notifier.notify_new_response(
            inquiry_id="RFQ-001", vendor_id="djcargo", vendor_name="DJCargo",
            intent="rate_quote", summary="Vendor provided sea and land rates",
            confidence=0.95, has_rates=True,
            client=mock_slack_client,
        )
        assert result is not None

    def test_question(self, mock_slack_client):
        result = slack_notifier.notify_new_response(
            inquiry_id="RFQ-001", vendor_id="csc", vendor_name="CSC Logistics",
            intent="question", summary="Asking about volume", confidence=0.88,
            client=mock_slack_client,
        )
        assert result is not None

    def test_decline(self, mock_slack_client):
        result = slack_notifier.notify_new_response(
            inquiry_id="RFQ-001", vendor_id="v1", vendor_name="Declined Co",
            intent="decline", summary="Does not service Thailand", confidence=0.92,
            client=mock_slack_client,
        )
        assert result is not None


# ── notify_escalation tests ──────────────────────────────────


class TestNotifyEscalation:
    def test_with_contacts(self, mock_slack_client):
        result = slack_notifier.notify_escalation(
            inquiry_id="RFQ-001", vendor_id="v1", vendor_name="Test Co",
            reason="Legal terms detected",
            vendor_contacts={"contact_email": "test@test.com", "contact_wechat": "test123"},
            client=mock_slack_client,
        )
        assert result is not None

    def test_without_contacts(self, mock_slack_client):
        result = slack_notifier.notify_escalation(
            inquiry_id="RFQ-001", vendor_id="v1", vendor_name="Test Co",
            reason="Auto-reply limit",
            client=mock_slack_client,
        )
        assert result is not None


# ── notify_auto_reply_sent tests ─────────────────────────────


class TestNotifyAutoReplySent:
    def test_with_answers(self, mock_slack_client):
        result = slack_notifier.notify_auto_reply_sent(
            inquiry_id="RFQ-001", vendor_id="v1", vendor_name="DJCargo",
            confidence=0.92, answers=["Annual volume: 200-400 CBM"],
            client=mock_slack_client,
        )
        assert result is not None


# ── notify_draft_for_approval tests ───────────────────────────


class TestNotifyDraftForApproval:
    def test_draft(self, mock_slack_client):
        result = slack_notifier.notify_draft_for_approval(
            inquiry_id="RFQ-001", vendor_id="v1", vendor_name="CSC Logistics",
            draft_subject="Re: RFQ Question",
            draft_body_preview="Thank you for your inquiry...",
            confidence=0.72,
            client=mock_slack_client,
        )
        assert result is not None


# ── notify_rate_anomaly tests ─────────────────────────────────


class TestNotifyRateAnomaly:
    def test_anomalies(self, mock_slack_client):
        result = slack_notifier.notify_rate_anomaly(
            inquiry_id="RFQ-001", vendor_id="v1", vendor_name="Expensive Co",
            anomalies=["Sea LCL/CBM: 15,000 is 3.3x baseline (4,600)"],
            client=mock_slack_client,
        )
        assert result is not None


# ── notify_reminder_summary tests ─────────────────────────────


class TestNotifyReminderSummary:
    def test_with_actions(self, mock_slack_client):
        result = slack_notifier.notify_reminder_summary(
            inquiry_id="RFQ-001",
            summary={"reminder_1_sent": 3, "reminder_2_sent": 1, "escalated": 2, "closed": 0},
            client=mock_slack_client,
        )
        assert result is not None

    def test_no_actions_returns_none(self, mock_slack_client):
        result = slack_notifier.notify_reminder_summary(
            inquiry_id="RFQ-001",
            summary={"reminder_1_sent": 0, "reminder_2_sent": 0, "escalated": 0, "closed": 0},
            client=mock_slack_client,
        )
        assert result is None


# ── notify_daily_digest tests ─────────────────────────────────


class TestNotifyDailyDigest:
    def test_normal_digest(self, mock_slack_client):
        result = slack_notifier.notify_daily_digest(
            inquiry_id="RFQ-001", inquiry_title="China to Bangkok Freight",
            status="active", vendor_count=13, responded=3,
            status_breakdown={"sent": 8, "response_received": 3, "declined": 1, "draft": 1},
            deadline="2026-04-19", days_remaining=11,
            client=mock_slack_client,
        )
        assert result is not None

    def test_urgent_digest(self, mock_slack_client):
        result = slack_notifier.notify_daily_digest(
            inquiry_id="RFQ-001", inquiry_title="Test",
            status="active", vendor_count=10, responded=2,
            status_breakdown={"sent": 8, "response_received": 2},
            deadline="2026-04-11", days_remaining=2,
            client=mock_slack_client,
        )
        assert result is not None
