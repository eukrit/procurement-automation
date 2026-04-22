#!/usr/bin/env python3
"""
seed_poe_display_rfq.py — Seed Firestore with PoE touch display RFQ.

Seeds the inquiry, email template, and 6 vendor records (5 Shenzhen OEMs
+ Qbic Technology, Taiwan) for the 10.1" Android PoE multi-touch display
procurement — replacement for the discontinued Philips 10BDL3051T/00.

Target: 12 units, ship to Bangkok, Thailand.

Usage:
    python scripts/seed_poe_display_rfq.py
    python scripts/seed_poe_display_rfq.py --template-only
    python scripts/seed_poe_display_rfq.py --dry
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
    os.path.dirname(__file__), "..", "data", "china_poe_touch_displays.json"
)

INQUIRY_ID = "RFQ-GO-2026-04-POE-DISPLAY"
TEMPLATE_ID = "poe-display-rfq-v1"
DEADLINE = "6 May 2026"
DEADLINE_CN = "2026年5月6日"
TARGET_QTY = 12
WHATSAPP = "+66 61 491 6393"
WECHAT = "eukrit"


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
        "website": company.get("website"),
        "contact_email": company.get("contact_email"),
        "contact_email_alt": company.get("contact_email_alt"),
        "contact_phone": company.get("phone"),
        "preferred_channel": "email",
        "languages": ["English"] if company.get("language_for_rfq") == "English"
                     else ["English", "Chinese"],
        "source": "web_research",
        "source_notes": company.get("notes", ""),
        "email_verified": company.get("email_verified", False),
        "email_notes": company.get("email_notes", ""),
        "country": company.get("country", "China"),
        "master_vendor_ref": f"vendor_directory/{vendor_id}",
        "status": "pending",
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
        "website": company.get("website"),
        "contacts": contacts,
        "categories": ["signage-display"],
        "subcategories": ["poe-touch-display", "android-signage"],
        "country": company.get("country", "China"),
        "regions_china": [company.get("city")] if company.get("city") else [],
        "certifications": company.get("certifications_claimed", []),
        "languages": ["English"] if company.get("language_for_rfq") == "English"
                     else ["English", "Chinese"],
        "campaign_history": [],
        "overall_rating": None,
        "notes": company.get("notes", ""),
        "tags": _build_tags(company),
    }


def _build_tags(company: dict) -> list[str]:
    tags = ["poe-touch", "android-signage", "10-inch"]
    if not company.get("email_verified", False):
        tags.append("email-unverified")
    if company.get("country", "China") == "Taiwan (ROC)":
        tags.append("taiwan")
    else:
        tags.append("china-oem")
    if company.get("shortlist_rank") == 1:
        tags.append("primary-rfq")
    return tags


def seed_inquiry(db, dry_run: bool = False) -> None:
    existing = get_inquiry(INQUIRY_ID, db=db)
    if existing:
        print(f"  Inquiry already exists: {INQUIRY_ID} (skipping create)")
        return

    config = {
        "inquiry_id": INQUIRY_ID,
        "title": f"10.1\" Android PoE+ Multi-Touch Signage Display — {TARGET_QTY} pcs",
        "category": "signage-display",
        "subcategory": "poe-touch-display",
        "template_id": TEMPLATE_ID,
        "target_quantity": TARGET_QTY,
        "reference_product": "Philips Signage Solutions 10BDL3051T/00 / 10BDL4551T/00 (discontinued)",
        "rfq_document": {
            "research_report": "docs/research/Philips-10BDL3051T-alternatives.md",
            "supplier_data": "data/china_poe_touch_displays.json",
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
            "slack_channel": "#shipment-notifications",
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
                "source": "Philips 10BDL4551T/00 retail, April 2026",
                "unit_price_usd_low": 600,
                "unit_price_usd_high": 800,
                "moq": 1,
            },
        },
        "response_deadline": "2026-05-06",
        "status": "draft",
        "vendor_count": 0,
        "created_by": "eukrit@goco.bz",
    }

    if dry_run:
        print(f"  [DRY] Would create inquiry: {INQUIRY_ID}")
        return

    create_inquiry(config, db=db)
    print(f"  Created inquiry: {INQUIRY_ID}")


def seed_vendors(db, companies: list[dict], dry_run: bool = False) -> None:
    for company in companies:
        vendor_data = build_vendor_data(company)
        vendor_id = _slugify(company["name_en"])

        if dry_run:
            email = company.get("contact_email", "(no email)")
            print(f"  [DRY] Would seed vendor: {vendor_id:50s} -> {email}")
            continue

        added_id = add_vendor_to_inquiry(INQUIRY_ID, vendor_data, db=db)
        print(f"  Added vendor to inquiry: {added_id}")

        directory_entry = build_vendor_directory_entry(company)
        upsert_vendor_directory(directory_entry, db=db)
        print(f"  Upserted vendor_directory: {added_id}")


def seed_template(db, dry_run: bool = False) -> None:
    template = {
        "name": "10\" PoE Android Touch Display RFQ",
        "category": "signage-display",
        "subcategory": "poe-touch-display",
        "version": 1,
        "email_template": {
            "subject": f"RFQ: 10.1\" Android PoE+ Multi-Touch Signage Display — {TARGET_QTY} pcs | GO Corporation Co., Ltd.",
            "body_en": (
                "Dear {{vendor_name}},\n\n"
                "GO Corporation Co., Ltd. is a Thailand-based procurement and project delivery company.\n\n"
                f"We are sourcing **{TARGET_QTY} units** of a **10.1\" Android PoE+ capacitive multi-touch wall-mount "
                "display** to replace the discontinued Philips Signage Solutions 10BDL3051T/00 "
                "(successor model: 10BDL4551T/00).\n\n"
                "We found your product to be a strong match for our requirements. "
                "Please provide a formal quotation for your equivalent 10\" PoE touch display model.\n\n"
                "**Minimum required specification:**\n"
                f"• Screen: 10.1\", IPS, ≥1280×800, ≥250 nits\n"
                "• Touch: Projected capacitive (PCAP), ≥5-point\n"
                "• Power: IEEE 802.3at PoE+ (single RJ45 cable for power + data)\n"
                "• OS: Android 8.1 or newer\n"
                "• Wireless: WiFi, Bluetooth\n"
                "• Wall-mount bracket included\n"
                "• Certifications: CE + FCC + RoHS (minimum)\n\n"
                "**Please quote the following for your closest matching model(s):**\n"
                f"• Unit price FOB Shenzhen / Taipei and DDP Bangkok, in USD\n"
                f"• MOQ and price break at {TARGET_QTY} pcs\n"
                "• Lead time from deposit to delivery Bangkok\n"
                "• Warranty: period and scope\n"
                "• Payment terms (we propose 30% deposit / 70% against B/L)\n"
                "• Full technical datasheet\n"
                "• Certifications in hand (CE, FCC, RoHS — please list any others)\n"
                "• Sample unit availability and pricing\n"
                "• Android MDM / CMS compatibility (Android Enterprise DPC, third-party MDM, or vendor CMS?)\n\n"
                f"Kindly submit your quotation by **{DEADLINE}** by replying to this email. "
                "Reply-To is shipping@goco.bz — please keep that address on all replies.\n\n"
                f"For questions, please reach me on:\n"
                f"• WhatsApp: {WHATSAPP}\n"
                f"• WeChat ID: {WECHAT}\n"
                f"• Email: eukrit@goco.bz\n\n"
                "We look forward to your response.\n\n"
                "Best regards,\n"
                "Eukrit Kraikosol"
            ),
            "body_cn": (
                "您好，\n\n"
                "GO Corporation Co., Ltd.（บริษัท จีโอ คอร์ปอเรชั่น จำกัด）是一家总部位于泰国曼谷的采购与项目执行公司。\n\n"
                f"我们正在采购 **{TARGET_QTY} 台** 10.1英寸 Android PoE+ 电容触控壁挂式显示屏，"
                "用于替换已停产的飞利浦 Signage Solutions 10BDL3051T/00（后续型号：10BDL4551T/00）。\n\n"
                "我们认为贵司产品与我们的需求高度匹配，诚邀您提供正式报价。\n\n"
                "**基本规格要求：**\n"
                "• 屏幕：10.1英寸 IPS，分辨率 ≥1280×800，亮度 ≥250 nits\n"
                "• 触摸：投射式电容（PCAP），≥5点同时触控\n"
                "• 供电：IEEE 802.3at PoE+（单网线同时传输电力和数据）\n"
                "• 系统：Android 8.1 或更新版本\n"
                "• 无线：WiFi、蓝牙\n"
                "• 含壁挂支架\n"
                "• 认证：CE + FCC + RoHS（最低要求）\n\n"
                "**请针对您最接近的对应型号，提供以下报价信息：**\n"
                "• 含税出厂价（FOB 深圳）及 DDP 曼谷到门价，单位：美元\n"
                f"• 最小起订量（MOQ）及 {TARGET_QTY} 台的批量价格\n"
                "• 从支付定金到货抵曼谷的交期\n"
                "• 质保期及质保范围\n"
                "• 付款条件（建议：30% 定金 / 70% 见提单）\n"
                "• 完整产品技术规格书\n"
                "• 已取得的认证（CE、FCC、RoHS，以及其他认证）\n"
                "• 样机供货情况及样机价格\n"
                "• 设备管理（MDM）兼容性：支持 Android Enterprise DPC、第三方 MDM 还是厂商自带 CMS？\n\n"
                f"请于 **{DEADLINE_CN}** 前回复本邮件。"
                "请将 shipping@goco.bz 保留在所有回复的收件人列表中。\n\n"
                "如有问题，欢迎通过以下方式联系我：\n"
                f"• WhatsApp：{WHATSAPP}\n"
                f"• 微信（WeChat）：{WECHAT}\n"
                f"• 邮箱：eukrit@goco.bz\n\n"
                "期待贵司回复，谢谢！\n\n"
                "Eukrit Kraikosol"
            ),
        },
        "required_fields": [
            "unit_price_fob_usd",
            "unit_price_ddp_bkk_usd",
            "moq",
            "lead_time_weeks",
            "android_version",
            "resolution",
            "brightness_nits",
            "poe_standard",
            "certifications",
            "warranty_months",
            "payment_terms",
        ],
    }

    if dry_run:
        print(f"  [DRY] Would create/update template: {TEMPLATE_ID}")
        return

    set_template(TEMPLATE_ID, template, db=db)
    print(f"  Created/updated template: {TEMPLATE_ID}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-only", action="store_true", help="Seed template only")
    parser.add_argument("--dry", action="store_true", help="Preview without writing to Firestore")
    args = parser.parse_args()

    print("=" * 60)
    print("  PROCUREMENT AUTOMATION — PoE DISPLAY RFQ SEED")
    print("=" * 60)
    print()

    db = None if args.dry else get_db()

    if args.template_only:
        print("[1/1] Creating PoE display RFQ template...")
        seed_template(db, dry_run=args.dry)
        print()
        print("=" * 60)
        print(f"  TEMPLATE SEEDED: {TEMPLATE_ID}")
        print("=" * 60)
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    companies = data["companies"]
    print(f"Loaded {len(companies)} vendors from {os.path.basename(DATA_FILE)}")
    print()

    print("[1/3] Creating PoE display RFQ template...")
    seed_template(db, dry_run=args.dry)
    print()

    print("[2/3] Creating RFQ inquiry...")
    seed_inquiry(db, dry_run=args.dry)
    print()

    print(f"[3/3] Seeding {len(companies)} vendors...")
    seed_vendors(db, companies, dry_run=args.dry)
    print()

    print("=" * 60)
    if args.dry:
        print("  DRY RUN COMPLETE — no changes written to Firestore")
    else:
        print(f"  SEEDED: {INQUIRY_ID}")
        print(f"  {len(companies)} vendors ready. Run:")
        print(f"    python scripts/send_poe_display_rfq.py --dry")
        print(f"    python scripts/send_poe_display_rfq.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
