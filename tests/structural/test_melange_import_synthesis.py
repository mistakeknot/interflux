"""Prose-integration and public-hygiene checks for the melange review-import path."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from _import_fixtures import ROOT

ENGINE = ROOT / "skills" / "flux-melange-engine"
SKILL = ENGINE / "SKILL.md"
PHASES = ENGINE / "phases"
REFS = ENGINE / "references"
IMPORT_REF = REFS / "import-review.md"
COMMAND = ROOT / "commands" / "flux-melange.md"

ADVISORY_SNIPPETS = (
    "### P1: Title",
    "- P1: Title",
    "P0–P3",
    "path:line",
    "path:start-end",
    "do not invent one",
    "Omit zero-count breakdown bullets",
    "make its counts exact",
    "VERDICT: PASS WITH NOTES",
    "VERDICT: FAIL",
    "no fences or HTML comments",
)

PROSE_FILES = [
    SKILL,
    PHASES / "assay.md",
    PHASES / "score.md",
    PHASES / "verify.md",
    PHASES / "synthesize.md",
    REFS / "ledger-schema.md",
    REFS / "heat-scoring.md",
    REFS / "fusion.md",
    IMPORT_REF,
    COMMAND,
]

NEW_FILES = [
    ROOT / "scripts" / "import-melange-review.py",
    ROOT / "scripts" / "scan-melange-import.py",
    ROOT / "config" / "flux-melange" / "import-gitleaks.toml",
    IMPORT_REF,
    ROOT / "tests" / "structural" / "_import_fixtures.py",
    ROOT / "tests" / "structural" / "test_melange_review_import.py",
    ROOT / "tests" / "structural" / "test_melange_import_scan.py",
    ROOT / "tests" / "structural" / "test_melange_import_synthesis.py",
    ROOT / "tests" / "structural" / "test_melange_secret_redaction.py",
    ROOT / "hooks" / "redact-melange-write.py",
]

PROTECTED_UNCHANGED = (
    "hooks/hooks.json",
    "hooks/redact-melange-write.sh",
    "scripts/findings-helper.sh",
    "scripts/sanitize_untrusted.py",
    "scripts/_melange_score.py",
    "scripts/ci-checks.sh",
    "skills/flux-melange-engine/workflow/",
    "skills/flux-melange-engine/phases/charter.md",
    "skills/flux-melange-engine/phases/seed.md",
    "skills/flux-melange-engine/phases/retarget.md",
    "skills/flux-melange-engine/phases/probe.md",
)


def text(path: Path) -> str:
    assert path.is_file(), f"missing {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def section(body: str, heading: str) -> str:
    match = re.search(rf"^{re.escape(heading)}.*?(?=^## |\Z)", body, re.DOTALL | re.MULTILINE)
    assert match, f"missing section {heading!r}"
    return match.group(0)


# --------------------------------------------------------------- SKILL.md


def test_step_2_5_sits_between_the_loop_and_synthesis():
    body = text(SKILL)
    headings = [m.group(0) for m in re.finditer(r"^## Step [0-9.]+.*$", body, re.MULTILINE)]
    names = [h.split(":")[0] for h in headings]
    assert "## Step 2.5" in names
    assert names.index("## Step 2") < names.index("## Step 2.5") < names.index("## Step 3")


def test_step_2_5_orders_the_assimilation_after_the_final_score():
    step = section(text(SKILL), "## Step 2.5")
    for phrase in ("should_stop", "import_assimilation", "bundle_ids", "remaining-clamped", "assay", "verify", "link", "synthesi"):
        assert phrase in step, phrase
    positions = [step.index(p) for p in ("should_stop", "assay", "verify", "link", "synthesi")]
    assert positions == sorted(positions)
    assert "import_scan" in step and "import_completion" in step
    assert "references/import-review.md" in step


def test_step_2_5_runs_only_when_a_bundle_exists_and_leaves_ordinary_runs_alone():
    step = section(text(SKILL), "## Step 2.5")
    assert re.search(r"no\s+(?:import\s+)?bundles?", step, re.IGNORECASE)
    assert "--peers=off" in step or "ordinary" in step.lower()


def test_step_2_5_requires_the_applicability_justification():
    step = section(text(SKILL), "## Step 2.5")
    assert "import_applicability" in step
    assert re.search(r"justification", step, re.IGNORECASE)


def test_commands_in_the_skill_use_isolated_python_and_plugin_root():
    body = text(SKILL) + text(IMPORT_REF)
    assert 'python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/import-melange-review.py"' in body or \
        "python3 -I ${CLAUDE_PLUGIN_ROOT}/scripts/import-melange-review.py" in body
    assert "python3 -I" in body and "scan-melange-import.py" in body
    assert "/home/" not in body


# ------------------------------------------------------------ phase files


def test_assay_assimilates_imported_bundles_once_and_keeps_rows_raw():
    body = text(PHASES / "assay.md")
    assert "import" in body.lower() and "fd-external-review" in body
    assert re.search(r"\bonce\b", body)
    assert "raw" in body


def test_verify_checks_only_cited_rows_with_a_clamped_budget():
    body = text(PHASES / "verify.md")
    for phrase in ("cited", "budget-clamped", "sanitized excerpt", "import"):
        assert phrase in body, phrase
    assert re.search(r"max\(0,\s*floor\(remaining\)\)", body)
    assert "no-location" in body or "location-less" in body or "no location" in body


def test_score_has_an_import_only_link_mode_that_skips_the_scorer():
    body = text(PHASES / "score.md")
    assert "import-only" in body
    for excluded in ("convergence", "heat", "fusion", "Taste"):
        assert excluded in body, excluded
    assert "clusters" in body and "attribution" in body


def test_synthesize_reports_unverified_external_findings_in_their_own_section():
    body = text(PHASES / "synthesize.md")
    assert "External review findings (unverified)" in body
    assert "separate" in body and "surfaced" in body


def test_synthesize_pins_surfaced_evaluation_and_requires_surfaced_jsonl():
    body = text(PHASES / "synthesize.md")
    assert "--surfaced" in body
    assert "surfaced.jsonl" in body
    assert re.search(r"requir\w+[^.\n]*surfaced\.jsonl|surfaced\.jsonl[^.\n]*requir", body)


def test_synthesize_runs_the_completion_scan_after_synthesis():
    body = text(PHASES / "synthesize.md")
    assert "scan-melange-import.py" in body
    assert body.index("External review findings (unverified)") < body.index("scan-melange-import.py")
    assert "incomplete" in body


def test_imported_rows_never_reach_upheld_surfaced_scorer_heat_or_taste():
    combined = text(IMPORT_REF)
    for phrase in ("upheld", "surfaced.jsonl", "scorer", "convergence", "heat", "fusion", "Taste"):
        assert phrase in combined, phrase
    assert re.search(r"never\s+(?:reach|enter|become)", combined, re.IGNORECASE)


# ------------------------------------------------------------- references


def test_ledger_schema_documents_imported_row_fields():
    body = text(REFS / "ledger-schema.md")
    for phrase in ("source.import", "taste_kind", "fd-external-review", "import_assimilation", "bundle_ids", "import_scan", "import_applicability"):
        assert phrase in body, phrase
    for phrase in ("assay_dispatches", "link_dispatches", "budget_policy", "budget_before", "budget_after"):
        assert phrase in body, phrase


def test_heat_and_fusion_references_exclude_imports():
    for path in (REFS / "heat-scoring.md", REFS / "fusion.md"):
        body = text(path)
        assert re.search(r"import", body, re.IGNORECASE), path.name
        assert "fd-external-review" in body or "source.import" in body, path.name


def test_import_reference_covers_contract_exit_codes_and_limits():
    body = text(IMPORT_REF)
    for code in ("2", "10", "11", "12", "13", "14", "15", "16", "20", "21", "22", "23", "24"):
        assert re.search(rf"\|\s*{code}\s*\|", body), code
    for phrase in (
        "coordinator-asserted, receipt-consistent (verdict only)",
        "operator_hash_check",
        "target_check",
        "not-performed",
        "receipt-headings-v2",
        "not in receipt",
        "Limitations",
    ):
        assert phrase in body, phrase


def test_import_reference_does_not_overclaim():
    body = text(IMPORT_REF)
    lowered = body.lower()
    assert "receipt-verified" not in lowered and "receipt verified" not in lowered
    for claim in ("live mirror", "parley", "egress", "adaptive"):
        assert claim in lowered, f"limitations should name {claim!r} as out of scope"
    assert re.search(r"not\s+(?:a\s+)?live", lowered)


def test_import_reference_has_the_dispatch_side_format_contract_as_advisory():
    body = text(IMPORT_REF)
    for snippet in ADVISORY_SNIPPETS:
        assert snippet in body, snippet
    assert "advisory" in body.lower()


def test_command_documents_the_import_flags_and_the_format_contract():
    body = text(COMMAND)
    for flag in ("--run-dir", "--receipt", "--report", "--report-sha256"):
        assert flag in body, flag
    for snippet in ADVISORY_SNIPPETS:
        assert snippet in body, snippet
    assert "import-melange-review.py" in body and "${CLAUDE_PLUGIN_ROOT}" in body


# ----------------------------------------------------------- public hygiene

# Patterns are assembled from fragments so this file does not match itself.
_HOSTS = "|".join(["zk" + "lw", "clavain" + r"\.local", "auta" + "rch", "getbb" + r"\.app"])
_BOARDS = "|".join(["SY" + "LV", "MS" + "Q", "IF" + "S", "AL" + "PH"])
HYGIENE_PATTERNS = {
    "home path": re.compile(r"/(?:ho" + "me|Us" + r"ers)/[A-Za-z0-9._-]+/"),
    "internal host": re.compile(rf"\b(?:{_HOSTS})\b", re.IGNORECASE),
    "ruling id": re.compile(r"\b[Qq][0-9]{3,5}\b"),
    "board key": re.compile(rf"\b(?:{_BOARDS})-[0-9]+\b"),
    "thread storage": re.compile("thread-" + "storage|" + r"\.bb-" + "machines|host-" + "data"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}"),
}


def hygiene_targets():
    return [p for p in NEW_FILES + PROSE_FILES if p.is_file()]


def test_new_and_changed_public_files_exist():
    missing = [str(p.relative_to(ROOT)) for p in NEW_FILES if not p.is_file()]
    assert not missing, missing


@pytest.mark.parametrize("label", sorted(HYGIENE_PATTERNS))
def test_public_files_carry_no_internal_identifiers(label):
    pattern = HYGIENE_PATTERNS[label]
    offenders = []
    for path in hygiene_targets():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert not offenders, f"{label}: {offenders[:5]}"


def test_public_files_carry_no_private_task_local_denylist_terms():
    """Terms come from a task-local file named by the environment; never committed or printed."""
    denylist = os.environ.get("MELANGE_IMPORT_PRIVATE_DENYLIST")
    if not denylist:
        pytest.fail("set MELANGE_IMPORT_PRIVATE_DENYLIST to a task-local file of private terms (one per line)")
    terms = [t.strip() for t in Path(denylist).read_text().splitlines() if t.strip() and not t.startswith("#")]
    assert terms, "denylist is empty"
    hits = 0
    for path in hygiene_targets():
        data = path.read_text(encoding="utf-8").lower()
        hits += sum(1 for t in terms if t.lower() in data)
    assert hits == 0, f"{hits} private-term hit(s) in public files"


def test_synthetic_secrets_are_not_committed_as_literals():
    offenders = []
    patterns = [
        re.compile(r"AKIA[A-Z0-9]{16}"),
        re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
        re.compile(r"sk_(?:live|test)_[A-Za-z0-9_-]{16,}"),
        re.compile(r"AIza[A-Za-z0-9_-]{35}"),
        re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ]
    # The baseline redaction test already carries a fake PEM header with no key
    # material; only that file is exempt, and only from the PEM pattern.
    pem_exempt = ROOT / "tests" / "structural" / "test_melange_secret_redaction.py"
    for path in hygiene_targets():
        data = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if path == pem_exempt and "PRIVATE KEY" in pattern.pattern:
                continue
            if pattern.search(data):
                offenders.append(f"{path.relative_to(ROOT)}: {pattern.pattern[:12]}")
    assert not offenders, offenders


# ------------------------------------------------------------- isolation


def changed_paths() -> set[str]:
    def git(*args: str) -> str:
        proc = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout

    base = git("merge-base", "HEAD", "main").strip() or git("rev-parse", "HEAD~0").strip()
    names = set(git("diff", "--name-only", base).splitlines())
    names |= {line[3:] for line in git("status", "--porcelain").splitlines()}
    return {n.strip() for n in names if n.strip()}


@pytest.mark.parametrize("protected", PROTECTED_UNCHANGED)
def test_protected_paths_are_unchanged(protected):
    touched = [p for p in changed_paths() if p == protected or (protected.endswith("/") and p.startswith(protected))]
    assert not touched, touched


def test_no_deferred_path_a_artifacts_are_touched():
    touched = [p for p in changed_paths() if re.search(r"(?:^|/)(?:spike|q57ak)", p)]
    assert not touched, touched


def test_workflow_entrypoint_still_carries_its_unguarded_write_marker():
    body = text(ENGINE / "workflow" / "melange-workflow.js")
    assert "WORKFLOW_UNGUARDED_WRITE" in body
