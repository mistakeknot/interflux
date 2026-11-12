"""Shared synthetic fixtures for the melange review-import tests.

Every receipt, report and credential-shaped string here is synthetic. Secret
shapes are assembled from fragments so no scannable literal is committed.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
IMPORT_SCRIPT = SCRIPTS / "import-melange-review.py"
SCAN_SCRIPT = SCRIPTS / "scan-melange-import.py"
HELPER = SCRIPTS / "findings-helper.sh"
HOOK = ROOT / "hooks" / "redact-melange-write.py"
GITLEAKS_CONFIG = ROOT / "config" / "flux-melange" / "import-gitleaks.toml"
MARKER = "[REDACTED SECRET]"

# Credential-shaped synthetic strings (fragments joined at runtime).
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
SLACK_TOKEN = "xox" + "b-123456789012-abcdefghijkl"
STRIPE_KEY = "sk_" + "live_" + "A1b2C3d4E5f6G7h8I9j0"
GOOGLE_KEY = "AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p67"
JWT = "ey" + "J" + "hbGci." + "abcdefgh12." + "ABCDEFGH12"
LEGACY_NPM = "npm_" + "E" * 36
FIVE_FORMATS = {
    "aws": AWS_KEY,
    "slack": SLACK_TOKEN,
    "stripe": STRIPE_KEY,
    "google": GOOGLE_KEY,
    "jwt": JWT,
}
PEM = "-----BEGIN PRIVATE " + "KEY-----\nQUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=\n-----END PRIVATE " + "KEY-----"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    return module


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def bundle_id(receipt_sha: str, report_sha: str) -> str:
    return sha256_bytes(b"melange-import-v3\0" + receipt_sha.encode() + b"\0" + report_sha.encode())


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


@dataclass
class Ctx:
    tmp: Path
    project: Path
    run: Path
    inputs: Path

    @property
    def imports(self) -> Path:
        return self.run / "imports"

    @property
    def staging(self) -> Path:
        return self.project / ".clavain" / "melange-import-staging"


def make_project(tmp_path: Path, *, gitignore: bool = True, name: str = "proj") -> Ctx:
    project = tmp_path / name
    run = project / "docs" / "research" / "flux-melange" / "example-run"
    run.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(project)], check=True, capture_output=True)
    if gitignore:
        (project / ".gitignore").write_text(".clavain/\n")
    (run / "melange-state.json").write_text(json.dumps({"round": 3, "budget": {"remaining": 5}}) + "\n")
    (run / "heat-ledger.jsonl").write_text("")
    inputs = tmp_path / f"{name}-inputs"
    inputs.mkdir()
    return Ctx(tmp_path, project, run, inputs)


DEFAULT_RECEIPT = {
    "schema_version": 1,
    "kind": "cross-lab-review-receipt",
    "role": "cross-lab-review",
    "repo": "example-org/example-repo",
    "repo_id": "R_kgDOExample123",
    "pr": 42,
    "head_sha": "1" * 40,
    "head_tree": "2" * 40,
    "base_sha": "3" * 40,
    "expected_merge_tree": "4" * 40,
    "diff_sha256": "5" * 64,
    "policy_hash": "6" * 64,
    "diff_stat": " 1 file changed, 2 insertions(+)",
    "producer_identity": "claude/opus-5-5",
    "reviewer_identity": "codex/gpt-6-astra",
    "validator_relationship": None,
    "dispatch_id": "dispatch-1",
    "attempt_id": "attempt-1",
    "verdict": "PASS WITH NOTES",
    "created_at": "2026-11-11T10:00:00.123456789Z",
    "sequence": 1,
}


def make_receipt(**over) -> dict:
    receipt = copy.deepcopy(DEFAULT_RECEIPT)
    receipt.update(over)
    return receipt


def receipt_basename(receipt: dict) -> str:
    seq = receipt.get("sequence")
    suffix = "" if seq == 1 else f".{seq}"
    return f"{receipt.get('pr')}-{receipt.get('head_sha')}{suffix}.json"


def write_receipt(directory: Path, receipt: dict | None = None, *, raw: str | None = None, name: str | None = None) -> Path:
    receipt = receipt if receipt is not None else make_receipt()
    path = directory / (name or receipt_basename(receipt))
    path.write_text(raw if raw is not None else json.dumps(receipt, indent=2) + "\n")
    path.chmod(0o600)
    return path


def make_report(*lines: str, verdict: str = "PASS WITH NOTES") -> str:
    return "\n".join(lines) + f"\n\nVERDICT: {verdict}\n"


DEFAULT_REPORT = make_report(
    "## Review",
    "",
    "### P1: Unchecked index in loader",
    "src/loader.py:42 reads past the end of the buffer.",
    "More evidence here.",
    "",
    "- P2: Missing docs",
    "Cite docs/readme.md:10-12 for the gap.",
    "",
    "FINDINGS: 2 (P0: 0, P1: 1, P2: 1)",
)


def write_report(directory: Path, text: str = DEFAULT_REPORT, name: str = "report.md") -> tuple[Path, str]:
    path = directory / name
    path.write_text(text, encoding="utf-8", newline="")
    return path, sha256_file(path)


def stage_inputs(ctx: Ctx, *, receipt: dict | None = None, report: str = DEFAULT_REPORT, **receipt_over):
    receipt = receipt if receipt is not None else make_receipt(**receipt_over)
    receipt_path = write_receipt(ctx.inputs, receipt)
    report_path, report_sha = write_report(ctx.inputs, report)
    return receipt_path, report_path, report_sha


def import_argv(ctx: Ctx, receipt: Path | None, report: Path | None, sha: str | None) -> list[str]:
    argv = ["--run-dir", str(ctx.run)]
    if receipt is not None:
        argv += ["--receipt", str(receipt)]
    if report is not None:
        argv += ["--report", str(report)]
    if sha is not None:
        argv += ["--report-sha256", sha]
    return argv


def clean_env(extra: dict | None = None) -> dict:
    path = os.environ.get("PATH", "/usr/bin:/bin")
    local_bin = Path(os.environ.get("HOME", "/tmp")) / ".local" / "bin"
    if local_bin.is_dir() and str(local_bin) not in path.split(":"):
        path = f"{path}:{local_bin}"
    env = {"PATH": path, "HOME": os.environ.get("HOME", "/tmp"), "LANG": "C.UTF-8"}
    env.update(extra or {})
    return env


def run_script(script: Path, argv: list[str], *, cwd: Path | None = None, env: dict | None = None):
    return subprocess.run(
        [sys.executable, "-I", str(script), *argv],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=env or clean_env(),
        timeout=180,
    )


def do_import(ctx: Ctx, *, receipt: dict | None = None, report: str = DEFAULT_REPORT, sha: str | None = None, **receipt_over):
    receipt_path, report_path, report_sha = stage_inputs(ctx, receipt=receipt, report=report, **receipt_over)
    proc = run_script(IMPORT_SCRIPT, import_argv(ctx, receipt_path, report_path, sha or report_sha), cwd=ctx.tmp)
    return proc, receipt_path, report_path, report_sha


def published_bundle(ctx: Ctx) -> Path:
    bundles = sorted(p for p in ctx.imports.iterdir() if p.is_dir()) if ctx.imports.exists() else []
    assert len(bundles) == 1, f"expected one bundle, found {bundles}"
    return bundles[0]


def tree_snapshot(path: Path) -> dict[str, bytes]:
    return {str(p.relative_to(path)): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}
