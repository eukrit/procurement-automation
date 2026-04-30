# Build Plan: Procurement Automation Platform
## RFQ Workflow Engine — Phase 1: China-Bangkok Freight Agent Sourcing

**Repo:** eukrit/procurement-automation (branch: main)
**Firestore DB:** procurement-automation (us-central1)
**GCP Project:** ai-agents-go
**Version:** v1.0.0
**Date:** 2026-04-06

---

## Session Prompt

Copy this to start a new Claude Code session:

```
I'm building a procurement automation platform — an RFQ workflow engine
powered by Gemini that sends inquiries, monitors Gmail responses, auto-replies
to vendor questions, and tracks everything in Firestore.

Read the full build plan: docs/BuildPlans/RFQ-Automation-BuildPlan.md
Read the project CLAUDE.md for rules and credentials.

Context:
- NEW repo: eukrit/procurement-automation (branch: main)
- NEW Firestore DB: procurement-automation (us-central1, already created)
- GCP project: ai-agents-go, service account: claude@ai-agents-go.iam.gserviceaccount.com
- 20 freight forwarder candidates: data/china_thailand_freight_forwarders.json
- RFQ document: docs/reports/rfq-china-bangkok.html + docs/RFQ-GO-2026-04-FREIGHT-China-Bangkok.pdf
- Freight rate baseline: scripts/freight_calculator_china_thai.py
- Gemini model: gemini-2.5-flash
- Gmail: send from eukrit@goco.bz, Reply-To shipping@goco.bz, CC shipping@goco.bz
- Slack: #shipment-notifications (C08VD9PRSCU)
- WeChat/WhatsApp API = Phase 6 (defer)
- Architecture must be generic for ANY procurement category, not just freight

Execute phase by phase. Ask me before proceeding to each new phase.
Start with Phase 1: Firestore schema + seed vendors.
```

---

## Decisions

| Decision | Choice |
|---|---|
| Send-from email | `eukrit@goco.bz` with `Reply-To: shipping@goco.bz` and `CC: shipping@goco.bz` |
| Auto-reply approval | Hybrid: auto-send factual answers (conf > 0.8), Slack approval for pricing/terms |
| RFQ format | HTML email body (bilingual) + PDF attachment |
| Outreach language | Bilingual: Chinese body + English PDF |
| Automation level | Full automation using Gemini for all classification, extraction, and reply drafting |
| Slack channel | `#shipment-notifications` (C08VD9PRSCU) |
| WeChat/WhatsApp | Phase 6 (deferred) — Slack reminders for now |
| Repo | NEW: `eukrit/procurement-automation` |
| Firestore DB | NEW: `procurement-automation` |

---

## Architecture: Generic Procurement Platform

The platform is designed for **any** procurement category. The first campaign is freight agent sourcing, but the same engine handles future use cases.

### Future Campaign Types (same workflow engine)
| Campaign Type | Example | Vendors |
|---|---|---|
| **Freight agent sourcing** | China-Bangkok logistics RFQ (current) | Freight forwarders |
| **Material procurement** | HPL laminates, tiles, flooring for a hotel project | Material suppliers |
| **Furniture sourcing** | Custom furniture for Marriott fit-out | Furniture factories |
| **Service provider RFQ** | Installation contractors, design consultants | Service providers |
| **Equipment pricing** | Playground equipment for new resort | Equipment manufacturers |

All use the same: campaign → vendors → messages → Gemini classify/extract/reply → compare → award.

