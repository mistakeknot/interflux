"""Regression tests for issue #6 — OUTPUT_DIR content-address collision races.

Two concurrent flux-drive runs on the same target content-address to the
IDENTICAL OUTPUT_DIR. Before the fix, run B's pre-dispatch `find ... -delete`
could wipe run A's in-flight files, and both runs wrote the same agent
filenames. The converging fix has four parts, each asserted below:

1. RUN_UUID is carried in the agent output FILENAME (`{agent}.{RUN_UUID}.md`).
2. Synthesis globs are run-scoped (`*.{FLUX_RUN_UUID}.md`), not bare `*.md`.
3. An atomic occupancy lock (`mkdir .run-{UUID}.lock`) is taken BEFORE the
   destructive `find -delete`.
4. flux-review-engine passes a disjoint `--output-dir` per track.
5. Completion renames use `mv -n` (no-clobber).
"""

from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[2] / "skills" / "flux-engine"
REVIEW_ENGINE = Path(__file__).resolve().parents[2] / "skills" / "flux-review-engine"

LAUNCH = (ENGINE / "phases" / "launch.md").read_text()
SYNTHESIZE = (ENGINE / "phases" / "synthesize.md").read_text()
SHARED = (ENGINE / "phases" / "shared-contracts.md").read_text()
PROMPT_TEMPLATE = (ENGINE / "references" / "prompt-template.md").read_text()
SKILL = (ENGINE / "SKILL.md").read_text()
TRACK_DISPATCH = (REVIEW_ENGINE / "phases" / "track-dispatch.md").read_text()
TRACK_SYNTHESIS = (REVIEW_ENGINE / "phases" / "track-synthesis.md").read_text()


# --- Part 1: UUID-in-filename scheme is documented and used --------------------

def test_prompt_template_uses_uuid_in_filename():
    """Agents write to {agent-name}.{RUN_UUID}.md.partial / .md."""
    assert "{agent-name}.{RUN_UUID}.md.partial" in PROMPT_TEMPLATE
    assert "{agent-name}.{RUN_UUID}.md" in PROMPT_TEMPLATE


def test_launch_output_format_documents_uuid_filename():
    """The Phase 2 output-format summary references the UUID-in-filename scheme."""
    assert "{agent-name}.{RUN_UUID}.md.partial" in LAUNCH
    assert "{agent-name}.{RUN_UUID}.md" in LAUNCH


def test_research_mode_partial_uses_uuid_filename():
    """Research-mode partial writes also carry the run UUID in the filename."""
    assert "{agent-name}.{RUN_UUID}.md.partial" in LAUNCH


def test_oracle_output_uses_uuid_filename():
    """Oracle council output is run-scoped too."""
    assert "oracle-council.{RUN_UUID}.md" in LAUNCH


# --- Part 2: synthesis globs are run-scoped -----------------------------------

def test_synthesis_verification_glob_is_run_scoped():
    """Step 3.0 verification must glob the current run's UUID, not bare *.md."""
    assert "*.${FLUX_RUN_UUID}.md" in SYNTHESIZE
    # Explicit warning against the unsafe bare glob.
    assert "bare `ls {OUTPUT_DIR}/*.md`" in SYNTHESIZE or "bare `*.md`" in SYNTHESIZE


def test_synthesis_token_loop_is_run_scoped():
    """Step 3.4c token-count loop iterates only the current run's files."""
    assert '"${OUTPUT_DIR}"/*."${FLUX_RUN_UUID}".md' in SYNTHESIZE


def test_skill_documents_run_scoped_synthesis_glob():
    assert "*.{FLUX_RUN_UUID}.md" in SKILL


def test_retry_protocol_glob_is_run_scoped():
    """Retry race protocol globs partials within the current run only."""
    assert '"${FLUX_RUN_UUID}".md.partial' in SHARED


# --- Part 3: atomic occupancy lock before destructive clean -------------------

def test_launch_takes_atomic_lock():
    """An mkdir-based occupancy lock guards OUTPUT_DIR."""
    assert ".run-${FLUX_RUN_UUID}.lock" in LAUNCH
    assert "mkdir" in LAUNCH


def test_lock_precedes_destructive_find_delete():
    """The lock acquisition must appear BEFORE the find -delete pre-clean."""
    lock_pos = LAUNCH.find('mkdir "$LOCK_DIR"')
    delete_pos = LAUNCH.find("-delete")
    assert lock_pos != -1, "no lock acquisition found"
    assert delete_pos != -1, "no find -delete found"
    assert lock_pos < delete_pos, (
        "occupancy lock must be acquired before the destructive find -delete"
    )


def test_concurrent_run_auto_suffixes_output_dir():
    """A second concurrent run detects the peer lock and uses a disjoint dir."""
    assert "other_locks" in LAUNCH
    assert "{OUTPUT_DIR}-${FLUX_RUN_UUID}" in LAUNCH


def test_lock_released_at_cleanup():
    """Step 3.7 releases the occupancy lock."""
    assert ".run-${FLUX_RUN_UUID}.lock" in SYNTHESIZE
    assert "rmdir" in SYNTHESIZE


def test_skill_documents_lock_and_issue6():
    assert ".run-{UUID}.lock" in SKILL
    assert "issue #6" in SKILL


# --- Part 4: flux-review-engine passes disjoint --output-dir per track ---------

def test_track_dispatch_passes_per_track_output_dir():
    """Each inner flux-drive run gets an explicit, per-track --output-dir."""
    assert "--output-dir" in TRACK_DISPATCH
    assert "docs/research/flux-review/{SLUG}/track-{track_letter}" in TRACK_DISPATCH


def test_track_dispatch_explains_collision_rationale():
    """The per-track isolation references the collision being prevented."""
    assert "issue #6" in TRACK_DISPATCH
    assert "same INPUT_PATH" in TRACK_DISPATCH or "same `INPUT_PATH`" in TRACK_DISPATCH


def test_track_synthesis_reads_disjoint_track_dirs():
    """Synthesis reads from the disjoint per-track directories."""
    assert "track-{letter}" in TRACK_SYNTHESIS


# --- Part 5: mv -n on completion ----------------------------------------------

@pytest.mark.parametrize(
    "doc",
    [PROMPT_TEMPLATE, LAUNCH],
    ids=["prompt-template", "launch"],
)
def test_completion_uses_mv_n(doc):
    """Completion renames use mv -n (no-clobber)."""
    assert "mv -n" in doc


def test_shared_contracts_mandates_mv_n():
    """The invariant section mandates mv -n for completion renames."""
    assert "mv -n" in SHARED
    assert "no-clobber" in SHARED.lower() or "MUST use `mv -n`" in SHARED
