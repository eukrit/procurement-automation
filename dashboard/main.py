"""Master RFQ Dashboard — Cloud Run service.

Serves a live directory of all RFQ projects pulled from Firestore, with
per-project summary and status. No auth (internal use); lock down via IAP or
`--no-allow-unauthenticated` if needed.
"""
from __future__ import annotations

import html
import os
from datetime import datetime, timezone
from typing import Any

from flask import Flask, Response, abort
from google.cloud import firestore

PROJECT_ID = os.environ.get("GCP_PROJECT", "ai-agents-go")
DATABASE = os.environ.get("FIRESTORE_DATABASE", "procurement-automation")

app = Flask(__name__)
_db: firestore.Client | None = None


def db() -> firestore.Client:
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID, database=DATABASE)
    return _db


STATUS_COLORS = {
    "draft": ("#334155", "#cbd5e1"),
    "sending": ("#1e3a8a", "#93c5fd"),
    "active": ("#064e3b", "#6ee7b7"),
    "closed": ("#3f3f46", "#d4d4d8"),
    "awarded": ("#713f12", "#fde68a"),
    "cancelled": ("#7f1d1d", "#fca5a5"),
}
CATEGORY_LABELS = {
    "freight": "Freight & Logistics",
    "commodity": "Commodity Export",
    "electronics": "Electronics & Hardware",
    "solar": "Solar Equipment",
    "display": "Display Hardware",
}


def fmt_date(v: Any) -> str:
    if not v:
        return "—"
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    return str(v)[:10]


def days_until(deadline: Any) -> int | None:
    if not deadline:
        return None
    try:
        if isinstance(deadline, str):
            d = datetime.strptime(deadline[:10], "%Y-%m-%d").date()
        elif hasattr(deadline, "date"):
            d = deadline.date()
        else:
            return None
        return (d - datetime.now(timezone.utc).date()).days
    except Exception:
        return None


def load_inquiries() -> list[dict]:
    out = []
    for doc in db().collection("rfq_inquiries").stream():
        d = doc.to_dict() or {}
        inquiry_id = d.get("inquiry_id", doc.id)
        vendors = list(
            db().collection("rfq_inquiries").document(doc.id).collection("vendors").stream()
        )
        responded = 0
        awarded = None
        for v in vendors:
            vd = v.to_dict() or {}
            if vd.get("last_response_at") or vd.get("quote_received") or vd.get("rates"):
                rates = vd.get("rates") or {}
                if rates or vd.get("last_response_at"):
                    responded += 1
            if vd.get("vendor_id") == d.get("awarded_vendor_id"):
                awarded = vd.get("company_en") or vd.get("vendor_id")
        out.append(
            {
                "id": inquiry_id,
                "title": d.get("title", inquiry_id),
                "category": d.get("category", ""),
                "subcategory": d.get("subcategory", ""),
                "status": d.get("status", "draft"),
                "vendor_count": d.get("vendor_count", len(vendors)),
                "responded_count": d.get("responded_count", responded) or responded,
                "deadline": d.get("response_deadline"),
                "created_at": d.get("created_at"),
                "last_updated": d.get("last_updated"),
                "awarded_vendor": awarded,
                "created_by": d.get("created_by", ""),
                "template_id": d.get("template_id", ""),
            }
        )
    out.sort(key=lambda x: (x["status"] != "active", x["status"] != "sending", str(x["last_updated"])), reverse=False)
    return out


def badge(status: str) -> str:
    bg, fg = STATUS_COLORS.get(status, ("#334155", "#cbd5e1"))
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
        f'font-size:0.65rem;font-weight:700;text-transform:uppercase;'
        f'background:{bg};color:{fg}">{html.escape(status)}</span>'
    )


def response_bar(responded: int, total: int) -> str:
    pct = int((responded / total) * 100) if total else 0
    return (
        f'<div style="background:#0f1117;border-radius:8px;height:8px;overflow:hidden;margin-top:8px">'
        f'<div style="background:linear-gradient(90deg,#10b981,#3b82f6);height:100%;width:{pct}%"></div>'
        f"</div>"
    )