```
┌──────────────────────────────────────────────────────────────────────┐
│                  PROCUREMENT AUTOMATION PLATFORM                     │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────────┐    ┌─────────────────┐    ┌────────────────┐  │
│  │ vendor_directory  │    │ procurement_    │    │ workflow_      │  │
│  │ (master registry) │    │ templates       │    │ config         │  │
│  │                   │    │ (reusable RFQs) │    │ (rules/cron)   │  │
│  └────────┬─────────┘    └────────┬────────┘    └───────┬────────┘  │
│           │                       │                      │           │
│           ▼                       ▼                      ▼           │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                      rfq_campaigns/{id}                        │  │
│  │  status: draft → sending → active → evaluating → awarded       │  │
│  │  category: "freight" | "materials" | "furniture" | "services"  │  │
│  │  template_id: points to procurement_templates                  │  │
│  │                                                                │  │
│  │  ┌─────────────────────────────────────────────────────────┐   │  │
│  │  │              vendors/{vendor_id}                         │   │  │
│  │  │  status: draft → sent → responded → complete → awarded  │   │  │
│  │  │  rates: {} (category-specific extracted data)            │   │  │
│  │  │  score: {price, quality, capability, overall}            │   │  │
│  │  │                                                         │   │  │
│  │  │  ┌──────────────────────────────────────────────────┐   │   │  │
│  │  │  │           messages/{msg_id}                       │   │   │  │
│  │  │  │  direction: outbound | inbound                    │   │   │  │
│  │  │  │  gemini_analysis: {intent, extracted, confidence} │   │   │  │
│  │  │  └──────────────────────────────────────────────────┘   │   │  │
│  │  └─────────────────────────────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌──────────┐  ┌─────────┐  │
│  │ Gmail   │  │ Gemini  │  │ Slack   │  │ Drive    │  │ MCP/API │  │
│  │ Send +  │  │ 2.5     │  │ Notify  │  │ Attach   │  │ Query   │  │
│  │ Monitor │  │ Flash   │  │ Approve │  │ Storage  │  │ Compare │  │
│  └─────────┘  └─────────┘  └─────────┘  └──────────┘  └─────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Firestore Schema (Generic)

### Collection: `rfq_campaigns/{campaign_id}`

Each campaign is one sourcing round for any procurement category.

```json
{
  "campaign_id": "RFQ-GO-2026-04-FREIGHT",
  "title": "China to Bangkok Freight Forwarding",
  "category": "freight",
  "subcategory": "china-thailand",
  "template_id": "freight-agent-rfq-v1",

  "rfq_document": {
    "html_url": "https://eukrit.github.io/shipping-automation/rfq-china-bangkok.html",
    "pdf_path": "docs/RFQ-GO-2026-04-FREIGHT-China-Bangkok.pdf",
    "drive_url": null
  },

  "send_config": {
    "from_email": "eukrit@goco.bz",
    "reply_to": "shipping@goco.bz",
    "cc": ["shipping@goco.bz"],
    "subject_template": "RFQ: {title} | GO Corporation Co., Ltd.",
    "language": "bilingual",
    "attach_pdf": true,
    "inline_html": true
  },

  "automation_config": {
    "auto_reply_enabled": true,
    "auto_reply_min_confidence": 0.8,
    "approval_required_for": ["pricing", "terms", "commitments", "legal"],
    "max_auto_replies_per_vendor": 3,
    "reminder_day_1": 5,
    "reminder_day_2": 7,
    "escalate_day": 10,
    "slack_channel": "C08VD9PRSCU"
  },

  "scoring_config": {
    "weights": {
      "price": 0.40,
      "transit": 0.20,
      "capability": 0.20,
      "communication": 0.10,
      "payment_terms": 0.10
    },
    "baseline": {
      "source": "Gift Somlak rate card 2025",
      "sea_per_cbm": 4600,
      "sea_per_kg": 35,
      "land_per_cbm": 7200,
      "land_per_kg": 48
    }
  },

  "response_deadline": "2026-04-19",
  "status": "draft",
  "vendor_count": 20,
  "responded_count": 0,
  "awarded_vendor_id": null,

  "created_at": "timestamp",
  "last_updated": "timestamp",
  "created_by": "eukrit@goco.bz"
}
```

### Subcollection: `rfq_campaigns/{id}/vendors/{vendor_id}`

One document per vendor being solicited. Schema is generic — the `rates` field is flexible per category.

```json
{
  "vendor_id": "djcargo",
  "company_en": "DJCargo (DJ International Freight)",
  "company_cn": "广州递接国际货运代理有限公司",
  "website": "https://www.djcargo.cn",
  "contact_email": "info@djcargo.cn",
  "contact_phone": "020-86210536",
  "contact_wechat": "+86 15800246878",
  "contact_whatsapp": "+86 15800246878",
  "preferred_channel": "email",
  "languages": ["English", "Chinese"],
  "source": "web_research",
  "source_notes": "Canton Fair logistics, Guangzhou warehouse",
  "master_vendor_ref": "vendor_directory/djcargo",

  "status": "draft",
  "status_history": [
    {"status": "draft", "at": "timestamp", "by": "system", "note": ""}
  ],

  "email_tracking": {
    "thread_id": null,
    "message_ids": [],
    "outbound_count": 0,
    "inbound_count": 0,
    "auto_reply_count": 0,
    "last_outbound_at": null,
    "last_inbound_at": null
  },

  "rates": {},
  "benchmark": {},
  "capabilities": {},
  "attachments": [],

  "score": {
    "price_score": null,
    "transit_score": null,
    "capability_score": null,
    "communication_score": null,
    "overall": null
  },

  "escalation": {
    "escalated": false,
    "reason": null,
    "requires_human": false,
    "human_reason": null
  },

  "reminders": {
    "count": 0,
    "next_at": null,
    "wechat_reminder_sent": false,
    "whatsapp_reminder_sent": false
  },

  "created_at": "timestamp",
  "last_updated": "timestamp"
}
```

### Subcollection: `rfq_campaigns/{id}/vendors/{vendor_id}/messages/{msg_id}`

```json
{
  "message_id": "gmail_message_id",
  "direction": "outbound|inbound",
  "type": "rfq_initial|response|auto_reply|follow_up|reminder|escalation",
  "subject": "string",
  "sender": "string",
  "recipients": ["string"],
  "body_preview": "first 5000 chars",
  "gmail_link": "string",
  "thread_id": "string",
  "attachments": [
    {"filename": "", "mime_type": "", "gmail_id": "", "drive_url": ""}
  ],
  "gemini_analysis": {
    "intent": "rate_quote|question|decline|partial_response|counter_offer|out_of_office|unrelated",
    "confidence": 0.0,
    "summary": "",
    "extracted_data": {},
    "questions_from_vendor": [],
    "missing_fields": [],
    "auto_reply_draft": null,
    "auto_reply_confidence": null,
    "should_escalate": false,
    "escalation_reason": null,
    "language": "zh|en|mixed"
  },
  "timestamp": "timestamp"
}
```

### Collection: `vendor_directory/{vendor_id}`

Master vendor registry shared across all campaigns.

```json
{
  "vendor_id": "djcargo",
  "company_en": "DJCargo (DJ International Freight)",
  "company_cn": "广州递接国际货运代理有限公司",
  "website": "https://www.djcargo.cn",
  "contacts": [
    {
      "name": "",
      "email": "info@djcargo.cn",
      "phone": "020-86210536",
      "wechat": "+86 15800246878",
      "whatsapp": "+86 15800246878",
      "role": "sales"
    }
  ],
  "categories": ["freight"],
  "subcategories": ["china-thailand", "sea-lcl", "land-transport"],
  "services": ["Sea LCL/FCL", "Land transport", "Warehouse Guangzhou"],
  "regions_china": ["Guangzhou", "Shenzhen", "Foshan"],
  "warehouse_locations": ["Guangzhou Baiyun"],
  "certifications": [],
  "languages": ["English", "Chinese"],
  "api_available": false,
  "tracking_portal": true,

  "campaign_history": [
    {"campaign_id": "RFQ-GO-2026-04-FREIGHT", "status": "responded", "score": 72}
  ],

  "overall_rating": null,
  "notes": "",
  "tags": ["guangdong", "lcl-specialist"],
  "created_at": "timestamp",
  "last_updated": "timestamp"
}
```

### Collection: `procurement_templates/{template_id}`

Reusable RFQ templates for future campaigns.

```json
{
  "template_id": "freight-agent-rfq-v1",
  "name": "China-Thailand Freight Agent RFQ",
  "category": "freight",
  "version": 1,

  "email_template": {
    "subject": "RFQ: {title} | GO Corporation Co., Ltd.",
    "body_cn": "Chinese cover letter template with {placeholders}...",
    "body_en": "English summary template with {placeholders}..."
  },

  "required_fields": [
    "d2d_sea_lcl_per_cbm", "d2d_land_per_cbm", "transit_sea_days",
    "transit_land_days", "billing_rule", "last_mile_standard",
    "warehouse_china", "customs_clearance", "payment_terms"
  ],

  "extraction_schema": {
    "rates": {
      "d2d_sea_lcl_per_cbm": {"type": "number", "unit": "THB/CBM"},
      "d2d_sea_lcl_per_kg": {"type": "number", "unit": "THB/KG"},
      "d2d_land_per_cbm": {"type": "number", "unit": "THB/CBM"},
      "d2d_land_per_kg": {"type": "number", "unit": "THB/KG"},
      "exw_sea_lcl_per_cbm": {"type": "number", "unit": "THB/CBM"},
      "exw_sea_lcl_per_kg": {"type": "number", "unit": "THB/KG"},
      "exw_land_per_cbm": {"type": "number", "unit": "THB/CBM"},
      "exw_land_per_kg": {"type": "number", "unit": "THB/KG"},
      "d2d_fcl_20": {"type": "number", "unit": "THB/container"},
      "d2d_fcl_40": {"type": "number", "unit": "THB/container"},
      "d2d_fcl_40hc": {"type": "number", "unit": "THB/container"},
      "exw_fcl_20": {"type": "number", "unit": "THB/container"},
      "exw_fcl_40": {"type": "number", "unit": "THB/container"},
      "exw_fcl_40hc": {"type": "number", "unit": "THB/container"},
      "transit_sea_days": {"type": "number", "unit": "days"},
      "transit_land_days": {"type": "number", "unit": "days"},
      "min_charge": {"type": "number", "unit": "THB"},
      "last_mile_standard": {"type": "number", "unit": "THB"},
      "last_mile_oversized": {"type": "number", "unit": "THB"},
      "oversized_surcharge": {"type": "number", "unit": "THB"},
      "billing_rule": {"type": "string"},
      "insurance_rate": {"type": "string"},
      "payment_terms": {"type": "string"},
      "currency": {"type": "string"},
      "pickup_surcharges": {"type": "object"}
    },
    "benchmark": {
      "sea_total_d2d": {"type": "number", "unit": "THB"},
      "sea_total_exw": {"type": "number", "unit": "THB"},
      "land_total_d2d": {"type": "number", "unit": "THB"},
      "land_total_exw": {"type": "number", "unit": "THB"}
    },
    "capabilities": {
      "warehouse_china": {"type": "boolean"},
      "warehouse_bangkok": {"type": "boolean"},
      "customs_clearance": {"type": "boolean"},
      "cargo_insurance": {"type": "boolean"},
      "api_tracking": {"type": "boolean"},
      "wechat_support": {"type": "boolean"},
      "consolidation": {"type": "boolean"},
      "free_storage_days": {"type": "number"}
    }
  },

  "auto_reply_context": "GO Corporation imports furniture, lighting, playground equipment, and construction materials from 74 vendors across China (primarily Guangdong). Annual volume: 200-400 CBM across 30-50 POs. Trade term: EXW from factory. HS codes: 9403 (furniture 20%), 7610 (aluminum 10%), 9405 (lighting 20%), 7308 (steel 10%).",

  "created_at": "timestamp",
  "last_updated": "timestamp"
}
```

### Collection: `workflow_config/{config_id}`

Global automation rules.

```json
{
  "config_id": "default",
  "escalation_rules": {
    "low_confidence_threshold": 0.6,
    "max_auto_replies": 3,
    "escalate_keywords": ["exclusive", "minimum commitment", "penalty", "contract", "NDA", "legal"],
    "escalate_on_phone_request": true,
    "escalate_on_meeting_request": true,
    "price_anomaly_factor": 2.0
  },
  "reminder_schedule": {
    "day_1": 5,
    "day_2": 7,
    "escalate_day": 10,
    "close_after_deadline_grace_days": 3
  },
  "notification_channels": {
    "slack_channel": "C08VD9PRSCU",
    "slack_enabled": true,
    "email_digest_to": "eukrit@goco.bz"
  },
  "gemini_config": {
    "model": "gemini-2.5-flash",
    "temperature": 0.0,
    "classify_max_tokens": 1024,
    "extract_max_tokens": 4096,
    "reply_max_tokens": 2048,
    "auto_reply_min_confidence": 0.8
  }
}
```

---

## Vendor Status State Machine

```
draft → sent → response_received → complete_response → evaluating → awarded
            ↘                   ↗                                  → not_selected
         reminder_1 (Day 5) → reminder_2 (Day 7) → escalated (Day 10) → closed
            ↘
         partial_response → (auto-reply) → awaiting_response → response_received
            ↘
         question_received → (auto-reply) → awaiting_response → response_received
            ↘
         declined → closed
