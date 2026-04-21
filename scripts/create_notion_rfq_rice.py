#!/usr/bin/env python3
"""
create_notion_rfq_rice.py
Creates RFQ Rice Inquiry page in Thai under Nubo International Notion page.

Usage:
    NOTION_API_KEY=secret_xxx python scripts/create_notion_rfq_rice.py
"""

import json
import os
import sys
import requests

NOTION_VERSION = "2022-06-28"
NOTION_API = "https://api.notion.com/v1"

# Parent page: Nubo International
PARENT_PAGE_ID = "23082cea8bb080f8a7bbfdcab1f1e68f"

# Address page to read buyer info from
ADDRESS_PAGE_ID = "23082cea8bb080619450cf4506dd615f"

BUYER = {
    "name": "Nubo International Pte. Ltd.",
    "contact_name": "Eukrit Sae-Lim",
    "email": "eukrit@nubo.asia",
    "mobile": "+66 61 491 6393",
}


def get_token():
    token = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN")
    if not token:
        for path in [
            os.path.expanduser("~/.notion_token"),
            "/run/secrets/notion_api_key",
            "/home/user/.notion_token",
        ]:
            if os.path.exists(path):
                with open(path) as f:
                    token = f.read().strip()
                break
    if not token:
        print("ERROR: No Notion API token found.")
        print("Set NOTION_API_KEY env var and retry:")
        print("  NOTION_API_KEY=secret_xxx python scripts/create_notion_rfq_rice.py")
        sys.exit(1)
    return token


def headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def get_page_text(token, page_id):
    """Pull plain text from a Notion page's blocks."""
    r = requests.get(f"{NOTION_API}/blocks/{page_id}/children", headers=headers(token))
    if r.status_code != 200:
        return None
    lines = []
    for block in r.json().get("results", []):
        for rt in block.get(block.get("type", ""), {}).get("rich_text", []):
            lines.append(rt.get("plain_text", ""))
    return "\n".join(lines) if lines else None


def txt(content, bold=False, color="default"):
    return {"type": "text", "text": {"content": content}, "annotations": {"bold": bold, "color": color}}


def heading1(text):
    return {"object": "block", "type": "heading_1", "heading_1": {"rich_text": [txt(text, bold=True)]}}


def heading2(text):
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [txt(text)]}}


def heading3(text):
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [txt(text)]}}


def para(*parts):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": list(parts)}}


def bullet(text, bold=False):
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [txt(text, bold=bold)]}}


def divider():
    return {"object": "block", "type": "divider", "divider": {}}


def callout(text, emoji="📋"):
    return {"object": "block", "type": "callout",
            "callout": {"rich_text": [txt(text)], "icon": {"type": "emoji", "emoji": emoji}}}


def table_row(cells):
    return {"type": "table_row", "table_row": {"cells": [[txt(c)] for c in cells]}}


def table(headers_row, rows):
    return {
        "object": "block", "type": "table",
        "table": {
            "table_width": len(headers_row),
            "has_column_header": True,
            "has_row_header": False,
            "children": [table_row(headers_row)] + [table_row(r) for r in rows],
        }
    }


