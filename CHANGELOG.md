# Changelog

All notable changes to the Procurement Automation system are documented here.

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