```

---

## Codebase Patterns (from shipping-automation, MUST FOLLOW)

### Firestore Client
```python
import os
from google.cloud import firestore

GCP_PROJECT = os.environ.get("GCP_PROJECT", "ai-agents-go")
FIRESTORE_DATABASE = os.environ.get("FIRESTORE_DATABASE", "procurement-automation")

def get_db():
    return firestore.Client(project=GCP_PROJECT, database=FIRESTORE_DATABASE)
```

### Gemini Client
```python
from google import genai
import json

GCP_PROJECT = os.environ.get("GCP_PROJECT", "ai-agents-go")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

client = genai.Client(project=GCP_PROJECT, location="us-central1")

response = client.models.generate_content(
    model=GEMINI_MODEL,
    contents=[prompt],
    config=genai.types.GenerateContentConfig(
        temperature=0.0,
        max_output_tokens=2048,
        response_mime_type="application/json",
        system_instruction="You are a procurement assistant..."
    ),
)
result = json.loads(response.text)
```

### Gmail Auth (domain-wide delegation)
```python
from google.oauth2 import service_account
from googleapiclient.discovery import build

GMAIL_SEND_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]
IMPERSONATE_USER = os.environ.get("IMPERSONATE_USER", "eukrit@goco.bz")

def get_gmail_service():
    credentials = service_account.Credentials.from_service_account_file(
        "ai-agents-go-0d28f3991b7b.json",  # local only
        scopes=GMAIL_SEND_SCOPES,
    )
    delegated = credentials.with_subject(IMPERSONATE_USER)
    return build("gmail", "v1", credentials=delegated)
