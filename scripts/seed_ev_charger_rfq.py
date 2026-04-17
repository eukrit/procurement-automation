#!/usr/bin/env python3
"""
seed_ev_charger_rfq.py — Seed Firestore with Chinese EV wallbox (V2H/V2G)
supplier vendors, the EV charger RFQ inquiry, and the EV charger template.

Target product: iocharger-style OCPP 2.0.1 V2H/V2G 7 kW AC wallbox
(benchmark: Xiamen Galaxy Camphol Technology Co., Ltd. — NOT contacted).

Usage:
    python scripts/seed_ev_charger_rfq.py
    python scripts/seed_ev_charger_rfq.py --template-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rfq_store import (
    add_vendor_to_inquiry,
    create_inquiry,
    get_db,
    get_inquiry,
    get_template,
    set_template,
    upsert_vendor_directory,
)

DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "china_ev_charger_suppliers.json"
)

INQUIRY_ID = "RFQ-GO-2026-04-EV-CHARGER"
TEMPLATE_ID = "ev-charger-rfq-v1"


def _slugify(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"\s*\(.*?\)\s*", " ", slug)
    slug = re.sub(r"[^a-z0-9\s]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug.strip("-")


def build_vendor_data(company: dict) -> dict:
    vendor_id = _slugify(company["name_en"])
    return {
        "vendor_id": vendor_id,
        "company_en": company["name_en"],
        "company_cn": company.get("name_cn"),
        "website": company.get("website"),
        "contact_email": company.get("contact_email"),
        "contact_email_alt": company.get("contact_email_alt"),
        "contact_phone": company.get("phone"),
        "contact_phone_alt": company.get("phone_alt"),
        "preferred_channel": "email",
        "languages": company.get("languages", ["English", "Chinese"]),
        "source": "web_research",
        "source_notes": company.get("notes", ""),
        "email_verified": company.get("email_verified", False),
        "email_notes": company.get("email_notes", ""),
        "master_vendor_ref": f"vendor_directory/{vendor_id}",
    }


def build_vendor_directory_entry(company: dict) -> dict:
    vendor_id = _slugify(company["name_en"])

    contacts = []
    email = company.get("contact_email")
    if email:
        contacts.append({
            "name": "",
            "email": email,
            "phone": company.get("phone"),
            "role": "sales",
        })
    email_alt = company.get("contact_email_alt")
    if email_alt:
        contacts.append({
            "name": "",
            "email": email_alt,
            "role": "sales_alt",
        })

    return {
        "vendor_id": vendor_id,
        "company_en": company["name_en"],
        "company_cn": company.get("name_cn"),
        "website": company.get("website"),
        "contacts": contacts,
        "categories": ["ev-charger"],
        "subcategories": ["v2h-v2g", "ac-wallbox"],
        "services": [],
        "regions_china": [company.get("city")] if company.get("city") else [],
        "certifications": company.get("certifications_claimed", []),
        "languages": company.get("languages", ["English", "Chinese"]),
        "campaign_history": [],
        "overall_rating": None,
        "notes": company.get("notes", ""),
        "tags": _build_tags(company),
        "product_claims": {
            "power_ratings_kw": company.get("power_ratings_kw", []),
            "connectors": company.get("connectors_claimed", []),
            "v2h_v2g": company.get("v2h_v2g_claimed", False),
            "ocpp_version": company.get("ocpp_version_claimed"),
            "iso15118": company.get("iso15118_claimed", False),
            "hubject_plug_and_charge": company.get("hubject_plug_and_charge_claimed", False),
        },
    }


def _build_tags(company: dict) -> list[str]:
    tags = []
    if company.get("v2h_v2g_claimed"):
        tags.append("v2h-v2g")
    if company.get("iso15118_claimed"):
        tags.append("iso15118")
    if company.get("hubject_plug_and_charge_claimed"):
        tags.append("plug-and-charge")
    ocpp = (company.get("ocpp_version_claimed") or "").lower()
    if "2.0.1" in ocpp:
        tags.append("ocpp-2-0-1")
    elif "2.0" in ocpp:
        tags.append("ocpp-2-0")
    elif "1.6" in ocpp:
        tags.append("ocpp-1-6")
    if not company.get("email_verified", False):
        tags.append("email-unverified")
    return tags


def seed_inquiry(db) -> None:
    """Create the EV charger RFQ inquiry (idempotent)."""
    existing = get_inquiry(INQUIRY_ID, db=db)
    if existing:
        print(f"  Inquiry already exists: {INQUIRY_ID} (skipping create)")
        return

    config = {
        "inquiry_id": INQUIRY_ID,
        "title": "7kW OCPP 2.0.1 V2H/V2G AC Wallbox + Comparable Models",
        "category": "ev-charger",
        "subcategory": "v2h-v2g-ac-wallbox",
        "template_id": TEMPLATE_ID,
        "rfq_document": {
            "html_url": None,
            "pdf_path": None,
            "drive_url": None,
        },
        "send_config": {
            "from_email": "eukrit@goco.bz",
            "reply_to": "shipping@goco.bz",
            "cc": ["shipping@goco.bz"],
            "subject_template": "RFQ: {title} | GO Corporation Co., Ltd.",
            "language": "bilingual",
            "attach_pdf": False,
            "inline_html": True,
        },
        "automation_config": {
            "auto_reply_enabled": True,
            "auto_reply_min_confidence": 0.8,
            "approval_required_for": ["pricing", "terms", "commitments", "legal"],
            "max_auto_replies_per_vendor": 3,
            "reminder_day_1": 5,
            "reminder_day_2": 7,
            "escalate_day": 10,
            "slack_channel": "C0AC8GK12N6",
        },
        "scoring_config": {
            "weights": {
                "price": 0.40,
                "capability": 0.25,
                "lead_time": 0.15,
                "certification": 0.10,
                "payment_terms": 0.10,
            },
            "baseline": {
                "source": "Xiamen Galaxy Camphol (iocharger) Alibaba listing, April 2026",
                "unit_price_thb_low": 10473.19,
                "unit_price_thb_high": 13418.77,
                "moq": 2,
            },
        },
        "response_deadline": "2026-05-01",
        "status": "draft",
        "vendor_count": 0,
        "created_by": "eukrit@goco.bz",
    }
    create_inquiry(config, db=db)
    print(f"  Created inquiry: {INQUIRY_ID}")


def seed_vendors(db, companies: list[dict]) -> None:
    for company in companies:
        vendor_data = build_vendor_data(company)
        vendor_id = add_vendor_to_inquiry(INQUIRY_ID, vendor_data, db=db)
        print(f"  Added vendor to inquiry: {vendor_id}")

        directory_entry = build_vendor_directory_entry(company)
        upsert_vendor_directory(directory_entry, db=db)
        print(f"  Upserted vendor_directory: {vendor_id}")


def seed_template(db) -> None:
    """Seed the EV charger RFQ template (idempotent)."""
    template = {
        "name": "China V2H/V2G AC Wallbox RFQ",
        "category": "ev-charger",
        "subcategory": "v2h-v2g-ac-wallbox",
        "version": 1,
        "email_template": {
            "subject": "RFQ: {title} | GO Corporation Co., Ltd.",
            "body_cn": (
                "您好，\n\n"
                "GO Corporation Co., Ltd.（บริษัท จีโอ คอร์ปอเรชั่น จำกัด）是泰国一家专注于"
                "住宅、酒店及商业项目的设计和采购公司。我们正在为泰国市场评估"
                "V2H/V2G 双向 AC 壁挂式充电桩，对标产品为 7kW OCPP 2.0.1 Type 2 / Type 1 双向壁挂机。\n\n"
                "请就以下产品提供正式报价：\n"
                "• 7kW 单相 AC V2H/V2G 双向壁挂充电桩（OCPP 2.0.1，Type 2 和 Type 1 两种插头）\n"
                "• 并同时提供贵司适用于家用 V2H/V2G 场景的其他相近型号"
                "（如 11kW / 22kW 三相、DC 双向壁挂机、不同认证等级的型号等）\n\n"
                "需要报价和规格信息：\n"
                "• FOB（厦门 / 深圳 / 宁波）及 DDP 曼谷（泰国）含税到门价（美元或人民币）\n"
                "• 按 MOQ 阶梯报价：2台 / 10台 / 50台 / 100台\n"
                "• 交货期（从定金到出厂，到曼谷）\n"
                "• 保修年限和保修范围\n"
                "• 付款条件（建议 30% 定金 / 70% 见提单）\n"
                "• 认证状态：CE、Hubject EVSE Check、Plug & Charge、ISO 15118、OCPP 2.0.1 Core Certified、"
                "IEC 61851、TUV、UL 等\n"
                "• 固件升级机制（OTA 支持与否）\n"
                "• 是否支持 OEM / ODM 定制（外壳、贴牌、App）\n"
                "• 样机可用性和样机价格\n\n"
                "请在 {deadline} 前回复本邮件报价。如需进一步信息，请随时通过邮件、电话或微信与我联系。\n\n"
                "期待贵司回复。"
            ),
            "body_en": (
                "Dear {vendor_name},\n\n"
                "GO Corporation Co., Ltd. is a Thai-based procurement and project delivery company. "
                "We are evaluating V2H/V2G bidirectional AC wallbox EV chargers for the Thai market, "
                "benchmarked against a 7 kW OCPP 2.0.1 Type 2 / Type 1 bidirectional wallbox.\n\n"
                "Please quote on the following:\n\n"
                "1. Your closest match to: 7 kW single-phase AC V2H/V2G bidirectional wallbox, "
                "OCPP 2.0.1, Type 2 AND Type 1 plug variants.\n"
                "2. Your full range of comparable models suitable for residential V2H/V2G use — "
                "including any 11 kW / 22 kW three-phase, DC bidirectional wallbox, or higher-certification "
                "variants you offer in the same application space.\n\n"
                "For every model you quote, please provide:\n"
                "• FOB price (Xiamen / Shenzhen / Ningbo) AND DDP Bangkok (Thailand) landed price, "
                "in USD or CNY, per unit.\n"
                "• MOQ-tiered pricing at 2 / 10 / 50 / 100 units.\n"
                "• Lead time from deposit (ex-works) through delivery to Bangkok.\n"
                "• Warranty: years + scope of coverage.\n"
                "• Payment terms (we prefer 30% deposit / 70% against B/L).\n"
                "• Certification status: CE, Hubject EVSE Check, Plug & Charge, ISO 15118, "
                "OCPP 2.0.1 Core Certified, IEC 61851, TUV, UL — please confirm which are in hand "
                "vs. in progress.\n"
                "• Firmware update mechanism (is OTA supported?).\n"
                "• OEM / ODM customization options (enclosure, branding, mobile app).\n"
                "• Sample availability and sample unit pricing.\n\n"
                "Kindly submit your quotation by {deadline} by replying to this email. "
                "Reply-To is shipping@goco.bz; please keep that address on any reply. "
                "Questions welcome by email, phone, or WeChat.\n\n"
                "Looking forward to your response."
            ),
        },
        "required_fields": [
            "unit_price_fob_usd",
            "unit_price_ddp_bkk_thb",
            "moq",
            "lead_time_weeks",
            "ocpp_version",
            "power_rating_kw",
            "v2h_support",
            "v2g_support",
            "connector_types",
            "certifications",
            "warranty_months",
            "payment_terms",
        ],
        "extraction_schema": {
            "rates": {
                "unit_price_fob_usd": {"type": "number", "unit": "USD/unit"},
                "unit_price_ddp_bkk_thb": {"type": "number", "unit": "THB/unit"},
                "unit_price_ddp_bkk_usd": {"type": "number", "unit": "USD/unit"},
                "moq": {"type": "number", "unit": "units"},
                "tier_price_2_units": {"type": "number", "unit": "USD/unit"},
                "tier_price_10_units": {"type": "number", "unit": "USD/unit"},
                "tier_price_50_units": {"type": "number", "unit": "USD/unit"},
                "tier_price_100_units": {"type": "number", "unit": "USD/unit"},
                "sample_unit_price": {"type": "number", "unit": "USD"},
                "lead_time_weeks": {"type": "number", "unit": "weeks"},
                "warranty_months": {"type": "number", "unit": "months"},
                "payment_terms": {"type": "string"},
                "currency": {"type": "string"},
                "incoterm": {"type": "string"},
            },
            "product_specs": {
                "model_number": {"type": "string"},
                "power_rating_kw": {"type": "number", "unit": "kW"},
                "phase": {"type": "string"},
                "ac_or_dc": {"type": "string"},
                "connector_types": {"type": "array"},
                "ocpp_version": {"type": "string"},
                "iso15118_supported": {"type": "boolean"},
                "plug_and_charge": {"type": "boolean"},
                "v2h_support": {"type": "boolean"},
                "v2g_support": {"type": "boolean"},
                "v2l_support": {"type": "boolean"},
                "ip_rating": {"type": "string"},
                "efficiency_pct": {"type": "number"},
                "firmware_ota": {"type": "boolean"},
            },
            "capabilities": {
                "oem_odm_available": {"type": "boolean"},
                "white_label_branding": {"type": "boolean"},
                "mobile_app_customization": {"type": "boolean"},
                "ce_certified": {"type": "boolean"},
                "hubject_evse_check": {"type": "boolean"},
                "ocpp_2_0_1_core_certified": {"type": "boolean"},
                "iec_61851_certified": {"type": "boolean"},
                "tuv_certified": {"type": "boolean"},
                "ul_certified": {"type": "boolean"},
            },
        },
        "auto_reply_context": (
            "GO Corporation Co., Ltd. is a Thailand-based procurement and project company "
            "evaluating V2H/V2G bidirectional AC wallbox EV chargers for the Thai residential "
            "market. Benchmark product is 7 kW OCPP 2.0.1 V2H/V2G Type 2/Type 1 wallbox "
            "(reference: iocharger by Xiamen Galaxy Camphol). Pilot quantity target: 10-50 "
            "units for a first order. Ship-to: Bangkok, Thailand. Preferred payment terms: "
            "30% deposit / 70% against B/L. Required certifications baseline: CE + OCPP 2.0.1 "
            "Core. Nice-to-have: Hubject, Plug & Charge, ISO 15118, TUV. Questions about "
            "Thailand-specific certifications (TISI) should be escalated — we need to check."
        ),
    }
    set_template(TEMPLATE_ID, template, db=db)
    print(f"  Created/updated template: {TEMPLATE_ID}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--template-only",
        action="store_true",
        help="Only seed the template, skip inquiry and vendors",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  PROCUREMENT AUTOMATION — EV CHARGER RFQ SEED")
    print("=" * 60)
    print()

    db = get_db()

    if args.template_only:
        print("[1/1] Creating EV charger RFQ template...")
        seed_template(db)
        print()
        print("=" * 60)
        print(f"  TEMPLATE SEEDED: {TEMPLATE_ID}")
        print("=" * 60)
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    companies = data["companies"]
    print(f"Loaded {len(companies)} companies from {os.path.basename(DATA_FILE)}")
    print()

    print("[1/3] Creating EV charger RFQ template...")
    seed_template(db)
    print()

    print("[2/3] Creating RFQ inquiry...")
    seed_inquiry(db)
    print()

    print(f"[3/3] Seeding {len(companies)} vendors...")
    seed_vendors(db, companies)
    print()

    print("=" * 60)
    print("  SEED COMPLETE")
    print(f"  Inquiry:          {INQUIRY_ID}")
    print(f"  Vendors seeded:   {len(companies)}")
    print(f"  Template:         {TEMPLATE_ID}")
    print(f"  Slack routing:    #areda-mike (per-inquiry override)")
    print(f"  Firestore DB:     procurement-automation (asia-southeast1)")
    print("=" * 60)


if __name__ == "__main__":
    main()
