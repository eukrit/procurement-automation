"""
rfq_gemini.py — Gemini prompts for RFQ classification, rate extraction,
and auto-reply generation.

Model: gemini-2.5-flash (configurable via GEMINI_MODEL env var)
Temperature: 0.0 (deterministic)
Response format: JSON
"""

from __future__ import annotations

import json
import logging
import os

import re

from google import genai

logger = logging.getLogger(__name__)


def _safe_json_parse(text: str) -> dict | None:
    """Try to parse JSON, with fallback cleanup for common Gemini issues."""
    # First try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences if present
    cleaned = re.sub(r"^```json\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try fixing trailing commas before } or ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    return None

# ── Config ────────────────────────────────────────────────────

GCP_PROJECT = os.environ.get("GCP_PROJECT", "ai-agents-go")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_LOCATION = os.environ.get("GEMINI_LOCATION", "us-central1")
GEMINI_ENABLED = os.environ.get("GEMINI_ENABLED", "true").lower() == "true"

_client = None

SA_KEY_FILE = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "..", "..", "ai-agents-go-4c81b70995db.json"),
)


def _get_client():
    global _client
    if _client is None:
        if os.path.exists(SA_KEY_FILE):
            _client = genai.Client(
                vertexai=True,
                project=GCP_PROJECT,
                location=GEMINI_LOCATION,
            )
        else:
            _client = genai.Client(
                vertexai=True,
                project=GCP_PROJECT,
                location=GEMINI_LOCATION,
            )
    return _client


# ── Prompt 1: Classify Vendor Response ────────────────────────


CLASSIFY_SYSTEM_PROMPT = """\
You are an expert procurement assistant for GO Corporation, a Thai company that \
imports furniture, lighting, playground equipment, and construction materials from \
China. You are analyzing inbound emails in response to an RFQ (Request for Quotation) \
sent to freight forwarding companies.

Your task is to classify the email and extract key information.

IMPORTANT: Respond ONLY with valid JSON. No markdown, no code fences."""

CLASSIFY_USER_TEMPLATE = """\
Analyze this email received in response to our RFQ for "{inquiry_title}".

Sender: {sender}
Subject: {subject}

Email body:
---
{body}
---

Classify this email and return JSON with these fields:
{{
  "is_rfq_response": true/false (is this a response to our RFQ, or unrelated?),
  "intent": one of ["rate_quote", "question", "decline", "partial_response", "counter_offer", "out_of_office", "auto_reply_bounce", "unrelated"],
  "confidence": 0.0-1.0 (how confident are you in this classification?),
  "summary": "1-2 sentence summary of the email content",
  "questions_from_vendor": ["list of questions the vendor is asking us, if any"],
  "has_rate_data": true/false (does the email contain any pricing/rate information?),
  "has_attachment": true/false (does the vendor reference an attachment with rates?),
  "missing_fields": ["list of rate fields we requested but vendor did not provide"],
  "language": "zh" or "en" or "mixed" (primary language of the email),
  "urgency": "normal" or "high" (high if vendor has deadline question or time-sensitive matter),
  "should_escalate": true/false,
  "escalation_reason": "reason for escalation, if any"
}}

Our RFQ requested: sea LCL/FCL rates, land transport rates, transit times, \
billing rules, last-mile delivery costs, warehouse/customs clearance capabilities, \
and payment terms. All for China (Guangdong) to Bangkok corridor."""


