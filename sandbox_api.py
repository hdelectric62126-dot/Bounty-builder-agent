"""Private API for the isolated runner. Do not attach a public domain."""

import os
import secrets
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from sandbox_runner import IsolationUnavailable, SandboxRunner


app = FastAPI(title="Bounty Builder Isolated Workspace", version="1.0.0")
runner = SandboxRunner()


class Job(BaseModel):
    profile: str
    files: dict[str, str] = Field(min_length=1, max_length=150)


def authorize(token):
    expected = os.getenv("SANDBOX_TOKEN", "")
    if not expected or not token or not secrets.compare_digest(expected, token):
        raise HTTPException(403, "sandbox authorization required")


@app.get("/health")
def health():
    ready = runner.capability_check()
    return {"status": "ready" if ready else "isolation_unavailable",
            "execution": "fail_closed", "network_during_jobs": "disabled",
            "credentials_available_to_jobs": False}


@app.post("/jobs")
def run_job(job: Job, x_sandbox_token: str | None = Header(default=None)):
    authorize(x_sandbox_token)
    try:
        return runner.execute(job.files, job.profile).to_dict()
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except IsolationUnavailable as exc:
        raise HTTPException(503, str(exc))
