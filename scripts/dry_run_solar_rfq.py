#!/usr/bin/env python3
"""
dry_run_solar_rfq.py — Render the Solar PV RFQ email for preview WITHOUT
sending anything. Sends ZERO emails, writes ZERO Firestore docs.

Purpose: let the user sanity-check the recipient list + subject + rendered
body before authorising the real dispatch.

Usage:
    python scripts/dry_run_solar_rfq.py                 # preview first vendor
    python scripts/dry_run_solar_rfq.py --all           # preview every vendor body
    python scripts/dry_run_solar_rfq.py --vendor aiko   # preview a single vendor (slug match)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Reuse the single source of truth for the template + ids.
import scripts.seed_solar_pv_rfq as seed  # noqa: E402

DATA_FILE = seed.DATA_FILE
INQUIRY_ID = seed.INQUIRY_ID
TEMPLATE_ID = seed.TEMPLATE_ID
DEADLINE = seed.RESPONSE_DEADLINE
SLACK_CHANNEL = seed.SLACK_CHANNEL


# The template dict lives inline inside seed_solar_pv_rfq.seed_template().
# Duplicate the minimum here to keep this preview script independent of
# Firestore. Kept in sync manually — this is documentation, not production.
SUBJECT_TEMPLATE = "RFQ: {title} | GO Corporation Co., Ltd."

TITLE = (
    "~50 m² / ~10 kW Back Contact (IBC/ABC/HBC/HPBC) Solar PV Modules "
    "for Thailand Pilot — with Container / Utility Scale-up Pricing"
)

# Load EN/CN bodies by introspecting the seed module's seed_template()
# closure is overkill; instead, render from a local mirror.
BODY_EN = (
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
)

BODY_CN = (
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
)


def _slug(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    return s


def render_for_vendor(company: dict) -> dict:
    vendor_name = company["name_en"]
    subj = SUBJECT_TEMPLATE.format(title=TITLE)
    en = BODY_EN.format(vendor_name=vendor_name, deadline=DEADLINE)
    cn = BODY_CN.format(vendor_name=company.get("name_cn") or vendor_name,
                        deadline=DEADLINE)
    return {
        "to": company.get("contact_email"),
        "cc": company.get("contact_email_alt"),
        "reply_to": "procurement@goco.bz",
        "from_email": "eukrit@goco.bz",
        "subject": subj,
        "body_en": en,
        "body_cn": cn,
    }


def print_recipient_table(companies: list[dict]) -> None:
    print("-" * 100)
    print(f"{'#':>2}  {'Vendor':<42}  {'Primary email':<35}  {'Verified':<8}  Tech")
    print("-" * 100)
    for i, c in enumerate(companies, 1):
        tech = ", ".join(c.get("cell_technology", []))[:24]
        email = c.get("contact_email") or "—"
        ver = "yes" if c.get("email_verified") else "NO"
        print(f"{i:>2}  {c['name_en'][:42]:<42}  {email:<35}  {ver:<8}  {tech}")
    print("-" * 100)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true",
                        help="Render rendered body for every vendor, not just first")
    parser.add_argument("--vendor", default=None,
                        help="Preview a single vendor (substring of slug or name_en)")
    args = parser.parse_args()

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    companies = data["companies"]

    print("=" * 80)
    print("  DRY-RUN PREVIEW — Solar PV RFQ (NO emails sent, NO Firestore writes)")
    print("=" * 80)
    print(f"  Inquiry ID:        {INQUIRY_ID}")
    print(f"  Template ID:       {TEMPLATE_ID}")
    print(f"  Response deadline: {DEADLINE}")
    print(f"  Slack channel:     {SLACK_CHANNEL}")
    print(f"  From / Reply-To:   eukrit@goco.bz / procurement@goco.bz")
    print(f"  Vendors on list:   {len(companies)}")
    print()

    print_recipient_table(companies)
    print()

    # Pick which vendors to render bodies for.
    if args.vendor:
        needle = args.vendor.lower()
        chosen = [c for c in companies
                  if needle in _slug(c["name_en"]) or needle in c["name_en"].lower()]
        if not chosen:
            print(f"No vendor matched '{args.vendor}'.")
            sys.exit(1)
    elif args.all:
        chosen = companies
    else:
        chosen = companies[:1]

    for c in chosen:
        render = render_for_vendor(c)
        print("=" * 80)
        print(f"  VENDOR: {c['name_en']}  ({c.get('name_cn', '')})")
        print("=" * 80)
        print(f"From:     {render['from_email']}")
        print(f"To:       {render['to']}")
        print(f"Cc:       {render['cc']}")
        print(f"Reply-To: {render['reply_to']}")
        print(f"Subject:  {render['subject']}")
        print()
        print("--- ENGLISH BODY ---")
        print(render["body_en"])
        print()
        print("--- CHINESE BODY (中文) ---")
        print(render["body_cn"])
        print()

    print("=" * 80)
    print("  END OF PREVIEW — NOTHING WAS SENT OR WRITTEN.")
    print("=" * 80)


if __name__ == "__main__":
    main()
