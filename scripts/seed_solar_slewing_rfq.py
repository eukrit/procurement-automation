#!/usr/bin/env python3
"""
seed_solar_slewing_rfq.py — Seed Firestore with Chinese slewing drive
supplier vendors, the Solar Slewing RFQ inquiry, and the slewing drive template.

Target product: SDE9 worm-drive slewing drive for dual-axis solar tracking systems
(benchmark: Jimmy Technology (Huizhou) Co., Ltd. — NOT contacted).

Usage:
    python scripts/seed_solar_slewing_rfq.py
    python scripts/seed_solar_slewing_rfq.py --template-only
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
    os.path.dirname(__file__), "..", "data", "china_solar_slewing_drive_suppliers.json"
)

INQUIRY_ID = "RFQ-GO-2026-04-SOLAR-SLEWING"
TEMPLATE_ID = "solar-slewing-rfq-v1"


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

    tags = _build_tags(company)

    return {
        "vendor_id": vendor_id,
        "company_en": company["name_en"],
        "company_cn": company.get("name_cn"),
        "website": company.get("website"),
        "contacts": contacts,
        "categories": ["solar-tracker"],
        "subcategories": ["slewing-drive", "worm-drive"],
        "services": [],
        "regions_china": [company.get("city")] if company.get("city") else [],
        "certifications": company.get("certifications_claimed", []),
        "languages": company.get("languages", ["English", "Chinese"]),
        "campaign_history": [],
        "overall_rating": None,
        "notes": company.get("notes", ""),
        "tags": tags,
        "product_claims": {
            "sde_series_available": company.get("sde_series_available", False),
            "solar_tracker_experience": company.get("solar_tracker_experience", False),
        },
    }


def _build_tags(company: dict) -> list[str]:
    tags = []
    if company.get("sde_series_available"):
        tags.append("sde-series")
    if company.get("solar_tracker_experience"):
        tags.append("solar-tracker")
    if not company.get("email_verified", False):
        tags.append("email-unverified")
    return tags


def seed_inquiry(db) -> None:
    """Create the Solar Slewing RFQ inquiry (idempotent)."""
    existing = get_inquiry(INQUIRY_ID, db=db)
    if existing:
        print(f"  Inquiry already exists: {INQUIRY_ID} (skipping create)")
        return

    config = {
        "inquiry_id": INQUIRY_ID,
        "title": "SDE9 Slewing Drive — Dual Axis Solar Tracker",
        "category": "solar-tracker",
        "subcategory": "slewing-drive",
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
            "slack_channel": "#areda-mike",
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
                "source": "Jimmy Technology (Huizhou) Co., Ltd. Alibaba listing, April 2026",
                "unit_price_thb_2_99": 14856.19,
                "unit_price_thb_100_499": 13205.50,
                "unit_price_thb_500_999": 11554.81,
                "unit_price_thb_1000_plus": 10564.40,
                "bore_size_inch": 9,
                "od_inch": 12,
            },
        },
        "response_deadline": "2026-05-07",
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
    """Seed the Solar Slewing Drive RFQ template (idempotent)."""
    template = {
        "name": "China SDE9 Solar Slewing Drive RFQ",
        "category": "solar-tracker",
        "subcategory": "slewing-drive",
        "version": 1,
        "email_template": {
            "subject": "RFQ: {title} | GO Corporation Co., Ltd.",
            "body_cn": (
                "您好，\n\n"
                "GO Corporation Co., Ltd.（บริษัท จีโอ คอร์ปอเรชั่น จำกัด）是泰国一家专注于"
                "住宅、酒店及商业项目的设计和采购公司。我们目前正在为泰国市场的双轴太阳能跟踪系统"
                "采购回转驱动器，对标产品为 SDE9 蜗轮蜗杆驱动回转驱动器（孔径9英寸，外径12英寸/30.48厘米）。\n\n"
                "请就以下产品提供正式报价：\n"
                "• 贵司最接近 SDE9 规格的蜗轮蜗杆回转驱动器（孔径约9英寸，外径约12英寸），"
                "适用于双轴太阳能跟踪系统\n"
                "• 同时请提供贵司完整的太阳能跟踪器回转驱动系列产品（SE6、SE7、SE9、SE12等，"
                "包括不同孔径、扭矩及认证等级的型号）\n\n"
                "每个报价型号需提供以下信息：\n"
                "• FOB（惠州/广州/深圳）及 DDP 曼谷（泰国）含税到门价（美元或人民币，每台）\n"
                "• 按 MOQ 阶梯报价：2台 / 10台 / 50台 / 100台\n"
                "• 交货期（从定金到出厂，到曼谷）\n"
                "• 保修年限和保修范围\n"
                "• 付款条件（建议 30% 定金 / 70% 见提单）\n"
                "• 防护等级（IP 等级）\n"
                "• 额定输出扭矩（Nm）及最大扭矩\n"
                "• 回程间隙（弧分）\n"
                "• 是否具备自锁功能\n"
                "• 认证状态：CE、ISO 9001 等\n"
                "• OEM / ODM 定制选项（外壳、标志、颜色）\n"
                "• 样品供货情况及样品价格\n\n"
                "**请随报价附上贵司完整产品目录（PDF 格式优先）及完整价目表。**\n\n"
                "请在 {deadline} 前回复本邮件报价。如需进一步信息，请随时通过邮件、电话或微信与我联系。\n\n"
                "期待贵司回复。"
            ),
            "body_en": (
                "Dear {vendor_name},\n\n"
                "GO Corporation Co., Ltd. is a Thai-based procurement and project delivery company "
                "specialising in residential, hospitality, and commercial projects. We are sourcing "
                "slewing drives for dual-axis solar tracking systems for the Thai market, benchmarked "
                "against an SDE9 worm-drive slewing drive (9\" bore, 12\" / 30.48 cm OD).\n\n"
                "Please quote on the following:\n\n"
                "1. Your closest equivalent to the SDE9 specification — worm-drive slewing drive, "
                "~9\" bore, ~12\" OD, suitable for dual-axis solar trackers.\n"
                "2. Your full range of solar tracker slewing drives "
                "(SE6, SE7, SE9, SE12, or equivalent series — different bore sizes, torque ratings, "
                "and certification tiers).\n\n"
                "For every model you quote, please provide:\n"
                "• FOB price (Huizhou / Guangzhou / Shenzhen) AND DDP Bangkok (Thailand) landed price, "
                "in USD or CNY, per unit.\n"
                "• MOQ-tiered pricing at 2 / 10 / 50 / 100 units.\n"
                "• Lead time from deposit (ex-works) through delivery to Bangkok.\n"
                "• Warranty: years + scope of coverage.\n"
                "• Payment terms (we prefer 30% deposit / 70% against B/L).\n"
                "• IP protection rating.\n"
                "• Rated output torque (Nm) and maximum torque.\n"
                "• Backlash (arc-minutes).\n"
                "• Self-locking: yes/no.\n"
                "• Certification status: CE, ISO 9001, others — please confirm what is in hand.\n"
                "• OEM / ODM customization options (housing, logo, colour).\n"
                "• Sample availability and sample unit pricing.\n\n"
                "**Please also attach your full product catalog (PDF preferred) and complete price list "
                "for your slewing drive range.**\n\n"
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
            "bore_size_inch",
            "od_inch",
            "output_torque_nm",
            "backlash_arcmin",
            "self_locking",
            "ip_rating",
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
                "bore_size_inch": {"type": "number", "unit": "inches"},
                "od_inch": {"type": "number", "unit": "inches"},
                "drive_type": {"type": "string"},
                "output_torque_nm": {"type": "number", "unit": "Nm"},
                "max_torque_nm": {"type": "number", "unit": "Nm"},
                "backlash_arcmin": {"type": "number", "unit": "arc-minutes"},
                "self_locking": {"type": "boolean"},
                "ip_rating": {"type": "string"},
                "gear_ratio": {"type": "string"},
                "tilt_moment_capacity_knm": {"type": "number", "unit": "kNm"},
                "weight_kg": {"type": "number", "unit": "kg"},
            },
            "capabilities": {
                "ce_certified": {"type": "boolean"},
                "iso_9001_certified": {"type": "boolean"},
                "oem_odm_available": {"type": "boolean"},
                "white_label_branding": {"type": "boolean"},
                "solar_tracker_experience": {"type": "boolean"},
                "catalog_attached": {"type": "boolean"},
                "price_list_attached": {"type": "boolean"},
            },
        },
        "auto_reply_context": (
            "GO Corporation Co., Ltd. is a Thailand-based procurement and project company "
            "sourcing slewing drives for dual-axis solar tracking systems for the Thai market. "
            "Benchmark product: SDE9 worm-drive slewing drive, 9\" bore, 12\" OD "
            "(reference: Jimmy Technology (Huizhou) Co., Ltd., Alibaba April 2026, THB 14,856/unit at 2–99 pcs). "
            "Pilot quantity target: 10–50 units for a first order. "
            "Ship-to: Bangkok, Thailand. "
            "Preferred payment terms: 30% deposit / 70% against B/L. "
            "Required certifications baseline: CE + ISO 9001. "
            "Application: dual-axis solar tracker — self-locking worm drive is essential. "
            "Questions about Thai TISI or local certifications should be escalated."
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
    print("  PROCUREMENT AUTOMATION — SOLAR SLEWING DRIVE RFQ SEED")
    print("=" * 60)
    print()

    db = get_db()

    if args.template_only:
        print("[1/1] Creating solar slewing drive RFQ template...")
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

    print("[1/3] Creating solar slewing drive RFQ template...")
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
    print(f"  Deadline:         2026-05-07")
    print(f"  Slack routing:    #areda-mike (per-inquiry override)")
    print(f"  Gmail label:      Suppliers/Solar")
    print(f"  Firestore DB:     procurement-automation (asia-southeast1)")
    print("=" * 60)


if __name__ == "__main__":
    main()
