"""Tests for scripts/verify-synthesis-grounding.sh (issue #10, finding C-5).

The synthesis subagent is the sole reader of agent prose and the host never opens
agent output files, so an invented or blended finding in findings.json would reach
the user undetected. verify-synthesis-grounding.sh asserts every (severity, id) pair
in findings.json is backed by a real agent's machine-parseable Findings Index entry.
"""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "verify-synthesis-grounding.sh"

RUN = "RUN-UUID-1"


def _agent_file(d: Path, name: str, index_lines: list[str], run_uuid: str = RUN) -> None:
    """Write an agent output .md file with a quire-mark and a Findings Index block."""
    body = [f"<!-- run-uuid: {run_uuid} -->", "### Findings Index", *index_lines, "Verdict: risky"]
    (d / f"{name}.md").write_text("\n".join(body) + "\n")


def _findings_json(d: Path, findings: list[dict]) -> None:
    (d / "findings.json").write_text(json.dumps({"findings": findings, "verdict": "risky"}))


def _run(output_dir: Path, *args, run_uuid: str = RUN):
    env_prefix = {"FLUX_RUN_UUID": run_uuid} if run_uuid is not None else {}
    import os

    env = {**os.environ, **env_prefix}
    return subprocess.run(
        ["bash", str(SCRIPT), str(output_dir), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def test_script_exists_and_executable():
    assert SCRIPT.exists(), f"{SCRIPT} missing"


class TestFaithfulSynthesis:
    """A findings.json whose every finding maps to a real index entry must pass."""

    def test_all_grounded_passes(self, tmp_path):
        _agent_file(tmp_path, "fd-safety", ['- P0 | P0-1 | "Auth" | Token leak',
                                            '- P1 | P1-1 | "Cache" | Stale entry'])
        _agent_file(tmp_path, "fd-quality", ['- P2 | P2-1 | "Style" | Naming'])
        _findings_json(tmp_path, [
            {"id": "P0-1", "severity": "P0"},
            {"id": "P1-1", "severity": "P1"},
            {"id": "P2-1", "severity": "P2"},
        ])
        r = _run(tmp_path)
        assert r.returncode == 0, r.stderr
        assert "OK" in r.stdout

    def test_zero_findings_is_vacuously_ok(self, tmp_path):
        _agent_file(tmp_path, "fd-safety", [])
        _findings_json(tmp_path, [])
        r = _run(tmp_path)
        assert r.returncode == 0, r.stderr


class TestInventedFinding:
    """A finding NOT present in any agent index ('invented coastline') must be flagged."""

    def test_invented_p0_fails(self, tmp_path):
        _agent_file(tmp_path, "fd-safety", ['- P0 | P0-1 | "Auth" | Token leak'])
        _findings_json(tmp_path, [
            {"id": "P0-1", "severity": "P0"},
            {"id": "P0-99", "severity": "P0"},  # invented
        ])
        r = _run(tmp_path)
        assert r.returncode == 3, f"expected violation exit 3, got {r.returncode}: {r.stdout}{r.stderr}"
        assert "P0-99" in r.stderr
        assert "VIOLATION" in r.stderr

    def test_invented_p1_fails(self, tmp_path):
        _agent_file(tmp_path, "fd-safety", ['- P1 | P1-1 | "Cache" | Stale entry'])
        _findings_json(tmp_path, [{"id": "P1-7", "severity": "P1"}])  # invented
        r = _run(tmp_path)
        assert r.returncode == 3, r.stdout + r.stderr

    def test_invented_p2_only_warns_but_passes(self, tmp_path):
        """P2+ ungrounded is below the blocking threshold by default → warn, exit 0."""
        _agent_file(tmp_path, "fd-quality", ['- P2 | P2-1 | "Style" | Naming'])
        _findings_json(tmp_path, [
            {"id": "P2-1", "severity": "P2"},
            {"id": "P2-99", "severity": "P2"},  # invented but only P2
        ])
        r = _run(tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "warn" in r.stderr and "P2-99" in r.stderr

    def test_invented_p2_fails_under_strict(self, tmp_path):
        _agent_file(tmp_path, "fd-quality", ['- P2 | P2-1 | "Style" | Naming'])
        _findings_json(tmp_path, [{"id": "P2-99", "severity": "P2"}])
        r = _run(tmp_path, "--strict")
        assert r.returncode == 3, r.stdout + r.stderr


class TestSeverityMismatch:
    """An id present under a different severity is a (default non-blocking) mismatch."""

    def test_escalation_warns_by_default(self, tmp_path):
        _agent_file(tmp_path, "fd-safety", ['- P1 | P1-1 | "Cache" | Stale entry'])
        _findings_json(tmp_path, [{"id": "P1-1", "severity": "P0"}])  # escalated P1->P0
        r = _run(tmp_path)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "severity differs" in r.stderr

    def test_escalation_fails_under_strict(self, tmp_path):
        _agent_file(tmp_path, "fd-safety", ['- P1 | P1-1 | "Cache" | Stale entry'])
        _findings_json(tmp_path, [{"id": "P1-1", "severity": "P0"}])
        r = _run(tmp_path, "--strict")
        assert r.returncode == 3, r.stdout + r.stderr


class TestQuireMark:
    """Foreign files (wrong/missing run-uuid) must not ground synthesized findings."""

    def test_foreign_file_cannot_launder_invented_finding(self, tmp_path):
        # Invented finding only appears in a foreign (prior-run) file.
        _agent_file(tmp_path, "fd-safety", ['- P0 | P0-1 | "Auth" | Token leak'])
        _agent_file(tmp_path, "fd-stale", ['- P0 | P0-99 | "X" | invented'], run_uuid="OLD-RUN")
        _findings_json(tmp_path, [{"id": "P0-99", "severity": "P0"}])
        r = _run(tmp_path)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "P0-99" in r.stderr

    def test_foreign_count_reported_in_json(self, tmp_path):
        _agent_file(tmp_path, "fd-safety", ['- P0 | P0-1 | "Auth" | Token leak'])
        _agent_file(tmp_path, "fd-stale", ['- P0 | P0-1 | "Auth" | Token leak'], run_uuid="OLD")
        _findings_json(tmp_path, [{"id": "P0-1", "severity": "P0"}])
        r = _run(tmp_path, "--json")
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["foreign_skipped"] == 1
        assert out["status"] == "ok"


class TestInvocation:
    def test_missing_findings_json_exits_2(self, tmp_path):
        _agent_file(tmp_path, "fd-safety", ['- P0 | P0-1 | "Auth" | Token leak'])
        r = _run(tmp_path)
        assert r.returncode == 2

    def test_missing_dir_exits_2(self, tmp_path):
        r = _run(tmp_path / "nope")
        assert r.returncode == 2

    def test_synthesis_and_reaction_files_excluded(self, tmp_path):
        """summary/synthesis/findings and *.reactions files are not agent indexes."""
        _agent_file(tmp_path, "fd-safety", ['- P0 | P0-1 | "Auth" | Token leak'])
        # A reaction file containing an index-like line must NOT ground a finding.
        (tmp_path / "fd-safety.reactions.md").write_text(
            f"<!-- run-uuid: {RUN} -->\n### Findings Index\n- P0 | P0-99 | \"X\" | y\n"
        )
        _findings_json(tmp_path, [{"id": "P0-99", "severity": "P0"}])
        r = _run(tmp_path)
        assert r.returncode == 3, r.stdout + r.stderr
