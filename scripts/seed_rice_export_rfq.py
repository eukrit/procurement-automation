#!/usr/bin/env python3
"""
seed_rice_export_rfq.py — Seed Firestore with Thai rice exporter vendors,
the Rice Export RFQ inquiry, and the rice export template.

Target product: Thai White Rice 5% Broken (Well Milled), 200,000 MT to China.
Spec: RFL Standard (matches Thai Rice Standard).

Usage:
    python scripts/seed_rice_export_rfq.py
    python scripts/seed_rice_export_rfq.py --template-only
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
    os.path.dirname(__file__), "..", "data", "thailand_rice_exporters.json"
)

INQUIRY_ID = "RFQ-GO-2026-04-RICE-EXPORT"
TEMPLATE_ID = "rice-export-rfq-v1"


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
        "company_th": company.get("name_th"),
        "website": company.get("website"),
        "contact_email": company.get("contact_email"),
        "contact_email_alt": company.get("contact_email_alt"),
        "contact_phone": company.get("phone"),
        "contact_phone_alt": company.get("phone_alt"),
        "preferred_channel": "email",
        "languages": ["English", "Thai"],
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
            "role": "export_sales",
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
        "company_th": company.get("name_th"),
        "website": company.get("website"),
        "contacts": contacts,
        "categories": ["rice", "agricultural-commodities"],
        "subcategories": ["thai-white-rice-5pct-broken"],
        "services": ["export", "milling", "packaging"],
        "regions_thailand": [company.get("province")] if company.get("province") else [],
        "certifications": company.get("certifications_claimed", []),
        "languages": ["English", "Thai"],
        "campaign_history": [],
        "overall_rating": None,
        "notes": company.get("notes", ""),
        "tags": _build_tags(company),
    }


def _build_tags(company: dict) -> list[str]:
    tags = []
    if company.get("china_experience"):
        tags.append("china-export")
    certs = company.get("certifications_claimed", [])
    for cert in certs:
        tag = cert.lower().replace(" ", "-").replace("(", "").replace(")", "")
        tags.append(cert.lower())
    if not company.get("email_verified", False):
        tags.append("email-unverified")
    if company.get("estimated_capacity_mt_year", 0) >= 500000:
        tags.append("large-capacity")
    return tags


def seed_inquiry(db) -> None:
    """Create the Rice Export RFQ inquiry (idempotent)."""
    existing = get_inquiry(INQUIRY_ID, db=db)
    if existing:
        print(f"  Inquiry already exists: {INQUIRY_ID} (skipping create)")
        return

    config = {
        "inquiry_id": INQUIRY_ID,
        "title": "Thai White Rice 5% Broken — 200,000 MT Export to China",
        "category": "rice",
        "subcategory": "thai-white-rice-5pct-broken",
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
            "approval_required_for": ["pricing", "terms", "commitments", "legal", "contract"],
            "max_auto_replies_per_vendor": 3,
            "reminder_day_1": 5,
            "reminder_day_2": 7,
            "escalate_day": 10,
            "slack_channel": "#partner-nick",
        },
        "scoring_config": {
            "weights": {
                "price": 0.40,
                "quality_compliance": 0.20,
                "capacity_reliability": 0.15,
                "lead_time": 0.10,
                "certification": 0.10,
                "payment_terms": 0.05,
            },
            "baseline": {
                "source": "Thai Rice Exporters Association / market price April 2026",
                "reference_price_usd_per_mt": 415,
                "quantity_mt": 200000,
            },
        },
        "response_deadline": "2026-05-10",
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
    """Seed the Rice Export RFQ template (idempotent)."""
    template = {
        "name": "Thai White Rice 5% Broken — Export to China RFQ",
        "category": "rice",
        "subcategory": "thai-white-rice-5pct-broken",
        "version": 1,
        "email_template": {
            "subject": "RFQ: {title} | GO Corporation Co., Ltd.",
            "body_th": (
                "เรียน {vendor_name},\n\n"
                "บริษัท จีโอ คอร์ปอเรชั่น จำกัด (GO Corporation Co., Ltd.) เป็นบริษัทจัดซื้อและ"
                "บริหารโครงการในประเทศไทย ขณะนี้เรากำลังจัดหาข้าวขาว 5% สำหรับส่งออกไปยัง"
                "สาธารณรัฐประชาชนจีน ปริมาณ 200,000 ตัน\n\n"
                "กรุณาเสนอราคาตามรายละเอียดดังนี้:\n\n"
                "สินค้า: ข้าวขาวไทย 5% (Thai White Rice 5% Broken)\n"
                "มาตรฐาน: มาตรฐานข้าวไทย / RFL Standard\n"
                "ปริมาณ: 200,000 เมตริกตัน (แบ่งส่งมอบเป็นงวด)\n"
                "ปลายทาง: ท่าเรือในจีน (กรุณาระบุท่าเรือที่สะดวก)\n\n"
                "ข้อมูลสเปค:\n"
                "• ความชื้น: ไม่เกิน 14%\n"
                "• เมล็ดข้าวเต็มเมล็ด: ไม่น้อยกว่า 60%\n"
                "• ข้าวหัก (4.6 มม.): ไม่เกิน 7%\n"
                "• เมล็ดแดง/สีน้อย: ไม่เกิน 2%\n"
                "• เมล็ดเหลือง: ไม่เกิน 0.5%\n"
                "• เมล็ดท้องไข่: ไม่เกิน 6%\n"
                "• เมล็ดเสีย: ไม่เกิน 0.25%\n"
                "• ข้าวเหนียว: ไม่เกิน 1.5%\n"
                "• สิ่งเจือปน/เมล็ดลีบ: ไม่เกิน 0.3%\n"
                "• เมล็ดข้าวเปลือก: ไม่เกิน 8 เมล็ด/กก.\n"
                "• ระดับการสี: สีดี (Well Milled)\n\n"
                "กรุณาระบุ:\n"
                "• ราคา FOB (ท่าเรือไทย) ต่อเมตริกตัน (USD)\n"
                "• ราคา CIF (ท่าเรือจีน) ต่อเมตริกตัน (USD) — ถ้ามี\n"
                "• ราคาแบ่งตามปริมาณ: 10,000 / 50,000 / 100,000 / 200,000 ตัน\n"
                "• กำหนดส่งมอบ (จากวันสั่งซื้อถึงถึงท่าเรือจีน)\n"
                "• บรรจุภัณฑ์ (กระสอบ PP ขนาดมาตรฐาน / bulk)\n"
                "• เงื่อนไขการชำระเงิน (L/C at sight, T/T, อื่นๆ)\n"
                "• ใบรับรอง: GACC registration, Phytosanitary Certificate, Certificate of Origin, SGS/Intertek inspection\n"
                "• ตารางการส่งมอบ (กี่ตันต่อเดือน, ระยะเวลาสัญญา)\n"
                "• ประสบการณ์ส่งออกข้าวไปจีน (จำนวนตัน/ปี)\n\n"
                "กรุณาตอบกลับภายใน {deadline}\n"
                "หากมีข้อสงสัยสามารถสอบถามทางอีเมล์ หรือโทรศัพท์ได้ตลอดเวลา\n\n"
                "ขอแสดงความนับถือ"
            ),
            "body_en": (
                "Dear {vendor_name},\n\n"
                "GO Corporation Co., Ltd. is a Thailand-based procurement and project delivery "
                "company. We are sourcing Thai White Rice 5% Broken for export to the People's "
                "Republic of China, total quantity 200,000 metric tons.\n\n"
                "Please quote on the following:\n\n"
                "Product: Thai White Rice 5% Broken (Well Milled)\n"
                "Standard: Thai Rice Standard / RFL Standard\n"
                "Quantity: 200,000 metric tons (staged delivery)\n"
                "Destination: China ports (please specify preferred discharge port)\n\n"
                "Quality Specification:\n"
                "• Moisture: 14% max\n"
                "• Whole Kernels: 60% min\n"
                "• Broken (4.6 mm): 7% max\n"
                "• Red & Undermilled Kernels: 2% max\n"
                "• Yellow Kernels: 0.5% max\n"
                "• Chalky Kernels: 6% max\n"
                "• Damaged Kernels: 0.25% max\n"
                "• White Glutinous Rice: 1.5% max\n"
                "• Undeveloped, Immature Kernels, Other Seeds & Foreign Matter: 0.3% max\n"
                "• Paddy: 8 grains per 1 kg max\n"
                "• Milling Degree: Well Milled\n\n"
                "For your quotation, please provide:\n"
                "• FOB price (Thai port) per metric ton in USD\n"
                "• CIF price (China port) per metric ton in USD — if available\n"
                "• Volume-tiered pricing at 10,000 / 50,000 / 100,000 / 200,000 MT\n"
                "• Delivery schedule (from order confirmation to China port arrival)\n"
                "• Packaging (standard PP bags / bulk / other)\n"
                "• Payment terms (L/C at sight, T/T, other)\n"
                "• Certifications: GACC registration status, Phytosanitary Certificate, "
                "Certificate of Origin, SGS/Intertek pre-shipment inspection\n"
                "• Delivery schedule capability (MT per month, contract duration)\n"
                "• China export track record (MT per year, ports served)\n\n"
                "Kindly submit your quotation by {deadline} by replying to this email. "
                "Reply-To is shipping@goco.bz; please keep that address on any reply. "
                "Questions welcome by email or phone.\n\n"
                "Looking forward to your response.\n\n"
                "Best regards"
            ),
        },
        "required_fields": [
            "price_fob_usd_per_mt",
            "price_cif_usd_per_mt",
            "moq_mt",
            "delivery_schedule_days",
            "packaging_type",
            "payment_terms",
            "gacc_registered",
            "monthly_capacity_mt",
            "china_export_experience",
        ],
        "extraction_schema": {
            "rates": {
                "price_fob_usd_per_mt": {"type": "number", "unit": "USD/MT"},
                "price_cif_usd_per_mt": {"type": "number", "unit": "USD/MT"},
                "tier_price_10k_mt": {"type": "number", "unit": "USD/MT"},
                "tier_price_50k_mt": {"type": "number", "unit": "USD/MT"},
                "tier_price_100k_mt": {"type": "number", "unit": "USD/MT"},
                "tier_price_200k_mt": {"type": "number", "unit": "USD/MT"},
                "moq_mt": {"type": "number", "unit": "MT"},
                "delivery_schedule_days": {"type": "number", "unit": "days"},
                "monthly_capacity_mt": {"type": "number", "unit": "MT/month"},
                "payment_terms": {"type": "string"},
                "currency": {"type": "string"},
                "incoterm": {"type": "string"},
            },
            "product_specs": {
                "rice_grade": {"type": "string"},
                "broken_percentage": {"type": "number", "unit": "%"},
                "moisture_percentage": {"type": "number", "unit": "%"},
                "milling_degree": {"type": "string"},
                "packaging_type": {"type": "string"},
                "packaging_weight_kg": {"type": "number", "unit": "kg"},
                "crop_year": {"type": "string"},
                "loading_port": {"type": "string"},
                "discharge_port": {"type": "string"},
            },
            "capabilities": {
                "gacc_registered": {"type": "boolean"},
                "phytosanitary_cert": {"type": "boolean"},
                "certificate_of_origin": {"type": "boolean"},
                "sgs_intertek_inspection": {"type": "boolean"},
                "china_export_experience": {"type": "boolean"},
                "china_annual_volume_mt": {"type": "number", "unit": "MT/year"},
                "total_annual_capacity_mt": {"type": "number", "unit": "MT/year"},
                "contract_duration_months": {"type": "number", "unit": "months"},
                "iso_certified": {"type": "boolean"},
                "haccp_certified": {"type": "boolean"},
                "brc_certified": {"type": "boolean"},
            },
        },
        "auto_reply_context": (
            "GO Corporation Co., Ltd. is a Thailand-based procurement and project company "
            "sourcing Thai White Rice 5% Broken (Well Milled) for export to China. "
            "Total quantity: 200,000 metric tons, staged delivery over 12 months. "
            "Spec follows Thai Rice Standard / RFL Standard. "
            "Preferred payment: L/C at sight or 30% T/T deposit / 70% against B/L. "
            "Required certifications: GACC registration for China, Phytosanitary Certificate, "
            "Certificate of Origin, and SGS or Intertek pre-shipment inspection. "
            "Preferred loading ports: Bangkok (Klong Toey), Laem Chabang, or Si Racha. "
            "Discharge ports in China to be confirmed (likely Guangzhou, Shanghai, or Tianjin). "
            "Questions about China customs duties, import quotas, or bilateral trade agreements "
            "should be escalated to human — we need to verify current AQSIQ/GACC requirements. "
            "Standard packaging: new PP bags, 25 kg or 50 kg, palletized in 20ft containers."
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
    print("  PROCUREMENT AUTOMATION — RICE EXPORT RFQ SEED")
    print("=" * 60)
    print()

    db = get_db()

    if args.template_only:
        print("[1/1] Creating Rice Export RFQ template...")
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

    print("[1/3] Creating Rice Export RFQ template...")
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
    print(f"  Slack routing:    #partner-nick")
    print(f"  Firestore DB:     procurement-automation (asia-southeast1)")
    print("=" * 60)


if __name__ == "__main__":
    main()
