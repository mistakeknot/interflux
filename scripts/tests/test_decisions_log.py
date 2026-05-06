"""Unit tests for scripts/_decisions_log.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import _decisions_log as dl  # noqa: E402

SCRIPT = str(ROOT / "scripts" / "_decisions_log.py")


# --- get_log_path --------------------------------------------------------


def test_get_log_path() -> None:
    assert dl.get_log_path("/tmp/run") == "/tmp/run/decisions.log"


# --- log_decision: write paths -------------------------------------------


def test_log_decision_writes_with_output_dir(tmp_path: Path) -> None:
    written = dl.log_decision(
        "triage-rank", "fd-architecture top score 0.87",
        decision_type="triage",
        output_dir=str(tmp_path),
        score=0.87,
    )
    assert written is True
    log = (tmp_path / "decisions.log").read_text().strip().split("\n")
    assert len(log) == 1
    rec = json.loads(log[0])
    assert rec["name"] == "triage-rank"
    assert rec["decision_type"] == "triage"
    assert rec["state"] == "VERIFIED"
    assert rec["extra"] == {"score": 0.87}


def test_log_decision_uses_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLUX_OUTPUT_DIR", str(tmp_path))
    written = dl.log_decision("test", "ev")
    assert written is True
    assert (tmp_path / "decisions.log").exists()


def test_log_decision_explicit_overrides_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("FLUX_OUTPUT_DIR", str(tmp_path))
    dl.log_decision("test", "ev", output_dir=str(other))
    # Explicit wins
    assert (other / "decisions.log").exists()
    assert not (tmp_path / "decisions.log").exists()


def test_log_decision_appends(tmp_path: Path) -> None:
    dl.log_decision("a", "1", output_dir=str(tmp_path))
    dl.log_decision("b", "2", output_dir=str(tmp_path))
    dl.log_decision("c", "3", output_dir=str(tmp_path))
    lines = (tmp_path / "decisions.log").read_text().strip().split("\n")
    assert [json.loads(l)["name"] for l in lines] == ["a", "b", "c"]


def test_log_decision_propagates_run_uuid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLUX_RUN_UUID", "run-abc-123")
    dl.log_decision("x", "y", output_dir=str(tmp_path))
    rec = json.loads((tmp_path / "decisions.log").read_text().strip())
    assert rec["run_uuid"] == "run-abc-123"


# --- log_decision: no-op paths -------------------------------------------


def test_log_decision_no_env_no_arg_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLUX_OUTPUT_DIR", raising=False)
    assert dl.log_decision("test", "ev") is False


def test_log_decision_nonexistent_dir_no_op(tmp_path: Path) -> None:
    """Don't auto-create OUTPUT_DIR — silent log creation would mask bugs."""
    bogus = tmp_path / "does-not-exist"
    written = dl.log_decision("test", "ev", output_dir=str(bogus))
    assert written is False
    assert not bogus.exists()


# --- read_log -----------------------------------------------------------


def test_read_log_empty_dir(tmp_path: Path) -> None:
    assert dl.read_log(str(tmp_path)) == []


def test_read_log_roundtrip(tmp_path: Path) -> None:
    dl.log_decision("a", "1", output_dir=str(tmp_path), score=0.5)
    dl.log_decision("b", "2", output_dir=str(tmp_path), decision_type="triage")
    records = dl.read_log(str(tmp_path))
    assert len(records) == 2
    assert records[0]["name"] == "a"
    assert records[0]["extra"] == {"score": 0.5}
    assert records[1]["decision_type"] == "triage"


def test_read_log_skips_malformed_lines(tmp_path: Path) -> None:
    """Robust to partial writes during dev — skip non-JSON lines."""
    log = tmp_path / "decisions.log"
    log.write_text(
        '{"name":"good","state":"VERIFIED","evidence":"e"}\n'
        'this is not json\n'
        '{"name":"also-good","state":"VERIFIED","evidence":"f"}\n'
    )
    records = dl.read_log(str(tmp_path))
    assert len(records) == 2
    assert [r["name"] for r in records] == ["good", "also-good"]


def test_read_log_skips_blank_lines(tmp_path: Path) -> None:
    log = tmp_path / "decisions.log"
    log.write_text(
        '{"name":"a","state":"VERIFIED","evidence":"e"}\n\n\n'
        '{"name":"b","state":"VERIFIED","evidence":"f"}\n'
    )
    records = dl.read_log(str(tmp_path))
    assert [r["name"] for r in records] == ["a", "b"]


# --- CLI ----------------------------------------------------------------


def _run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_cli_log_basic(tmp_path: Path) -> None:
    result = _run_cli(
        "log", "triage-rank", "fd-architecture top",
        "--decision-type", "triage",
        "--output-dir", str(tmp_path),
    )
    assert result.returncode == 0
    rec = json.loads((tmp_path / "decisions.log").read_text().strip())
    assert rec["name"] == "triage-rank"
    assert rec["decision_type"] == "triage"


def test_cli_log_with_extra_json(tmp_path: Path) -> None:
    result = _run_cli(
        "log", "budget-cut", "stage-2 reduced from 6 to 4 by token budget",
        "--decision-type", "budget",
        "--extra-json", '{"original_count":6,"final_count":4,"reason":"token_ceiling"}',
        "--output-dir", str(tmp_path),
    )
    assert result.returncode == 0
    rec = json.loads((tmp_path / "decisions.log").read_text().strip())
    assert rec["extra"]["original_count"] == 6
    assert rec["extra"]["final_count"] == 4


def test_cli_log_no_op_silent_without_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without FLUX_OUTPUT_DIR or --output-dir, exit 0 with no error."""
    env = {k: v for k, v in __import__("os").environ.items() if k != "FLUX_OUTPUT_DIR"}
    result = _run_cli("log", "test", "ev", env=env)
    assert result.returncode == 0


def test_cli_log_invalid_extra_json(tmp_path: Path) -> None:
    result = _run_cli(
        "log", "x", "y",
        "--extra-json", "{not json",
        "--output-dir", str(tmp_path),
    )
    assert result.returncode == 4
    assert "invalid" in result.stderr


def test_cli_log_extra_json_must_be_object(tmp_path: Path) -> None:
    result = _run_cli(
        "log", "x", "y",
        "--extra-json", '"a string not an object"',
        "--output-dir", str(tmp_path),
    )
    assert result.returncode == 4
    assert "must be an object" in result.stderr
