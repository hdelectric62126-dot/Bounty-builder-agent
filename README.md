# Bounty Builder Agent

An approval-gated revenue opportunity system powered by a six-agent team:

- **Bounty Builder** orchestrates storage, audits, and the dashboard.
- **Opportunity Scout** searches multiple bounded public GitHub queries and deduplicates results.
- **Repository Analyst** checks licensing, activity, language, tests, and issue clarity.
- **Risk & Compliance Agent** applies hard stops and payment-adjusted expected value.
- **Solution Planner** creates a proposal and test checklist only after risk approval.
- **Performance Learner** measures real outcomes and proposes bounded changes; it cannot self-promote.

Every public submission, paid action, and learning promotion remains subject to Daniel's authenticated approval.

The live dashboard now includes per-opportunity detail pages with Repository Analyst,
Risk & Compliance, and Solution Planner records, plus a complete audit feed. Verified
income, costs, and hours can be recorded through the authenticated `POST /outcomes`
endpoint so projected value never gets confused with money actually earned.

A real-world, approval-gated agent that discovers public open-source coding bounties, verifies repository licenses, estimates risk-adjusted value, stores an audit trail, and learns from measured outcomes.

## Safety contract

- Aggressive discovery is allowed; unsafe execution is not.
- Unknown or non-allowlisted licenses are rejected.
- Security exploitation, credential work, malware, phishing, and authentication bypass tasks are rejected.
- No public submission, contract acceptance, spending, or financial action occurs automatically.
- Learning changes are proposals until Daniel explicitly approves promotion.
- No claim of guaranteed profit is made. Realized income is recorded separately from estimated value.

## Run

```bash
python -m pip install -r requirements.txt
DATA_DIR=./data python app.py
```

Optional environment variables:

- `GITHUB_TOKEN`: raises GitHub API rate limits. Use a least-privilege token with public-repository read access only.
- `DATA_DIR`: defaults to `/data` for a Railway volume.
- `SCAN_SECONDS`: defaults to six hours.

## Test

```bash
python -m unittest discover -s tests -v
```

## Current milestone

Version 1 performs real public discovery, license checks, deterministic risk screening, persistent audit logging, and bounded learning proposals. Automated code solving, isolated execution, and public submission remain disabled until a hardened sandbox and explicit approval workflow are added.
