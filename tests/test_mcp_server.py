"""Tests for mcp-server/server.py — rate comparison and scoring logic."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "mcp-server"))

from server import _score_vendor_rates, BASELINE, BENCHMARK_SHIPMENT


# ── _score_vendor_rates tests ─────────────────────────────────


class TestScoreVendorRates:
    def test_cheaper_than_baseline(self):
        rates = {"d2d_sea_lcl_per_cbm": 4000, "d2d_sea_lcl_per_kg": 30}
        scores = _score_vendor_rates(rates, BASELINE)
        assert scores["sea_lcl_ratio"] < 1.0
        assert scores["sea_lcl_savings_pct"] > 0

    def test_more_expensive_than_baseline(self):
        rates = {"d2d_sea_lcl_per_cbm": 5500}
        scores = _score_vendor_rates(rates, BASELINE)
        assert scores["sea_lcl_ratio"] > 1.0
        assert scores["sea_lcl_savings_pct"] < 0

    def test_exact_baseline(self):
        rates = {"d2d_sea_lcl_per_cbm": 4600}
        scores = _score_vendor_rates(rates, BASELINE)
        assert scores["sea_lcl_ratio"] == 1.0
        assert scores["sea_lcl_savings_pct"] == 0.0

    def test_land_scoring(self):
        rates = {"d2d_land_per_cbm": 6000}
        scores = _score_vendor_rates(rates, BASELINE)
        assert scores["land_ratio"] < 1.0
        assert scores["land_savings_pct"] > 0

    def test_benchmark_sea_calculation(self):
        rates = {"d2d_sea_lcl_per_cbm": 4600, "d2d_sea_lcl_per_kg": 35}
        scores = _score_vendor_rates(rates, BASELINE)
        assert "benchmark_sea_freight" in scores
        assert "benchmark_sea_landed" in scores
        # CBM cost: 4600 * 2.394 = 11,012.40
        # KG cost: 35 * 120 = 4,200
        # Freight = max(11012.40, 4200) = 11012
        assert scores["benchmark_sea_freight"] == 11012.0
        # Landed = 150000 + 11012 + 3500 = 164512
        assert scores["benchmark_sea_landed"] == 164512.0

    def test_benchmark_land_calculation(self):
        rates = {"d2d_land_per_cbm": 7200, "d2d_land_per_kg": 48}
        scores = _score_vendor_rates(rates, BASELINE)
        assert "benchmark_land_freight" in scores
        # CBM cost: 7200 * 2.394 = 17,236.80
        # KG cost: 48 * 120 = 5,760
        # Freight = max(17236.80, 5760) = 17237
        assert scores["benchmark_land_freight"] == 17237.0

    def test_empty_rates(self):
        scores = _score_vendor_rates({}, BASELINE)
        assert scores == {}

    def test_partial_rates(self):
        rates = {"d2d_sea_lcl_per_cbm": 4200}
        scores = _score_vendor_rates(rates, BASELINE)
        assert "sea_lcl_ratio" in scores
        assert "land_ratio" not in scores
        # Without per-kg rate, still calculates benchmark from CBM only
        assert "benchmark_sea_freight" in scores

    def test_billing_rule_kg_wins(self):
        # When KG cost exceeds CBM cost
        rates = {"d2d_sea_lcl_per_cbm": 2000, "d2d_sea_lcl_per_kg": 100}
        scores = _score_vendor_rates(rates, BASELINE)
        # CBM: 2000 * 2.394 = 4788
        # KG: 100 * 120 = 12000
        # Freight = max(4788, 12000) = 12000
        assert scores["benchmark_sea_freight"] == 12000.0


# ── Baseline constants tests ─────────────────────────────────


class TestBaselineConstants:
    def test_baseline_values(self):
        assert BASELINE["sea_per_cbm"] == 4600
        assert BASELINE["sea_per_kg"] == 35
        assert BASELINE["land_per_cbm"] == 7200
        assert BASELINE["land_per_kg"] == 48

    def test_benchmark_shipment(self):
        assert BENCHMARK_SHIPMENT["cbm"] == 2.394
        assert BENCHMARK_SHIPMENT["kg"] == 120
        assert BENCHMARK_SHIPMENT["exw_thb"] == 150000
