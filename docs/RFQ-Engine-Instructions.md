# RFQ Engine — How to Launch a New Procurement Inquiry

## Overview

This procurement automation platform handles the full RFQ lifecycle for **any product category** — not just freight. The same engine works for materials, furniture, equipment, services, or any vendor sourcing round.

## Prerequisites

Before launching a new inquiry, ensure:
1. Cloud Functions are deployed (`send-rfq`, `process-procurement-email`, `rfq-reminder-cron`)
2. Gmail watch is active (`python scripts/setup_gmail_watch.py`)
3. Cloud Scheduler is running (daily 09:00 Bangkok)
4. Firestore DB `procurement-automation` is accessible

## Step-by-Step: Launch a New RFQ

### Step 1: Prepare Your Vendor List

Create a JSON file in `data/` with your vendor candidates:

```json
{
  "metadata": {
    "title": "HPL Laminate Suppliers",
    "compiled_date": "2026-05-01",
    "total_companies": 15
  },
  "companies": [
    {
      "id": 1,
      "name_en": "Vendor Name",
      "name_cn": "中文名",
      "website": "https://...",
      "contact_email": "sales@vendor.com",
      "phone": "+86...",
      "services": ["HPL Laminates", "Custom Colors"],
      "notes": "Key supplier info"
    }
  ]
}
```

### Step 2: Create the RFQ Document

Create your RFQ document:
- **HTML version**: `docs/rfq-{category}.html` (for email body if needed)
- **PDF version**: `docs/RFQ-GO-{year}-{month}-{category}.pdf` (email attachment)

The PDF should contain:
- Company introduction
- What you're sourcing
- Required information from vendors
- Deadline
- Contact details

### Step 3: Create a Procurement Template

Templates define the email body, required fields, and extraction schema. Add to Firestore via a seed script or MCP tool.

```python
template = {
    "template_id": "hpl-supplier-rfq-v1",
    "name": "HPL Laminate Supplier RFQ",
    "category": "materials",
    "version": 1,
    "email_template": {
        "subject": "RFQ: {title} | GO Corporation Co., Ltd.",
        "body_cn": "Chinese email body with {vendor_name}, {deadline}, {title} placeholders...",
        "body_en": "English email body with {vendor_name}, {deadline}, {title} placeholders..."
    },
    "required_fields": [
        "price_per_sheet", "moq", "lead_time", "color_options"
    ],
    "extraction_schema": {
        "rates": {
            "price_per_sheet_4x8": {"type": "number", "unit": "THB/sheet"},
            "price_per_sqm": {"type": "number", "unit": "THB/sqm"},
            "moq": {"type": "number", "unit": "sheets"},
            "lead_time_days": {"type": "number", "unit": "days"}
        }
    },
    "auto_reply_context": "GO Corporation is a Thai design and procurement company. We need HPL laminates for hotel renovation projects. Typical order: 500-2000 sheets per project."
}
```

### Step 4: Create the Inquiry

Write a seed script (or use the MCP tool) to create the inquiry in Firestore:

```python
from src.rfq_store import create_inquiry, add_vendor_to_inquiry, set_template

# 1. Set template
set_template("hpl-supplier-rfq-v1", template_data)

# 2. Create inquiry
config = {
    "inquiry_id": "RFQ-GO-2026-05-HPL",
    "title": "HPL Laminate Supplier Sourcing",
    "category": "materials",
    "subcategory": "hpl-laminates",
    "template_id": "hpl-supplier-rfq-v1",
    "rfq_document": {
        "pdf_path": "docs/RFQ-GO-2026-05-HPL.pdf",
    },
    "send_config": {
        "from_email": "eukrit@goco.bz",
        "reply_to": "shipping@goco.bz",  # or category-specific
        "cc": ["shipping@goco.bz"],
        "subject_template": "RFQ: {title} | GO Corporation Co., Ltd.",
        "language": "bilingual",
        "attach_pdf": True,
    },
    "automation_config": {
        "auto_reply_enabled": True,
        "auto_reply_min_confidence": 0.8,
        "approval_required_for": ["pricing", "terms", "commitments"],
        "max_auto_replies_per_vendor": 3,
        "reminder_day_1": 5,
        "reminder_day_2": 7,
        "escalate_day": 10,
        "slack_channel": "C08VD9PRSCU",
    },
    "scoring_config": {
        "weights": {
            "price": 0.50,
            "quality": 0.20,
            "lead_time": 0.15,
            "moq": 0.15,
        },
        "baseline": {
            "source": "Current supplier rate card",
            "price_per_sheet": 850,
            "trade_term": "FOB",
        },
    },
    "response_deadline": "2026-05-15",
    "status": "draft",
    "created_by": "eukrit@goco.bz",
}
create_inquiry(config)

# 3. Add vendors
for company in vendor_list:
    add_vendor_to_inquiry("RFQ-GO-2026-05-HPL", {
        "vendor_id": slugify(company["name_en"]),
        "company_en": company["name_en"],
        "contact_email": company.get("contact_email"),
        # ... other fields
    })
```