```

### Slack Notifications
```python
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL", "C08VD9PRSCU")
# Uses Secret Manager: SLACK_BOT_TOKEN
# Pattern: _post_slack_message(channel, blocks, text)
```

### Cloud Functions Entry Points
```python
import functions_framework

@functions_framework.http
def send_rfq(request):
    """HTTP trigger to dispatch RFQ emails."""

@functions_framework.cloud_event
def process_procurement_email(cloud_event):
    """Pub/Sub trigger from Gmail watch."""

@functions_framework.http
def rfq_reminder_cron(request):
    """HTTP trigger from Cloud Scheduler (daily 09:00 Bangkok)."""
```

---

## Phase 1: Firestore Schema + Seed Vendors

### Files to Create
| File | Purpose |
|---|---|
| `src/rfq_store.py` | Firestore CRUD: campaigns, vendors, messages, vendor_directory |
| `scripts/seed_rfq_agents.py` | Load `data/china_thailand_freight_forwarders.json` → Firestore |

### Tasks
1. Create `rfq_store.py` with functions:
   - `create_campaign(config)` → campaign_id
   - `add_vendor_to_campaign(campaign_id, vendor_data)` → vendor_id
   - `update_vendor_status(campaign_id, vendor_id, status, note="")`
   - `get_campaign(campaign_id)` → dict
   - `get_campaign_vendors(campaign_id, status_filter=None)` → list
   - `get_vendor(campaign_id, vendor_id)` → dict
   - `match_sender_to_vendor(sender_email)` → {campaign_id, vendor_id} or None
   - `log_message(campaign_id, vendor_id, message_data)`
   - `update_vendor_rates(campaign_id, vendor_id, rates, benchmark, capabilities)`
   - `upsert_vendor_directory(vendor_data)` — master registry

2. Create `scripts/seed_rfq_agents.py`:
   - Read `data/china_thailand_freight_forwarders.json`
   - Create campaign `RFQ-GO-2026-04-FREIGHT` with config
   - Seed 20 vendors into campaign
   - Also seed into `vendor_directory` master registry
   - Seed `procurement_templates/freight-agent-rfq-v1`
   - Seed `workflow_config/default`

3. Update `CLAUDE.md` collections list

4. Run seed script and verify

---

## Phase 2: Gmail Sender + RFQ Dispatch

### Prerequisite (MANUAL)
Add `gmail.send` scope to domain-wide delegation in Google Workspace Admin Console:
- URL: https://admin.google.com → Security → API Controls → Domain-wide delegation
- Client: `claude@ai-agents-go.iam.gserviceaccount.com`
- Add: `https://www.googleapis.com/auth/gmail.send`