def build_blocks(buyer_address):
    today = "21 เมษายน 2569"
    deadline = "10 พฤษภาคม 2569"

    blocks = [
        callout("เอกสารนี้เป็นใบขอเสนอราคา (RFQ) สำหรับข้าวขาวไทย 5% หัก สำหรับส่งออกไปยังจีน ปริมาณ 200,000 เมตริกตัน", "🍚"),
        callout(
            "⚠️ ต้องการราคาดีที่สุดภายในวันนี้ — กรุณาส่งใบเสนอราคาพร้อมรูปถ่ายบรรจุภัณฑ์จริง "
            "(ตัวอย่างกระสอบ, การพิมพ์ยี่ห้อ, มาตรฐานการบรรจุ) และเอกสารมาตรฐานที่เกี่ยวข้องทั้งหมด "
            "ภายในวันนี้ // We need your BEST PRICE today — please include photos of your actual "
            "packaging (bag samples, printing/branding, packing standards) and all relevant "
            "standards/spec sheets in your reply.",
            "🚨"
        ),
        divider(),

        heading1("ใบขอเสนอราคา (Request for Quotation)"),
        heading2("ข้าวขาวไทย 5% หัก — ส่งออกไปยังสาธารณรัฐประชาชนจีน"),
        divider(),

        # Reference info
        heading3("ข้อมูลเอกสาร"),
        table(
            ["รายการ", "รายละเอียด"],
            [
                ["เลขที่ RFQ", "RFQ-GO-2026-04-RICE-EXPORT"],
                ["วันที่ออกเอกสาร", today],
                ["กำหนดตอบรับ", deadline],
                ["สถานะ", "Draft"],
            ]
        ),
        divider(),

        # Buyer info
        heading3("ข้อมูลผู้ซื้อ (Buyer)"),
        table(
            ["รายการ", "รายละเอียด"],
            [
                ["บริษัท", BUYER["name"]],
                ["ที่อยู่", buyer_address or "ดูหน้า Nubo International Address ใน Notion"],
                ["ผู้ติดต่อ", BUYER["contact_name"]],
                ["อีเมล", BUYER["email"]],
                ["โทรศัพท์มือถือ", BUYER["mobile"]],
            ]
        ),
        divider(),

        # Product
        heading3("สินค้าที่ต้องการ"),
        table(
            ["รายการ", "รายละเอียด"],
            [
                ["ชนิดสินค้า", "ข้าวขาวไทย 5% หัก (Thai White Rice 5% Broken)"],
                ["มาตรฐาน", "มาตรฐานข้าวไทย / RFL Standard"],
                ["ระดับการสี", "สีดี (Well Milled)"],
                ["ปริมาณรวม", "200,000 เมตริกตัน"],
                ["วิธีส่งมอบ", "แบ่งส่งมอบเป็นงวด (ประมาณ 12 เดือน)"],
                ["ปลายทาง", "ท่าเรือในประเทศจีน (กว่างโจว / เซี่ยงไฮ้ / เทียนจิน)"],
                ["ท่าเรือต้นทาง", "กรุงเทพฯ (คลองเตย) / แหลมฉบัง / ศรีราชา"],
            ]
        ),
        divider(),

        # Quality spec
        heading3("สเปคคุณภาพ (Quality Specification)"),
        table(
            ["คุณสมบัติ", "ค่ามาตรฐาน", "หมายเหตุ"],
            [
                ["ความชื้น (Moisture)", "ไม่เกิน 14%", ""],
                ["เมล็ดข้าวเต็มเมล็ด (Whole Kernels)", "ไม่น้อยกว่า 60%", ""],
                ["ข้าวหัก 4.6 มม. (Broken)", "ไม่เกิน 7%", ""],
                ["เมล็ดแดง/สีน้อย (Red & Undermilled)", "ไม่เกิน 2%", ""],
                ["เมล็ดเหลือง (Yellow Kernels)", "ไม่เกิน 0.5%", ""],
                ["เมล็ดท้องไข่ (Chalky Kernels)", "ไม่เกิน 6%", ""],
                ["เมล็ดเสีย (Damaged Kernels)", "ไม่เกิน 0.25%", ""],
                ["ข้าวเหนียว (White Glutinous)", "ไม่เกิน 1.5%", ""],
                ["สิ่งเจือปน/เมล็ดลีบ (Foreign Matter)", "ไม่เกิน 0.3%", ""],
                ["เมล็ดข้าวเปลือก (Paddy)", "ไม่เกิน 8 เมล็ด/กก.", ""],
            ]
        ),
        divider(),

        # Quotation requirements
        heading3("ข้อมูลที่ต้องการจากผู้ขาย"),
        bullet("ราคา FOB (ท่าเรือไทย) ต่อเมตริกตัน — USD/MT"),
        bullet("ราคา CIF (ท่าเรือจีน) ต่อเมตริกตัน — USD/MT (ถ้ามี)"),
        bullet("ราคาแบ่งตามปริมาณ: 10,000 / 50,000 / 100,000 / 200,000 MT"),
        bullet("กำหนดส่งมอบ (จากวันสั่งซื้อถึงถึงท่าเรือจีน)"),
        bullet("บรรจุภัณฑ์ — กระสอบ PP ใหม่ 25 กก. หรือ 50 กก. / bulk"),
        bullet("เงื่อนไขการชำระเงิน — L/C at sight / T/T 30%+70% B/L / อื่นๆ"),
        bullet("ใบรับรอง: GACC, Phytosanitary Certificate, Certificate of Origin, SGS/Intertek"),
        bullet("กำลังการผลิต — ตันต่อเดือน และระยะเวลาสัญญา"),
        bullet("ประสบการณ์ส่งออกข้าวไปจีน — ตัน/ปี และท่าเรือที่ใช้"),
        divider(),

        # Pricing table (blank for vendor to fill)
        heading3("ตารางเสนอราคา (กรุณากรอก)"),
        table(
            ["ปริมาณ (MT)", "ราคา FOB (USD/MT)", "ราคา CIF (USD/MT)", "Incoterm", "หมายเหตุ"],
            [
                ["10,000", "", "", "", ""],
                ["50,000", "", "", "", ""],
                ["100,000", "", "", "", ""],
                ["200,000", "", "", "", ""],
            ]
        ),
        divider(),

        # Certifications
        heading3("ใบรับรองที่จำเป็น"),
        bullet("GACC Registration (ลงทะเบียนกับ General Administration of Customs China)", bold=True),
        bullet("Phytosanitary Certificate — จากกรมวิชาการเกษตร"),
        bullet("Certificate of Origin — Form A / Form E (ASEAN-China FTA)"),
        bullet("SGS หรือ Intertek Pre-shipment Inspection"),
        bullet("ISO 9001 / HACCP / BRC (ถ้ามี)"),
        divider(),

        # Reply info
        heading3("การตอบรับ"),
        para(txt("กรุณาตอบกลับมาที่: "), txt("shipping@goco.bz", bold=True)),
        para(txt("ผู้ติดต่อ: "), txt(f"{BUYER['contact_name']} | {BUYER['email']} | {BUYER['mobile']}", bold=True)),
        para(txt("กำหนดตอบ: "), txt(deadline, bold=True)),
        divider(),

        # Footer
        para(txt("เอกสารนี้จัดทำโดย GO Corporation Co., Ltd. ในนามของ Nubo International Pte. Ltd.")),
        para(txt("อีเมลอัตโนมัติ: eukrit@goco.bz | Reply-To: shipping@goco.bz")),
    ]
    return blocks


