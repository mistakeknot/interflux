# Synthetic usage fixtures

All records here are independently authored synthetic shapes, with no transcript
bodies, credentials or captured private usage. `codex-two-turns.jsonl` intentionally
does **not** establish per-turn versus cumulative scope. It must remain incomplete
with `usage_scope_unknown`; neither summing the two turns nor taking the last
counter is justified by the event name.

Adapter contracts are derived from Clavain 0.6.332's `provider_usage.py`,
`lib-dispatch-audit.sh`, `claude_usage.py`, and `docs/guides/claude-usage-accounting.md`.
Receipt input/cache basis and Claude cumulative replacement semantics follow
those documented interfaces. Codex receipt aggregation in that version sums
turn events and is not independent scope proof. Multi-turn additive Codex
accounting stays disabled until independently supported, version-bound evidence
is added through a reviewed change. Single selected turns report their observed
usage only, relative to the explicitly declared manifest scope.

Run the complete synthetic example from the repository root:

```sh
python3 scripts/review_token_ledger.py --manifest tests/fixtures/review-evidence/usage/manifest.json --json
```

The manifest declares the invocation inventory and safe output aliases. Paths are
relative to the manifest. Each invocation represents one attempt; its sources
are alternative views of that attempt, never additional charges. A shared Claude
transcript needs an explicit session and message-ID selection. Receipts select a
dispatch and, when necessary, its attempt. Codex and terminal-result streams use
explicit session plus zero-based physical record indices. Cumulative Claude
records select dispatch and invocation IDs. Unknown selectors/formats remain
unaccounted, with reason codes.

Output completeness is relative to the declared inventory. It cannot prove that
every review invocation was listed. Observed subtotals, estimates, missing usage
and conflicts remain separate. Last Claude message records replace earlier
updates, including decreasing or missing fields. Terminal cumulative totals
replace snapshots; they are not added to message totals. Receipt statuses remain
visible even when separate provider evidence completes the accounting.

Alternative views compare only categories both observed. A disagreement is a
conflict; preferred evidence can fill missing categories only. Historical Claude
receipt zeros remain unknown until original provider evidence establishes zero.
Raw records, transcript bodies, commands, provider error text and source paths
are excluded from output; caller aliases must be public-safe. Optional price
tables produce `estimated_list_cost`, never subscription quota consumption.