### Files to Create
| File | Purpose |
|---|---|
| `src/gmail_sender.py` | Gmail send client with domain-wide delegation |
| `main.py` | Cloud Function entry point `send_rfq` |

### Email Template (Bilingual)

**Subject:** `RFQ: China to Bangkok Freight Forwarding | GO Corporation Co., Ltd.`

**Reply-To:** `shipping@goco.bz`

**Body:**
```
您好，

GO Corporation Co., Ltd.（บริษัท จีโอ คอร์ปอเรชั่น จำกัด）是泰国一家专注于
酒店、商业及住宅室内装修项目的设计和采购公司。我们从中国74家供应商处采购家具、
灯具、游乐设备及建筑材料，年运输量约200-400立方米。

我们目前正在寻找新的中国至曼谷物流合作伙伴。随函附上我们的询价书（RFQ），
涵盖海运拼箱/整箱、陆运、门到门及EXW条款的报价要求。

请在2026年4月19日前回复此邮件提供报价。如有任何问题，欢迎通过以下方式联系：

---

Dear Sir/Madam,

GO Corporation Co., Ltd. is a Thai-based procurement and project delivery company.
We import furniture, lighting, playground equipment, and construction materials from
74 vendors across China (primarily Guangdong, Zhejiang, and central China).

Please find attached our Request for Quotation (RFQ) for China to Bangkok freight
forwarding services covering sea LCL/FCL, land transport, door-to-door and EXW terms.

Kindly submit your quotation by 19 April 2026 by replying to this email.

---

Eukrit Kraikosol | 尤克里
GO Corporation Co., Ltd.
Email: eukrit@goco.bz | Reply-To: shipping@goco.bz
WeChat: eukrit | Tel: +66 61 491 6393
11/2 P23 Tower, Unit 8A, Sukhumvit 23, Bangkok 10110, Thailand
```