def classify_vendor_response(
    sender: str,
    subject: str,
    body: str,
    inquiry_title: str = "China to Bangkok Freight Forwarding",
) -> dict:
    """Classify an inbound vendor email using Gemini.

    Returns dict with: is_rfq_response, intent, confidence, summary,
    questions_from_vendor, has_rate_data, language, should_escalate, etc.
    """
    if not GEMINI_ENABLED:
        logger.info("Gemini disabled — returning default classification")
        return {
            "is_rfq_response": False,
            "intent": "unrelated",
            "confidence": 0.0,
            "summary": "Gemini disabled",
            "questions_from_vendor": [],
            "has_rate_data": False,
            "has_attachment": False,
            "missing_fields": [],
            "language": "en",
            "urgency": "normal",
            "should_escalate": False,
            "escalation_reason": None,
        }

    prompt = CLASSIFY_USER_TEMPLATE.format(
        inquiry_title=inquiry_title,
        sender=sender,
        subject=subject,
        body=body[:8000],  # Truncate very long emails
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt],
            config=genai.types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=2048,
                response_mime_type="application/json",
                system_instruction=CLASSIFY_SYSTEM_PROMPT,
            ),
        )
        result = _safe_json_parse(response.text)
        if result is None:
            logger.warning("Failed to parse classify JSON, raw: %s", response.text[:200])
            raise ValueError("Malformed JSON from Gemini classify")
        logger.info(
            "Classified email from %s: intent=%s confidence=%.2f",
            sender,
            result.get("intent"),
            result.get("confidence", 0),
        )
        return result
    except Exception as e:
        logger.error("Gemini classify error: %s", e)
        return {
            "is_rfq_response": False,
            "intent": "unrelated",
            "confidence": 0.0,
            "summary": f"Classification error: {str(e)}",
            "questions_from_vendor": [],
            "has_rate_data": False,
            "has_attachment": False,
            "missing_fields": [],
            "language": "en",
            "urgency": "normal",
            "should_escalate": True,
            "escalation_reason": f"Gemini error: {str(e)}",
        }


# ── Prompt 2: Extract Vendor Rates ────────────────────────────


EXTRACT_SYSTEM_PROMPT = """\
You are a procurement data extraction specialist. Your task is to extract \
structured rate data from vendor emails and attachments responding to a freight \
forwarding RFQ.

Extract ALL numeric rates, transit times, and capabilities mentioned. \
Convert all currencies to THB where possible. If the vendor quotes in USD or CNY, \
note the original currency and amount.

IMPORTANT: Respond ONLY with valid JSON. No markdown, no code fences."""

EXTRACT_USER_TEMPLATE = """\
Extract structured rate data from this vendor response.

Vendor: {vendor_name} ({vendor_company})
Email body:
---
{body}
---
{attachment_section}

IMPORTANT: Identify the trade term the vendor is quoting under. Common trade terms:
- DDP (Delivered Duty Paid): all-inclusive — warehouse, freight, customs, taxes, last-mile delivery
- DDU (Delivered Duty Unpaid): freight + delivery but buyer pays customs/taxes
- D2D (Door-to-Door consolidated): freight + last-mile, may or may not include customs
- EXW (Ex Works): pickup from factory, buyer arranges everything
- FOB (Free on Board): seller delivers to port, buyer arranges sea freight onward
- CIF (Cost, Insurance, Freight): seller pays freight + insurance to destination port

Extract and return JSON matching this schema:
{{
  "trade_term": "DDP" or "DDU" or "D2D" or "EXW" or "FOB" or "CIF" or "other",
  "trade_term_notes": "what exactly is included in the quoted price",
  "rates": {{
    "sea_lcl_per_cbm": number or null (THB/CBM),
    "sea_lcl_per_kg": number or null (THB/KG),
    "land_per_cbm": number or null (THB/CBM),
    "land_per_kg": number or null (THB/KG),
    "fcl_20": number or null (THB per 20ft container),
    "fcl_40": number or null (THB per 40ft container),
    "fcl_40hc": number or null (THB per 40HC container),
    "transit_sea_days": number or null,
    "transit_land_days": number or null,
    "min_charge": number or null (THB minimum charge),
    "billing_rule": string or null (e.g. "charge the higher of CBM or KG"),
    "insurance_rate": string or null,
    "payment_terms": string or null,
    "currency": string (original currency quoted, e.g. "THB", "CNY", "USD"),
    "fx_rate_used": number or null (if conversion was needed)
  }},
  "includes": {{
    "china_warehouse": true/false/null,
    "china_pickup": true/false/null,
    "freight": true/false/null,
    "customs_china": true/false/null,
    "customs_thailand": true/false/null,
    "import_taxes": true/false/null,
    "last_mile_delivery": true/false/null,
    "cargo_insurance": true/false/null
  }},
  "surcharges": {{
    "last_mile_standard": number or null (THB, if charged separately),
    "last_mile_oversized": number or null (THB),
    "pickup_fee": number or null (THB, if charged separately),
    "sensitive_goods_surcharge": number or null (THB/CBM or description),
    "oversized_surcharge": string or null
  }},
  "capabilities": {{
    "warehouse_china": true/false/null,
    "warehouse_bangkok": true/false/null,
    "customs_clearance": true/false/null (double clearance CN+TH?),
    "cargo_insurance": true/false/null,
    "api_tracking": true/false/null,
    "wechat_support": true/false/null,
    "consolidation": true/false/null,
    "free_storage_days": number or null
  }},
  "missing_fields": ["list of fields we need but vendor did not provide"],
  "notes": "any important caveats, conditions, or non-standard terms",
  "confidence": 0.0-1.0 (how complete and reliable is this extraction?)
}}

Our baseline rates (Gift Somlak 2025, D2D consolidated, freight-only):
  Sea: 4,600 THB/CBM or 35 THB/KG
  Land: 7,200 THB/CBM or 48 THB/KG"""


