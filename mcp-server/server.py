"""
server.py — MCP + REST API for procurement automation.

MCP tools for Claude Code to query inquiries, vendors, rates, and trigger actions.
REST endpoints for dashboard/external integration.

Run locally:  uvicorn mcp-server.server:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import json
import logging
import os
import sys

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent

from src.rfq_store import (
    get_db,
    get_inquiry,
    get_inquiry_vendors,
    get_vendor,
    get_template,
    get_workflow_config,
    list_inquiries,
    log_message,
    update_vendor_status,
)
from src.gmail_sender import send_reminder as gmail_send_reminder, send_auto_reply
from src.rfq_workflow import check_rate_anomaly

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Rate Comparison Engine ────────────────────────────────────

# Gift Somlak baseline (confirmed 2025)
# Trade term: D2D consolidated (freight + last-mile only, no customs/taxes)
BASELINE = {
    "sea_per_cbm": 4600,
    "sea_per_kg": 35,
    "land_per_cbm": 7200,
    "land_per_kg": 48,
    "trade_term": "D2D",
    "source": "Gift Somlak rate card 2025",
}

# Benchmark shipment: ED 70 Aluminum Folding Door
BENCHMARK_SHIPMENT = {
    "product": "ED 70 Aluminum Folding Door",
    "cbm": 2.394,
    "kg": 120,
    "exw_thb": 150000,
    "last_mile_thb": 3500,
}


def _get_rate_fields(rates: dict) -> tuple:
    """Extract sea/land CBM/KG rates from either new or legacy schema."""
    # New schema: rates nested under trade_term-aware structure
    sea_cbm = rates.get("sea_lcl_per_cbm") or rates.get("d2d_sea_lcl_per_cbm")
    sea_kg = rates.get("sea_lcl_per_kg") or rates.get("d2d_sea_lcl_per_kg")
    land_cbm = rates.get("land_per_cbm") or rates.get("d2d_land_per_cbm")
    land_kg = rates.get("land_per_kg") or rates.get("d2d_land_per_kg")
    return sea_cbm, sea_kg, land_cbm, land_kg


def _score_vendor_rates(rates: dict, baseline: dict) -> dict:
    """Score a vendor's rates vs baseline. Lower is better."""
    scores = {}

    vendor_sea, vendor_sea_kg, vendor_land, vendor_land_kg = _get_rate_fields(rates)

    # Sea LCL score
    if vendor_sea and baseline.get("sea_per_cbm"):
        scores["sea_lcl_ratio"] = round(vendor_sea / baseline["sea_per_cbm"], 3)
        scores["sea_lcl_savings_pct"] = round(
            (1 - vendor_sea / baseline["sea_per_cbm"]) * 100, 1
        )

    # Land score
    if vendor_land and baseline.get("land_per_cbm"):
        scores["land_ratio"] = round(vendor_land / baseline["land_per_cbm"], 3)
        scores["land_savings_pct"] = round(
            (1 - vendor_land / baseline["land_per_cbm"]) * 100, 1
        )

    # Benchmark shipment cost (sea)
    if vendor_sea:
        cbm = BENCHMARK_SHIPMENT["cbm"]
        kg = BENCHMARK_SHIPMENT["kg"]
        cbm_cost = vendor_sea * cbm
        kg_cost = (vendor_sea_kg or 0) * kg
        freight = max(cbm_cost, kg_cost) if vendor_sea_kg else cbm_cost
        scores["benchmark_sea_freight"] = round(freight, 0)
        scores["benchmark_sea_landed"] = round(
            BENCHMARK_SHIPMENT["exw_thb"] + freight + BENCHMARK_SHIPMENT["last_mile_thb"], 0
        )

    # Benchmark shipment cost (land)
    if vendor_land:
        cbm = BENCHMARK_SHIPMENT["cbm"]
        kg = BENCHMARK_SHIPMENT["kg"]
        cbm_cost = vendor_land * cbm
        kg_cost = (vendor_land_kg or 0) * kg
        freight = max(cbm_cost, kg_cost) if vendor_land_kg else cbm_cost
        scores["benchmark_land_freight"] = round(freight, 0)
        scores["benchmark_land_landed"] = round(
            BENCHMARK_SHIPMENT["exw_thb"] + freight + BENCHMARK_SHIPMENT["last_mile_thb"], 0
        )

    return scores


