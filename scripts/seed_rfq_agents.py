#!/usr/bin/env python3
"""
seed_rfq_agents.py — Seed Firestore with freight forwarder vendors,
the first RFQ inquiry, procurement template, and workflow config.

Usage:
    python scripts/seed_rfq_agents.py
"""

from __future__ import annotations

import json
import os
import re
import sys

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rfq_store import (
    add_vendor_to_inquiry,
    create_inquiry,
    get_db,
    set_template,
    set_workflow_config,
    upsert_vendor_directory,
)

DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "china_thailand_freight_forwarders.json"
)

INQUIRY_ID = "RFQ-GO-2026-04-FREIGHT"


def _slugify(name: str) -> str:
    slug = name.lower()
    slug = re.sub(r"\s*\(.*?\)\s*", " ", slug)
    slug = re.sub(r"[^a-z0-9\s]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug.strip("-")


def _extract_contact_email(company: dict) -> str | None:
    """Get the primary contact email from various field names."""
    for key in ["contact_email", "email"]:
        if company.get(key):
            return company[key]
    return None


def _extract_contact_email_alt(company: dict) -> str | None:
    for key in ["contact_email_alt"]:
        if company.get(key):
            return company[key]
    return None


def _extract_phone(company: dict) -> str | None:
    for key in ["phone", "phone_wechat_whatsapp"]:
        if company.get(key):
            return company[key]
    return None


def _extract_wechat(company: dict) -> str | None:
    for key in ["whatsapp_wechat", "wechat", "wechat_id"]:
        if company.get(key):
            return company[key]
    return None


def _extract_whatsapp(company: dict) -> str | None:
    for key in ["whatsapp_wechat", "whatsapp"]:
        if company.get(key):
            return company[key]
    return None


def build_vendor_data(company: dict) -> dict:
    """Transform a raw JSON company entry into the vendor schema."""
    vendor_id = _slugify(company["name_en"])
    return {
        "vendor_id": vendor_id,
        "company_en": company["name_en"],
        "company_cn": company.get("name_cn"),
        "website": company.get("website"),
        "contact_email": _extract_contact_email(company),
        "contact_email_alt": _extract_contact_email_alt(company),
        "contact_phone": _extract_phone(company),
        "contact_wechat": _extract_wechat(company),
        "contact_whatsapp": _extract_whatsapp(company),
        "preferred_channel": "email",
        "languages": company.get("languages", []),
        "source": "web_research",
        "source_notes": company.get("notes", ""),
        "master_vendor_ref": f"vendor_directory/{vendor_id}",
    }


def build_vendor_directory_entry(company: dict) -> dict:
    """Transform a raw JSON company entry into the vendor_directory schema."""
    vendor_id = _slugify(company["name_en"])

    contacts = []
    email = _extract_contact_email(company)
    if email:
        contacts.append({
            "name": "",
            "email": email,
            "phone": _extract_phone(company),
            "wechat": _extract_wechat(company),
            "whatsapp": _extract_whatsapp(company),
            "role": "sales",
        })

    return {
        "vendor_id": vendor_id,
        "company_en": company["name_en"],
        "company_cn": company.get("name_cn"),
        "website": company.get("website"),
        "contacts": contacts,
        "categories": ["freight"],
        "subcategories": _build_subcategories(company),
        "services": company.get("services", []),
        "regions_china": company.get("key_regions_china", []),
        "warehouse_locations": (
            ["Guangdong"] if company.get("warehouse_guangdong") else []
        ),
        "certifications": company.get("certifications", []),
        "languages": company.get("languages", []),
        "api_available": company.get("api_tracking_portal", False),
        "tracking_portal": company.get("api_tracking_portal", False),
        "campaign_history": [],
        "overall_rating": None,
        "notes": company.get("notes", ""),
        "tags": _build_tags(company),
    }


def _build_subcategories(company: dict) -> list[str]:
    subs = ["china-thailand"]
    modes = company.get("transport_modes", [])
    if "Sea" in modes:
        subs.append("sea-lcl")
    if "Land" in modes:
        subs.append("land-transport")
    if "Air" in modes:
        subs.append("air-freight")
    if "Rail" in modes:
        subs.append("rail-freight")
    return subs


def _build_tags(company: dict) -> list[str]:
    tags = []
    if company.get("warehouse_guangdong"):
        tags.append("guangdong")
    if company.get("canton_fair_service"):
        tags.append("canton-fair")
    if company.get("wechat_support"):
        tags.append("wechat")
    thai_spec = company.get("thailand_specifics", {})
    if thai_spec.get("based_in_thailand"):
        tags.append("thailand-based")
    return tags


def seed_inquiry(db) -> None:
    """Create the freight RFQ inquiry."""
    config = {
        "inquiry_id": INQUIRY_ID,
        "title": "China to Bangkok Freight Forwarding",
        "category": "freight",
        "subcategory": "china-thailand",
        "template_id": "freight-agent-rfq-v1",
        "rfq_document": {
            "html_url": None,
            "pdf_path": "docs/RFQ-GO-2026-04-FREIGHT-China-Bangkok.pdf",
            "drive_url": None,
        },
        "send_config": {
            "from_email": "eukrit@goco.bz",
            "reply_to": "shipping@goco.bz",
            "cc": ["shipping@goco.bz"],
            "subject_template": "RFQ: {title} | GO Corporation Co., Ltd.",
            "language": "bilingual",
            "attach_pdf": True,
            "inline_html": True,
        },
        "automation_config": {
            "auto_reply_enabled": True,
            "auto_reply_min_confidence": 0.8,
            "approval_required_for": [
                "pricing",
                "terms",
                "commitments",
                "legal",
            ],
            "max_auto_replies_per_vendor": 3,
            "reminder_day_1": 5,
            "reminder_day_2": 7,
            "escalate_day": 10,
            "slack_channel": "C08VD9PRSCU",
        },
        "scoring_config": {
            "weights": {
                "price": 0.40,
                "transit": 0.20,
                "capability": 0.20,
                "communication": 0.10,
                "payment_terms": 0.10,
            },
            "baseline": {
                "source": "Gift Somlak rate card 2025",
                "sea_per_cbm": 4600,
                "sea_per_kg": 35,
                "land_per_cbm": 7200,
                "land_per_kg": 48,
            },
        },
        "response_deadline": "2026-04-19",
        "status": "draft",
        "vendor_count": 0,
        "created_by": "eukrit@goco.bz",
    }
    create_inquiry(config, db=db)
    print(f"  Created inquiry: {INQUIRY_ID}")


def seed_vendors(db, companies: list[dict]) -> None:
    """Seed vendors into the inquiry and vendor_directory."""
    for company in companies:
        vendor_data = build_vendor_data(company)
        vendor_id = add_vendor_to_inquiry(INQUIRY_ID, vendor_data, db=db)
        print(f"  Added vendor to inquiry: {vendor_id}")

        directory_entry = build_vendor_directory_entry(company)
        upsert_vendor_directory(directory_entry, db=db)
        print(f"  Upserted vendor_directory: {vendor_id}")


def seed_template(db) -> None:
    """Seed the freight agent RFQ template."""
    template = {
        "name": "China-Thailand Freight Agent RFQ",
        "category": "freight",
        "version": 1,
        "email_template": {
            "subject": "RFQ: {title} | GO Corporation Co., Ltd.",
            "body_cn": (
                "您好，\n\n"
                "GO Corporation Co., Ltd.（บริษัท จีโอ คอร์ปอเรชั่น จำกัด）是泰国一家专注于"
                "酒店、商业及住宅室内装修项目的设计和采购公司。我们从中国74家供应商处采购家具、"
                "灯具、游乐设备及建筑材料，年运输量约200-400立方米。\n\n"
                "我们目前正在寻找新的中国至曼谷物流合作伙伴。随函附上我们的询价书（RFQ），"
                "涵盖海运拼箱/整箱、陆运、门到门及EXW条款的报价要求。\n\n"
                "请在{deadline}前回复此邮件提供报价。如有任何问题，欢迎通过以下方式联系。"
            ),
            "body_en": (
                "Dear Sir/Madam,\n\n"
                "GO Corporation Co., Ltd. is a Thai-based procurement and project delivery company. "
                "We import furniture, lighting, playground equipment, and construction materials from "
                "74 vendors across China (primarily Guangdong, Zhejiang, and central China).\n\n"
                "Please find attached our Request for Quotation (RFQ) for China to Bangkok freight "
                "forwarding services covering sea LCL/FCL, land transport, door-to-door and EXW terms.\n\n"
                "Kindly submit your quotation by {deadline} by replying to this email."
            ),
        },
        "required_fields": [
            "d2d_sea_lcl_per_cbm",
            "d2d_land_per_cbm",
            "transit_sea_days",
            "transit_land_days",
            "billing_rule",
            "last_mile_standard",
            "warehouse_china",
            "customs_clearance",
            "payment_terms",
        ],
        "extraction_schema": {
            "rates": {
                "d2d_sea_lcl_per_cbm": {"type": "number", "unit": "THB/CBM"},
                "d2d_sea_lcl_per_kg": {"type": "number", "unit": "THB/KG"},
                "d2d_land_per_cbm": {"type": "number", "unit": "THB/CBM"},
                "d2d_land_per_kg": {"type": "number", "unit": "THB/KG"},
                "exw_sea_lcl_per_cbm": {"type": "number", "unit": "THB/CBM"},
                "exw_sea_lcl_per_kg": {"type": "number", "unit": "THB/KG"},
                "exw_land_per_cbm": {"type": "number", "unit": "THB/CBM"},
                "exw_land_per_kg": {"type": "number", "unit": "THB/KG"},
                "d2d_fcl_20": {"type": "number", "unit": "THB/container"},
                "d2d_fcl_40": {"type": "number", "unit": "THB/container"},
                "d2d_fcl_40hc": {"type": "number", "unit": "THB/container"},
                "exw_fcl_20": {"type": "number", "unit": "THB/container"},
                "exw_fcl_40": {"type": "number", "unit": "THB/container"},
                "exw_fcl_40hc": {"type": "number", "unit": "THB/container"},
                "transit_sea_days": {"type": "number", "unit": "days"},
                "transit_land_days": {"type": "number", "unit": "days"},
                "min_charge": {"type": "number", "unit": "THB"},
                "last_mile_standard": {"type": "number", "unit": "THB"},
                "last_mile_oversized": {"type": "number", "unit": "THB"},
                "oversized_surcharge": {"type": "number", "unit": "THB"},
                "billing_rule": {"type": "string"},
                "insurance_rate": {"type": "string"},
                "payment_terms": {"type": "string"},
                "currency": {"type": "string"},
                "pickup_surcharges": {"type": "object"},
            },
            "benchmark": {
                "sea_total_d2d": {"type": "number", "unit": "THB"},
                "sea_total_exw": {"type": "number", "unit": "THB"},
                "land_total_d2d": {"type": "number", "unit": "THB"},
                "land_total_exw": {"type": "number", "unit": "THB"},
            },
            "capabilities": {
                "warehouse_china": {"type": "boolean"},
                "warehouse_bangkok": {"type": "boolean"},
                "customs_clearance": {"type": "boolean"},
                "cargo_insurance": {"type": "boolean"},
                "api_tracking": {"type": "boolean"},
                "wechat_support": {"type": "boolean"},
                "consolidation": {"type": "boolean"},
                "free_storage_days": {"type": "number"},
            },
        },
        "auto_reply_context": (
            "GO Corporation imports furniture, lighting, playground equipment, and "
            "construction materials from 74 vendors across China (primarily Guangdong). "
            "Annual volume: 200-400 CBM across 30-50 POs. Trade term: EXW from factory. "
            "HS codes: 9403 (furniture 20%), 7610 (aluminum 10%), 9405 (lighting 20%), "
            "7308 (steel 10%)."
        ),
    }
    set_template("freight-agent-rfq-v1", template, db=db)
    print("  Created template: freight-agent-rfq-v1")


def seed_workflow_config(db) -> None:
    """Seed default workflow config."""
    config = {
        "escalation_rules": {
            "low_confidence_threshold": 0.6,
            "max_auto_replies": 3,
            "escalate_keywords": [
                "exclusive",
                "minimum commitment",
                "penalty",
                "contract",
                "NDA",
                "legal",
            ],
            "escalate_on_phone_request": True,
            "escalate_on_meeting_request": True,
            "price_anomaly_factor": 2.0,
        },
        "reminder_schedule": {
            "day_1": 5,
            "day_2": 7,
            "escalate_day": 10,
            "close_after_deadline_grace_days": 3,
        },
        "notification_channels": {
            "slack_channel": "C08VD9PRSCU",
            "slack_enabled": True,
            "email_digest_to": "eukrit@goco.bz",
        },
        "gemini_config": {
            "model": "gemini-2.5-flash",
            "temperature": 0.0,
            "classify_max_tokens": 1024,
            "extract_max_tokens": 4096,
            "reply_max_tokens": 2048,
            "auto_reply_min_confidence": 0.8,
        },
    }
    set_workflow_config("default", config, db=db)
    print("  Created workflow_config: default")


def main():
    print("=" * 60)
    print("  PROCUREMENT AUTOMATION — SEED SCRIPT")
    print("=" * 60)
    print()

    # Load vendor data
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    companies = data["companies"]
    print(f"Loaded {len(companies)} companies from JSON")
    print()

    db = get_db()

    # 1. Create inquiry
    print("[1/4] Creating RFQ inquiry...")
    seed_inquiry(db)
    print()

    # 2. Seed vendors
    print(f"[2/4] Seeding {len(companies)} vendors...")
    seed_vendors(db, companies)
    print()

    # 3. Seed template
    print("[3/4] Creating procurement template...")
    seed_template(db)
    print()

    # 4. Seed workflow config
    print("[4/4] Creating workflow config...")
    seed_workflow_config(db)
    print()

    # Summary
    print("=" * 60)
    print("  SEED COMPLETE")
    print(f"  Inquiry:          {INQUIRY_ID}")
    print(f"  Vendors seeded:   {len(companies)}")
    print(f"  Template:         freight-agent-rfq-v1")
    print(f"  Workflow config:  default")
    print(f"  Firestore DB:     procurement-automation (asia-southeast1)")
    print("=" * 60)


if __name__ == "__main__":
    main()
