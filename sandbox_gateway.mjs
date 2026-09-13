import { createServer } from "node:http";
import { createHash, timingSafeEqual } from "node:crypto";
import { Sandbox } from "railway";

const PORT = Number(process.env.PORT || 8080);
const MAX_BODY = 300 * 1024;
const MAX_FILES = 150;
const MAX_OUTPUT = 200 * 1024;
const TIMEOUT_SECONDS = 60;
const MAX_CONCURRENT = Math.max(1, Math.min(Number(process.env.SANDBOX_MAX_CONCURRENT || 2), 4));
const RESULT_CACHE_MS = 30_000;
const PYTHON_SANDBOX = Sandbox.template()
  .withPackages("python3", "nodejs", "npm", "git")
  .workdir("/root/work");

const PROFILES = Object.freeze({
  python_compile: "python3 -m compileall -q .",
  python_unittest: "python3 -m unittest discover -s tests -v",
  trusted_practice: "python3 -m unittest discover -s . -v",
  python_diagnostics: "python3 -m compileall -q . && python3 -m unittest discover -s . -p 'test*.py' -v",
  node_diagnostics: "if [ -f package.json ]; then npm test -- --runInBand; else node --test; fi",
});

let activeJobs = 0;
const waiters = [];
const inFlight = new Map();
const recent = new Map();

async function acquireSlot() {
  if (activeJobs >= MAX_CONCURRENT) await new Promise((resolve) => waiters.push(resolve));
  activeJobs += 1;
}

function releaseSlot() {
  activeJobs -= 1;
  waiters.shift()?.();
}

function jobId(job) {
  return createHash("sha256").update(JSON.stringify(job)).digest("hex").slice(0, 20);
}

function json(res, status, value) {
  const body = JSON.stringify(value);
  res.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(body) });
  res.end(body);
}

function authorized(candidate) {
  const expected = process.env.SANDBOX_TOKEN || "";
  const supplied = typeof candidate === "string" ? candidate : "";
  const a = Buffer.from(expected);
  const b = Buffer.from(supplied);
  return a.length > 0 && a.length === b.length && timingSafeEqual(a, b);
}

function validPath(name) {
  if (typeof name !== "string" || !name || name.startsWith("/") || name.includes("\\")) return false;
  const parts = name.split("/");
  return parts.every((part) => part && part !== ".." && part !== "." && !part.startsWith("."));
}

function validateJob(job) {
  if (!job || typeof job !== "object" || Array.isArray(job)) throw new Error("job must be an object");
  if (!Object.hasOwn(PROFILES, job.profile)) throw new Error("unknown execution profile");
  if (!job.files || typeof job.files !== "object" || Array.isArray(job.files)) throw new Error("files must be an object");
  const entries = Object.entries(job.files);
  if (entries.length < 1 || entries.length > MAX_FILES) throw new Error("invalid file count");
  for (const [name, content] of entries) {
    if (!validPath(name)) throw new Error(`invalid file path: ${name}`);
    if (typeof content !== "string") throw new Error(`file content must be text: ${name}`);
  }
  return { profile: job.profile, files: job.files };
}

async function readBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > MAX_BODY) throw new Error("request body too large");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function cap(value) {
  const text = String(value ?? "");
  return text.length <= MAX_OUTPUT ? text : `${text.slice(0, MAX_OUTPUT)}\n[output truncated]`;
}

async function runJob(job) {
  await acquireSlot();
  const started = Date.now();
  let sandbox;
  let output;
  try {
    sandbox = await Sandbox.create(PYTHON_SANDBOX, {
      idleTimeoutMinutes: 2,
      networkIsolation: "ISOLATED",
      env: {},
    });
    await Promise.all(Object.entries(job.files).map(
      ([name, content]) => sandbox.files.write(`/root/work/${name}`, content),
    ));

    const result = await sandbox.exec(PROFILES[job.profile], {
      cwd: "/root/work",
      timeoutSec: TIMEOUT_SECONDS,
      env: { HOME: "/root", PYTHONDONTWRITEBYTECODE: "1" },
    });
    output = {
      status: result.exitCode === 0 ? "PASSED" : "FAILED",
      profile: job.profile,
      exit_code: result.exitCode,
      duration_seconds: (Date.now() - started) / 1000,
      stdout: cap(result.stdout),
      stderr: cap(result.stderr),
      isolation: "railway_ephemeral_vm",
      network: "public_egress_only",
      credentials_injected: false,
    };
  } finally {
    if (sandbox) await sandbox.destroy();
    releaseSlot();
  }
  return { ...output, workspace_destroyed: true };
}

const server = createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    return json(res, 200, {
      status: process.env.RAILWAY_API_TOKEN && process.env.RAILWAY_ENVIRONMENT_ID ? "ready" : "missing_credentials",
      execution: "railway_ephemeral_vm",
      private_network_access: false,
      credentials_injected: false,
      teardown: "always",
      languages: ["python", "node"],
      max_concurrent: MAX_CONCURRENT,
      duplicate_window_seconds: RESULT_CACHE_MS / 1000,
    });
  }
  if (req.method !== "POST" || req.url !== "/jobs") return json(res, 404, { detail: "not found" });
  if (!authorized(req.headers["x-sandbox-token"])) return json(res, 403, { detail: "sandbox authorization required" });

  try {
    const job = validateJob(await readBody(req));
    const id = jobId(job);
    const cached = recent.get(id);
    if (cached && Date.now() - cached.savedAt < RESULT_CACHE_MS) {
      return json(res, 200, { ...cached.result, job_id: id, duplicate_suppressed: true });
    }
    let pending = inFlight.get(id);
    if (!pending) {
      pending = runJob(job);
      inFlight.set(id, pending);
    }
    const result = await pending;
    inFlight.delete(id);
    recent.set(id, { result, savedAt: Date.now() });
    const expiredBefore = Date.now() - RESULT_CACHE_MS;
    for (const [key, value] of recent) if (value.savedAt < expiredBefore) recent.delete(key);
    return json(res, 200, { ...result, job_id: id, duplicate_suppressed: false });
  } catch (error) {
    const message = error instanceof Error ? error.message : "sandbox execution failed";
    const clientError = /^(job|unknown|files|invalid|file content|request body|Unexpected token)/.test(message);
    return json(res, clientError ? 400 : 503, { detail: message });
  }
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(JSON.stringify({ event: "RAILWAY_SANDBOX_GATEWAY_READY", port: PORT }));
});
