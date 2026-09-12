import os
import secrets
import threading
import time
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import escape
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from learner import Learner
from opportunity_scout import OpportunityScout
from performance_learner import PerformanceLearner
from historical_experience import HistoricalExperienceCollector
from delivery_reviewer import CheckEvidence, review_delivery
from store import Store

DATA_DIR = os.getenv("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)
store = Store(os.path.join(DATA_DIR, "bounty_builder.db"))
learner = Learner(os.path.join(DATA_DIR, "ranking_weights.json"))
scout = OpportunityScout()
performance_learner = PerformanceLearner()
historian = HistoricalExperienceCollector(token=os.getenv("GITHUB_TOKEN"))
scan_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=worker, daemon=True).start()
    yield


app = FastAPI(title="Bounty Builder Agent", version="2.0.0", lifespan=lifespan)


class Promotion(BaseModel):
    challenger: dict


class Outcome(BaseModel):
    opportunity_id: int = Field(gt=0)
    result: str = Field(min_length=2, max_length=40)
    income: float = Field(default=0, ge=0, le=1_000_000)
    cost: float = Field(default=0, ge=0, le=1_000_000)
    hours: float = Field(default=0, ge=0, le=10_000)
    notes: str = Field(default="", max_length=2000)


class Check(BaseModel):
    name: str
    passed: bool
    command: str = Field(max_length=500)
    summary: str = Field(max_length=2000)


class WorkReview(BaseModel):
    opportunity_id: int = Field(gt=0)
    acceptance_criteria: list[str] = Field(max_length=50)
    checks: list[Check] = Field(max_length=20)
    changed_files: list[str] = Field(max_length=200)


def require_admin(x_admin_token: str | None):
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or not x_admin_token or not secrets.compare_digest(expected, x_admin_token):
        raise HTTPException(403, "authenticated Daniel approval is required")


def scan_once():
    if not scan_lock.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        report = scout.scan()
        items = report.opportunities
        for item in items:
            store.save_opportunity(item)
        proposal = learner.propose(store.outcomes())
        performance = performance_learner.propose(store.performance_rows())
        store.save_learning_proposal(performance)
        store.audit("scout_completed", {"items": len(items), "fetched": report.fetched,
                    "duplicates": report.duplicates, "rejected": report.rejected,
                    "query_errors": report.query_errors, "learning": proposal})
        return {"status": "complete", "items": len(items)}
    except Exception as exc:
        store.audit("scan_failed", {"error": type(exc).__name__, "message": str(exc)[:300]})
        return {"status": "failed", "error": type(exc).__name__}
    finally:
        scan_lock.release()


def worker():
    history_year = datetime.now(timezone.utc).year - 19
    while True:
        scan_once()
        try:
            report = historian.collect_year(history_year)
            saved = store.save_experience(report["cases"])
            store.audit("history_sampled", {"year": history_year, "sampled": report["sampled"],
                        "saved": saved, "code_copied": False})
        except Exception as exc:
            store.audit("history_failed", {"year": history_year, "error": type(exc).__name__,
                        "message": str(exc)[:300]})
        current_year = datetime.now(timezone.utc).year
        history_year = current_year - 19 if history_year >= current_year else history_year + 1
        time.sleep(int(os.getenv("SCAN_SECONDS", "21600")))


@app.get("/health")
def health():
    return {"status": "ok", "mode": "approval_gated_real_world", "stats": store.stats()}


@app.get("/api/agents")
def agents():
    return {"status": "ok", "agents": store.agent_activity(),
            "experience": store.experience_stats()}


@app.get("/api/audit")
def audit_feed(limit: int = 50):
    return {"events": store.recent_audit(max(1, min(limit, 200)))}


@app.get("/api/opportunities/{opportunity_id}")
def opportunity_data(opportunity_id: int):
    item = store.get_opportunity(opportunity_id)
    if not item:
        raise HTTPException(404, "opportunity not found")
    return {"opportunity": item, "agent_records": store.agent_records_for(item["external_id"])}


