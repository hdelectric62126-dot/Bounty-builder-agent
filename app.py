import os
import secrets
import threading
import time
import json
import hashlib
import hmac
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import escape
from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import requests
from pydantic import BaseModel, Field

from learner import Learner
from opportunity_scout import OpportunityScout
from performance_learner import PerformanceLearner
from historical_experience import HistoricalExperienceCollector
from delivery_reviewer import CheckEvidence, review_delivery
from deep_deliberation import deliberate
from store import Store
from coding_gym import CodingGym, EXERCISES
from training_scheduler import plan_training

DATA_DIR = os.getenv("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)
store = Store(os.path.join(DATA_DIR, "bounty_builder.db"))
learner = Learner(os.path.join(DATA_DIR, "ranking_weights.json"))
scout = OpportunityScout()
performance_learner = PerformanceLearner()
historian = HistoricalExperienceCollector(token=os.getenv("GITHUB_TOKEN"))
scan_lock = threading.Lock()


def execute_practice(files, profile):
    url = os.getenv("SANDBOX_URL", "").rstrip("/")
    token = os.getenv("SANDBOX_TOKEN", "")
    if not url or not token:
        return {"status": "ISOLATION_NOT_CONFIGURED", "network": "not_run"}
    response = requests.post(f"{url}/jobs", json={"files": files, "profile": profile},
        headers={"X-Sandbox-Token": token}, timeout=75)
    response.raise_for_status()
    return response.json()


coding_gym = CodingGym(execute_practice)


def run_practice_with_retry(sequence, attempts=3, pause=time.sleep):
    """Retry only transient sandbox transport/capacity failures."""
    last_error = None
    for attempt in range(attempts):
        try:
            return coding_gym.run(sequence)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status not in {429, 502, 503, 504}:
                raise
            last_error = exc
        if attempt + 1 < attempts:
            pause(min(2 ** attempt, 4))
    raise last_error


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


class ClientQuote(BaseModel):
    amount_cents: int = Field(ge=100, le=10_000_000)
    description: str = Field(min_length=3, max_length=500)


def require_admin(x_admin_token: str | None):
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or not x_admin_token or not secrets.compare_digest(expected, x_admin_token):
        raise HTTPException(403, "authenticated Daniel approval is required")


def verify_stripe_signature(payload: bytes, signature: str, secret: str) -> bool:
    parts = {}
    for item in signature.split(","):
        key, _, value = item.partition("=")
        parts.setdefault(key, []).append(value)
    try:
        timestamp = int(parts["t"][0])
    except (KeyError, ValueError):
        return False
    if abs(int(time.time()) - timestamp) > 300:
        return False
    signed = str(timestamp).encode() + b"." + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, value) for value in parts.get("v1", []))


def create_highlevel_contact(item):
    token = os.getenv("HIGHLEVEL_ACCESS_TOKEN", "")
    location_id = os.getenv("HIGHLEVEL_LOCATION_ID", "")
    if not token or not location_id:
        raise HTTPException(503, "HighLevel is not configured")
    first_name, _, last_name = item["name"].strip().partition(" ")
    response = requests.post("https://services.leadconnectorhq.com/contacts/",
        headers={"Authorization": f"Bearer {token}", "Version": "2021-07-28",
                 "Content-Type": "application/json"}, timeout=20,
        json={"locationId": location_id, "firstName": first_name,
              "lastName": last_name, "email": item["email"],
              "source": "Bounty Builder Agent",
              "tags": ["bounty-builder-client-request"]})
    if response.status_code >= 400:
        raise HTTPException(502, "HighLevel rejected client sync")
    contact = response.json().get("contact", response.json())
    if not contact.get("id"):
        raise HTTPException(502, "HighLevel returned no contact id")
    return contact["id"]


