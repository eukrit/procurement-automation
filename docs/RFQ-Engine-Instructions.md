# RFQ Engine — How to Launch a New Procurement Inquiry

## Overview

This procurement automation platform handles the full RFQ lifecycle for **any product category**. The same engine works for materials, equipment, services, or any vendor sourcing round. Core stack: Firestore + Gmail (DWD) + Gemini 2.5 Flash + Slack + Cloud Functions.

**Completed RFQs:**
- `RFQ-GO-2026-04-FREIGHT` — China→Bangkok freight forwarders (14 vendors)
- `RFQ-GO-2026-04-EV-CHARGER` — V2H/V2G AC wallbox (7 vendors) — [Dashboard](https://eukrit.github.io/business-automation/wallbox-ev-charger-rfq.html)
- `RFQ-GO-2026-04-RICE-EXPORT` — Thai white rice 5% broken, China export (12 vendors)
- `RFQ-GO-2026-04-SOLAR-SLEWING` — SDE9 dual-axis solar tracker slewing drives (7 vendors) — v1.3.0
- `RFQ-GO-2026-04-POE-DISPLAY` — 10.1" Android PoE+ multi-touch displays (6 vendors)
- `RFQ-GO-2026-04-SOLAR-PV` — Back Contact (IBC/ABC/HBC/HPBC) solar PV modules, ~10 kW pilot + container/MW scale-up (15 vendors, deadline 2026-05-15) — v1.5.0

**Live master dashboard (Firestore-backed, auto-updates):** https://rfq-dashboard-538978391890.asia-southeast1.run.app/

## Prerequisites

Before launching a new inquiry, ensure:
1. Cloud Functions are deployed (`send-rfq`, `process-procurement-email`, `rfq-reminder-cron`)
2. Gmail watch is active (`python scripts/setup_gmail_watch.py`)
3. Cloud Scheduler is running (daily 09:00 Bangkok)
4. Firestore DB `procurement-automation` is accessible
5. DWD scopes include `gmail.send`, `gmail.readonly`, `gmail.labels`, `gmail.settings.basic`

---

## Step-by-Step: Launch a New RFQ

### Step 1: Research & Prepare Vendor List

**Goal:** Create a JSON file in `data/` with shortlisted suppliers.

**How to research:**
- Made-in-China, Alibaba, GlobalSources for manufacturers
- ZoomInfo / LinkedIn for contact emails when not on vendor site
- Verify emails: mark `email_verified: true/false` and add `email_notes`
- Include both primary and alternate contacts

**File:** `data/{category}_suppliers.json`

```json
{
  "metadata": {
    "title": "HPL Laminate Suppliers",
    "description": "What we're sourcing and why",
    "compiled_date": "2026-05-01",
    "total_companies": 15,
    "search_criteria": {
      "target_product": "HPL Laminates, 4x8 sheets",
      "priority_features": ["fire-rated", "UV-stable"],
      "priority_regions": ["Guangdong", "Zhejiang"]
    },
    "email_verification_notes": {
      "verified_from_vendor_site_or_directory": ["sales@vendor1.com"],
      "inferred_from_domain_pattern": ["sales@vendor2.com"],
      "action_required": "Review inferred emails before dispatch."
    }
  },
  "companies": [
    {
      "id": 1,
      "name_en": "Vendor Name Co., Ltd.",
      "name_cn": "中文名",
      "website": "https://...",
      "contact_email": "sales@vendor.com",
      "contact_email_alt": "info@vendor.com",
      "email_verified": true,
      "email_notes": "Listed on company contact page",
      "phone": "+86...",
      "city": "Shenzhen",
      "province": "Guangdong",
      "product_summary": "What they make that's relevant",
      "notes": "Key supplier info, why shortlisted"
    }
  ]
}
```

### Step 2: Create a Procurement Template

**Goal:** Define the bilingual email body, extraction schema, and auto-reply context.

Templates are stored in Firestore `procurement_templates/{template_id}`. They define:
- **Email body** (Chinese + English) with `{vendor_name}`, `{deadline}`, `{title}` placeholders
- **Required fields** the vendor must provide
- **Extraction schema** for Gemini to parse responses into structured data
- **Auto-reply context** so Gemini answers vendor questions accurately

**Template structure:**

```python
template = {
    "name": "HPL Laminate Supplier RFQ",
    "category": "materials",
    "subcategory": "hpl-laminates",
    "version": 1,
    "email_template": {
        "subject": "RFQ: {title} | GO Corporation Co., Ltd.",
        "body_cn": "Chinese email body with {vendor_name}, {deadline}, {title} placeholders...",
        "body_en": "English email body with {vendor_name}, {deadline}, {title} placeholders...",
    },
    "required_fields": [
        "unit_price_fob_usd", "moq", "lead_time_weeks", ...
    ],
    "extraction_schema": {
        "rates": {
            "unit_price_fob_usd": {"type": "number", "unit": "USD/unit"},
            "moq": {"type": "number", "unit": "units"},
            "lead_time_weeks": {"type": "number", "unit": "weeks"},
        },
        "product_specs": { ... },
        "capabilities": { ... },
    },
    "auto_reply_context": "GO Corporation is a Thai company. We need... Typical order: ..."
}
```

**Tips:**
- The `extraction_schema` drives what Gemini looks for in vendor replies. Be specific with field names and units.
- The `auto_reply_context` should include: who we are, what we need, typical quantities, ship-to, payment terms, and what to escalate.
- See `scripts/seed_ev_charger_rfq.py` lines 210-341 for a complete real example.

### Step 3: Write the Seed Script

**Goal:** Create a Python script that seeds Firestore with the template, inquiry, and vendors.

**File:** `scripts/seed_{category}_rfq.py`

The seed script does 3 things:
1. **Seed template** → `procurement_templates/{template_id}`
2. **Create inquiry** → `rfq_inquiries/{inquiry_id}`
3. **Add vendors** → `rfq_inquiries/{id}/vendors/{vendor_id}` + `vendor_directory/{vendor_id}`

**Inquiry config — key fields:**

```python
config = {
    "inquiry_id": "RFQ-GO-{YYYY}-{MM}-{CATEGORY}",
    "title": "Human-readable title for email subject",
    "category": "ev-charger",           # broad category
    "subcategory": "v2h-v2g-ac-wallbox", # specific type
    "template_id": "{category}-rfq-v1",
    "rfq_document": {
        "pdf_path": None,               # or "docs/RFQ-GO-....pdf" if attaching
    },
    "send_config": {
        "from_email": "eukrit@goco.bz",
        "reply_to": "shipping@goco.bz",
        "cc": ["shipping@goco.bz"],
        "subject_template": "RFQ: {title} | GO Corporation Co., Ltd.",
        "language": "bilingual",
        "attach_pdf": False,             # True to attach PDF
        "inline_html": True,             # body from template
    },
    "automation_config": {
        "auto_reply_enabled": True,
        "auto_reply_min_confidence": 0.8,
        "approval_required_for": ["pricing", "terms", "commitments", "legal"],
        "max_auto_replies_per_vendor": 3,
        "reminder_day_1": 5,
        "reminder_day_2": 7,
        "escalate_day": 10,
        "slack_channel": "#areda-mike",  # per-inquiry override
    },
    "scoring_config": {
        "weights": { "price": 0.40, "capability": 0.25, ... },
        "baseline": { "source": "...", "reference_price": 1000 },
    },
    "response_deadline": "2026-05-15",
    "status": "draft",
    "created_by": "eukrit@goco.bz",
}
```

**Run:** `python scripts/seed_{category}_rfq.py`

### Step 4: Create Gmail Label + Filter

**Goal:** Auto-label inbound replies from vendor emails so they're organized and easy to monitor.

**File:** `scripts/setup_gmail_{category}_filter.py`

The script:
1. Creates a Gmail label (e.g., `Suppliers/EV Charger`)
2. Creates a filter matching all vendor email addresses → auto-apply label, never spam

**Pattern:** Copy from `scripts/setup_gmail_ev_charger_filter.py` and change:
- `LABEL_NAME` — the Gmail label path
- `VENDOR_EMAILS` — list of all vendor email addresses (primary + alt)

**Run:** `python scripts/setup_gmail_{category}_filter.py`

**Note:** Requires DWD scopes `gmail.labels` + `gmail.settings.basic`. If you get a 403, the scopes may not have propagated yet (up to 24h).

### Step 5: Send the RFQ

**Always dry-run first:**
```bash
curl -X POST https://us-central1-ai-agents-go.cloudfunctions.net/send-rfq \
  -H "Content-Type: application/json" \
  -d '{"inquiry_id": "RFQ-GO-2026-05-HPL", "dry_run": true}'
```

Review the rendered subjects and ensure vendor count matches.

**Live send (all vendors):**
```bash
curl -X POST https://us-central1-ai-agents-go.cloudfunctions.net/send-rfq \
  -H "Content-Type: application/json" \
  -d '{"inquiry_id": "RFQ-GO-2026-05-HPL"}'
```

**Send to specific vendors only:**
```bash
curl -X POST https://us-central1-ai-agents-go.cloudfunctions.net/send-rfq \
  -H "Content-Type: application/json" \
  -d '{"inquiry_id": "RFQ-GO-2026-05-HPL", "vendor_ids": ["vendor-1", "vendor-2"]}'
```

### Step 6: Create Dashboard Page

**Goal:** Public summary page for tracking the RFQ round.

**File:** `business-automation/docs/{slug}.html`

The dashboard page should include:
- KPI cards (vendors contacted, emails delivered, replies received)
- RFQ specification summary
- Vendor cards with capabilities, certifications, contact info
- Automation pipeline timeline
- Infrastructure details (inquiry ID, template, Slack channel, etc.)

**Pattern:** Copy from `business-automation/docs/reports/wallbox-ev-charger-rfq.html` and adapt.

**Commit to:** `eukrit/business-automation` repo → auto-deploys to GitHub Pages.

**URL:** `https://eukrit.github.io/business-automation/{slug}.html`

### Step 7: Monitor

Once sent, the automation handles:

1. **Gmail Watch** detects inbound replies via Pub/Sub → `process-procurement-email`
2. **Gemini classifies** each reply (rate_quote, question, decline, etc.)
3. **Gemini extracts** structured data using the template's `extraction_schema`
4. **Auto-reply engine** answers vendor questions:
   - Confidence > 0.8 → auto-send
   - Confidence 0.6-0.8 → Slack approval draft
   - Confidence < 0.6 → escalate to human
5. **Slack notifications** to the inquiry's `slack_channel` override
6. **Reminder cron** sends follow-ups on Day 5, Day 7, escalates Day 10

**Manual monitoring:**
- Gmail: check the label created in Step 4
- Slack: watch the inquiry's designated channel
- Firestore: `rfq_inquiries/{id}/vendors/{vid}` → `status` field

### Step 8: Compare Rates

**Via MCP tool:**
```
compare_rates(inquiry_id="RFQ-GO-2026-05-HPL")
```

**Via REST API:**
```
GET https://us-central1-ai-agents-go.cloudfunctions.net/procurement-mcp/api/inquiries/RFQ-GO-2026-05-HPL/compare
```

---

## Quick Launch Checklist

For each new RFQ round, do these in order:

| # | Step | Files to Create/Modify |
|---|------|------------------------|
| 1 | Research vendors | `data/{category}_suppliers.json` |
| 2 | Write template + seed script | `scripts/seed_{category}_rfq.py` |
| 3 | Run seed script | — |
| 4 | Create Gmail label + filter | `scripts/setup_gmail_{category}_filter.py` |
| 5 | Dry-run send | curl command |
| 6 | Live send | curl command |
| 7 | Create dashboard page | `business-automation/docs/{slug}.html` |
| 8 | Monitor + compare | Automated (Gemini + Slack + cron) |

**Total new files per RFQ:** 3 (vendor JSON, seed script, Gmail filter script) + 1 dashboard page

---

## Key Configuration Points

### Slack Channel Routing
Each inquiry can override the default Slack channel via `automation_config.slack_channel`. The `send_rfq` Cloud Function passes this to all `notify_*` calls.

### Trade Terms
The system tracks trade terms per vendor (DDP, DDU, D2D, EXW, FOB, CIF) and what's included in each price. This ensures apples-to-apples comparisons.

### Gemini Prompts
All 3 Gemini prompts auto-adapt to any product category:
- **Classify**: Detects intent regardless of product type
- **Extract**: Uses the inquiry's `extraction_schema` for structured data
- **Auto-reply**: Uses `auto_reply_context` from the template for accurate responses

### Escalation Keywords
These always trigger human escalation (Slack alert):
`exclusive`, `minimum commitment`, `penalty`, `contract`, `NDA`, `legal`, `binding`, `liability`, `indemnity`

### Naming Conventions
```
Inquiry ID:    RFQ-GO-{YYYY}-{MM}-{CATEGORY}
Template ID:   {category}-{subcategory}-rfq-v{version}
Vendor ID:     slugified company name (e.g., "shenzhen-infypower-co-ltd")
Vendor JSON:   data/{category}_suppliers.json
Seed script:   scripts/seed_{category}_rfq.py
Gmail filter:  scripts/setup_gmail_{category}_filter.py
Dashboard:     business-automation/docs/{slug}.html
```

---

## Vendor Status State Machine

```
draft --> sent --> response_received --> complete_response --> evaluating --> awarded
                                                                          --> not_selected
          --> reminder_1 (Day 5) --> reminder_2 (Day 7) --> escalated (Day 10) --> closed
          --> partial_response --> (auto-reply) --> awaiting_response --> response_received
          --> question_received --> (auto-reply) --> awaiting_response --> response_received
          --> declined --> closed
```

---

## File Map

| File | Purpose |
|---|---|
| `src/rfq_store.py` | Firestore CRUD (inquiries, vendors, messages, templates) |
| `src/gmail_sender.py` | Send emails (RFQ dispatch, auto-reply, reminders) |
| `src/gmail_reader.py` | Gmail watch + History API fetch |
| `src/gmail_auth.py` | Centralized Gmail auth (DWD, JSON-string or file path) |
| `src/parsers/rfq_gemini.py` | Gemini prompts (classify, extract, auto-reply) |
| `src/rfq_workflow.py` | State machine, decision engine, reminder logic |
| `src/slack_notifier.py` | Slack notifications (8 types) |
| `main.py` | Cloud Function entry points (per-inquiry Slack routing) |
| `mcp-server/server.py` | MCP tools + REST API |
| `data/*.json` | Vendor shortlists (one per product category) |
| `scripts/seed_*.py` | Firestore seed scripts (one per RFQ round) |
| `scripts/setup_gmail_*_filter.py` | Gmail label + filter scripts |
| `scripts/process_replies.py` | Batch process inbound replies |
| `scripts/send_followups.py` | Manual follow-up sender |
| `scripts/setup_gmail_watch.py` | Gmail watch setup/refresh |

---

## Quick Reference

| Action | Command |
|---|---|
| Seed Firestore | `python scripts/seed_{category}_rfq.py` |
| Create Gmail filter | `python scripts/setup_gmail_{category}_filter.py` |
| Dry-run RFQ | `POST /send-rfq {"inquiry_id": "...", "dry_run": true}` |
| Send RFQ | `POST /send-rfq {"inquiry_id": "..."}` |
| Check status | MCP: `get_inquiry_status("...")` |
| Compare rates | MCP: `compare_rates("...")` |
| Send reminder | MCP: `send_vendor_reminder("...", "vendor-id")` |
| Refresh Gmail watch | `python scripts/setup_gmail_watch.py` |
| Process replies | `python scripts/process_replies.py` |
| Manual reminder cron | `POST /rfq-reminder-cron {"inquiry_id": "..."}` |
