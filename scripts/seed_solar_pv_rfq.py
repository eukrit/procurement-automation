#!/usr/bin/env python3
"""
seed_solar_pv_rfq.py — Seed Firestore with Chinese Back-Contact (IBC/ABC/HBC/HPBC)
solar PV manufacturers, the solar panel RFQ inquiry, and the solar RFQ template.

Target: ~50 m² (~10 kW) rooftop pilot for GO Corporation (Thailand), with
scale-up pricing tiers for container / utility volumes. Focus: Back Contact
cell tech (Aiko ABC, LONGi HIBC/HPBC, Maxeon IBC, Huansheng/SPIC HBC, DAS XBC)
plus premium N-type alternatives (Trina / Jinko / JA / Canadian / Risen /
Tongwei / Jolywood).

Usage:
    python scripts/seed_solar_pv_rfq.py
    python scripts/seed_solar_pv_rfq.py --template-only
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
    set_template,
    upsert_vendor_directory,
)

DATA_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "china_solar_pv_suppliers.json"
)

INQUIRY_ID = "RFQ-GO-2026-04-SOLAR-PV"
TEMPLATE_ID = "solar-pv-rfq-v1"
RESPONSE_DEADLINE = "2026-05-15"  # Friday after China Golden Week
SLACK_CHANNEL = "#areda-mike"


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
    if company.get("contact_email"):
        contacts.append({
            "name": "",
            "email": company["contact_email"],
            "phone": company.get("phone"),
            "role": "sales",
        })
    if company.get("contact_email_alt"):
        contacts.append({
            "name": "",
            "email": company["contact_email_alt"],
            "role": "sales_alt",
        })

    return {
        "vendor_id": vendor_id,
        "company_en": company["name_en"],
        "company_cn": company.get("name_cn"),
        "website": company.get("website"),
        "contacts": contacts,
        "categories": ["solar-pv-module"],
        "subcategories": ["back-contact", "ibc-abc-hbc", "bifacial", "n-type"],
        "services": [],
        "regions_china": [company.get("city")] if company.get("city") else [],
        "certifications": company.get("certifications_claimed", []),
        "languages": company.get("languages", ["English", "Chinese"]),
        "campaign_history": [],
        "overall_rating": None,
        "notes": company.get("notes", ""),
        "tags": _build_tags(company),
        "product_claims": {
            "cell_technology": company.get("cell_technology", []),
            "power_ratings_w": company.get("power_ratings_w", []),
            "bifacial_available": company.get("bifacial_available", False),
            "all_black_available": company.get("all_black_available", False),
            "warranty_years_product": company.get("warranty_years_product"),
            "warranty_years_performance_linear": company.get(
                "warranty_years_performance_linear"
            ),
        },
    }


def _build_tags(company: dict) -> list[str]:
    tags = []
    cells = [c.lower() for c in company.get("cell_technology", [])]
    if any("ibc" in c or "abc" in c or "hbc" in c or "hpbc" in c or "xbc" in c
           or "back contact" in c for c in cells):
        tags.append("back-contact")
    if any("topcon" in c for c in cells):
        tags.append("topcon")
    if any("hjt" in c for c in cells):
        tags.append("hjt")
    if company.get("bifacial_available"):
        tags.append("bifacial")
    if company.get("all_black_available"):
        tags.append("all-black")
    if not company.get("email_verified", False):
        tags.append("email-unverified")
    return tags


def seed_inquiry(db) -> None:
    existing = get_inquiry(INQUIRY_ID, db=db)
    if existing:
        print(f"  Inquiry already exists: {INQUIRY_ID} (skipping create)")
        return

    config = {
        "inquiry_id": INQUIRY_ID,
        "title": (
            "~50 m² / ~10 kW Back Contact (IBC/ABC/HBC/HPBC) Solar PV Modules "
            "for Thailand Pilot — with Container / Utility Scale-up Pricing"
        ),
        "category": "solar-pv-module",
        "subcategory": "back-contact-ibc-abc-hbc",
        "template_id": TEMPLATE_ID,
        "rfq_document": {
            "html_url": None,
            "pdf_path": None,
            "drive_url": None,
        },
        "send_config": {
            "from_email": "eukrit@goco.bz",
            "reply_to": "procurement@goco.bz",
            "cc": ["procurement@goco.bz"],
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
            "reminder_day_1": 7,
            "reminder_day_2": 14,
            "escalate_day": 18,
            "slack_channel": SLACK_CHANNEL,
        },
        "scoring_config": {
            "weights": {
                "price": 0.35,
                "capability": 0.25,
                "lead_time": 0.15,
                "certification": 0.15,
                "warranty": 0.10,
            },
            "baseline": {
                "source": "Public Alibaba / Made-in-China ABC and TOPCon module listings, April 2026",
                "unit_price_usd_per_watt_low": 0.10,
                "unit_price_usd_per_watt_high": 0.28,
                "moq_hint_panels": 18,
                "pilot_m2": 50,
                "pilot_kw_approx": 10,
            },
        },
        "response_deadline": RESPONSE_DEADLINE,
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
    template = {
        "name": "China Back-Contact Solar PV Module RFQ",
        "category": "solar-pv-module",
        "subcategory": "back-contact-ibc-abc-hbc",
        "version": 1,
        "email_template": {
            "subject": "RFQ: {title} | GO Corporation Co., Ltd.",
            "body_cn": (
                "{vendor_name} 销售团队，您好，\n\n"
                "GO Corporation Co., Ltd.（บริษัท จีโอ คอร์ปอเรชั่น จำกัด）是泰国一家"
                "专注于住宅、酒店及商业项目设计和采购的公司。我们正在为泰国市场"
                "评估高效背接触（IBC / ABC / HBC / HPBC / XBC）光伏组件，"
                "首个试点项目约 50 平方米屋顶（约 10 kW），后续有望扩展至集装箱、"
                "百千瓦及兆瓦级的商业及工业项目。\n\n"
                "请就以下产品提供正式报价：\n"
                "1. 贵司最主流的背接触电池组件（IBC / ABC / HBC / HPBC / XBC），"
                "全黑外观优先；\n"
                "2. 可选：同功率等级下贵司的双面 N 型 TOPCon / HJT 组件，作为替代方案。\n\n"
                "需要提供的报价和规格信息：\n"
                "• FOB 中国主要港口（请注明：上海 / 宁波 / 深圳 / 厦门 / 青岛等）报价，"
                "单位：美元/瓦（USD/W）及美元/片（USD/pc）；\n"
                "• 分梯度报价：\n"
                "    – 试点量：约 18 片（~10 kW）\n"
                "    – 1 × 40HC 集装箱（约 30–40 kW）\n"
                "    – 100 kW / 500 kW / 1 MW\n"
                "• MOQ（最小起订量，按片和按瓦两种口径）；\n"
                "• 交货期（从定金至出厂、至中国港口装船）；\n"
                "• 付款条件（建议 30% 定金 / 70% 见提单副本）；\n"
                "• 产品质保年限 & 线性功率质保年限；\n"
                "• 完整认证清单（IEC 61215 / IEC 61730 / CE / TÜV / UL / MCS / JET / "
                "CEC / 泰国 MEA/PEA 认证等）—— 请说明已获与在办；\n"
                "• 最新产品目录 PDF（Datasheet）及完整认证证书副本；\n"
                "• 规格书：电池技术、组件效率、功率容差、工作温度、IP 等级、"
                "抗 PID 性能、接线盒型号、电缆规格、框架颜色、尺寸及重量；\n"
                "• 是否支持 OEM / 贴牌；\n"
                "• 样品可用性及样品价格。\n\n"
                "请在 {deadline} 前回复本邮件提供报价及资料。回复请保留抄送 "
                "procurement@goco.bz。如需进一步信息，欢迎通过邮件、电话或微信联系。\n\n"
                "期待贵司回复。\n\n"
                "此致\n"
                "GO Corporation Co., Ltd. — Procurement"
            ),
            "body_en": (
                "Dear {vendor_name} Sales Team,\n\n"
                "GO Corporation Co., Ltd. is a Thailand-based design and procurement "
                "company serving residential, hospitality and commercial projects. "
                "We are evaluating high-efficiency Back Contact (IBC / ABC / HBC / "
                "HPBC / XBC) solar PV modules for the Thai market. Our initial pilot "
                "is a ~50 m² rooftop (~10 kW), with scale-up to container, 100 kW–1 "
                "MW C&I projects targeted over the next 12 months.\n\n"
                "Please quote on the following:\n\n"
                "1. Your current best-in-class Back Contact module "
                "(IBC / ABC / HBC / HPBC / XBC) — all-black aesthetic preferred.\n"
                "2. OPTIONAL: Your comparable bifacial N-type TOPCon or HJT module at "
                "the same power class, as an alternative bid.\n\n"
                "For every model you quote, please provide:\n"
                "• FOB price at your nearest China port (please specify: Shanghai / "
                "Ningbo / Shenzhen / Xiamen / Qingdao), in USD/W AND USD/piece.\n"
                "• Tiered pricing at:\n"
                "    – Pilot quantity: ~18 panels (~10 kW)\n"
                "    – 1 x 40HC container (~30–40 kW)\n"
                "    – 100 kW / 500 kW / 1 MW\n"
                "• MOQ (both in pieces and in kW).\n"
                "• Lead time from deposit through ex-works through FOB port load.\n"
                "• Payment terms (we prefer 30% deposit / 70% against B/L copy).\n"
                "• Product warranty AND linear performance warranty (years).\n"
                "• Full certification list — IEC 61215, IEC 61730, CE, TÜV, UL 61730, "
                "MCS, JET, CEC, Thai MEA / PEA / TISI — indicate which are in hand "
                "vs. in progress. Please attach certification copies.\n"
                "• Latest product catalog (PDF datasheet) and full test reports.\n"
                "• Product specs: cell technology, module efficiency %, power "
                "tolerance, operating temp range, IP rating, anti-PID performance, "
                "junction box model, cable specs, frame colour, dimensions, weight.\n"
                "• OEM / white-label availability.\n"
                "• Sample availability and sample-unit pricing.\n\n"
                "Kindly submit your quotation by {deadline} by replying to this "
                "email. Reply-To is procurement@goco.bz — please keep that address "
                "on any reply. Questions welcome by email, phone, or WeChat.\n\n"
                "Looking forward to your response.\n\n"
                "Best regards,\n"
                "GO Corporation Co., Ltd. — Procurement"
            ),
        },
        "required_fields": [
            "unit_price_fob_usd_per_watt",
            "unit_price_fob_usd_per_piece",
            "tier_price_10kw_usd_per_watt",
            "tier_price_container_usd_per_watt",
            "tier_price_100kw_usd_per_watt",
            "tier_price_500kw_usd_per_watt",
            "tier_price_1mw_usd_per_watt",
            "moq_pieces",
            "moq_kw",
            "lead_time_weeks",
            "cell_technology",
            "module_power_w",
            "module_efficiency_pct",
            "bifacial",
            "all_black",
            "certifications",
            "warranty_years_product",
            "warranty_years_performance_linear",
            "payment_terms",
            "fob_port",
        ],
        "extraction_schema": {
            "rates": {
                "unit_price_fob_usd_per_watt": {"type": "number", "unit": "USD/W"},
                "unit_price_fob_usd_per_piece": {"type": "number", "unit": "USD/pc"},
                "tier_price_10kw_usd_per_watt": {"type": "number", "unit": "USD/W"},
                "tier_price_container_usd_per_watt": {"type": "number", "unit": "USD/W"},
                "tier_price_100kw_usd_per_watt": {"type": "number", "unit": "USD/W"},
                "tier_price_500kw_usd_per_watt": {"type": "number", "unit": "USD/W"},
                "tier_price_1mw_usd_per_watt": {"type": "number", "unit": "USD/W"},
                "sample_unit_price_usd": {"type": "number", "unit": "USD/pc"},
                "moq_pieces": {"type": "number", "unit": "pieces"},
                "moq_kw": {"type": "number", "unit": "kW"},
                "lead_time_weeks": {"type": "number", "unit": "weeks"},
                "warranty_years_product": {"type": "number", "unit": "years"},
                "warranty_years_performance_linear": {"type": "number", "unit": "years"},
                "payment_terms": {"type": "string"},
                "currency": {"type": "string"},
                "incoterm": {"type": "string"},
                "fob_port": {"type": "string"},
            },
            "product_specs": {
                "model_number": {"type": "string"},
                "cell_technology": {"type": "string"},
                "module_power_w": {"type": "number", "unit": "W"},
                "module_efficiency_pct": {"type": "number", "unit": "%"},
                "power_tolerance_pct": {"type": "string"},
                "bifacial": {"type": "boolean"},
                "bifaciality_pct": {"type": "number", "unit": "%"},
                "all_black": {"type": "boolean"},
                "frame_colour": {"type": "string"},
                "cell_count": {"type": "number"},
                "dimensions_mm": {"type": "string"},
                "weight_kg": {"type": "number"},
                "ip_rating": {"type": "string"},
                "operating_temp_range_c": {"type": "string"},
                "junction_box_model": {"type": "string"},
                "anti_pid_claimed": {"type": "boolean"},
            },
            "capabilities": {
                "oem_white_label_available": {"type": "boolean"},
                "iec_61215_certified": {"type": "boolean"},
                "iec_61730_certified": {"type": "boolean"},
                "ce_certified": {"type": "boolean"},
                "tuv_certified": {"type": "boolean"},
                "ul_certified": {"type": "boolean"},
                "mcs_certified": {"type": "boolean"},
                "jet_certified": {"type": "boolean"},
                "cec_listed": {"type": "boolean"},
                "thai_mea_listed": {"type": "boolean"},
                "thai_pea_listed": {"type": "boolean"},
                "thai_tisi_certified": {"type": "boolean"},
                "catalog_attached": {"type": "boolean"},
                "certs_attached": {"type": "boolean"},
            },
        },
        "auto_reply_context": (
            "GO Corporation Co., Ltd. is a Thailand-based design and procurement "
            "company evaluating Back Contact solar PV modules (IBC / ABC / HBC / "
            "HPBC / XBC) for a ~50 m² / ~10 kW rooftop pilot in Thailand, with "
            "planned scale-up to container / 100 kW–1 MW commercial and industrial "
            "projects. All-black aesthetic preferred; bifacial N-type TOPCon / HJT "
            "acceptable as alternative bid. Required certifications baseline: IEC "
            "61215 + IEC 61730 + CE + TÜV. Nice-to-have: UL, MCS, JET, CEC. "
            "Thailand-specific: MEA / PEA listing and TISI certification preferred. "
            "Preferred payment terms: 30% deposit / 70% against B/L copy. Questions "
            "about Thailand-specific certifications (MEA/PEA/TISI) should be "
            "escalated — confirm with the user before commitments."
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
    print("  PROCUREMENT AUTOMATION — SOLAR PV (BACK CONTACT) RFQ SEED")
    print("=" * 60)
    print()

    db = get_db()

    if args.template_only:
        print("[1/1] Creating solar-pv RFQ template...")
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

    print("[1/3] Creating solar-pv RFQ template...")
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
    print(f"  Deadline:         {RESPONSE_DEADLINE}")
    print(f"  Slack routing:    {SLACK_CHANNEL} (per-inquiry override)")
    print(f"  Firestore DB:     procurement-automation (asia-southeast1)")
    print("=" * 60)


if __name__ == "__main__":
    main()