@app.post("/scan")
def scan_now(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    result = scan_once()
    return {**result, "stats": store.stats()}


@app.post("/outcomes")
def record_outcome(body: Outcome, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    try:
        outcome_id = store.record_outcome(body.opportunity_id, body.result.strip(),
            body.income, body.cost, body.hours, body.notes.strip())
    except KeyError:
        raise HTTPException(404, "opportunity not found")
    return {"status": "recorded", "outcome_id": outcome_id, "stats": store.stats()}


@app.post("/reviews")
def record_review(body: WorkReview, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    checks = [CheckEvidence(**item.model_dump()) for item in body.checks]
    decision = review_delivery(body.acceptance_criteria, checks, body.changed_files).to_dict()
    try:
        store.save_work_review(body.opportunity_id, decision, body.model_dump())
    except KeyError:
        raise HTTPException(404, "opportunity not found")
    return {"status": "reviewed", "decision": decision}


@app.post("/learning/promote")
def promote(body: Promotion, x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    result = learner.promote(body.challenger, approved=True)
    store.audit("learning_promoted", {"weights": result})
    return {"status": "promoted", "weights": result}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    stats = store.stats()
    activity = stats["agent_activity"]
    rows = "".join(f"""<tr><td>{escape(x['status'])}</td><td>{x['risk_score']}</td>
      <td><a href='/opportunities/{x['id']}'>{escape(x['title'])}</a><br><small><a href='{escape(x['url'])}'>GitHub source</a></small></td>
      <td>{escape(x['repository'])}</td><td>${x['reward']:.2f}</td>
      <td>${x['expected_value']:.2f}</td><td>{escape(x['license'])}</td>
      <td>{escape(x['reason'])}</td></tr>""" for x in store.list_opportunities())
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width'>
    <title>Bounty Builder</title><style>body{{font-family:system-ui;background:#07111f;color:#eef;padding:24px}}
    .cards{{display:flex;gap:12px;flex-wrap:wrap}}.card{{background:#10223b;padding:16px;border-radius:12px}}
    table{{width:100%;border-collapse:collapse;margin-top:20px}}td,th{{padding:9px;border-bottom:1px solid #29405e;text-align:left}}
    a{{color:#62d9ff}}.warning{{color:#ffcf66}}</style></head><body>
    <h1>Bounty Builder Agent</h1><p class='warning'>Aggressive discovery. Licensed code only. Daniel approves every public submission and paid action.</p>
    <div class='cards'><div class='card'>Found<br><b>{stats['found']}</b></div>
    <div class='card'>Approved for work<br><b>{stats['approved'] or 0}</b></div>
    <div class='card'>Rejected by risk<br><b>{stats['rejected'] or 0}</b></div>
    <div class='card'>Realized income<br><b>${stats['realized_income']:.2f}</b></div></div>
    <h2>Agent team activity</h2><div class='cards'>
    <div class='card'>Scout scans<br><b>{activity['opportunity_scout']}</b></div>
    <div class='card'>Repository analyses<br><b>{activity['repository_analyst']}</b></div>
    <div class='card'>Risk decisions<br><b>{activity['risk_compliance_agent']}</b></div>
    <div class='card'>Solution plans<br><b>{activity['solution_planner']}</b></div>
    <div class='card'>Learning proposals<br><b>{activity['performance_learner']}</b></div>
    <div class='card'>Historical cases learned<br><b>{activity['historical_experience']}</b></div>
    <div class='card'>Delivery reviews<br><b>{activity['delivery_reviews']}</b></div></div>
    <table><thead><tr><th>Status</th><th>Score</th><th>Task</th><th>Repository</th><th>Reward</th><th>Expected value</th><th>License</th><th>Decision</th></tr></thead>
    <tbody>{rows or '<tr><td colspan=8>First scan is starting…</td></tr>'}</tbody></table>
    <p><a href='/audit'>View complete audit feed</a></p></body></html>"""


@app.get("/opportunities/{opportunity_id}", response_class=HTMLResponse)
def opportunity_detail(opportunity_id: int):
    item = store.get_opportunity(opportunity_id)
    if not item:
        raise HTTPException(404, "opportunity not found")
    records = store.agent_records_for(item["external_id"])
    panels = "".join(f"<h2>{escape(record['agent'].replace('_', ' ').title())}</h2>"
        f"<pre>{escape(json.dumps(record['payload'], indent=2))}</pre>" for record in records)
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width'>
    <title>{escape(item['title'])}</title><style>body{{font-family:system-ui;background:#07111f;color:#eef;padding:24px;max-width:1000px;margin:auto}}
    a{{color:#62d9ff}}pre{{white-space:pre-wrap;background:#10223b;padding:16px;border-radius:12px;overflow-wrap:anywhere}}</style></head><body>
    <p><a href='/'>← Dashboard</a></p><h1>{escape(item['title'])}</h1>
    <p>Status: <b>{escape(item['status'])}</b> · Score: {item['risk_score']} · Reward: ${item['reward']:.2f} · Expected value: ${item['expected_value']:.2f}</p>
    <p><a href='{escape(item['url'])}'>Open original GitHub issue</a></p>{panels or '<p>No agent records yet.</p>'}</body></html>"""


@app.get("/audit", response_class=HTMLResponse)
def audit_page():
    rows = "".join(f"<tr><td>{escape(x['created_at'])}</td><td>{escape(x['event'])}</td>"
        f"<td><pre>{escape(json.dumps(x['details'], indent=2))}</pre></td></tr>" for x in store.recent_audit())
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width'><title>Audit feed</title>
    <style>body{{font-family:system-ui;background:#07111f;color:#eef;padding:24px}}a{{color:#62d9ff}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;border-bottom:1px solid #29405e;text-align:left;vertical-align:top}}pre{{white-space:pre-wrap}}</style></head>
    <body><p><a href='/'>← Dashboard</a></p><h1>Complete audit feed</h1><table><tr><th>Time</th><th>Event</th><th>Details</th></tr>{rows}</table></body></html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
