# Phase 2 — Assay

One **Assayer** subagent (never a reviewer) reads the round's new findings, scores them on Novelty/Risk/Taste, clusters them, runs the fusion emergence gate, and appends scored finding objects to the ledger. The reviewers find; the Assayer judges — keeping novelty honest, since a lens always over-rates its own.

## Inputs

- The round's probe output dirs (`round-N/*/`).
- `findings-helper.sh read-indexes <output_dir>` for each, giving `agent<TAB>finding-line` — the deterministic overlap source.
- The full existing `heat-ledger.jsonl` (for cross-round novelty/cluster judgment).
- For fused-lens findings: both parents' Findings Indexes (for the emergence gate).

## Procedure

Launch **one** Assayer subagent per round (model: Sonnet for novelty/risk; Opus for the taste annotation — run as a single Opus Assayer on `--quality=balanced`+, or a Sonnet assayer + a small Opus taste pass on economy). It sees **all of the round's finding files at once**.

For each new finding, the Assayer:

1. **Cluster (deterministic pre-filter first).** Group by location overlap (same file + overlapping lines, OR same file + same top-level symbol). Only location-colliding candidates go to LLM same-root-cause judgment. Assign `cluster_id`; flag whether it opens a **new** cluster (not seen any prior round).
2. **Score NOVELTY (0–3)** as inverse measured overlap — see `references/heat-scoring.md`. Compute overlap from `read-indexes`, not the `convergence` command.
3. **Score RISK** — `blast_radius (0–3) × likelihood (0–3) = product`, decoupled from `severity`. Store both.
4. **Annotate TASTE (−2..+2)** — Opus only, only on `[t]`-flagged or form-over-function findings; else `taste = 0, taste_kind = null`.
5. **Emergence gate (fused-lens findings only).** Check the finding's location against both parents' indexes (`references/fusion.md` § emergence gate): demote to convergence if a parent already had it; promote to EMERGENT (novelty floored at 3) if neither did, or if both touched the location but neither connected the causes. Record `intersection_justification`.

Append one fully-scored JSON object per finding to `heat-ledger.jsonl` (schema: `references/ledger-schema.md`). Set `status = raw` (the verify phase will stamp `upheld`/`refuted` for the high-novelty/high-risk subset).

## Refresh lens records

Append this round's new finding ids to the relevant `lenses/{agent}.json` records, and create records for any newly generated lenses (probe lenses, fused lenses) so the next `retarget` sees an up-to-date lens graph.

## Output

The ledger now contains every finding through this round, scored. `phases/retarget.md` (in the loop) or `phases/score.md` (which also re-assays) reads it next. The assay itself does **not** compute the heat map — that is `retarget`'s job (round 1+) / `score`'s job (cross-round linking). Assay only scores and clusters individual findings.

## Why a separate Assayer

Reviewers systematically over-rate their own novelty and cannot see what other lenses found this round — so self-scored novelty is meaningless. A single Assayer with the whole round in view is the only place novelty-as-relative-overlap can be computed. This is also why per-round scores are *triage-grade*: the Assayer is fast and local; the synthesis agent re-scores the merged ledger for the trustworthy final numbers.