def compare_all_rates(inquiry_id: str, db=None) -> dict:
    """Build a full rate comparison table for all vendors with rates."""
    db = db or get_db()
    inquiry = get_inquiry(inquiry_id, db=db)
    if not inquiry:
        return {"error": f"Inquiry {inquiry_id} not found"}

    baseline = inquiry.get("scoring_config", {}).get("baseline", BASELINE)
    vendors = get_inquiry_vendors(inquiry_id, db=db)

    comparison = {
        "inquiry_id": inquiry_id,
        "baseline": baseline,
        "benchmark_shipment": BENCHMARK_SHIPMENT,
        "vendors": [],
    }

    for v in vendors:
        rates = v.get("rates", {})
        if not rates:
            continue

        scores = _score_vendor_rates(rates, baseline)
        anomalies = check_rate_anomaly(rates, baseline)

        sea_cbm, sea_kg, land_cbm, land_kg = _get_rate_fields(rates)

        comparison["vendors"].append({
            "vendor_id": v.get("vendor_id"),
            "company_en": v.get("company_en"),
            "status": v.get("status"),
            "trade_term": rates.get("trade_term", "unknown"),
            "trade_term_notes": rates.get("trade_term_notes", ""),
            "includes": rates.get("includes", {}),
            "rates": rates,
            "sea_lcl_per_cbm": sea_cbm,
            "land_per_cbm": land_cbm,
            "scores": scores,
            "anomalies": anomalies,
            "capabilities": v.get("capabilities", {}),
            "transit_sea_days": rates.get("transit_sea_days"),
            "transit_land_days": rates.get("transit_land_days"),
            "payment_terms": rates.get("payment_terms"),
        })

    # Sort by sea LCL ratio (cheapest first)
    comparison["vendors"].sort(
        key=lambda x: x.get("scores", {}).get("sea_lcl_ratio", 999)
    )

    return comparison


# ── MCP Server ────────────────────────────────────────────────

mcp_server = Server("procurement-automation")


