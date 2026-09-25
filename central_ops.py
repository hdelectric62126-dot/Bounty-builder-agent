"""Central Operations Dashboard for Daniel's agent stack.

Read-only control plane: aggregates health/metrics without exposing credentials or
adding write controls to downstream systems. Local tools report signed heartbeats.
"""

import json
import os
import secrets
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _status(ok, degraded=False):
    return "healthy" if ok and not degraded else ("warning" if ok else "offline")


def build_ops_router(store, data_dir, database_migration):
    router = APIRouter()
    heartbeat_path = Path(data_dir) / "central_ops_heartbeats.json"

    def require_admin(token):
        expected = os.getenv("ADMIN_TOKEN", "")
        if not expected or not token or not secrets.compare_digest(expected, token):
            raise HTTPException(403, "operations dashboard authentication required")

    def read_heartbeats():
        try:
            data = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def write_heartbeats(data):
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = heartbeat_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        tmp.replace(heartbeat_path)

    def heartbeat_state(name, heartbeats):
        row = heartbeats.get(name)
        if not isinstance(row, dict):
            return {"status": "offline", "detail": "No heartbeat received", "last_seen": None}
        try:
            age = max(0.0, time.time() - float(row.get("epoch", 0)))
        except (TypeError, ValueError):
            age = 999999
        if age <= 120:
            state = "healthy"
        elif age <= 600:
            state = "warning"
        else:
            state = "offline"
        return {
            "status": state,
            "detail": row.get("detail") or "Heartbeat received",
            "last_seen": row.get("timestamp"),
            "age_seconds": round(age, 1),
            "meta": row.get("meta") if isinstance(row.get("meta"), dict) else {},
        }

    def get_json(url, headers=None, timeout=4):
        try:
            response = requests.get(url, headers=headers or {}, timeout=timeout)
            payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            return response.status_code, payload
        except (requests.RequestException, ValueError):
            return None, {}

    def bounty_summary():
        try:
            stats = store.stats()
            disk = shutil.disk_usage(data_dir)
            writable = os.access(data_dir, os.W_OK)
            return {
                "status": "healthy",
                "detail": "Bounty Builder API and data store available",
                "metrics": {
                    "found": int(stats.get("found") or 0),
                    "approved": int(stats.get("approved") or 0),
                    "rejected": int(stats.get("rejected") or 0),
                    "realized_income": float(stats.get("realized_income") or 0),
                    "expected_value": float(stats.get("expected_value") or 0),
                },
                "storage": {
                    "writable": writable,
                    "free_gb": round(disk.free / (1024**3), 2),
                    "database": "postgres" if getattr(store, "postgres", False) else "sqlite",
                    "migration": database_migration,
                },
                "links": {"open": "/", "health": "/health"},
            }
        except Exception as exc:
            return {"status": "offline", "detail": f"Bounty summary unavailable: {type(exc).__name__}", "metrics": {}}

    def sandbox_summary():
        base = os.getenv("SANDBOX_URL", "").rstrip("/")
        token = os.getenv("SANDBOX_TOKEN", "")
        if not base:
            return {"status": "offline", "detail": "Sandbox URL not configured"}
        code, payload = get_json(
            base + "/health",
            headers={"X-Sandbox-Token": token} if token else {},
        )
        ok = code == 200
        return {
            "status": _status(ok, ok and payload.get("status") not in ("ready", "ok")),
            "detail": payload.get("status") if ok else "Isolated workspace unreachable",
            "metrics": payload,
        }

    def alpaca_summary():
        base = os.getenv(
            "OPS_ALPACA_URL",
            "https://alpaca-trading-agent-86-production.up.railway.app",
        ).rstrip("/")
        health_code, health = get_json(base + "/health")
        token = os.getenv("OPS_READ_TOKEN", "")
        dashboard = {}
        dash_code = None
        if token:
            dash_code, dashboard = get_json(
                base + "/api/dashboard?days=7",
                headers={"Authorization": "Bearer " + token},
            )
        ok = health_code == 200
        metrics = dashboard.get("metrics", {}) if dash_code == 200 else {}
        runtime = dashboard.get("runtime") or {}
        guardian = dashboard.get("guardian") or []
        guardian_blocked = any(int(row.get("failures") or 0) > 0 for row in guardian if isinstance(row, dict))
        return {
            "status": _status(ok and dash_code == 200, guardian_blocked),
            "detail": (
                "Paper trader connected and read-only telemetry authenticated"
                if ok and dash_code == 200
                else ("Health reachable; telemetry token not connected" if ok else "Alpaca agent unreachable")
            ),
            "metrics": {
                "mode": dashboard.get("mode"),
                "phase": runtime.get("phase"),
                "realized_pnl_7d": metrics.get("realized_pnl"),
                "closed_trades_7d": metrics.get("closed_trades"),
                "win_rate_7d": metrics.get("win_rate"),
                "drawdown_7d": metrics.get("drawdown"),
                "pending_orders": metrics.get("pending_orders"),
                "last_cycle": dashboard.get("last_cycle"),
                "guardian_issues": sum(1 for row in guardian if int(row.get("failures") or 0) > 0) if guardian else 0,
            },
            "links": {"open": base, "health": base + "/health"},
        }

    def optional_remote(label, env_name, default_url=None):
        base = (os.getenv(env_name, "") or (default_url or "")).rstrip("/")
        if not base:
            return {"status": "offline", "detail": f"{label} endpoint not connected", "metrics": {}}
        code, payload = get_json(base + "/health")
        return {
            "status": "healthy" if code == 200 else "offline",
            "detail": "Health endpoint connected" if code == 200 else f"{label} health check failed",
            "metrics": payload if code == 200 else {},
            "links": {"open": base, "health": base + "/health"},
        }

    @router.get("/ops", response_class=HTMLResponse)
    def ops_page():
        return HTMLResponse(DASHBOARD_HTML)

    @router.get("/ops/api/summary")
    def ops_summary(x_admin_token: str | None = Header(default=None)):
        require_admin(x_admin_token)
        heartbeats = read_heartbeats()
        systems = {
            "bounty": bounty_summary(),
            "workspace": sandbox_summary(),
            "alpaca": alpaca_summary(),
            "business1099": optional_remote("1099 Business OS", "OPS_1099_URL"),
            "localmind": heartbeat_state("localmind", heartbeats),
            "license_navigator": heartbeat_state("license-navigator", heartbeats),
            "license_scraper": heartbeat_state("license-scraper", heartbeats),
        }
        alerts = []
        for key, item in systems.items():
            if item.get("status") != "healthy":
                alerts.append({
                    "system": key,
                    "severity": "warning" if item.get("status") == "warning" else "critical",
                    "message": item.get("detail", "System requires attention"),
                })
        return {
            "generated_at": _utc(),
            "read_only": True,
            "systems": systems,
            "alerts": alerts,
            "counts": {
                "healthy": sum(v.get("status") == "healthy" for v in systems.values()),
                "warning": sum(v.get("status") == "warning" for v in systems.values()),
                "offline": sum(v.get("status") == "offline" for v in systems.values()),
            },
        }

    @router.post("/ops/api/heartbeat/{component}")
    async def heartbeat(component: str, request: Request, x_ops_token: str | None = Header(default=None)):
        expected = os.getenv("OPS_HEARTBEAT_TOKEN", "")
        if not expected or not x_ops_token or not secrets.compare_digest(expected, x_ops_token):
            raise HTTPException(403, "heartbeat authentication required")
        allowed = {"localmind", "license-navigator", "license-scraper", "1099-local"}
        if component not in allowed:
            raise HTTPException(404, "unknown component")
        try:
            body = await request.json()
        except Exception:
            body = {}
        now = datetime.now(timezone.utc)
        data = read_heartbeats()
        data[component] = {
            "epoch": now.timestamp(),
            "timestamp": now.isoformat(),
            "detail": str(body.get("detail") or "Heartbeat received")[:240],
            "meta": body.get("meta") if isinstance(body.get("meta"), dict) else {},
        }
        write_heartbeats(data)
        return {"ok": True, "component": component, "received_at": now.isoformat()}

    return router


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Central Operations</title>
<style>
:root{--bg:#081018;--panel:#0e1823;--panel2:#111f2c;--line:#24384a;--text:#e9f1f7;--muted:#8fa3b5;--good:#44d18b;--warn:#ffbd59;--bad:#ff6464;--accent:#70a7ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% -10%,#15304b 0,#081018 35%);color:var(--text);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:1500px;margin:auto;padding:24px}.top{display:flex;gap:18px;align-items:center;justify-content:space-between;margin-bottom:20px}.brand h1{margin:0;font-size:26px;letter-spacing:-.5px}.brand p{margin:4px 0 0;color:var(--muted)}
.toolbar{display:flex;gap:10px;align-items:center}.btn,input{background:#0d1823;border:1px solid var(--line);color:var(--text);border-radius:9px;padding:10px 12px}.btn{cursor:pointer;font-weight:700}.btn:hover{border-color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.card,.section{background:linear-gradient(180deg,rgba(17,31,44,.96),rgba(11,21,31,.96));border:1px solid var(--line);border-radius:14px;box-shadow:0 14px 40px #0004}.card{padding:17px}.k{font-size:12px;text-transform:uppercase;letter-spacing:.11em;color:var(--muted)}.v{font-size:28px;font-weight:800;margin-top:4px}
.section{margin-top:14px;padding:18px}.section h2{margin:0 0 14px;font-size:16px}.systems{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.system{background:#0b1620;border:1px solid #203445;border-radius:12px;padding:15px}.system-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.system h3{margin:0;font-size:15px}.status{font-size:11px;font-weight:800;text-transform:uppercase;padding:5px 8px;border-radius:999px}.healthy{background:#143d2d;color:#76edaf}.warning{background:#483819;color:#ffd27c}.offline{background:#4a2227;color:#ff9696}.detail{color:var(--muted);margin:8px 0 12px;min-height:20px}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.metric{background:#0e1c28;border-radius:8px;padding:9px}.metric b{display:block;font-size:15px;overflow:hidden;text-overflow:ellipsis}.metric span{color:var(--muted);font-size:11px}.links a{color:var(--accent);text-decoration:none;margin-right:12px;font-size:12px}
.alert{padding:10px 12px;border-left:3px solid var(--warn);background:#291f12;margin:8px 0;border-radius:6px}.alert.critical{border-color:var(--bad);background:#2c171b}.empty{color:var(--muted);padding:12px 0}.auth{max-width:420px;margin:100px auto;background:var(--panel);padding:24px;border:1px solid var(--line);border-radius:14px}.auth h2{margin-top:0}.auth input{width:100%;margin:10px 0}.hidden{display:none}
.footer{color:var(--muted);text-align:right;margin:14px 2px;font-size:11px}@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}.systems{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}}@media(max-width:520px){.wrap{padding:14px}.top{align-items:flex-start;flex-direction:column}.grid{grid-template-columns:1fr 1fr}.v{font-size:23px}}
</style></head><body>
<div id="auth" class="auth"><h2>Central Operations</h2><p style="color:var(--muted)">Enter the existing Bounty Builder admin token. It stays in this browser.</p><input id="token" type="password" autocomplete="off" placeholder="Admin token"><button class="btn" onclick="login()">Open Operations</button><p id="autherr" style="color:var(--bad)"></p></div>
<div id="app" class="wrap hidden">
<div class="top"><div class="brand"><h1>Central Operations</h1><p>One read-only control plane for the agent stack</p></div><div class="toolbar"><span id="stamp" style="color:var(--muted)"></span><button class="btn" onclick="load()">Refresh</button><button class="btn" onclick="logout()">Lock</button></div></div>
<div class="grid"><div class="card"><div class="k">Healthy</div><div class="v" id="healthy">—</div></div><div class="card"><div class="k">Warning</div><div class="v" id="warning">—</div></div><div class="card"><div class="k">Offline / Not Connected</div><div class="v" id="offline">—</div></div><div class="card"><div class="k">Control Plane</div><div class="v" style="font-size:18px;color:var(--good)">READ ONLY</div></div></div>
<div class="section"><h2>System Fleet</h2><div id="systems" class="systems"></div></div>
<div class="section"><h2>Attention Queue</h2><div id="alerts"></div></div>
<div class="footer">Auto-refresh 15s • No downstream write controls • Secrets never returned to browser</div>
</div>
<script>
const labels={bounty:"Bounty Builder",workspace:"Isolated Build Workspace",alpaca:"Alpaca Trading Agent",business1099:"1099 Business OS",localmind:"LocalMind",license_navigator:"License Navigator",license_scraper:"License Scraper"};
function esc(v){return String(v??"—").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]))}
function login(){localStorage.setItem("opsAdminToken",document.getElementById("token").value);load()}
function logout(){localStorage.removeItem("opsAdminToken");location.reload()}
function pretty(k){return k.replaceAll("_"," ").replace(/\b\w/g,m=>m.toUpperCase())}
async function load(){
 const token=localStorage.getItem("opsAdminToken")||"";
 if(!token){return}
 let r; try{r=await fetch("/ops/api/summary",{headers:{"X-Admin-Token":token},cache:"no-store"})}catch(e){document.getElementById("autherr").textContent="Dashboard request failed";return}
 if(r.status===403){document.getElementById("auth").classList.remove("hidden");document.getElementById("app").classList.add("hidden");document.getElementById("autherr").textContent="Invalid admin token";return}
 const d=await r.json();document.getElementById("auth").classList.add("hidden");document.getElementById("app").classList.remove("hidden");
 ["healthy","warning","offline"].forEach(k=>document.getElementById(k).textContent=d.counts[k]??0);
 document.getElementById("stamp").textContent=new Date(d.generated_at).toLocaleTimeString();
 const box=document.getElementById("systems");box.innerHTML="";
 for(const [key,s] of Object.entries(d.systems)){
   const metrics=Object.entries(s.metrics||{}).filter(([k,v])=>v!==null&&v!==undefined&&typeof v!=="object").slice(0,9).map(([k,v])=>`<div class="metric"><b>${esc(typeof v==="number"?Math.round(v*100)/100:v)}</b><span>${esc(pretty(k))}</span></div>`).join("");
   const links=Object.entries(s.links||{}).map(([k,v])=>`<a href="${esc(v)}" target="_blank" rel="noopener">${esc(pretty(k))} ↗</a>`).join("");
   box.innerHTML+=`<div class="system"><div class="system-head"><h3>${esc(labels[key]||pretty(key))}</h3><span class="status ${esc(s.status)}">${esc(s.status)}</span></div><div class="detail">${esc(s.detail)}</div><div class="metrics">${metrics||'<div class="empty">No live metrics</div>'}</div><div class="links">${links}</div></div>`;
 }
 const alerts=document.getElementById("alerts");alerts.innerHTML=d.alerts.length?d.alerts.map(a=>`<div class="alert ${esc(a.severity)}"><b>${esc(labels[a.system]||pretty(a.system))}</b> — ${esc(a.message)}</div>`).join(""):'<div class="empty">No systems require attention.</div>';
}
document.getElementById("token").addEventListener("keydown",e=>{if(e.key==="Enter")login()});if(localStorage.getItem("opsAdminToken"))load();setInterval(()=>{if(!document.getElementById("app").classList.contains("hidden"))load()},15000);
</script></body></html>"""
