# Procurement Automation — Claude Code Instructions

## Project Overview
AI-powered procurement automation for GO Corporation. Manages RFQ workflows, vendor sourcing, rate comparison, and automated follow-ups across any procurement category. Core engine: Gemini 2.5 Flash + Gmail + Firestore.

## Key Rules

### Code Control
- **Primary branch:** `main` — auto-deploys via Cloud Build on push
- **Always commit with Co-Authored-By:** `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`
- **Version tags:** Use semantic versioning (vX.Y.Z), update CHANGELOG.md
- **Run tests before push:** `pytest tests/`
- **Never force-push to main**
- **GitHub repo:** eukrit/procurement-automation

### CI/CD
- Cloud Build trigger `procurement-automation-deploy` fires on push to `main`
- Config: `cloudbuild.yaml`
- Monitor: https://console.cloud.google.com/cloud-build/builds?project=ai-agents-go

### Credentials
- All API credentials in Google Secret Manager (project: ai-agents-go)
- Service account key: `ai-agents-go-4c81b70995db.json` (local only, gitignored)
- Do NOT store credentials in code or commits

### GCP Details
- **Project:** ai-agents-go
- **Region:** us-central1
- **Service Account:** claude@ai-agents-go.iam.gserviceaccount.com
- **Compute SA:** 538978391890-compute@developer.gserviceaccount.com

### Firestore Database
- **Database:** `procurement-automation` (named database, us-central1) — NOT `(default)`
- **Env var:** `FIRESTORE_DATABASE=procurement-automation`
- **Collections:**
  - `rfq_campaigns` — RFQ campaigns (each campaign = one sourcing round)
  - `rfq_campaigns/{id}/vendors/{vendor_id}` — Vendor responses per campaign
  - `rfq_campaigns/{id}/vendors/{vendor_id}/messages/{msg_id}` — Email thread per vendor
  - `vendor_directory` — Master vendor directory (cross-campaign)
  - `procurement_templates` — Reusable RFQ templates
  - `workflow_config` — Automation rules, escalation thresholds, reminder schedules

### Gmail Integration
- **Send from:** eukrit@goco.bz
- **Reply-To:** shipping@goco.bz (or category-specific address)
- **CC:** shipping@goco.bz (for automation monitoring)
- **Scopes required:** `gmail.send` + `gmail.readonly`
- **Impersonation:** eukrit@goco.bz via domain-wide delegation

### Slack
- **Channel:** #shipment-notifications (C08VD9PRSCU)
- Bot must be invited to any new channels

### Gemini
- **Model:** gemini-2.5-flash (configurable via GEMINI_MODEL env var)
- **Temperature:** 0.0 (deterministic classification/extraction)
- **Response format:** JSON (response_mime_type="application/json")

### Key Files
- `main.py` — Cloud Function entry points
- `src/rfq_store.py` — Firestore CRUD for RFQ campaigns
- `src/gmail_sender.py` — Gmail send client
- `src/parsers/rfq_gemini.py` — Gemini prompts for RFQ classification, extraction, auto-reply
- `src/rfq_workflow.py` — State machine, auto-reply orchestration, escalation
- `mcp-server/server.py` — MCP + REST API
- `scripts/seed_rfq_agents.py` — Seed vendor data
- `data/china_thailand_freight_forwarders.json` — Freight forwarder candidates
- `docs/BuildPlans/RFQ-Automation-BuildPlan.md` — Full build plan

### gcloud CLI on Windows
```python
gcloud = r'C:\Users\eukri\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd'
```

### Per-Release Documentation Updates
1. `CHANGELOG.md` — Add new version section
2. `docs/index.html` — Update dashboard
3. Tag with `git tag -a vX.Y.Z` and push with `--tags`

### Testing
- Run: `pytest tests/`
- Mock external services (Firestore, Gemini, Gmail, Slack)