def scan_once():
    if not scan_lock.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        report = scout.scan()
        items = report.opportunities
        for item in items:
            store.save_opportunity(item)
        stale_rejected = 0
        if report.query_errors == 0:
            stale_rejected = store.reject_unseen_approvals(
                item["external_id"] for item in items
            )
        for saved in (x for x in store.list_opportunities(200) if x["status"] == "APPROVED"):
            thought = deliberate(saved, store.agent_record_map(saved["external_id"]),
                                 store.experience_stats(), store.skill_profile()).to_dict()
            stage = store.enqueue_work(saved["id"], thought)
            store.audit("deep_deliberation_completed", {"opportunity_id": saved["id"],
                        "decision_id": thought["decision_id"], "stage": stage,
                        "confidence": thought["confidence"]})
        proposal = learner.propose(store.outcomes())
        performance = performance_learner.propose(store.performance_rows())
        store.save_learning_proposal(performance)
        store.audit("scout_completed", {"items": len(items), "fetched": report.fetched,
                    "duplicates": report.duplicates, "rejected": report.rejected,
                    "query_errors": report.query_errors, "stale_rejected": stale_rejected,
                    "learning": proposal})
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
        if not store.stats()["approved"]:
            rounds = max(1, min(int(os.getenv("PRACTICE_ROUNDS_PER_CYCLE", "10")), 20))
            training_plan = plan_training(EXERCISES, store.practice_history(), rounds)
            store.audit("adaptive_training_planned", {
                "rounds": len(training_plan),
                "targets": [{k: item[k] for k in ("exercise_id", "category", "language", "reason")}
                            for item in training_plan],
            })
            for item in training_plan:
                try:
                    result = run_practice_with_retry(item["sequence"])
                    saved = store.save_practice_run(result)
                    store.audit("coding_practice_completed", {
                        "exercise_id": result["exercise_id"], "score": result["score"],
                        "verified_pass": result["verified_pass"], "saved": saved,
                        "practice_only": True,
                    })
                except Exception as exc:
                    store.audit("coding_practice_failed", {"error": type(exc).__name__,
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
            "experience": store.experience_stats(), "skills": store.skill_profile()}


@app.get("/api/skills")
def skills():
    return {"status": "ok", "profile": store.skill_profile(),
            "next_training": plan_training(EXERCISES, store.practice_history(), 5)}


@app.get("/api/audit")
def audit_feed(limit: int = 50):
    return {"events": store.recent_audit(max(1, min(limit, 200)))}


@app.get("/api/work-queue")
def queue_data():
    return {"jobs": store.work_queue()}


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


@app.get("/hire", response_class=HTMLResponse)
def hire_page():
    return """<!doctype html><html><head><meta name='viewport' content='width=device-width'>
    <title>Hire Bounty Builder</title><style>body{font-family:system-ui;background:#07111f;color:#eef;padding:24px;max-width:720px;margin:auto}input,textarea{box-sizing:border-box;width:100%;padding:12px;margin:6px 0 16px;border-radius:8px;border:1px solid #49627f}button{padding:12px 18px;background:#62d9ff;border:0;border-radius:8px;font-weight:700}</style></head><body>
    <h1>Request a software project</h1><p>Describe the work. Daniel reviews every scope and price before payment is enabled.</p>
    <form method='post' action='/client-requests'><label>Name<input name='name' required maxlength='100'></label>
    <label>Email<input name='email' type='email' required maxlength='254'></label>
    <label>Project details<textarea name='project' required minlength='20' maxlength='5000' rows='10'></textarea></label>
    <label>Budget or range<input name='budget' maxlength='100'></label><button type='submit'>Send project request</button></form></body></html>"""


@app.post("/client-requests")
def create_client_request(name: str = Form(min_length=2, max_length=100),
                          email: str = Form(min_length=5, max_length=254),
                          project: str = Form(min_length=20, max_length=5000),
                          budget: str = Form(default="", max_length=100)):
    request_id = store.create_client_request(name.strip(), email.strip(), project.strip(), budget.strip())
    return RedirectResponse(f"/client-requests/{request_id}/received", status_code=303)


@app.get("/client-requests/{request_id}/received", response_class=HTMLResponse)
def client_request_received(request_id: int):
    item = store.get_client_request(request_id)
    if not item:
        raise HTTPException(404, "client request not found")
    return """<!doctype html><html><head><meta name='viewport' content='width=device-width'><title>Request received</title></head>
    <body style='font-family:system-ui;max-width:720px;margin:40px auto;padding:20px'><h1>Request received</h1>
    <p>Daniel will review the scope and price. You will receive a secure payment link only after approval.</p></body></html>"""


@app.get("/api/client-requests")
def client_requests(x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    return {"requests": store.list_client_requests()}


@app.get("/api/integrations")
def integration_status():
    return {"stripe": bool(os.getenv("STRIPE_SECRET_KEY")),
            "stripe_webhook": bool(os.getenv("STRIPE_WEBHOOK_SECRET")),
            "highlevel": bool(os.getenv("HIGHLEVEL_ACCESS_TOKEN") and
                              os.getenv("HIGHLEVEL_LOCATION_ID"))}


@app.post("/api/client-requests/{request_id}/sync-highlevel")
def sync_client_to_highlevel(request_id: int,
                             x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    item = store.get_client_request(request_id)
    if not item:
        raise HTTPException(404, "client request not found")
    previous = store.get_crm_sync(request_id)
    if previous:
        return {"status": "already_synced", "contact_id": previous["external_contact_id"]}
    contact_id = create_highlevel_contact(item)
    store.record_crm_sync(request_id, "highlevel", contact_id)
    return {"status": "synced", "contact_id": contact_id}


@app.post("/api/client-requests/{request_id}/quote")
def quote_client_request(request_id: int, body: ClientQuote,
                         x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    try:
        store.quote_client_request(request_id, body.amount_cents, body.description.strip())
    except KeyError:
        raise HTTPException(404, "client request not found")
    return {"status": "quoted", "client_request_id": request_id}


@app.post("/api/client-requests/{request_id}/checkout")
def create_checkout(request_id: int, request: Request,
                    x_admin_token: str | None = Header(default=None)):
    require_admin(x_admin_token)
    item = store.get_client_request(request_id)
    if not item:
        raise HTTPException(404, "client request not found")
    if item["status"] != "QUOTED" or not item["quote_cents"]:
        raise HTTPException(409, "Daniel must approve a quote before checkout")
    secret = os.getenv("STRIPE_SECRET_KEY", "")
    if not secret:
        raise HTTPException(503, "Stripe is not configured")
    base = str(request.base_url).rstrip("/")
    response = requests.post("https://api.stripe.com/v1/checkout/sessions",
        auth=(secret, ""), timeout=20, data={
          "mode": "payment", "customer_email": item["email"],
          "line_items[0][price_data][currency]": "usd",
          "line_items[0][price_data][product_data][name]": item["quote_description"],
          "line_items[0][price_data][unit_amount]": item["quote_cents"],
          "line_items[0][quantity]": 1,
          "metadata[client_request_id]": request_id,
          "success_url": f"{base}/payment/success",
          "cancel_url": f"{base}/payment/cancelled"})
    if response.status_code >= 400:
        raise HTTPException(502, "Stripe rejected checkout creation")
    session = response.json()
    store.set_checkout_session(request_id, session["id"])
    return {"status": "checkout_ready", "url": session["url"]}


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(default="")):
    payload = await request.body()
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    if not secret or not verify_stripe_signature(payload, stripe_signature, secret):
        raise HTTPException(400, "invalid Stripe signature")
    event = json.loads(payload)
    if event.get("type") == "checkout.session.completed":
        session = event.get("data", {}).get("object", {})
        store.mark_client_request_paid(session.get("id", ""), session.get("payment_status", "paid"))
    return {"received": True}


@app.get("/payment/success", response_class=HTMLResponse)
def payment_success():
    return "<h1>Payment received</h1><p>Your project is now queued for work.</p>"


@app.get("/payment/cancelled", response_class=HTMLResponse)
def payment_cancelled():
    return "<h1>Payment cancelled</h1><p>No charge was completed.</p>"


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
    <p><a href='/hire'>Client project request form</a></p>
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
    <div class='card'>Delivery reviews<br><b>{activity['delivery_reviews']}</b></div>
    <div class='card'>Deep deliberations<br><b>{activity['deep_deliberations']}</b></div>
    <div class='card'>Practice drills<br><b>{activity['practice']['drills']}</b></div>
    <div class='card'>Verified practice passes<br><b>{activity['practice']['verified_passes']}</b></div>
    <div class='card'>Practice score<br><b>{activity['practice']['average_score']}</b></div></div>
    <table><thead><tr><th>Status</th><th>Score</th><th>Task</th><th>Repository</th><th>Reward</th><th>Expected value</th><th>License</th><th>Decision</th></tr></thead>
    <tbody>{rows or '<tr><td colspan=8>First scan is starting…</td></tr>'}</tbody></table>
    <p><a href='/work-queue'>Review deep-thinking work queue</a> · <a href='/audit'>View complete audit feed</a></p></body></html>"""


@app.get("/work-queue", response_class=HTMLResponse)
def queue_page():
    rows = "".join(f"<tr><td>{escape(x['stage'])}</td><td>{x['deliberation']['confidence']:.0%}</td>"
        f"<td><a href='/opportunities/{x['opportunity_id']}'>{escape(x['title'])}</a></td>"
        f"<td>${x['expected_value']:.2f}</td><td>{escape(', '.join(x['deliberation']['unresolved']) or 'none')}</td></tr>"
        for x in store.work_queue())
    return f"""<!doctype html><html><head><meta name='viewport' content='width=device-width'><title>Work queue</title>
    <style>body{{font-family:system-ui;background:#07111f;color:#eef;padding:24px}}a{{color:#62d9ff}}table{{width:100%;border-collapse:collapse}}td,th{{padding:9px;border-bottom:1px solid #29405e;text-align:left}}</style></head>
    <body><p><a href='/'>← Dashboard</a></p><h1>Deep-thinking work queue</h1><p>Six evidence passes, including verified task-matched skills, must agree before an isolated build is authorized.</p>
    <table><tr><th>Stage</th><th>Confidence</th><th>Opportunity</th><th>Expected value</th><th>Unresolved</th></tr>{rows}</table></body></html>"""


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
