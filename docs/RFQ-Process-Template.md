# RFQ Process — Instruction Template

> **Purpose:** Step-by-step template for Claude (or any operator) to run a new RFQ project end-to-end, from vendor sourcing to live tracking on the Master RFQ Dashboard. Each new RFQ follows this exact sequence.
>
> **Hard stops** marked 🛑 **REQUIRE HUMAN INPUT** — Claude must pause and ask the user, never guess.

---

## 0. Prerequisites (check once per session)
- `gcloud config` → project=`ai-agents-go`, account=`claude@ai-agents-go.iam.gserviceaccount.com`
- `FIRESTORE_DATABASE=procurement-automation`
- `.claude/PROGRESS.md` and `PROJECT_INDEX.md` read
- Dashboard live: <https://rfq-dashboard-538978391890.asia-southeast1.run.app>

---

## 1. Define the RFQ

Gather from the user (or infer from the request) and confirm back before any code:

| Field | Example | Notes |
| --- | --- | --- |
| **Inquiry ID** | `RFQ-GO-YYYY-MM-<CATEGORY>` | Follow existing pattern. e.g. `RFQ-GO-2026-04-SOLAR-SLEWING` |
| **Title** | "SDE9 Slewing Drive — Dual Axis Solar Tracker" | Human-readable, one line |
| **Category** | `freight` / `commodity` / `electronics` / `solar` / `display` / new | Reuse if possible |
| **Subcategory** | free text | e.g. `china-thailand`, `sde9-slewing` |
| **Quantity & spec** | e.g. 7 kW OCPP 2.0.1 wallbox, 12 pcs | Include units |
| **Benchmark** | Incumbent vendor + price | Used for rate-anomaly scoring |
| **Deadline** | `YYYY-MM-DD` | Response deadline for vendors |
| **Languages** | `bilingual` / `en` / `zh` / `th` | Template rendering |
| **Reply-To / CC** | defaults: `shipping@goco.bz` / `shipping@goco.bz` | Override only if requested |

Write these into the first lines of the seeding script and the CHANGELOG entry.

---

## 2. Source vendors → `data/<category>_<slug>_suppliers.json`

Research 6–12 competing vendors. For each, capture:

```json
{
  "vendor_id": "luoyang-hengguan",
  "company_en": "Luoyang Hengguan Heavy Machinery Co., Ltd.",
  "company_cn": "洛阳恒冠重型机械有限公司",
  "website": "https://...",
  "contact_email": "sales@...",
  "contact_email_alt": "info@...",
  "contact_phone": "+86 ...",
  "contact_whatsapp": "+86 ...",
  "contact_wechat": "wechat_id",
  "languages": ["zh", "en"],
  "preferred_channel": "email",
  "capabilities": ["..."],
  "source": "Alibaba / Made-in-China / referral",
  "source_notes": "..."
}
```

🛑 **Exclude the incumbent/benchmark vendor from the outreach list** — keep them as `benchmark` metadata on the inquiry.

---

## 3. 🛑 HUMAN INPUT — Slack routing channel

Before seeding Firestore, **ask the user**:

> _"Which Slack channel should inbound vendor replies + escalations for **`<INQUIRY_ID>`** route to? Default is `#shipment-notifications` (C08VD9PRSCU). Common alternates: `#areda-mike`, `#procurement-alerts`. Please confirm channel name **and** channel ID."_

Record both in the seeding script as `slack_channel` on `automation_config`. If the channel is new, remind the user to invite the bot: `/invite @Procurement Bot`.

---

## 4. 🛑 HUMAN INPUT — Gmail filter & label

Before sending, **ask the user**:

> _"For inbound replies on **`<INQUIRY_ID>`**, I'll create a Gmail label. Confirm:_
> _1. **Label name** (default: `Suppliers/<CategoryTitleCase>`, e.g. `Suppliers/Solar`, `Suppliers/Freight`) — reuse an existing label if one fits._
> _2. **Filter addresses** — should the filter cover all primary + alt vendor emails from the suppliers JSON? (default: yes, all of them)._
> _3. Should the filter **skip inbox** / **mark important** / **auto-archive**? (default: label only, keep in inbox)."_

Then run `scripts/setup_gmail_<category>_filter.py` (copy from `scripts/setup_gmail_solar_filter.py` as the reference). Log the created `Label_<id>` in the seeding script output and in `CHANGELOG.md`.