**Attachment:** `RFQ-GO-2026-04-FREIGHT-China-Bangkok.pdf`

### Key Functions in `gmail_sender.py`
```python
def get_gmail_send_service(impersonate_user=None):
    """Build Gmail service with gmail.send + gmail.readonly scope."""

def send_email(to, subject, body_html, reply_to=None, cc=None,
               attachments=None, in_reply_to=None, thread_id=None):
    """Send email. Returns {'message_id': ..., 'thread_id': ...}."""

def send_rfq_to_vendor(campaign, vendor_doc):
    """Compose bilingual email + attach PDF. Returns send result."""

def send_auto_reply(vendor_doc, subject, body, thread_id):
    """Reply in existing thread."""

def send_reminder(vendor_doc, campaign, reminder_number):
    """Send follow-up reminder."""
```

### cloudbuild.yaml
```yaml
steps:
  # Service 1: Send RFQ (HTTP trigger)
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - functions
      - deploy
      - send-rfq
      - --gen2
      - --runtime=python312
      - --region=us-central1
      - --source=.
      - --entry-point=send_rfq
      - --trigger-http
      - --allow-unauthenticated
      - --memory=512Mi
      - --timeout=300s
      - --set-env-vars=GCP_PROJECT=ai-agents-go,FIRESTORE_DATABASE=procurement-automation

  # Service 2: Process inbound emails (Pub/Sub)
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - functions
      - deploy
      - process-procurement-email
      - --gen2
      - --runtime=python312
      - --region=us-central1
      - --source=.
      - --entry-point=process_procurement_email
      - --trigger-topic=gmail-procurement-watch
      - --memory=512Mi
      - --timeout=120s
      - --set-env-vars=GCP_PROJECT=ai-agents-go,FIRESTORE_DATABASE=procurement-automation,IMPERSONATE_USER=eukrit@goco.bz,SLACK_CHANNEL=C08VD9PRSCU,GEMINI_ENABLED=true

  # Service 3: Reminder cron (HTTP, invoked by Cloud Scheduler)
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - functions
      - deploy
      - rfq-reminder-cron
      - --gen2
      - --runtime=python312
      - --region=us-central1
      - --source=.
      - --entry-point=rfq_reminder_cron
      - --trigger-http
      - --allow-unauthenticated
      - --memory=256Mi
      - --timeout=120s
      - --set-env-vars=GCP_PROJECT=ai-agents-go,FIRESTORE_DATABASE=procurement-automation,SLACK_CHANNEL=C08VD9PRSCU

  # Service 4: MCP + REST API (Cloud Run)
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - run
      - deploy
      - procurement-mcp
      - --source=mcp-server
      - --region=us-central1
      - --memory=512Mi
      - --timeout=60
      - --port=8080
      - --allow-unauthenticated
      - --set-env-vars=GCP_PROJECT=ai-agents-go,FIRESTORE_DATABASE=procurement-automation
```

