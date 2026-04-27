# Changelog

All notable changes to the Procurement Automation system are documented here.

---

## [v1.7.0] — 2026-04-28

### Added — Gmail Router migration (Stage C, dual-path with feature flag)

The first consumer migration off a private `gmail_sender.py` and onto the
central Gmail Router (`data-comms-send-email` in the `data-communications`
repo). Soft cutover: both paths coexist behind `USE_GMAIL_ROUTER`; first
deploy keeps the flag **off** so behaviour is unchanged.

- **New module `src/gmail_router_client.py`** — HTTP client for Gmail
  Router. `send_via_router(...)` mirrors the legacy `send_email` shape
  (`{message_id, thread_id, label_ids}`) so all 3 callers (`rfq_workflow`,
  `send_followups`, `send_rice_call_followup`) need zero changes.
- **Authentication via metadata server** — `google.oauth2.id_token.fetch_id_token`
  fetches a JWT whose `aud` claim equals the Gmail Router URL. Signed by
  the Cloud Functions runtime SA (`538978391890-compute@developer`,
  already added to `email_sender_allowlist` in data-communications). No
  keys to manage.
- **Attachments are read + base64-encoded** in the wrapper — Gmail Router
  expects `{filename, mimeType, contentBase64}` whereas the legacy path
  took raw filesystem paths. Same callers, transparent to them.
- `src/gmail_sender.py` `send_email()` now dispatches on
  `is_router_enabled()` (env `USE_GMAIL_ROUTER ∈ {true,1,yes,on}`).
  When on: delegates to `send_via_router`. When off: legacy MIME-build
  path runs unchanged. Recipient normalization (string → list) happens
  before the dispatch so both paths see identical inputs.
- `cloudbuild.yaml` — `USE_GMAIL_ROUTER=false` added to all 4 functions'
  `--set-env-vars` so the flag is **explicitly visible** in the deploy
  config. Flip to `true` (per function) via `gcloud functions deploy
  --update-env-vars=USE_GMAIL_ROUTER=true` once the Router path is
  verified for that function.
- `requirements.txt` — added `requests>=2.32.0` (used by the Router HTTP
  call; previously transitive).
- **9 new tests** in `tests/test_gmail_sender.py`: `TestGmailRouterDispatch`
  (4 tests covering flag-on dispatch, recipient normalization, threading
  passthrough, flag-off legacy fallback) + `TestGmailRouterClient` (5
  tests covering env-var truthy/falsy parsing, attachment encoding,
  missing-file error). Existing 18 tests still pass — public API is
  unchanged.

### Why this migration first?

Of the 6 outbound senders across the workspace, procurement-automation
has the highest send volume (RFQ dispatch, follow-ups, reminders) and
the most complex shape (CC, threading, attachments). If the Router can
serve procurement-automation, it can serve the other 5.

### Cutover plan

1. **Deploy** with `USE_GMAIL_ROUTER=false` (this PR). Verify nothing breaks.
2. Pick a low-traffic function (probably `rfq-reminder-cron` since it's
   scheduled and easy to monitor). Flip its env var to `true`. Watch
   the next reminder cycle. Confirm `email_sends` rows in the
   data-communications Firestore have `caller="procurement-automation/gmail_sender"`
   and `callerSa="538978391890-compute@developer.gserviceaccount.com"`.
3. Flip `send-rfq` next. Then `process-procurement-email`. Then the
   bridge subscriber.
4. Once all 4 are running on the Router for ~1 week, flip the cloudbuild
   defaults to `USE_GMAIL_ROUTER=true` and remove the legacy MIME path
   from `gmail_sender.py`. Delete `gmail_auth.py` if no other module
   uses it.

### Files

- `src/gmail_router_client.py` (new) — `send_via_router`,
  `_file_to_attachment_dict`, `is_router_enabled`.
- `src/gmail_sender.py` — dispatch in `send_email`.
- `tests/test_gmail_sender.py` — `TestGmailRouterDispatch` (4),
  `TestGmailRouterClient` (5).
- `cloudbuild.yaml` — `USE_GMAIL_ROUTER=false` added to all 4 functions.
- `requirements.txt` — `requests>=2.32.0`.

### Outstanding

- Flag is `false` in this PR. **No behaviour change at deploy time.**
  Manual env-var flip required to actually exercise the Router path
  in production.
- Once all callers run on the Router for a week, delete the legacy MIME
  path. That follow-up is tracked but deliberately out of scope here —
  a single-PR rip-and-replace is too risky for the org's primary
  outbound channel.
- The 5 other outbound senders (accounting-automation × 3, shipping-automation,
  go-documents, human-resources, 2025 Latirra Ads) are still on private
  paths. Their migrations follow this same template once procurement
  is verified.

### Outcome

Pending push + Cloud Build deploy. Pure additive at the deploy boundary.