### Step 5: Send the RFQ

**Option A: Via Cloud Function**
```bash
curl -X POST https://us-central1-ai-agents-go.cloudfunctions.net/send-rfq \
  -H "Content-Type: application/json" \
  -d '{"inquiry_id": "RFQ-GO-2026-05-HPL"}'
```

**Option B: Dry run first**
```bash
curl -X POST https://us-central1-ai-agents-go.cloudfunctions.net/send-rfq \
  -H "Content-Type: application/json" \
  -d '{"inquiry_id": "RFQ-GO-2026-05-HPL", "dry_run": true}'
```

**Option C: Send to specific vendors only**
```bash
curl -X POST https://us-central1-ai-agents-go.cloudfunctions.net/send-rfq \
  -H "Content-Type: application/json" \
  -d '{"inquiry_id": "RFQ-GO-2026-05-HPL", "vendor_ids": ["vendor-1", "vendor-2"]}'
```

### Step 6: Monitor

Once sent, the automation handles:

1. **Gmail Watch** detects inbound replies via Pub/Sub
2. **Gemini classifies** each reply (rate_quote, question, decline, etc.)
3. **Gemini extracts** structured data (rates, capabilities, trade terms)
4. **Auto-reply engine** answers vendor questions (confidence > 0.8 = auto-send, 0.6-0.8 = Slack approval, < 0.6 = escalate)
5. **Slack notifications** to `#shipment-notifications` with `[Procurement]` prefix
6. **Reminder cron** sends follow-ups on Day 5, Day 7, escalates Day 10

### Step 7: Compare Rates

**Via MCP tool:**
```
compare_rates(inquiry_id="RFQ-GO-2026-05-HPL")
```

**Via REST API:**
```
GET https://us-central1-ai-agents-go.cloudfunctions.net/procurement-mcp/api/inquiries/RFQ-GO-2026-05-HPL/compare
```

**Via Dashboard:**
Update `docs/index.html` with the new inquiry data.

---

## Key Configuration Points

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

### Naming Convention
```
Inquiry ID:  RFQ-GO-{YYYY}-{MM}-{CATEGORY}
Template ID: {category}-{subcategory}-rfq-v{version}
Vendor ID:   slugified company name (e.g., "canton-cargo")
```

---

## File Map

| File | Purpose |
|---|---|
| `src/rfq_store.py` | Firestore CRUD (inquiries, vendors, messages, templates) |
| `src/gmail_sender.py` | Send emails (RFQ dispatch, auto-reply, reminders) |
| `src/gmail_reader.py` | Gmail watch + History API fetch |
| `src/gmail_auth.py` | Centralized Gmail auth (domain-wide delegation) |
| `src/parsers/rfq_gemini.py` | Gemini prompts (classify, extract, auto-reply) |
| `src/rfq_workflow.py` | State machine, decision engine, reminder logic |
| `src/slack_notifier.py` | Slack notifications (8 types) |
| `main.py` | Cloud Function entry points |
| `mcp-server/server.py` | MCP tools + REST API |
| `scripts/seed_rfq_agents.py` | Example seed script (freight forwarders) |
| `scripts/process_replies.py` | Batch process inbound replies |
| `scripts/send_followups.py` | Manual follow-up sender |
| `scripts/setup_gmail_watch.py` | Gmail watch setup/refresh |

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

## Quick Reference

| Action | Command |
|---|---|
| Send RFQ | `POST /send-rfq {"inquiry_id": "..."}` |
| Check status | MCP: `get_inquiry_status("...")` |
| Compare rates | MCP: `compare_rates("...")` |
| Send reminder | MCP: `send_vendor_reminder("...", "vendor-id")` |
| Refresh Gmail watch | `python scripts/setup_gmail_watch.py` |
| Process replies manually | `python scripts/process_replies.py` |
| Run reminder cron manually | `POST /rfq-reminder-cron {"inquiry_id": "..."}` |