---

## Phase 3: Gmail Watch + Gemini Classification

### Gmail Watch Setup
Set up Gmail push notifications for `shipping@goco.bz` (where Reply-To points):
```python
# Pub/Sub topic: gmail-procurement-watch
# Watch query: in:inbox to:shipping@goco.bz
# Same pattern as shipping-automation's gmail_client.py setup_watch()
```

### Files to Create
| File | Purpose |
|---|---|
| `src/parsers/rfq_gemini.py` | 3 Gemini prompts: classify, extract, auto-reply |

### Gemini Prompt 1: `classify_vendor_response`
```python
def classify_vendor_response(sender, subject, body, campaign_context):
    """Returns: {is_rfq_response, intent, confidence, summary,
                 questions_from_vendor, has_rate_data, language}"""
```

### Gemini Prompt 2: `extract_vendor_rates`
```python
def extract_vendor_rates(body, attachment_text, extraction_schema):
    """Uses campaign's extraction_schema to parse structured rates.
    Returns: {rates, benchmark, capabilities, missing_fields, confidence}"""
```

### Routing in `process_procurement_email`
```python
def process_procurement_email(cloud_event):
    # 1. Get Gmail history (same as shipping-automation pattern)
    # 2. For each new message, extract sender email
    # 3. Match sender to active campaign vendor via rfq_store.match_sender_to_vendor()
    # 4. If match: classify with Gemini → route by intent
    # 5. If no match: log and skip
```

---

## Phase 4: Auto-Reply Engine + Reminder Cron

### Files to Create
| File | Purpose |
|---|---|
| `src/rfq_workflow.py` | State machine, auto-reply orchestration, escalation rules |

### Gemini Prompt 3: `generate_auto_reply`
```python
def generate_auto_reply(vendor_name, vendor_company, questions,
                        missing_fields, campaign_context, conversation_history):
    """Returns: {subject, body, confidence, should_escalate, escalation_reason}

    Context includes campaign's auto_reply_context from procurement_templates.
    Body language matches vendor's language (Chinese/English/bilingual).
    """
```

### Auto-Reply Decision Matrix
| Condition | Action |
|---|---|
| Factual question, confidence > 0.8 | Auto-send |
| Missing fields identified | Auto-send requesting missing info |
| Question, confidence 0.6-0.8 | Slack draft for approval |
| Confidence < 0.6 | Escalate to human |
| Auto-reply count > 3 | Escalate |
| Legal/contract/commitment language | Escalate immediately |
| Phone/meeting request | Slack alert with vendor contact |
| Primarily Chinese, low parse confidence | Slack remind to use WeChat |
| Rates > 2x or < 0.5x baseline | Flag for review |

### Reminder Cron
```python
def rfq_reminder_cron(request):
    """Daily 09:00 Bangkok (02:00 UTC).
    Day 5: Email follow-up
    Day 7: Second reminder, mention WeChat as alternative
    Day 10: Slack escalation — human should contact via WeChat/WhatsApp
    Post-deadline + 3 days grace: Close non-responsive vendors
    """
```

### Cloud Scheduler
```bash
gcloud scheduler jobs create http rfq-reminder-cron \
  --location=us-central1 \
  --schedule="0 2 * * *" \
  --uri="https://us-central1-ai-agents-go.cloudfunctions.net/rfq-reminder-cron" \
  --http-method=POST \
  --time-zone="Asia/Bangkok"
```

---

## Phase 5: MCP Tools + Rate Comparison + Digest

