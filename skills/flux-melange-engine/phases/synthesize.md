# Phase 7 — Synthesize (the Eye of Distance)

One Opus agent reads the **full** ledger and produces a **surfacing-first** report — never a flat severity list. It re-scores the merged ledger (the per-round assayer scores were triage-grade; these are the trustworthy numbers) and emits five views plus a spice-trail appendix.

## Launch

Dispatch `Agent` with `subagent_type: interflux:melange-worker`. Pass the
synthesis model from `references/budget-ladder.md`: Opus on `balanced`/`max`,
Sonnet on `economy`. Input: the entire `heat-ledger.jsonl`,
`melange-state.json`, all `round-N-directives.json`, and `lenses/`.

Prompt template (verbatim):
```
You are writing the synthesis for a flux-melange spice-loop review — the eye of distance.

Target: {TARGET_DESC}    File: {INPUT_PATH}
Goal: {GOAL}    Weights: {WEIGHTS}
The loop ran {rounds} rounds and halted: {halt_reason}.

Here is the full heat ledger (every finding, scored on novelty/risk/taste, with
cluster/convergence/disagreement links and status), the per-round directives, and
the lens records:
{ledger + directives + lens records}

First, RE-SCORE the merged ledger yourself — the per-round scores were fast triage
estimates. Then produce these five views (surface the spice; do NOT sort by severity):

## 1. Novelty×Risk Frontier
The Pareto FRONT (not a single sort) of upheld findings on (novelty, risk.product):
surface a max-novelty/mid-risk finding AND a mid-novelty/max-risk finding — both
lead. For each: the claim, lens(es), the risk decomposition (blast × likelihood),
and severity FOR REFERENCE ONLY. This is where a rare-catastrophe (blast 3 ×
likelihood 1) every ancestor buries finally surfaces.

## 2. Top Fusions
Emergent findings no single lens could produce — the section this mode exists for.
Rank by novelty×risk. For each: the parent pair, the intersection_justification,
and the evidence. Report zero-emergent fusions as negative results ("A × B:
independent here").

## 3. Taste Calls
Top +taste elegance to preserve and top -taste smells to fix (Opus annotation; may
be empty). Name the taste_kind.

## 4. Convergence Spine
flux-review's signal, KEPT but DEMOTED: high-convergence findings = high confidence,
LOW novelty (commodity you can trust). One section, not the headline.

## 5. Live Disagreements
Contradictions still open at halt — flux-review discards these as non-convergent
noise; here they are primary signal (often unresolved taste calls: elegant vs reckless).

Then an appendix:

## Spice Trail
Per round: yield, novel_cluster_rate, the directives chosen and WHY (the rationale),
what steered where, and the halt reason. This is the audit trail of how the loop moved.

Optionally, a single "If you read one thing" = argmax(heat), |taste| as tiebreaker.

Write in direct technical prose. Name agents/lenses when attributing. Rank by HEAT
(novelty × risk), never by severity alone.
```

## Imported reviews (only when Step 2.5 ran)

When the run has import bundles, add a seventh block after the five views and before the Spice Trail, and tell the synthesis agent (in the prompt above) to exclude every row whose agent starts with `fd-external-review-` from the five views, the frontier, the fusions and the "If you read one thing" line:

```
## External review findings (unverified)
For each bundle: the bundle id, the manifest label, and its applicability justification.
List its rows with severity, claim, location, and any verification result from
melange-state.json:import_assimilation (confirmed / contradicted / no-location /
budget-clamped). State that these are one external reviewer's claims, not the run's
findings, and that rows marked confirmed were only checked against the cited location.
```

Imported rows never appear in `surfaced.jsonl`, and the section states that.

## Output

Write to `{OUTPUT_ROOT}/{DATE}-synthesis.md` with frontmatter:
```yaml
---
artifact_type: melange-synthesis
method: flux-melange
target: "{INPUT_PATH}"
target_description: "{TARGET_DESC}"
goal: "{GOAL}"
weights: {WEIGHTS}
rounds_run: {N}
halt_reason: {DRY | BUDGET | CEILING | GOAL-MET}
total_fusions: {attempted}
emergent_findings: {count of EMERGENT findings}
date: {DATE}
---
```

Include any caveats discovered during synthesis (a probe that failed and contributed no findings; a fusion that produced only redundant findings; a region the loop never reached before halting on budget).

## Also emit `surfaced.jsonl` (the report's output contract)

Alongside the markdown, write `{OUTPUT_ROOT}/surfaced.jsonl` — one line per finding that appears in **any** of the five views, tagged by which view(s) surfaced it. This is the machine-readable answer to "what did the report actually show the user," and it is what evaluation scores against (the raw `heat-ledger.jsonl` includes raw/refuted/convergent rows that were never surfaced, so scoring the ledger over-counts; a single Pareto front under-counts because it discards the buried finding the *risk axis* surfaces and the taste call the *Taste view* surfaces — experiment E1 found both errors). Shape:

```json
{"id": "f-027", "views": ["frontier", "if-you-read-one-thing"], "novelty": 3, "risk": {"product": 6}, "taste": 0, "claim": "...", "location": "token_cache.py:48-51", "status": "upheld"}
```

`views` is any subset of `frontier` | `fusion` | `taste` | `convergence` | `disagreement` | `if-you-read-one-thing`. A finding surfaced by the risk axis of view 1 OR the taste view OR the fusions view all belong here — the surfaced set is the **union** of the five views, not a single Pareto front. Refuted findings never appear. This file is the eval target for `scripts/_melange_score.py`.

**Do not write it in the same agent turn as the report.** A run without `surfaced.jsonl` cannot be scored at all, and it is the cheapest artifact of the phase — so it must never queue behind the most expensive one. Write the report, *then* start a fresh pass for the surfacing record; if the report-writing pass has run long, hand the extraction to a new agent. The historical Workflow ordering is documented in `references/workflow-args.md`, but that runtime is disabled until its subagent writes have a before-disk guard.

## Import-aware surfaced pass and completion scan

When the run has import bundles, the surfaced pass is a separate pass pinned to the native five views. Start a fresh agent with `--surfaced` semantics: it reads the finished synthesis, includes only native rows (never any `fd-external-review-` row, which is also excluded from the union), and the pass requires that `surfaced.jsonl` is written before anything else continues. Do not mark the run complete until `surfaced.jsonl` exists.

Before the scan, list `imports/` again. The sorted bundle ids on disk must equal `import_assimilation.bundle_ids`. A difference means a bundle appeared or vanished after the snapshot, which only happens when an import raced the marker. Set `import_completion` to `incomplete`, tell the operator, and **stop here: do not run the completion scan and never set `complete` for this run**. A clean scan does not repair a bundle-set mismatch.

Then run the completion scan, once, after both files are written:

```bash
python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/scan-melange-import.py" --run-dir {OUTPUT_ROOT}
```

Exit 0 means the whole run tree is clean. Any other exit (residue 20, scanner failure 22, invalid run 23) means the import is not complete: use a guarded Edit to set `import_scan.status` to `failed` and `import_completion` to `incomplete` in `melange-state.json`, report the exit code and the file names the scanner printed (it never prints the matched text), and do not describe the run as clean. On exit 0, and only when the bundle-set check above matched, set `import_scan.status` to `clean` and `import_completion` to `complete`.

## Then → Phase 8 Report

Return to `SKILL.md` § Report to print the paths, spice trail, halt reason, total cost, and regeneration hints.