## [v1.6.0] — 2026-04-26

### Added — Bridge subscriber for `gmail-classified-events`
- New Cloud Function `process-classified-event` (Pub/Sub trigger on `gmail-classified-events` from `data-communications`). Entry point: `main.process_classified_event`. Decodes the v1 envelope (see `data-communications/docs/BRIDGE_CONTRACT.md`), drops own-mailbox senders (loop guard), drops non-procurement events (mirrors the server-side filter `category="procurement" OR vendorName != ""`), and adapts the envelope into the internal `msg` shape via `_envelope_to_msg` so the existing `_process_single_message` chain (`match_sender_to_vendor` → `classify_vendor_response` → `extract_vendor_rates` → `rfq_workflow`) works unchanged.
- **Deployed in dry-run mode** (`BRIDGE_DRY_RUN=true`). For a 7-day audit window the legacy `process-procurement-email` (Pub/Sub on `gmail-procurement-watch`) continues to drive real state changes; the bridge subscriber observes the same traffic, writes to a new audit collection `bridge_processed_messages`, and posts/writes nothing else. Idempotency is keyed on `messageId` in that collection.
- After 7 days of clean dry-run observation: flip `BRIDGE_DRY_RUN=false`, drop the legacy function deploy, stop renewing `gmail-procurement-watch`. From that point `data-communications` is the single intake for `eukrit@goco.bz`.

### Files
- `main.py` — added `process_classified_event` entry, `_envelope_to_msg`, `_is_relevant`.
- `cloudbuild.yaml` — added `process-classified-event` deploy step.

### Outcome
Pending Cloud Build; legacy path untouched so this PR is risk-isolated.

---

## [v1.5.0] — 2026-04-24

### Added — Solar PV (Back Contact) RFQ: `RFQ-GO-2026-04-SOLAR-PV`
- `data/china_solar_pv_suppliers.json` — 15 Chinese Tier-1 PV manufacturers,
  focused on Back Contact cell technology (Aiko ABC, LONGi HIBC / HPBC,
  Maxeon IBC, Huansheng HBC, Xi'an SPIC HBC, DAS XBC, Akcome HJT-IBC,
  GS-Solar HBC) with premium N-type alternates (Trina, JinkoSolar, JA,
  Canadian, Risen HJT, Tongwei HJT, Jolywood n-TOPCon).
- `scripts/seed_solar_pv_rfq.py` — seeds `procurement_templates/solar-pv-rfq-v1`
  (bilingual EN/CN body), inquiry `RFQ-GO-2026-04-SOLAR-PV`, and 15 vendors
  into `vendor_directory`. Pilot quantity ~18 panels (~10 kW) + tiered
  container / 100 kW / 500 kW / 1 MW pricing. Requests full cert list
  (IEC 61215/61730, CE, TÜV, UL, MCS, JET, CEC, Thai MEA/PEA/TISI),
  datasheets, and sample pricing.
- `scripts/setup_gmail_solar_pv_filter.py` — extends the shared Gmail
  label `Suppliers/Solar` (created in v1.3.0 for slewing-drive vendors)
  with a PV-module `from:` filter across all 30 vendor addresses.
- `scripts/dry_run_solar_rfq.py` — rendered-body preview (no writes, no
  sends) used for user approval before dispatch.
- Deadline `2026-05-15` (Fri after China Golden Week — pushed out from
  default 2-week window to avoid May 1–5 factory shutdown).
- Slack routing override: `#areda-mike` (per-inquiry override on the
  inquiry doc).
- Reply-To `procurement@goco.bz`; From `eukrit@goco.bz`.
- Executed 2026-04-24 — dispatched via `https://send-rfq-rg5gmtwrfa-uc.a.run.app`:
  **15 sent, 0 skipped, 0 errors**. Slack dispatch summary posted manually
  to `#areda-mike` (Cloud Function's auto-notify silently no-op'd this
  time — follow-up task to investigate).
- ⚠️ All 30 vendor emails are domain-inferred (not verified personal
  contacts) — bounces expected; triage on reply.

### Follow-up tasks (not in this commit)
- Investigate why `notify_rfq_dispatched` didn't post to `#areda-mike`
  for this dispatch (POE-DISPLAY earlier the same day did post).
- Verify top-5 vendor contacts (Aiko, LONGi, Maxeon, DAS, Trina) against
  current contact pages to reduce bounce rate on next dispatch.

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
- RFQ document (HTML + PDF): `docs/reports/rfq-china-bangkok.html`
- Freight rate baseline calculator: `scripts/freight_calculator_china_thai.py`
- Firestore database `procurement-automation` created (us-central1)
- Generic procurement schema designed for multi-category RFQ campaigns
- Project CLAUDE.md with credentials, Firestore, and deployment rules
