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

## Experience and delivery intelligence

- A rolling twenty-year collector samples closed public software work one year at a
  time and stores derived metadata such as category, cycle time, discussion volume,
  and completion reason. It does not copy source code or issue bodies.
- The delivery reviewer requires evidence for tests, linting, security review, and
  acceptance criteria. Failed or missing checks block delivery.
- Even a fully passing review stops at `AWAITING_DANIEL_APPROVAL`; client handoff is
  never automatic.
- When no bounty is approved, the coding gym runs bounded fail-then-fix drills in
  the isolated workspace. It records test evidence, scores, and lessons—not source
  code—and never presents practice as paid client experience.

## Hardened isolated workspace

Candidate Python files can be sent to a separate private Railway service. Each job
runs in a disposable Bubblewrap namespace with networking disabled, a cleared
environment, read-only system files, fixed execution profiles, and limits on CPU,
memory, processes, files, runtime, and output. The service has no public domain and
receives no trading, GitHub, client, or deployment credentials. If kernel isolation
is unavailable, execution fails closed.

## Deep deliberation queue

Approved opportunities pass through five recorded reviews: requirements,
repository feasibility, financial/compliance risk, implementation critique, and
historical calibration. Only unanimous evidence places work in Daniel's approval
queue; incomplete cases remain on hold instead of being rushed.

A real-world, approval-gated agent that discovers public open-source coding bounties, verifies repository licenses, estimates risk-adjusted value, stores an audit trail, and learns from measured outcomes.

## Safety contract

- Aggressive discovery is allowed; unsafe execution is not.
- Unknown or non-allowlisted licenses are rejected.
- Already-assigned issues and issues with more than two linked competing pull requests are rejected.
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
- `STRIPE_SECRET_KEY`: Stripe restricted or secret key used to create approved Checkout Sessions.
- `STRIPE_WEBHOOK_SECRET`: signing secret for `POST /stripe/webhook`.

## Client intake and payment

Clients submit project requests at `/hire`. Requests remain unpaid until Daniel approves a
specific quote through the authenticated API. Only then can the agent create a Stripe Checkout
Session. Stripe's signed webhook marks the request paid; no project request, quote, or browser
redirect is treated as proof of payment.

## Test

```bash
python -m unittest discover -s tests -v
```

## Current milestone

Version 1 performs real public discovery, license checks, deterministic risk screening, persistent audit logging, and bounded learning proposals. Automated code solving, isolated execution, and public submission remain disabled until a hardened sandbox and explicit approval workflow are added.
