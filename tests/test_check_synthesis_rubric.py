"""Advisory synthesis checker. Fixtures are built from flagged findings in a
manual review of real syntheses."""
import subprocess
import sys
from pathlib import Path

import check_synthesis_rubric as c

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_synthesis_rubric.py"

# Flagged finding: headline 91 (12/38/30/11) but per-agent rows give 13/38/30/11 = 92.
HERMES = """# Runtime surface review
Verdict: risky. 91 findings (12 P0 / 38 P1 / 30 P2 / 11 P3), the sum of per-agent rows

| Agent | Findings (P0/P1/P2/P3) |
|---|---|
| fd-a | 5/20/15/6 |
| fd-b | 8/18/15/5 |
"""

# Flagged finding: "500 SKUs x 20 categories = 100+ fuzzy reviews a month" does not compute.
JAWN = """- P1 | Fuzzy review volume: 500 SKUs x 20 categories = 100+ fuzzy reviews a month, add a batch job
"""


def msgs(report, check=None):
    return [f["message"] for f in report["flags"] if check in (None, f["check"])]


def test_hermes_91_vs_92_is_flagged():
    got = msgs(c.run(HERMES), "count")
    assert any("91" in m and "92" in m for m in got), got


def test_consistent_counts_are_not_flagged():
    ok = HERMES.replace("91 findings", "92 findings").replace("12 P0", "13 P0")
    assert msgs(c.run(ok), "count") == []


def test_deduplicated_total_is_not_flagged():
    """Synthesis dedups, so 91 after merging 92 raw agent findings is fine."""
    dedup = HERMES.replace(", the sum of per-agent rows", " after deduplication")
    assert msgs(c.run(dedup), "count") == []


ROWS4 = """
| Agent | Findings (P0/P1/P2) |
|---|---|
| fd-a | 1/1/0 |
| fd-b | 1/1/0 |
"""


def test_document_wide_dedup_wording_does_not_enable_comparison():
    t = "2 findings (1 P0 / 1 P1) after deduplication\nRaw agent totals before deduplication are shown below.\n" + ROWS4
    assert msgs(c.run(t), "count") == []


def test_negated_sum_claim_does_not_enable_comparison():
    t = "2 findings (1 P0 / 1 P1) after deduplication, not the sum of per-agent rows\n" + ROWS4
    assert msgs(c.run(t), "count") == []


def test_negation_without_dedup_word_does_not_enable_comparison():
    t = "2 findings (1 P0 / 1 P1), not the sum of per-agent rows\n" + ROWS4
    assert msgs(c.run(t), "count") == []


def test_affirmative_headline_sum_is_compared():
    t = "2 findings (1 P0 / 1 P1), the sum of per-agent rows\n" + ROWS4
    assert any("4" in m for m in msgs(c.run(t), "count"))


def test_decimal_product_is_not_misread_as_whole_number():
    assert c.run("- P2 | Cost: 1.5 x 2 = 3 calls per run, add caching")["flags"] == []
    bad = c.run("- P2 | Cost: 1.5 x 2 = 4 calls, add caching")["flags"]
    assert any("1.5 x 2 = 3" in f["message"] for f in bad)


def test_bad_product_is_flagged_dim2():
    flags = c.run(JAWN)["flags"]
    assert any(f["dim"] == 2 and "10000" in f["message"] for f in flags), flags


def test_effort_sizing_without_cause_is_dim3_and_with_cause_is_not():
    bare = "- P2 | Quality score: 30 min to add a 0-1 field"
    caused = "- P2 | Quality score: 30 min to add a field because the schema already has the column"
    assert any(f["dim"] == 3 for f in c.run(bare)["flags"])
    assert not any(f["dim"] == 3 for f in c.run(caused)["flags"])


def test_hedged_fix_is_dim8():
    t = "- P1 | Freshness: add either a daily batch or a sub-5-minute refresh, consider both"
    assert any(f["dim"] == 8 for f in c.run(t)["flags"])


def test_line_reference_beyond_eof_is_flagged_only_when_resolvable(tmp_path):
    (tmp_path / "a.py").write_text("x\ny\n")
    t = "- P0 | Bug at a.py:2 and a.py:99 and gone.py:5"
    r = c.run(t, tmp_path)
    got = msgs(r, "ref")
    assert len(got) == 1 and "a.py:99" in got[0]
    assert r["refs"] == {"resolved": 2, "unresolved": 1}


def test_cli_exits_zero_with_flags_and_never_rewrites(tmp_path):
    f = tmp_path / "synthesis.md"
    f.write_text(HERMES)
    before = f.read_text()
    p = subprocess.run([sys.executable, str(SCRIPT), str(f)], capture_output=True, text=True)
    assert p.returncode == 0
    assert "Rubric flags (advisory)" in p.stdout and "91" in p.stdout
    assert f.read_text() == before


def test_cli_missing_file_is_invocation_error(tmp_path):
    p = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "nope.md")], capture_output=True, text=True)
    assert p.returncode == 2