### MCP Tools (mcp-server/server.py)
```python
@server.tool()
def get_campaign_status(campaign_id: str) → dict
    """Overview: vendor count, response count, status breakdown."""

@server.tool()
def get_vendor_detail(campaign_id: str, vendor_id: str) → dict
    """Full vendor info including rates, messages, score."""

@server.tool()
def compare_rates(campaign_id: str) → dict
    """Side-by-side rate comparison table, scored vs baseline."""

@server.tool()
def send_reminder(campaign_id: str, vendor_id: str) → dict
    """Manually trigger follow-up reminder."""

@server.tool()
def approve_reply(campaign_id: str, vendor_id: str, msg_id: str) → dict
    """Approve pending auto-reply draft."""

@server.tool()
def list_campaigns(status: str = None) → list
    """List all campaigns, optionally filtered by status."""
```

### REST Endpoints
```
GET  /api/campaigns                           → List all
GET  /api/campaigns/{id}                      → Campaign overview
GET  /api/campaigns/{id}/vendors              → All vendors
GET  /api/campaigns/{id}/vendors/{vid}        → Vendor detail
GET  /api/campaigns/{id}/compare              → Rate comparison
POST /api/campaigns/{id}/send                 → Send RFQ
POST /api/campaigns/{id}/vendors/{vid}/remind → Send reminder
POST /api/campaigns/{id}/vendors/{vid}/approve-reply/{mid} → Approve
```

### Rate Comparison
Use `scripts/freight_calculator_china_thai.py` baseline:
- Gift Somlak sea: 4,600 THB/CBM, land: 7,200 THB/CBM
- Benchmark shipment: ED 70 door, 2.394 CBM, 120 kg → 164,512 THB landed

---

## Phase 6: WeChat / WhatsApp API (DEFERRED)

Current: Slack reminders with vendor WeChat/WhatsApp contact info.
Future: WeChat Official Account API or WhatsApp Business API.

---

## File Map

### New Files
| File | Phase |
|---|---|
| `CLAUDE.md` | 0 (done) |
| `src/rfq_store.py` | 1 |
| `scripts/seed_rfq_agents.py` | 1 |
| `src/gmail_sender.py` | 2 |
| `main.py` | 2 |
| `cloudbuild.yaml` | 2 |
| `src/parsers/rfq_gemini.py` | 3 |
| `src/rfq_workflow.py` | 4 |
| `mcp-server/server.py` | 5 |
| `tests/test_rfq_store.py` | 1 |
| `tests/test_rfq_gemini.py` | 3 |
| `tests/test_rfq_workflow.py` | 4 |
| `CHANGELOG.md` | 5 |
| `requirements.txt` | 1 |

### Environment Variables
```
GCP_PROJECT=ai-agents-go
FIRESTORE_DATABASE=procurement-automation
IMPERSONATE_USER=eukrit@goco.bz
SLACK_CHANNEL=C08VD9PRSCU
GEMINI_ENABLED=true
GEMINI_MODEL=gemini-2.5-flash
```

---

## Manual Steps Required

1. **Google Workspace Admin** (before Phase 2):
   Add `https://www.googleapis.com/auth/gmail.send` to domain-wide delegation
   for client `claude@ai-agents-go.iam.gserviceaccount.com`

2. **Cloud Build Trigger** (before first deploy):
   ```bash
   gcloud builds triggers create github \
     --repo-name=procurement-automation \
     --repo-owner=eukrit \
     --branch-pattern=^main$ \
     --build-config=cloudbuild.yaml \
     --name=procurement-automation-deploy \
     --region=us-central1
   ```

3. **Gmail Watch** (Phase 3):
   Set up Pub/Sub topic `gmail-procurement-watch` and Gmail watch on `shipping@goco.bz`
   (may share existing watch from shipping-automation — check if same inbox)

---

## Testing Strategy

- Mock all externals: Firestore, Gemini, Gmail, Slack
- Test state machine transitions exhaustively
- Test Gemini prompts with sample emails (English + Chinese + mixed)
- Test bilingual email rendering
- Test escalation rules with edge cases
- `pytest tests/` before every push

---

## Gift Somlak Baseline

```
Sea CBM: 4,600 THB/CBM | Sea KGS: 35 THB/KG
Land CBM: 7,200 THB/CBM | Land KGS: 48 THB/KG
Billing rule: max(CBM-based, KGS-based)
Last-mile standard: 1,500-2,500 THB | Oversized 6-wheel: 3,500 THB
Benchmark: ED 70 door, 2.394 CBM, 120 kg → 164,512 THB landed (no duty/VAT)
```
