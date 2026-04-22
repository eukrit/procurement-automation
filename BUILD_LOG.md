# Build Log — procurement-automation

_Semver, dated entries. One section per version._

---

## [0.2.1-research.2] — 2026-04-22

**Summary:** Added Qbic Technology TD-1060 Slim (Taiwan) as vendor #6 to the PoE display supplier list. Wrote seed + dispatch scripts for all 6 vendors (5 Shenzhen OEMs + Qbic). Added bilingual (EN+CN) RFQ email for Chinese vendors and English-only for Qbic.

**Branch:** `claude/research-led-poe-alternatives-SIbjj`

**Files changed:**
- `data/china_poe_touch_displays.json` — added Qbic Technology as vendor #6 (Taiwan); updated total_companies to 6; expanded description
- `scripts/seed_poe_display_rfq.py` — new: seeds Firestore with inquiry, template, and all 6 vendors for `RFQ-GO-2026-04-POE-DISPLAY`
- `scripts/send_poe_display_rfq.py` — new: dispatches initial RFQ emails to all 6 vendors; bilingual EN+CN for Chinese OEMs, English-only for Qbic; logs to Firestore; `--dry` preview flag
- `BUILD_LOG.md` — this entry

**Qbic TD-1060 Slim key specs vs Philips baseline:**
- 350 nits (EXCEEDS Philips 300 nits)
- 1000:1 contrast (EXCEEDS Philips 500:1)
- 10-point PCAP touch (EXCEEDS Philips 5-point)
- LED light bar, 20.8 mm slim profile
- Android 8.1 (parity), PoE+ (parity), WiFi 802.11ac dual-band (better than Philips)
- Taiwan-brand quality; integrated with SOTI MDM, Flowscape, TigerMeeting room-booking platforms

**To run (from local machine with credentials):**
```bash
python scripts/seed_poe_display_rfq.py --dry     # verify 6 vendors
python scripts/seed_poe_display_rfq.py            # write to Firestore
python scripts/send_poe_display_rfq.py --dry      # preview emails
python scripts/send_poe_display_rfq.py            # live send
```

**Outcome:** 6 RFQ send scripts ready. Run from local machine with GOOGLE_APPLICATION_CREDENTIALS set.

**Co-Authored-By:** Claude Opus 4.6 (1M context) <noreply@anthropic.com>

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
