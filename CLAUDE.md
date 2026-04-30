# Procurement Automation — Claude Code Instructions

> **Session start protocol (Rule 6):** read `.claude/PROGRESS.md` and `PROJECT_INDEX.md` before making changes. Check `COLLABORATORS.md` and `SECURITY.md` before granting access. Update `.claude/PROGRESS.md` before ending any turn that edited code.

> **Primary GCP project: `ai-agents-go`** (538978391890, region `asia-southeast1`). Do NOT use `ai-agents-eukrit` — that project is reserved for the `2026 Eukrit Expenses Claude/` folder only.

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
- Service account key: `ai-agents-go-0d28f3991b7b.json` (local only, gitignored)
- Do NOT store credentials in code or commits

### GCP Details
- **Project:** ai-agents-go
- **Region:** us-central1
- **Service Account:** claude@ai-agents-go.iam.gserviceaccount.com
- **Compute SA:** 538978391890-compute@developer.gserviceaccount.com

### Firestore Database
- **Database:** `procurement-automation` (named database, asia-southeast1) — NOT `(default)`
- **Env var:** `FIRESTORE_DATABASE=procurement-automation`
- **Collections:**
  - `rfq_inquiries` — RFQ inquiries (each inquiry = one sourcing round)
  - `rfq_inquiries/{id}/vendors/{vendor_id}` — Vendor responses per inquiry
  - `rfq_inquiries/{id}/vendors/{vendor_id}/messages/{msg_id}` — Email thread per vendor
  - `vendor_directory` — Master vendor directory (cross-inquiry)
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
- `src/rfq_store.py` — Firestore CRUD for RFQ inquiries
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

---

## Page Hosting (Rule 14)

> **Rule 14a — Exclusive hosting.** All generated non-website HTML for this project (dashboards, reports, summaries, forms, documents, hub, build-summary, architecture) is served exclusively at `https://gateway.goco.bz/procurement-automation/<path>`. Do not link, share, or reference raw `*.run.app`, `storage.googleapis.com`, `raw.githubusercontent.com`, or `eukrit.github.io` URLs anywhere a reader will see (BUILD_LOGs, hub configs, READMEs, chat).
>
> **Rule 14b — Project root = hub.** `https://gateway.goco.bz/procurement-automation/` (and `https://gateway.goco.bz/procurement-automation` with no slash) resolves to this project's `docs/hub.html` for every backend kind. The slug catchall in `go-access-gateway/services/access_gateway/routes/pages.py` normalizes the empty path. Keep `docs/hub.html` fresh per Rule 13f — `verify.sh` blocks any push that leaves it stale.
>
> **Canonical paths** (must always work, mirroring `gateway.goco.bz/directory`):
> - `https://gateway.goco.bz/procurement-automation/docs/hub.html` — Hub
> - `https://gateway.goco.bz/procurement-automation/docs/build-summary.html` — Build Summary
> - `https://gateway.goco.bz/procurement-automation/docs/architecture.html` — Architecture
> - `https://gateway.goco.bz/procurement-automation/BUILD_LOG.md` — Build Log

All HTML pages, dashboards, summaries, and forms in this project are served via the **`go-access-gateway`** at `https://gateway.goco.bz/procurement-automation/...` — NOT directly from this project's Cloud Run URL.

- **Public URL pattern:** `https://gateway.goco.bz/procurement-automation/<path>`
- **Backend Cloud Run service:** must be `--no-allow-unauthenticated`. The gateway SA `claude@ai-agents-go.iam.gserviceaccount.com` is granted `roles/run.invoker` on this service.
- **Default page visibility:** `admin` (only `eukrit@goco.bz`). Toggle public, or share with specific emails, via the [gateway admin UI](https://gateway.goco.bz/admin).
- **Hub link target:** `hub.config.json` `LIVE_URL_BASE` should be `https://gateway.goco.bz/procurement-automation`.
- **Migration status:** see Phase D of the rollout plan at `~/.claude/plans/go-through-all-projects-structured-cherny.md`. Until migrated, this project's Cloud Run is still public.

Hard rules: no `--allow-unauthenticated` on this project's Cloud Run after migration. No public GCS buckets for HTML. No bypass auth in the backend. Full text: Rule 14 in `Credentials Claude Code/Instructions/Claude Process Standards.md`.

## Claude Process Standards (MANDATORY)

Full reference: `Credentials Claude Code/Instructions/Claude Process Standards.md`

0. **`goco-project-template` is READ-ONLY** — never edit, commit, or push to the `goco-project-template` folder or `eukrit/goco-project-template` repo. It exists only to be copied when scaffolding new projects. If any project's `origin` points at `goco-project-template`, STOP and remove/fix the remote before doing anything else.
1. **Always maintain a todo list** — use `TodoWrite` for any task with >1 step or that edits files; mark items done immediately.
2. **Always update a build log** — append a dated, semver entry to `BUILD_LOG.md` (or existing `CHANGELOG.md`) for every build/version: version, date (YYYY-MM-DD), summary, files changed, outcome. The log lives in **this project's own folder** — never in `business-automation/`.
3. **Plan in batches; run them as one chained autonomous pass** — group todos into batches, surface the plan once, then execute every batch back-to-back in a single run. No turn-taking between todos or batches. Run long work with `run_in_background: true`; parallelize independent tool calls. Only stop for true blockers: destructive/unauthorized actions, missing credentials, genuine ambiguity, unrecoverable external errors, or explicit user confirmation request.
4. **Always update `docs/build-summary.html` at THIS project's root** for every build/version (template: `Credentials Claude Code/Instructions/build-summary.template.html`). Per-project — DO NOT write into `business-automation/`. Touch the workspace dashboard at `business-automation/docs/index.html` only for cross-project / architecture changes.
5. **Always commit and push — verify repo mapping first** — run `git remote -v` and confirm the remote repo name matches the local folder name (per the Code Sync Rules in the root `CLAUDE.md`). If mismatch (especially `goco-project-template`), STOP and ask the user. Never push to the wrong repo.