def extract_vendor_rates(
    body: str,
    vendor_name: str = "",
    vendor_company: str = "",
    attachment_text: str | None = None,
) -> dict:
    """Extract structured rate data from a vendor response using Gemini.

    Returns dict with: rates, capabilities, missing_fields, notes, confidence.
    """
    if not GEMINI_ENABLED:
        return {
            "rates": {},
            "capabilities": {},
            "missing_fields": [],
            "notes": "Gemini disabled",
            "confidence": 0.0,
        }

    attachment_section = ""
    if attachment_text:
        attachment_section = f"\nAttachment content:\n---\n{attachment_text[:10000]}\n---"

    prompt = EXTRACT_USER_TEMPLATE.format(
        vendor_name=vendor_name,
        vendor_company=vendor_company,
        body=body[:8000],
        attachment_section=attachment_section,
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt],
            config=genai.types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=4096,
                response_mime_type="application/json",
                system_instruction=EXTRACT_SYSTEM_PROMPT,
            ),
        )
        result = _safe_json_parse(response.text)
        if result is None:
            logger.warning("Failed to parse extract JSON, raw: %s", response.text[:200])
            raise ValueError("Malformed JSON from Gemini extract")
        logger.info(
            "Extracted rates from %s: confidence=%.2f missing=%d",
            vendor_company,
            result.get("confidence", 0),
            len(result.get("missing_fields", [])),
        )
        return result
    except Exception as e:
        logger.error("Gemini extract error: %s", e)
        return {
            "rates": {},
            "capabilities": {},
            "missing_fields": [],
            "notes": f"Extraction error: {str(e)}",
            "confidence": 0.0,
        }


# ── Prompt 3: Generate Auto-Reply ─────────────────────────────


AUTO_REPLY_SYSTEM_PROMPT = """\
You are a professional procurement assistant for GO Corporation Co., Ltd., \
a Thai company that imports goods from China. You are drafting a reply to a \
vendor's email regarding a freight forwarding RFQ.

Rules:
1. Be professional, concise, and helpful
2. Match the vendor's language — if they wrote in Chinese, reply in Chinese \
   with English summary. If English, reply in English with Chinese summary.
3. Answer factual questions about GO Corporation honestly
4. Never commit to pricing, exclusive contracts, minimum volumes, or legal terms
5. If the vendor asks for something you're not sure about, indicate you need to \
   check with management
6. Always sign as "Eukrit Kraikosol | GO Corporation Co., Ltd."

IMPORTANT: Respond ONLY with valid JSON. No markdown, no code fences."""

AUTO_REPLY_USER_TEMPLATE = """\
Draft a reply to this vendor's email.

Vendor: {vendor_name} ({vendor_company})
Their email:
---
{vendor_email_body}
---

Questions they asked:
{questions_list}

Missing rate fields we still need from them:
{missing_fields_list}

Context about GO Corporation:
{auto_reply_context}

Previous conversation messages (most recent first):
{conversation_history}

Return JSON:
{{
  "subject": "Re: [appropriate subject line]",
  "body_html": "<div>...full HTML reply body...</div>",
  "body_language": "zh" or "en" or "bilingual",
  "confidence": 0.0-1.0 (how appropriate is this auto-reply?),
  "should_escalate": true/false,
  "escalation_reason": "reason if should_escalate is true, else null",
  "answers_given": ["list of questions answered in this reply"],
  "info_requested": ["list of info we're asking the vendor to provide"]
}}"""


