#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
freight_calculator_china_thai.py
GO Corporation — China-Thai Landed Cost Calculator

Route: China (Foshan / Guangzhou) → Bangkok, Thailand
Agent: Gift Somlak (Murazame / Profreight)

China-Thai service is a door-to-door consolidated freight service.
No customs clearance, no import duty, no VAT, no cargo insurance required.
Cost = EXW + freight + extras (factory-to-port, oversized, last-mile).

Usage:
    Edit the INPUT block below, then run:
        python scripts/freight_calculator_china_thai.py

    Or import and call programmatically:
        from scripts.freight_calculator_china_thai import calculate_landed_cost
        result = calculate_landed_cost(exw_thb=150000, length_cm=285, ...)

Rate sources:
  - Sea/Land rates: Gift Somlak rate card (China-Thai, confirmed 2025)
  - Implied FX: 32.76 THB/USD (derived from Gift rate card)

RATE TABLE (Gift Somlak / China-Thai, confirmed):
  Sea  CBM : 4,600 THB/CBM
  Sea  KGS :    35 THB/KG
  Land CBM : 7,200 THB/CBM
  Land KGS :    48 THB/KG

Billing rule: charge whichever is HIGHER — CBM-based or KGS-based.
"""

from __future__ import annotations

import argparse
import json
import sys

# ──────────────────────────────────────────────
#  RATE CARD (Gift Somlak, confirmed 2025)
# ──────────────────────────────────────────────

RATE_CARD = {
    "sea_per_cbm": 4600,
    "sea_per_kg": 35,
    "land_per_cbm": 7200,
    "land_per_kg": 48,
    "source": "Gift Somlak rate card 2025",
}

# ──────────────────────────────────────────────
#  INPUT — edit this block for interactive use
# ──────────────────────────────────────────────

PRODUCT_NAME = "ED 70 Aluminum Folding Door"

# EXW price — set one of the two:
EXW_PRICE_FOREIGN = 0            # Foreign currency amount (set 0 to use THB)
EXW_CURRENCY = "USD"             # "USD" | "EUR" | "CNY"
FX_RATE_TO_THB = 32.76           # THB per 1 unit of foreign currency

EXW_PRICE_THB = 150000           # Set in THB directly — overrides FX calc if > 0

# Package dimensions and weight
PKG_LENGTH_CM = 285
PKG_WIDTH_CM = 30
PKG_HEIGHT_CM = 280
PKG_ACTUAL_KG = 120

# Freight mode
MODE = "sea"                     # "sea" | "land"

# Factory → port delivery cost (ask supplier or Gift)
FACTORY_TO_PORT_THB = 0

# Oversized length surcharge (ask Gift for items >250cm in any dimension)
OVERSIZED_SURCHARGE_THB = 0

# Last-mile Bangkok delivery
# Confirmed from Slack #shipping-china-thai:
#   Standard 4-wheel truck: THB 1,500–2,500
#   Oversized item, 6-wheel truck: THB 3,500
LAST_MILE_THB = 3500


# ──────────────────────────────────────────────
#  CALCULATION ENGINE
# ──────────────────────────────────────────────

def calc_cbm(l_cm: float, w_cm: float, h_cm: float) -> float:
    """Volume in CBM: L x W x H (cm) / 1,000,000."""
    return (l_cm * w_cm * h_cm) / 1_000_000


def calc_freight(
    mode: str,
    cbm: float,
    actual_kg: float,
    rate_card: dict | None = None,
) -> dict:
    """Calculate freight cost using the 'charge the higher' billing rule.

    Returns dict with: freight_thb, cbm_cost, kg_cost, billing_basis, mode.
    """
    rc = rate_card or RATE_CARD

    if mode == "sea":
        rate_cbm = rc["sea_per_cbm"]
        rate_kg = rc["sea_per_kg"]
    elif mode == "land":
        rate_cbm = rc["land_per_cbm"]
        rate_kg = rc["land_per_kg"]
    else:
        raise ValueError(f"Unknown mode: {mode}. China-Thai supports 'sea' or 'land'.")

    cbm_cost = cbm * rate_cbm
    kg_cost = actual_kg * rate_kg
    freight = max(cbm_cost, kg_cost)
    basis = "CBM" if cbm_cost >= kg_cost else "KGS"

    return {
        "freight_thb": round(freight, 2),
        "cbm_cost": round(cbm_cost, 2),
        "kg_cost": round(kg_cost, 2),
        "billing_basis": basis,
        "rate_cbm": rate_cbm,
        "rate_kg": rate_kg,
        "mode": mode,
    }


def calculate_landed_cost(
    exw_thb: float = 0,
    exw_foreign: float = 0,
    fx_rate: float = 32.76,
    length_cm: float = 0,
    width_cm: float = 0,
    height_cm: float = 0,
    actual_kg: float = 0,
    mode: str = "sea",
    factory_to_port_thb: float = 0,
    oversized_surcharge_thb: float = 0,
    last_mile_thb: float = 3500,
    rate_card: dict | None = None,
) -> dict:
    """Calculate full landed cost for a China-Thai shipment.

    No insurance, no import duty, no VAT — Gift Somlak handles
    consolidated door-to-door delivery.

    Returns a dict with all cost components and totals.
    """
    # EXW price
    if exw_thb > 0:
        exw = exw_thb
    else:
        exw = exw_foreign * fx_rate

    # Dimensions
    cbm = calc_cbm(length_cm, width_cm, height_cm)

    # Freight
    freight = calc_freight(mode, cbm, actual_kg, rate_card)

    # Extras
    extras = factory_to_port_thb + oversized_surcharge_thb

    # Total landed cost
    landed = exw + freight["freight_thb"] + extras + last_mile_thb

    # Freight as percentage of goods
    freight_pct = (freight["freight_thb"] / exw * 100) if exw > 0 else 0

    return {
        "exw_thb": round(exw, 2),
        "cbm": round(cbm, 4),
        "actual_kg": actual_kg,
        "freight": freight,
        "factory_to_port_thb": factory_to_port_thb,
        "oversized_surcharge_thb": oversized_surcharge_thb,
        "last_mile_thb": last_mile_thb,
        "freight_pct_of_goods": round(freight_pct, 2),
        "landed_cost_thb": round(landed, 2),
        "sell_price_20pct_gm": round(landed / 0.80, 2),
        "sell_price_25pct_gm": round(landed / 0.75, 2),
        "sell_price_30pct_gm": round(landed / 0.70, 2),
        "rate_card": rate_card or RATE_CARD,
    }


# ──────────────────────────────────────────────
#  CLI OUTPUT
# ──────────────────────────────────────────────

def print_report(result: dict, product_name: str = "") -> None:
    """Print a formatted landed cost report."""
    sep = "=" * 60
    div = "-" * 60
    f = result["freight"]

    print(sep)
    print("  GO CORPORATION — CHINA-THAI LANDED COST CALCULATOR")
    print(sep)
    if product_name:
        print(f"  Product  : {product_name}")
    print(f"  Mode     : {f['mode'].upper()}")
    print(f"  Agent    : Gift Somlak (Murazame / Profreight)")
    print()

    print(f"  EXW price              : THB {result['exw_thb']:>12,.2f}")
    print(f"  Volume                 : {result['cbm']:.4f} CBM")
    print(f"  Actual weight          : {result['actual_kg']} kg")
    print()

    print(f"  --- FREIGHT ({f['mode'].upper()}) ---")
    print(f"  Rate (CBM)             : THB {f['rate_cbm']:,.0f}/CBM")
    print(f"  Rate (KGS)             : THB {f['rate_kg']:,.0f}/KG")
    print(f"  CBM cost ({result['cbm']:.4f} CBM) : THB {f['cbm_cost']:>10,.2f}")
    print(f"  KGS cost ({result['actual_kg']} kg)      : THB {f['kg_cost']:>10,.2f}")
    arrow = "<<< BILLED"
    if f["billing_basis"] == "CBM":
        print(f"  >> Billing basis: CBM  {arrow}  (CBM >= KGS)")
    else:
        print(f"  >> Billing basis: KGS  {arrow}  (KGS > CBM)")
    print(f"  Freight cost           : THB {f['freight_thb']:>12,.2f}")

    extras = result["factory_to_port_thb"] + result["oversized_surcharge_thb"]
    if extras > 0:
        print(f"  Factory->port          : THB {result['factory_to_port_thb']:>12,.2f}")
        print(f"  Oversized surcharge    : THB {result['oversized_surcharge_thb']:>12,.2f}")

    print(f"  Last-mile delivery     : THB {result['last_mile_thb']:>12,.2f}")
    print()
    print(f"  Freight % of goods     : {result['freight_pct_of_goods']:.1f}%")

    print()
    print(div)
    print(f"  TOTAL LANDED COST      : THB {result['landed_cost_thb']:>12,.2f}")
    print(div)
    print()

    print(f"  Min sell price (20% GM): THB {result['sell_price_20pct_gm']:>12,.2f}")
    print(f"  At 25% GM              : THB {result['sell_price_25pct_gm']:>12,.2f}")
    print(f"  At 30% GM              : THB {result['sell_price_30pct_gm']:>12,.2f}")
    print()

    # Breakdown
    print("  COST BREAKDOWN:")
    landed = result["landed_cost_thb"]
    items = [
        ("EXW product price", result["exw_thb"]),
        ("Freight", f["freight_thb"]),
        ("Factory->port / oversize", extras),
        ("Last-mile delivery", result["last_mile_thb"]),
    ]
    for name, amt in items:
        if amt == 0:
            continue
        pct = (amt / landed * 100) if landed > 0 else 0
        print(f"    {name:<26} THB {amt:>10,.0f}  ({pct:.1f}%)")
    print(div)
    print()
    print("  NOTE: China-Thai service — no insurance, duty, or VAT.")
    print("  Rate source: Gift Somlak rate card (2025).")
    print("  Always get a fresh quote before quoting customer.")
    print(sep)


def main():
    parser = argparse.ArgumentParser(
        description="China-Thai freight landed cost calculator"
    )
    parser.add_argument("--exw-thb", type=float, default=0, help="EXW price in THB")
    parser.add_argument("--exw-foreign", type=float, default=0, help="EXW price in foreign currency")
    parser.add_argument("--fx-rate", type=float, default=32.76, help="FX rate to THB")
    parser.add_argument("--length", type=float, default=0, help="Package length (cm)")
    parser.add_argument("--width", type=float, default=0, help="Package width (cm)")
    parser.add_argument("--height", type=float, default=0, help="Package height (cm)")
    parser.add_argument("--kg", type=float, default=0, help="Actual weight (kg)")
    parser.add_argument("--mode", choices=["sea", "land"], default="sea", help="Freight mode")
    parser.add_argument("--last-mile", type=float, default=3500, help="Last-mile delivery THB")
    parser.add_argument("--factory-to-port", type=float, default=0, help="Factory-to-port cost THB")
    parser.add_argument("--oversized", type=float, default=0, help="Oversized surcharge THB")
    parser.add_argument("--product", type=str, default="", help="Product name")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    # Use CLI args if provided, otherwise fall back to INPUT block constants
    exw_thb = args.exw_thb or EXW_PRICE_THB
    exw_foreign = args.exw_foreign or EXW_PRICE_FOREIGN
    fx_rate = args.fx_rate or FX_RATE_TO_THB
    length = args.length or PKG_LENGTH_CM
    width = args.width or PKG_WIDTH_CM
    height = args.height or PKG_HEIGHT_CM
    kg = args.kg or PKG_ACTUAL_KG
    mode = args.mode or MODE
    product = args.product or PRODUCT_NAME

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    result = calculate_landed_cost(
        exw_thb=exw_thb,
        exw_foreign=exw_foreign,
        fx_rate=fx_rate,
        length_cm=length,
        width_cm=width,
        height_cm=height,
        actual_kg=kg,
        mode=mode,
        factory_to_port_thb=args.factory_to_port,
        oversized_surcharge_thb=args.oversized,
        last_mile_thb=args.last_mile,
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_report(result, product_name=product)

    return result


if __name__ == "__main__":
    main()
