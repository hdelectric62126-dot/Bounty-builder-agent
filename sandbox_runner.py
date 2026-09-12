"""Fail-closed disposable runner for untrusted candidate code."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path, PurePosixPath
import resource
import shutil
import subprocess
import tempfile
import time


MAX_FILES = 150
MAX_TOTAL_BYTES = 2_000_000
MAX_OUTPUT_BYTES = 200_000
PROFILES = {
    "python_compile": ("python", "-I", "-m", "compileall", "-q", "/work"),
    "python_unittest": ("python", "-I", "-m", "unittest", "discover", "-s", "/work", "-v"),
}


@dataclass(frozen=True)
class SandboxResult:
    status: str
    profile: str
    exit_code: int | None
    duration_seconds: float
    stdout: str
    stderr: str
    network: str = "disabled"
    workspace: str = "destroyed"

    def to_dict(self):
        return asdict(self)


class IsolationUnavailable(RuntimeError):
    pass


def validate_files(files: dict[str, str]) -> dict[str, str]:
    if not files or len(files) > MAX_FILES:
        raise ValueError("job must contain between 1 and 150 files")
    total = 0
    safe = {}
    for raw_path, content in files.items():
        path = PurePosixPath(str(raw_path).replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("unsafe file path")
        if any(part.startswith(".") for part in path.parts):
            raise ValueError("hidden files are not allowed")
        encoded = str(content).encode("utf-8")
        total += len(encoded)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("job exceeds two megabytes")
        safe[str(path)] = str(content)
    return safe


class SandboxRunner:
    def __init__(self, bubblewrap="/usr/bin/bwrap", timeout_seconds=30):
        self.bubblewrap = bubblewrap
        self.timeout_seconds = max(1, min(timeout_seconds, 60))

    def capability_check(self) -> bool:
        if not Path(self.bubblewrap).is_file():
            return False
        command = [self.bubblewrap, "--unshare-all", "--new-session", "--die-with-parent",
                   "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
                   "--proc", "/proc", "--dev", "/dev", "/bin/true"]
        try:
            return subprocess.run(command, capture_output=True, timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def execute(self, files: dict[str, str], profile: str) -> SandboxResult:
        if profile not in PROFILES:
            raise ValueError("unsupported execution profile")
        safe = validate_files(files)
        if not self.capability_check():
            raise IsolationUnavailable("kernel isolation unavailable; execution refused")
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="bounty-job-") as directory:
            root = Path(directory)
            for relative, content in safe.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            os.chmod(root, 0o755)
            command = [self.bubblewrap, "--unshare-all", "--new-session", "--die-with-parent",
                "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
                "--ro-bind", directory, "/work", "--tmpfs", "/tmp",
                "--proc", "/proc", "--dev", "/dev", "--chdir", "/work",
                "--clearenv", "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
                *PROFILES[profile]]
            try:
                process = subprocess.run(command, capture_output=True, text=True,
                    timeout=self.timeout_seconds, preexec_fn=_limits)
                status = "PASSED" if process.returncode == 0 else "FAILED"
                return SandboxResult(status, profile, process.returncode,
                    round(time.monotonic() - started, 3),
                    process.stdout[:MAX_OUTPUT_BYTES], process.stderr[:MAX_OUTPUT_BYTES])
            except subprocess.TimeoutExpired as exc:
                return SandboxResult("TIMEOUT", profile, None,
                    round(time.monotonic() - started, 3),
                    (exc.stdout or "")[:MAX_OUTPUT_BYTES], (exc.stderr or "")[:MAX_OUTPUT_BYTES])


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))
