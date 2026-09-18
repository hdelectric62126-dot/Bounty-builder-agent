"""Compact performance dashboard for Bounty Builder.

Pure aggregation only: no external actions, policy changes, or autonomous promotion.
"""

from __future__ import annotations
from collections import Counter


def build_performance_snapshot(store) -> dict:
    stats = store.stats()
    opportunities = store.list_opportunities(500)
    jobs = store.list_client_jobs(500)
    outcomes = store.outcomes()
    audits = store.recent_audit(500)

    job_status = Counter(str(row.get("status") or "UNKNOWN") for row in jobs)
    net_income = sum(float(row.get("income") or 0) - float(row.get("cost") or 0)
                     for row in outcomes)
    paid_outcomes = sum(1 for row in outcomes if float(row.get("income") or 0) > 0)
    hours = sum(float(row.get("hours") or 0) for row in outcomes)

    return {
        "opportunities": {
            "found": int(stats.get("found") or 0),
            "approved": int(stats.get("approved") or 0),
            "rejected": int(stats.get("rejected") or 0),
            "expected_value": round(float(stats.get("expected_value") or 0), 2),
        },
        "client_jobs": {
            "total": len(jobs),
            "by_status": dict(sorted(job_status.items())),
        },
        "outcomes": {
            "recorded": len(outcomes),
            "paid": paid_outcomes,
            "net_income": round(net_income, 2),
            "hours": round(hours, 2),
            "net_income_per_hour": round(net_income / hours, 2) if hours else 0.0,
        },
        "learning": stats.get("agent_activity", {}),
        "audit": {
            "events_sampled": len(audits),
            "latest_event": audits[0]["event"] if audits else None,
            "latest_at": audits[0]["created_at"] if audits else None,
        },
        "storage": {
            "opportunity_rows_sampled": len(opportunities),
            "persistent": True,
        },
    }