def generate_auto_reply(
    vendor_name: str,
    vendor_company: str,
    vendor_email_body: str,
    questions: list[str] | None = None,
    missing_fields: list[str] | None = None,
    auto_reply_context: str = "",
    conversation_history: list[dict] | None = None,
) -> dict:
    """Generate an auto-reply to a vendor email using Gemini.

    Returns dict with: subject, body_html, confidence, should_escalate, etc.
    """
    if not GEMINI_ENABLED:
        return {
            "subject": "",
            "body_html": "",
            "body_language": "en",
            "confidence": 0.0,
            "should_escalate": True,
            "escalation_reason": "Gemini disabled",
            "answers_given": [],
            "info_requested": [],
        }

    questions_list = "\n".join(f"- {q}" for q in (questions or [])) or "None"
    missing_fields_list = "\n".join(f"- {f}" for f in (missing_fields or [])) or "None"

    # Format conversation history
    history_text = ""
    if conversation_history:
        for msg in conversation_history[-5:]:  # Last 5 messages
            direction = msg.get("direction", "unknown")
            body = msg.get("body_preview", "")[:500]
            history_text += f"\n[{direction}] {body}\n---"
    else:
        history_text = "No previous messages."

    prompt = AUTO_REPLY_USER_TEMPLATE.format(
        vendor_name=vendor_name,
        vendor_company=vendor_company,
        vendor_email_body=vendor_email_body[:5000],
        questions_list=questions_list,
        missing_fields_list=missing_fields_list,
        auto_reply_context=auto_reply_context or "No additional context.",
        conversation_history=history_text,
    )

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[prompt],
            config=genai.types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=4096,
                response_mime_type="application/json",
                system_instruction=AUTO_REPLY_SYSTEM_PROMPT,
            ),
        )
        raw_text = response.text
        result = _safe_json_parse(raw_text)
        if result is None:
            # Gemini sometimes produces malformed JSON with unescaped HTML.
            # Fall back to regex extraction.
            result = _repair_auto_reply_json(raw_text)

        logger.info(
            "Generated auto-reply for %s: confidence=%.2f escalate=%s",
            vendor_company,
            result.get("confidence", 0),
            result.get("should_escalate", False),
        )
        return result
    except Exception as e:
        logger.error("Gemini auto-reply error: %s", e)
        return {
            "subject": "",
            "body_html": "",
            "body_language": "en",
            "confidence": 0.0,
            "should_escalate": True,
            "escalation_reason": f"Gemini error: {str(e)}",
            "answers_given": [],
            "info_requested": [],
        }


def _repair_auto_reply_json(raw: str) -> dict:
    """Attempt to repair malformed JSON from Gemini auto-reply output."""
    import re

    result = {
        "subject": "",
        "body_html": "",
        "body_language": "en",
        "confidence": 0.0,
        "should_escalate": False,
        "escalation_reason": None,
        "answers_given": [],
        "info_requested": [],
    }

    # Extract subject
    m = re.search(r'"subject"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    if m:
        result["subject"] = m.group(1)

    # Extract body_html — grab everything between "body_html": " and the next known key
    m = re.search(
        r'"body_html"\s*:\s*"(.*?)",\s*"body_language"',
        raw,
        re.DOTALL,
    )
    if m:
        result["body_html"] = m.group(1).replace('\\"', '"').replace("\\n", "\n")

    # Extract confidence
    m = re.search(r'"confidence"\s*:\s*([\d.]+)', raw)
    if m:
        result["confidence"] = float(m.group(1))

    # Extract should_escalate
    m = re.search(r'"should_escalate"\s*:\s*(true|false)', raw, re.IGNORECASE)
    if m:
        result["should_escalate"] = m.group(1).lower() == "true"

    # Extract body_language
    m = re.search(r'"body_language"\s*:\s*"(\w+)"', raw)
    if m:
        result["body_language"] = m.group(1)

    logger.info("Repaired malformed auto-reply JSON (confidence=%.2f)", result["confidence"])
    return result