def render_index(inquiries: list[dict]) -> str:
    total_vendors = sum(i["vendor_count"] or 0 for i in inquiries)
    total_responses = sum(i["responded_count"] or 0 for i in inquiries)
    active = sum(1 for i in inquiries if i["status"] in ("active", "sending"))

    cards = []
    for i in inquiries:
        du = days_until(i["deadline"])
        deadline_txt = fmt_date(i["deadline"])
        if du is not None:
            if du < 0:
                deadline_txt += f' <span style="color:#fca5a5">({-du}d overdue)</span>'
            elif du <= 3:
                deadline_txt += f' <span style="color:#fbbf24">({du}d left)</span>'
            else:
                deadline_txt += f' <span style="color:#94a3b8">({du}d left)</span>'
        cat = CATEGORY_LABELS.get(i["category"], i["category"] or "—")
        cards.append(
            f"""
<a href="/rfq/{html.escape(i['id'])}" class="card">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
    <div style="flex:1">
      <div class="card-title">{html.escape(i['title'])}</div>
      <div class="card-id">{html.escape(i['id'])} · {html.escape(cat)}</div>
    </div>
    {badge(i['status'])}
  </div>
  <div class="stats">
    <div><span class="n">{i['responded_count']}</span><span class="l">/ {i['vendor_count']} responses</span></div>
    <div><span class="l">Deadline:</span> {deadline_txt}</div>
  </div>
  {response_bar(i['responded_count'] or 0, i['vendor_count'] or 0)}
</a>
"""
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Master RFQ Dashboard | GO Corporation</title>
<style>
  :root {{ --bg:#0f1117; --surface:#1a1d27; --border:#2d3140; --accent:#3b82f6; --text:#e2e8f0; --muted:#94a3b8; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Inter','Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; padding:40px 20px; }}
  .container {{ max-width:1000px; margin:0 auto; }}
  h1 {{ font-size:1.8rem; margin-bottom:6px; }}
  .sub {{ color:var(--muted); font-size:0.9rem; margin-bottom:24px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px; margin-bottom:32px; }}
  .kpi {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:16px 20px; }}
  .kpi .v {{ font-size:2rem; font-weight:700; }}
  .kpi .k {{ color:var(--muted); font-size:0.75rem; text-transform:uppercase; letter-spacing:0.05em; }}
  .card {{ display:block; background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:14px; text-decoration:none; color:var(--text); transition:border-color 0.15s, transform 0.15s; }}
  .card:hover {{ border-color:var(--accent); transform:translateY(-1px); }}
  .card-title {{ font-weight:600; font-size:1.05rem; margin-bottom:4px; }}
  .card-id {{ color:var(--muted); font-size:0.78rem; font-family:'JetBrains Mono',monospace; }}
  .stats {{ display:flex; justify-content:space-between; margin-top:14px; font-size:0.85rem; color:var(--muted); flex-wrap:wrap; gap:12px; }}
  .stats .n {{ color:var(--text); font-weight:700; font-size:1.1rem; margin-right:6px; }}
  .stats .l {{ color:var(--muted); }}
  footer {{ margin-top:40px; padding-top:20px; border-top:1px solid var(--border); color:var(--muted); font-size:0.78rem; text-align:center; }}
  footer a {{ color:var(--accent); text-decoration:none; margin:0 8px; }}
</style>
</head>
<body>
<div class="container">
  <h1>Master RFQ Dashboard</h1>
  <p class="sub">GO Corporation · Live from Firestore ({html.escape(DATABASE)}) · {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>

  <div class="kpis">
    <div class="kpi"><div class="v">{len(inquiries)}</div><div class="k">Total RFQ projects</div></div>
    <div class="kpi"><div class="v">{active}</div><div class="k">Active / Sending</div></div>
    <div class="kpi"><div class="v">{total_vendors}</div><div class="k">Vendors engaged</div></div>
    <div class="kpi"><div class="v">{total_responses}</div><div class="k">Responses received</div></div>
  </div>

  <h2 style="font-size:1.1rem;margin-bottom:12px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em">RFQ Projects Directory</h2>
  {''.join(cards) if cards else '<p style="color:var(--muted)">No RFQ inquiries found.</p>'}

  <footer>
    <a href="/api/inquiries">JSON API</a> ·
    <a href="/healthz">Health</a> ·
    <a href="https://github.com/eukrit/procurement-automation">GitHub</a> ·
    <a href="https://console.cloud.google.com/firestore/databases/procurement-automation/data/panel/rfq_inquiries?project=ai-agents-go">Firestore</a>
  </footer>
</div>
</body>
</html>"""


def render_detail(i: dict, vendors: list[dict]) -> str:
    rows = []
    for v in vendors:
        status = v.get("status", "pending")
        rates = v.get("rates") or {}
        rate_txt = ", ".join(f"{k}: {val}" for k, val in list(rates.items())[:3]) if rates else "—"
        last = fmt_date(v.get("last_response_at") or v.get("last_updated"))
        rows.append(
            f"""<tr>
  <td>{html.escape(v.get('company_en') or v.get('vendor_id',''))}</td>
  <td>{html.escape(v.get('contact_email') or '—')}</td>
  <td>{badge(status)}</td>
  <td style="font-size:0.8rem;color:var(--muted)">{html.escape(rate_txt)}</td>
  <td>{last}</td>
</tr>"""
        )

    du = days_until(i["deadline"])
    deadline_txt = fmt_date(i["deadline"])
    if du is not None:
        deadline_txt += f" ({du}d {'overdue' if du < 0 else 'left'})"

    cat = CATEGORY_LABELS.get(i["category"], i["category"])
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(i['title'])} | RFQ Dashboard</title>
<style>
  :root {{ --bg:#0f1117; --surface:#1a1d27; --border:#2d3140; --accent:#3b82f6; --text:#e2e8f0; --muted:#94a3b8; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Inter','Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--text); min-height:100vh; padding:40px 20px; }}
  .container {{ max-width:1100px; margin:0 auto; }}
  a {{ color:var(--accent); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .back {{ font-size:0.85rem; margin-bottom:16px; display:inline-block; }}
  h1 {{ font-size:1.6rem; margin-bottom:6px; }}
  .id {{ color:var(--muted); font-family:'JetBrains Mono',monospace; font-size:0.85rem; margin-bottom:20px; }}
  .panel {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:20px; margin-bottom:16px; }}
  .meta {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; }}
  .meta .k {{ color:var(--muted); font-size:0.7rem; text-transform:uppercase; letter-spacing:0.05em; margin-bottom:4px; }}
  .meta .v {{ font-size:1rem; font-weight:500; }}
  table {{ width:100%; border-collapse:collapse; }}
  th, td {{ padding:10px 12px; text-align:left; border-bottom:1px solid var(--border); font-size:0.88rem; }}
  th {{ color:var(--muted); font-size:0.7rem; text-transform:uppercase; letter-spacing:0.05em; font-weight:600; }}
</style>
</head><body>
<div class="container">
  <a href="/" class="back">← Back to dashboard</a>
  <h1>{html.escape(i['title'])} {badge(i['status'])}</h1>
  <div class="id">{html.escape(i['id'])}</div>

  <div class="panel">
    <div class="meta">
      <div><div class="k">Category</div><div class="v">{html.escape(cat or '—')}</div></div>
      <div><div class="k">Subcategory</div><div class="v">{html.escape(i['subcategory'] or '—')}</div></div>
      <div><div class="k">Vendors</div><div class="v">{i['vendor_count']}</div></div>
      <div><div class="k">Responses</div><div class="v">{i['responded_count']} / {i['vendor_count']}</div></div>
      <div><div class="k">Deadline</div><div class="v">{deadline_txt}</div></div>
      <div><div class="k">Created</div><div class="v">{fmt_date(i['created_at'])}</div></div>
      <div><div class="k">Last updated</div><div class="v">{fmt_date(i['last_updated'])}</div></div>
      <div><div class="k">Template</div><div class="v">{html.escape(i['template_id'] or '—')}</div></div>
      <div><div class="k">Awarded</div><div class="v">{html.escape(i['awarded_vendor'] or '—')}</div></div>
    </div>
    {response_bar(i['responded_count'] or 0, i['vendor_count'] or 0)}
  </div>

  <div class="panel">
    <h2 style="font-size:1rem;margin-bottom:14px;color:var(--muted);text-transform:uppercase;letter-spacing:0.05em">Vendors ({len(vendors)})</h2>
    <table>
      <thead><tr><th>Company</th><th>Email</th><th>Status</th><th>Latest rates</th><th>Last update</th></tr></thead>
      <tbody>{''.join(rows) if rows else '<tr><td colspan="5" style="color:var(--muted)">No vendor records.</td></tr>'}</tbody>
    </table>
  </div>
</div>
</body></html>"""


@app.route("/")
def index():
    return Response(render_index(load_inquiries()), mimetype="text/html")


@app.route("/rfq/<inquiry_id>")
def detail(inquiry_id: str):
    ref = db().collection("rfq_inquiries").document(inquiry_id)
    doc = ref.get()
    if not doc.exists:
        abort(404)
    d = doc.to_dict() or {}
    vendors_raw = list(ref.collection("vendors").stream())
    vendors = [v.to_dict() or {} for v in vendors_raw]
    responded = sum(1 for v in vendors if v.get("last_response_at") or v.get("rates"))
    i = {
        "id": d.get("inquiry_id", inquiry_id),
        "title": d.get("title", inquiry_id),
        "category": d.get("category", ""),
        "subcategory": d.get("subcategory", ""),
        "status": d.get("status", "draft"),
        "vendor_count": d.get("vendor_count", len(vendors)),
        "responded_count": d.get("responded_count", responded) or responded,
        "deadline": d.get("response_deadline"),
        "created_at": d.get("created_at"),
        "last_updated": d.get("last_updated"),
        "awarded_vendor": d.get("awarded_vendor_id"),
        "template_id": d.get("template_id", ""),
    }
    return Response(render_detail(i, vendors), mimetype="text/html")


@app.route("/api/inquiries")
def api_inquiries():
    from flask import jsonify
    data = load_inquiries()
    for i in data:
        for k in ("created_at", "last_updated", "deadline"):
            if hasattr(i[k], "isoformat"):
                i[k] = i[k].isoformat()
    return jsonify({"count": len(data), "inquiries": data})


@app.route("/healthz")
def health():
    return {"ok": True, "project": PROJECT_ID, "database": DATABASE}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