If the user says "reuse `Suppliers/<X>`", verify it exists first with `gmail.users().labels().list()` and append new filter addresses to the existing filter rather than creating a duplicate.

---

## 5. Seed Firestore

Create `scripts/seed_<category>_<slug>_rfq.py`. Pattern (see `scripts/seed_solar_slewing_rfq.py`):

1. Create/upsert `procurement_templates/<template_id>` (bilingual subject + body, merge fields).
2. Create `rfq_inquiries/<INQUIRY_ID>` with:
   - `status="draft"`, `category`, `subcategory`, `title`, `template_id`
   - `response_deadline`, `created_by="eukrit@goco.bz"`
   - `send_config`: `{language, inline_html, attach_pdf, reply_to, cc}`
   - `automation_config`: `{max_auto_replies_per_vendor, reminder_day_1, escalate_day, slack_channel, slack_channel_id, auto_reply_enabled}`
   - `scoring_config`: `{baseline: {...}, notes}`
   - `rfq_document`: `{html_url, pdf_path, drive_url}`
3. Seed each vendor under `rfq_inquiries/<INQUIRY_ID>/vendors/<vendor_id>`.

Verify counts: `db.collection('rfq_inquiries').document(INQUIRY_ID).collection('vendors').count()` == suppliers JSON length.

---

## 6. Draft the RFQ document
- HTML: `docs/<category>-<slug>-rfq.html` (renders as email body + downloadable page)
- PDF: `docs/RFQ-GO-YYYY-MM-<CATEGORY>-<Slug>.pdf` (attached to email)
- Update `docs/index.html` directory with a link to the new page + badge

---

## 7. Send RFQ
Call the `send-rfq` Cloud Function (HTTP trigger) or run locally:

```bash
curl -X POST https://send-rfq-<...>-uc.a.run.app \
  -H 'Content-Type: application/json' \
  -d '{"inquiry_id":"<INQUIRY_ID>","dry_run":true}'
```

**Dry-run first** → review per-vendor rendered email → only then send for real. Expect every vendor to transition `draft → sent` with a Gmail `thread_id` stored.

---

## 8. Verify on Master RFQ Dashboard
Hit <https://rfq-dashboard-538978391890.asia-southeast1.run.app>, confirm:
- New card appears with correct title, status, vendor count, deadline.
- Click through to `/rfq/<INQUIRY_ID>` — every vendor shown with status `sent`.

If card is missing, check `db().collection('rfq_inquiries').document(INQUIRY_ID).get().exists`.

---

## 9. Log & ship
1. Append CHANGELOG entry (`[vX.Y.Z] — YYYY-MM-DD`, summary of spec + benchmark + vendor count + Slack channel + Gmail label).
2. Update `build-summary.html` "Latest build" block + recent versions table.
3. Update `.claude/PROGRESS.md` (Last Touched, Recent Sessions).
4. Commit on a feature branch → PR → merge to `main` (branch protection requires PR).

---

## 10. Follow-up cadence (automated)
- **Day 5:** reminder_1 auto-sent in-thread (reuses Gmail `thread_id`)
- **Day 7:** reminder_2
- **Day 10:** escalation → Slack channel from step 3 pings operator
- **Deadline − 1:** final reminder
- **Deadline day:** `status → closed`; operator scores vendors in dashboard.

Manual intervention templates (Thai call-me, Notion mirror, etc.) live under `scripts/send_<category>_call_followup.py` — copy and adapt only when needed.

---

## Checklist (paste into the PR description)

```
- [ ] Inquiry ID + title + category + deadline confirmed
- [ ] Vendor JSON created (benchmark excluded)
- [ ] 🛑 Slack channel confirmed by user: #__________ (ID: __________)
- [ ] 🛑 Gmail label confirmed by user: Suppliers/__________ (reuse? yes/no)
- [ ] Firestore seeded; vendor count matches JSON
- [ ] HTML + PDF drafted; docs/index.html updated
- [ ] Dry-run reviewed → RFQ sent
- [ ] Dashboard card live (/rfq/<ID> loads)
- [ ] CHANGELOG + build-summary.html + PROGRESS.md updated
- [ ] PR opened and merged
```
