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
- The expanded curriculum verifies authentication, state-machine, observability,
  migration, error-handling, API, database, filesystem, input-validation, and job
  reliability skills. Python and Node proficiency are scored independently.
- Transient sandbox capacity and transport failures are retried three times with
  bounded backoff; permanent validation failures remain immediate hard stops.
- Adaptive practice spends disposable VM runs on unverified skills first, then
  language evidence gaps, mastery confirmation, and spaced refreshes. The next
  five targets and their reasons are visible through `GET /api/skills`.
- Discovery, historical study, and adaptive training run in separate workers, so
  a slow external API cannot stall the other jobs. SQLite uses WAL plus a bounded
  busy timeout for safe concurrent reads and audit writes.

## Hardened isolated workspace

Candidate Python files are sent to a private Railway gateway. Each job runs in a
new Railway Sandbox VM with a fixed execution profile, bounded input/runtime/output,
no production private-network access, and no injected application credentials. The
gateway destroys the VM in a `finally` block after every pass, failure, or timeout.
The gateway itself has no public domain and requires a constant-time checked shared
token from the main service.

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
- `HIGHLEVEL_ACCESS_TOKEN`: private-integration token for the connected HighLevel account.
- `HIGHLEVEL_LOCATION_ID`: HighLevel sub-account/location that owns client records.

## Client intake and payment

Clients submit project requests at `/hire`. Requests remain unpaid until Daniel approves a
specific quote through the authenticated API. Only then can the agent create a Stripe Checkout
Session. Stripe's signed webhook marks the request paid; no project request, quote, or browser
redirect is treated as proof of payment.

HighLevel sync is also approval-gated. `POST /api/client-requests/{id}/sync-highlevel`
copies a reviewed client's name and email into the configured CRM once, records the external
contact ID, and never exposes the access token. `GET /api/integrations` reports connector
readiness using booleans only.

## Client job builder

After Stripe confirms payment, Daniel can queue a bounded Python or Node project through
`POST /api/client-requests/{id}/jobs`. The gate requires task-matched verified skills,
safe text files, explicit acceptance criteria, an OpenAI coding engine, and the private
Railway sandbox. The coding engine returns strict schema-constrained complete files; it
receives no tools or credentials. A separate worker runs the merged project under a fixed
diagnostic profile and stores digests plus isolation evidence. Passing work stops at
`AWAITING_DELIVERY_REVIEW`; it is never submitted or delivered automatically.

## Test

```bash
python -m unittest discover -s tests -v
```

## Current milestone

Version 1 performs real public discovery, license checks, deterministic risk screening, persistent audit logging, bounded learning proposals, and isolated code verification in disposable Railway Sandbox VMs. Public submission remains approval-gated.