def create_page(token, buyer_address):
    payload = {
        "parent": {"type": "page_id", "page_id": PARENT_PAGE_ID},
        "icon": {"type": "emoji", "emoji": "🍚"},
        "cover": None,
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": "RFQ — ข้าวขาวไทย 5% หัก ส่งออกจีน 200,000 MT"}}]
            }
        },
        "children": build_blocks(buyer_address),
    }
    r = requests.post(f"{NOTION_API}/pages", headers=headers(token), json=payload)
    if r.status_code == 200:
        page = r.json()
        url = page.get("url", "")
        print(f"\n✅ Notion page created successfully!")
        print(f"   URL: {url}")
        print(f"   Page ID: {page['id']}")
        return page
    else:
        print(f"\n❌ Failed to create page: {r.status_code}")
        print(r.text)
        sys.exit(1)


def main():
    token = get_token()
    print(f"✅ Token loaded ({token[:12]}...)")

    print("📄 Fetching Nubo International address from Notion...")
    address_text = get_page_text(token, ADDRESS_PAGE_ID)
    if address_text:
        print(f"   Address found: {address_text[:80]}...")
    else:
        print("   Address page not accessible — using placeholder")
        address_text = "ดูหน้า Nubo International Address ใน Notion"

    print("📝 Creating RFQ Rice Inquiry page...")
    create_page(token, address_text)


if __name__ == "__main__":
    main()