@mcp_server.list_tools()
async def list_tools():
    return [
        Tool(
            name="get_inquiry_status",
            description="Get overview of an RFQ inquiry: vendor count, response count, status breakdown",
            inputSchema={
                "type": "object",
                "properties": {
                    "inquiry_id": {"type": "string", "description": "The inquiry ID, e.g. RFQ-GO-2026-04-FREIGHT"},
                },
                "required": ["inquiry_id"],
            },
        ),
        Tool(
            name="get_vendor_detail",
            description="Get full vendor info including rates, messages, score, and contact details",
            inputSchema={
                "type": "object",
                "properties": {
                    "inquiry_id": {"type": "string"},
                    "vendor_id": {"type": "string"},
                },
                "required": ["inquiry_id", "vendor_id"],
            },
        ),
        Tool(
            name="compare_rates",
            description="Side-by-side rate comparison table for all vendors with rates, scored vs Gift Somlak baseline",
            inputSchema={
                "type": "object",
                "properties": {
                    "inquiry_id": {"type": "string"},
                },
                "required": ["inquiry_id"],
            },
        ),
        Tool(
            name="send_vendor_reminder",
            description="Manually trigger a follow-up reminder email to a specific vendor",
            inputSchema={
                "type": "object",
                "properties": {
                    "inquiry_id": {"type": "string"},
                    "vendor_id": {"type": "string"},
                    "reminder_number": {"type": "integer", "enum": [1, 2], "default": 1},
                },
                "required": ["inquiry_id", "vendor_id"],
            },
        ),
        Tool(
            name="list_inquiries",
            description="List all RFQ inquiries, optionally filtered by status",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by status: draft, sending, active, evaluating, awarded"},
                },
            },
        ),
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    db = get_db()

    if name == "get_inquiry_status":
        inquiry_id = arguments["inquiry_id"]
        inquiry = get_inquiry(inquiry_id, db=db)
        if not inquiry:
            return [TextContent(type="text", text=f"Inquiry {inquiry_id} not found")]

        vendors = get_inquiry_vendors(inquiry_id, db=db)
        status_counts = {}
        for v in vendors:
            s = v.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

        result = {
            "inquiry_id": inquiry_id,
            "title": inquiry.get("title"),
            "status": inquiry.get("status"),
            "category": inquiry.get("category"),
            "response_deadline": inquiry.get("response_deadline"),
            "vendor_count": inquiry.get("vendor_count", 0),
            "responded_count": inquiry.get("responded_count", 0),
            "status_breakdown": status_counts,
            "vendors": [
                {
                    "vendor_id": v.get("vendor_id"),
                    "company_en": v.get("company_en"),
                    "status": v.get("status"),
                    "contact_email": v.get("contact_email"),
                    "has_rates": bool(v.get("rates")),
                }
                for v in vendors
            ],
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    elif name == "get_vendor_detail":
        inquiry_id = arguments["inquiry_id"]
        vendor_id = arguments["vendor_id"]
        vendor = get_vendor(inquiry_id, vendor_id, db=db)
        if not vendor:
            return [TextContent(type="text", text=f"Vendor {vendor_id} not found in {inquiry_id}")]

        # Get messages
        msgs_ref = (
            db.collection("rfq_inquiries")
            .document(inquiry_id)
            .collection("vendors")
            .document(vendor_id)
            .collection("messages")
        )
        messages = [doc.to_dict() for doc in msgs_ref.stream()]
        messages.sort(key=lambda m: m.get("timestamp", ""), reverse=True)

        result = {
            **vendor,
            "messages": messages[:10],  # Last 10 messages
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    elif name == "compare_rates":
        inquiry_id = arguments["inquiry_id"]
        result = compare_all_rates(inquiry_id, db=db)
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    elif name == "send_vendor_reminder":
        inquiry_id = arguments["inquiry_id"]
        vendor_id = arguments["vendor_id"]
        reminder_number = arguments.get("reminder_number", 1)

        inquiry = get_inquiry(inquiry_id, db=db)
        vendor = get_vendor(inquiry_id, vendor_id, db=db)
        if not inquiry or not vendor:
            return [TextContent(type="text", text="Inquiry or vendor not found")]

        try:
            gmail_send_reminder(vendor, inquiry, reminder_number)
            update_vendor_status(
                inquiry_id, vendor_id,
                f"reminder_{reminder_number}",
                note=f"Manual reminder {reminder_number} sent",
                db=db,
            )
            return [TextContent(type="text", text=f"Reminder {reminder_number} sent to {vendor.get('company_en', vendor_id)}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error sending reminder: {str(e)}")]

    elif name == "list_inquiries":
        status = arguments.get("status")
        inquiries = list_inquiries(status=status, db=db)
        result = [
            {
                "inquiry_id": inq.get("inquiry_id"),
                "title": inq.get("title"),
                "status": inq.get("status"),
                "category": inq.get("category"),
                "vendor_count": inq.get("vendor_count", 0),
                "responded_count": inq.get("responded_count", 0),
                "response_deadline": inq.get("response_deadline"),
            }
            for inq in inquiries
        ]
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ── REST API ──────────────────────────────────────────────────


async def api_list_inquiries(request: Request) -> JSONResponse:
    status = request.query_params.get("status")
    db = get_db()
    inquiries = list_inquiries(status=status, db=db)
    return JSONResponse([
        {
            "inquiry_id": inq.get("inquiry_id"),
            "title": inq.get("title"),
            "status": inq.get("status"),
            "vendor_count": inq.get("vendor_count", 0),
            "responded_count": inq.get("responded_count", 0),
        }
        for inq in inquiries
    ])


async def api_get_inquiry(request: Request) -> JSONResponse:
    inquiry_id = request.path_params["inquiry_id"]
    db = get_db()
    inquiry = get_inquiry(inquiry_id, db=db)
    if not inquiry:
        return JSONResponse({"error": "Not found"}, status_code=404)

    vendors = get_inquiry_vendors(inquiry_id, db=db)
    status_counts = {}
    for v in vendors:
        s = v.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    return JSONResponse({
        **{k: v for k, v in inquiry.items() if not isinstance(v, (bytes,))},
        "status_breakdown": status_counts,
    }, default=str)


async def api_get_vendors(request: Request) -> JSONResponse:
    inquiry_id = request.path_params["inquiry_id"]
    db = get_db()
    vendors = get_inquiry_vendors(inquiry_id, db=db)
    return JSONResponse([
        {
            "vendor_id": v.get("vendor_id"),
            "company_en": v.get("company_en"),
            "status": v.get("status"),
            "contact_email": v.get("contact_email"),
            "has_rates": bool(v.get("rates")),
            "rates": v.get("rates", {}),
        }
        for v in vendors
    ], default=str)


async def api_get_vendor(request: Request) -> JSONResponse:
    inquiry_id = request.path_params["inquiry_id"]
    vendor_id = request.path_params["vendor_id"]
    db = get_db()
    vendor = get_vendor(inquiry_id, vendor_id, db=db)
    if not vendor:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse(vendor, default=str)


async def api_compare_rates(request: Request) -> JSONResponse:
    inquiry_id = request.path_params["inquiry_id"]
    db = get_db()
    result = compare_all_rates(inquiry_id, db=db)
    return JSONResponse(result, default=str)


async def api_health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "procurement-mcp"})


# ── MCP SSE Transport ─────────────────────────────────────────

sse = SseServerTransport("/mcp/messages/")


async def handle_sse(request: Request):
    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_server.run(
            streams[0], streams[1], mcp_server.create_initialization_options()
        )


# ── Starlette App ─────────────────────────────────────────────

app = Starlette(
    routes=[
        # Health
        Route("/health", api_health),
        # REST API
        Route("/api/inquiries", api_list_inquiries),
        Route("/api/inquiries/{inquiry_id}", api_get_inquiry),
        Route("/api/inquiries/{inquiry_id}/vendors", api_get_vendors),
        Route("/api/inquiries/{inquiry_id}/vendors/{vendor_id}", api_get_vendor),
        Route("/api/inquiries/{inquiry_id}/compare", api_compare_rates),
        # MCP SSE
        Route("/mcp/sse", handle_sse),
        Route("/mcp/messages/", sse.handle_post_message, methods=["POST"]),
    ],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
