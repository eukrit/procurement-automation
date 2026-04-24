# Changelog

All notable changes to the Procurement Automation system are documented here.

---

## [v1.4.0] — 2026-04-24

### Added — Master RFQ Dashboard (Cloud Run)
- `dashboard/main.py` — Flask app serving a live master RFQ dashboard that
  reads `rfq_inquiries` + `vendors` subcollections from Firestore
  (`procurement-automation` database) and renders:
  - Root `/`: KPI strip (projects / active / vendors / responses) + directory
    of every RFQ project with status badge, response progress bar, and
    deadline countdown.
  - `/rfq/<inquiry_id>`: Per-project detail page with metadata panel and full
    vendor table (company, email, status, latest rates, last update).
  - `/api/inquiries`: JSON API for the same data.
  - `/healthz`: health probe.
- `dashboard/Dockerfile`, `dashboard/requirements.txt` — gunicorn + Flask +
  `google-cloud-firestore`.
- Deployed to Cloud Run `rfq-dashboard` (asia-southeast1, service account
  `claude@ai-agents-go.iam.gserviceaccount.com`, public/unauth'd).
- **Live URL:** https://rfq-dashboard-538978391890.asia-southeast1.run.app
- Smoke-tested 2026-04-24: HTTP 200, 5 RFQ projects listed (FREIGHT,
  RICE-EXPORT, EV-CHARGER, POE-DISPLAY, SOLAR-SLEWING).

---

## [v1.3.0] — 2026-04-24

### Added — Solar Slewing Drive RFQ: SDE9 Dual Axis Solar Tracker
- `data/china_solar_slewing_drive_suppliers.json` — 7 competing Chinese SDE9/slewing
  drive manufacturers (Luoyang Hengguan, Xuzhou Wanda, Hangzhou Chinabase, Suzhou Haydon,
  Shenzhen Topele, Yantai Hengfengtai, Luoyang Longwei). Benchmark: Jimmy Technology
  (Huizhou) Co., Ltd. at THB 14,856/unit (2–99 pcs) — NOT contacted.
- `scripts/seed_solar_slewing_rfq.py` — Seeds Firestore inquiry
  `RFQ-GO-2026-04-SOLAR-SLEWING`, template `solar-slewing-rfq-v1`, and 7 vendor
  documents. Bilingual (CN/EN) email asks for SDE9-equivalent quote, full slewing
  drive range, catalog (PDF), and complete price list. Deadline 2026-05-07.
  Slack routing: `#areda-mike`.
- `scripts/setup_gmail_solar_filter.py` — Creates Gmail label `Suppliers/Solar`
  (id=Label_518) and filter tagging inbound mail from all 11 vendor contact addresses.
- Executed 2026-04-24 — 7 RFQ emails dispatched to all vendors, all status=`sent`.

---

## [v1.2.0] — 2026-04-21

### Added — Rice Export RFQ: Thai Notion RFQ Page
- `scripts/create_notion_rfq_rice.py` — Creates a fully-formatted Thai RFQ page
  in Notion under the Nubo International parent page. Posts product spec tables,
  quality spec, pricing tiers by contract length, certification list, and reply
  instructions.
- Quantity locked to 200 MT/month (~2,400 MT/year over a 12-month contract),
  with pricing tiers at 1 / 3 / 6 / 12 months.
- Packaging locked to 25 kg new PP bags only — vendors asked to send actual
  bag photos, branding/printing, and packing standards.
- 🚨 Urgent callout at top of page: BEST PRICE required by end-of-business today
  (21 April 2026, 18:00), bilingual Thai/English.
- Buyer contact corrected to Eukrit Kraikosol; buyer address baked in as
  fallback constant (`BUYER_ADDRESS_FALLBACK`) when the integration can't
  access the Nubo International Address sub-page.
- Executed 2026-04-21 — live page:
  https://www.notion.so/RFQ-5-200-MT-34982cea8bb081c29f25f580990b5a06

---

## [v1.1.0] — 2026-04-20

### Added — Rice Export RFQ: Thai Call-Me Follow-up
- `scripts/send_rice_call_followup.py` — Sends a simple Thai follow-up to every
  silent Rice Export RFQ vendor (status=`sent`), replying in the existing Gmail
  thread and asking the recipient to call +66 61 491 6393 for further discussion.
- Logs each outbound as a `follow_up_call` message, bumps the vendor status to
  `reminder_1`, and increments `reminders.count`.
- Executed against inquiry `RFQ-GO-2026-04-RICE-EXPORT` on 2026-04-20 —
  12 / 12 silent vendors received the follow-up.

---

## [v1.0.0] — 2026-04-06

### Added — Phase 1: Firestore Schema + Seed Vendors
- `src/rfq_store.py` — Full Firestore CRUD (inquiries, vendors, messages, directory, templates, config)
- `scripts/seed_rfq_agents.py` — Seeds 20 freight forwarders, inquiry, template, workflow config
- Firestore DB moved from us-central1 to asia-southeast1
- Renamed "campaigns" to "inquiries" throughout
- 27 unit tests for rfq_store

### Added — Phase 2: Gmail Sender + RFQ Dispatch
- `src/gmail_sender.py` — Gmail client with domain-wide delegation (send, auto-reply, reminders)
- `main.py` — Cloud Function entry point `send_rfq` (HTTP trigger)
- `cloudbuild.yaml` — Cloud Functions + Cloud Run deployment config
- Bilingual email templates (Chinese + English)
- 18 unit tests for gmail_sender

### Added — Phase 3: Gmail Watch + Gemini Classification
- `src/gmail_reader.py` — Gmail watch setup, History API fetch, body/attachment parsing
- `src/parsers/rfq_gemini.py` — 3 Gemini prompts: classify, extract rates, auto-reply
- Full inbound email routing in `process_procurement_email`: match sender → classify → extract → route
- Pub/Sub topic `gmail-procurement-watch` with Gmail push permissions
- `scripts/setup_gmail_watch.py` — Watch setup/refresh script
- 30 unit tests for gmail_reader + rfq_gemini

### Added — Phase 4: Auto-Reply Engine + Reminder Cron
- `src/rfq_workflow.py` — 15-state machine, auto-reply decision engine, rate anomaly detection, reminder scheduler
- `src/slack_notifier.py` — 6 Slack notification types with Block Kit formatting
- Full `rfq_reminder_cron` (Day 5/7/10/close logic)
- Slack notifications wired into escalation, auto-reply, rate anomaly flows
- 30 unit tests for rfq_workflow + slack_notifier

### Added — Phase 5: MCP Tools + Rate Comparison + REST API
- `mcp-server/server.py` — MCP server with 5 tools + 5 REST endpoints
- Rate comparison engine: score vendors vs Gift Somlak baseline, benchmark ED 70 shipment
- MCP tools: get_inquiry_status, get_vendor_detail, compare_rates, send_vendor_reminder, list_inquiries
- REST API: /api/inquiries, /api/inquiries/{id}/vendors, /api/inquiries/{id}/compare
- SSE transport for MCP connectivity

---

## [v0.1.0] — 2026-04-06

### Added
- Initial project setup
- Build plan: `docs/BuildPlans/RFQ-Automation-BuildPlan.md`
- 20 China-Thailand freight forwarder candidates: `data/china_thailand_freight_forwarders.json`
- RFQ document (HTML + PDF): `docs/rfq-china-bangkok.html`
- Freight rate baseline calculator: `scripts/freight_calculator_china_thai.py`
- Firestore database `procurement-automation` created (us-central1)
- Generic procurement schema designed for multi-category RFQ campaigns
- Project CLAUDE.md with credentials, Firestore, and deployment rules
