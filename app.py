import os
import threading
import time
from html import escape
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from discovery import GitHubDiscovery
from learner import Learner
from store import Store

DATA_DIR = os.getenv("DATA_DIR", "/data")
os.makedirs(DATA_DIR, exist_ok=True)
store = Store(os.path.join(DATA_DIR, "bounty_builder.db"))
learner = Learner(os.path.join(DATA_DIR, "ranking_weights.json"))
discovery = GitHubDiscovery()
app = FastAPI(title="Bounty Builder Agent", version="1.0.0")


class Promotion(BaseModel):
    challenger: dict
    daniel_approved: bool = False


def scan_once():
    try:
        items = discovery.scan()
        for item in items:
            store.save_opportunity(item)
        proposal = learner.propose(store.outcomes())
        store.audit("scan_completed", {"items": len(items), "learning": proposal})
    except Exception as exc:
        store.audit("scan_failed", {"error": type(exc).__name__, "message": str(exc)[:300]})


def worker():
    while True:
        scan_once()
        time.sleep(int(os.getenv("SCAN_SECONDS", "21600")))


@app.on_event("startup")
def start_worker():
    threading.Thread(target=worker, daemon=True).start()


@app.get("/health")
def health():
    return {"status": "ok", "mode": "approval_gated_real_world", "stats": store.stats()}


@app.post("/scan")
def scan_now():
    scan_once()
    return {"status": "complete", "stats": store.stats()}


@app.post("/learning/promote")
def promote(body: Promotion):
    if not body.daniel_approved:
        raise HTTPException(403, "Daniel's explicit approval is required")
    result = learner.promote(body.challenger, approved=True)
    store.audit("learning_promoted", {"weights": result})
    return {"status": "promoted", "weights": result}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    stats = store.stats()
    rows = "".join(f"""<tr><td>{escape(x['status'])}</td><td>{x['risk_score']}</td>
      <td><a href='{escape(x['url'])}'>{escape(x['title'])}</a></td>
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
    <table><thead><tr><th>Status</th><th>Score</th><th>Task</th><th>Repository</th><th>Reward</th><th>Expected value</th><th>License</th><th>Decision</th></tr></thead>
    <tbody>{rows or '<tr><td colspan=8>First scan is starting…</td></tr>'}</tbody></table></body></html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))

