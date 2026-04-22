# Build Log — procurement-automation

_Semver, dated entries. One section per version._

---

## [0.2.0-research.1] — 2026-04-22

**Summary:** Added research deliverable — Chinese supplier shortlist for 10" PoE Android multi-touch signage displays as replacements for the discontinued Philips 10BDL3051T/00 (and successor 10BDL4551T/00). 12-pc procurement target.

**Branch:** `claude/research-led-poe-alternatives-SIbjj`

**Files changed:**
- `data/china_poe_touch_displays.json` — new structured supplier shortlist (5 vendors, Shenzhen-based, with full specs, certifications, contact info, FOB estimates, shortlist ranking)
- `docs/research/Philips-10BDL3051T-alternatives.md` — new research report with Philips baseline, per-vendor profiles, comparison table, landed-cost budget for 12 pcs, recommended next steps
- `BUILD_LOG.md` — new (first entry)
- `.claude/PROGRESS.md` — new (session-start protocol)

**Key findings:**
- Philips 10BDL3051T/00 and 10BDL4551T/00 are both end-of-life / unavailable on Philips Thailand.
- 5 credible Shenzhen manufacturers shortlisted: **ELC Sign**, **MIO-LCD**, **RAYPODO**, **AIYOS**, **HDFocus**.
- All support IEEE 802.3at PoE+, 10.1" IPS 1280×800 (AIYOS offers FHD upgrade), 10-point PCAP touch (exceeds Philips 5-point), Android 8.1–11, CE/FCC/RoHS.
- Estimated landed cost for 12 pcs to Thailand: USD 1,800–3,800 (vs ~USD 7,200–9,600 for equivalent Philips retail — 60–75% savings).
- RAYPODO sells retail on Amazon/Newegg/Walmart → can sample 1 unit for evaluation before placing factory order.

**Outcome:** Research deliverable ready for RFQ dispatch via the existing `rfq_inquiries` workflow. Recommend sampling (RAYPODO retail + ELC Sign direct) before the 12-pc main order.

**Co-Authored-By:** Claude Opus 4.7 (1M context) <noreply@anthropic.com>

---
