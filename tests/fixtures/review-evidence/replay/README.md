# Synthetic accepted-gold replay example

All text and judgments here are independently authored fictional data. There are
no captured reviews, transcripts, credentials or document-derived fixtures.
The generator creates snapshot-bound files using the current parser digest.

```sh
python3 tests/fixtures/review-evidence/replay/make_example.py --output /tmp/synthetic-replay
python3 scripts/score_review_replay.py candidates --gold /tmp/synthetic-replay/gold.json --runs /tmp/synthetic-replay/runs.json --json
python3 scripts/score_review_replay.py score --gold /tmp/synthetic-replay/gold.json --runs /tmp/synthetic-replay/runs.json --judgments /tmp/synthetic-replay/judgments.json --json
```

The example has one accepted decision, one accepted plain fix, one rejected
recommendation and one additional finding. Synthetic judgments produce recall
1 for each accepted category and a valid extra. This is an offline scoring
example, not an actual review replay or evidence that a model or human reviewed it.

## Input contract

Gold is a schema-version-1 object with `snapshot`, `index` (relative path) and
`items`. Snapshot keys are `document_id`, `document_sha256`, `parser_version`,
`parser_sha256`, `syntax_profile` and `index_sha256`, exactly as the section index
emits them. The index must have a valid canonical hash, current supported parser
contract and nonoverlapping direct line ownership. Each gold item has a unique
`id`, exact `claim`, `sections`, `disposition` (`accepted`, `rejected` or null),
and `kind` (`decision`, `plain_fix` or null). Missing labels stay unknown.
Rejected items do not enter recall denominators; accepted items without a kind
cannot enter either denominator. Labels are never inferred from finding status.

The runs manifest has `schema_version: 1` and a nonempty `runs` array. Each run
has a unique public-safe `id`, the same `snapshot`, a relative `findings` path,
`input_mode` (`snapshot` or `ledger`), a public-safe `stage`, and nonempty `passes`.
The supplied artifact is the explicit selected finding set; the scorer never
derives surfaced findings from verification stamps or pools separate runs.
Every finding must declare `pass_id`, a nonempty `pass_ids` array, or both.
All values must be public-safe pass aliases within the selected scope. If both
fields are present, both are validated and `pass_ids` must include `pass_id`;
empty, malformed, contradictory or out-of-scope provenance is invalid. These
checks also apply independently to each ablation's selected pass subset.

Finding records require `id`, `claim` and `location`. The shared findings loader
handles full-row ledger stamps, duplicate records and immutable-field conflicts.
Locations use a rightmost numeric `path:line` or `path:start-end` suffix.
Line numbers use ASCII digits only; other numeral spellings are unparseable.
Paths are canonical repository-relative identities; line ranges must be positive,
ordered and in bounds. All intersected direct section owners are retained.
Optional declared `sections` are validated and kept alongside derived sections;
disagreements remain visible. Invalid or other-document locations produce no
automatic candidates but do not exclude external semantic judgment.

An unsplit compound finding remains one vertex and cannot satisfy two gold items.
Externally reviewed splits may carry `split_from` plus `split_provenance` with
`judgment_id`, `judge`, exact `reason`, and `source_findings_sha256`. The tool
checks shape and binds these assertions to the input hash; it does not attest
that an external reviewer actually ran. It never splits claims automatically.

## Scope and external judgments

Candidate section overlap is a retrieval hint, never a semantic match.
`inputs_sha256` hashes a versioned canonical envelope containing the evaluation
scope (run, stage, selected passes, invocation scope and optional ablation ID),
snapshot/index metadata, exact input-file hashes, gold sorted by ID, effective
selected findings with their exact claims/locations/quotes/provenance and resolved
sections, and loader/derivation versions. Judgment records are excluded to avoid
circular hashing. Source files and finding locations are never rewritten.

The hash is repeatable for identical inputs and deliberately sensitive to exact
file bytes. Reordering source rows changes the file hash and invalidates prior
judgments even though the matching algorithm itself is permutation-invariant.
Separate ablations have separate hashes; judgments are not silently reused.

Judgment JSON has `schema_version: 1` and arrays `judgments`, `resolutions` and
`coverage` (omitted arrays default empty). A judgment has unique `id`, `run_id`,
optional `ablation_id`, `inputs_sha256`, `type`, `finding_id`, `judge`, `reason`
and `verdict`. Match judgments additionally require `gold_id` and use
`same_issue`, `different_issue` or `uncertain`. Extra judgments use `valid`,
`invalid` or `uncertain`. Judge provenance has `id`, `kind` (`human` or `model`)
and public-safe `family`, optionally `model` and `receipt_id`.

Only resolved `same_issue` judgments create accepted-gold edges, including
externally judged nonoverlapping pairs. Uncertain/conflicting judgments create no
edge. A resolution is another judgment with nonempty `supersedes` IDs from the
same group and binding. Cycles, dangling references and stale hashes are errors.
Every original judgment and resolution is retained in the report. Structured
judgment rationales are repeated: keep real evaluation reports private.

A semantic coverage attestation has unique `id`, `run_id`, optional
`ablation_id`, `inputs_sha256`, `type: "semantic"`, boolean `complete`, `judge`
and `reason`. `complete: true` attests review of the entire selected finding/gold
universe and completeness of supplied positive edges. Exhaustively resolved
pairs also establish coverage; an empty pair universe is vacuously covered.
An attestation cannot resolve a conflicting or uncertain pair.
Any unsuperseded `complete: false` coverage record keeps semantic review
incomplete, even if another record says true or all individual pairs have
judgments. An external coverage resolution uses `type: "semantic"`, `complete`,
judge/reason/binding and nonempty `supersedes` IDs in `resolutions`. It may
supersede only coverage records for that same run/ablation and current binding.
Cycles and dangling references fail. Original coverage records and coverage
resolutions are all retained in the report's `coverage` array.

## Matching and ambiguity

Matching maximizes decision matches, then plain-fix matches. Feasibility uses
unit-capacity finding-to-gold flow and exact kind quotas with deterministic
Edmonds–Karp paths. Forced edges remove incident vertices and consume quotas;
forbidden edges include all edges for a chosen unmatched gold item.

Canonical assignment visits decision gold first, then plain fixes, in Unicode
code-point ID order; each tries finding IDs in code-point order, then unmatched.
Each choice must preserve the optimal count pair. Maximum cardinality is computed
independently. Edge membership, deterministic priority-optimal witnesses and all
recall-changing maximum-cardinality count vectors are reported separately.

Per-gold ambiguity includes `unmatched_possible`, proved by forbidding **all**
incident edges, and explicit `occurrence_ambiguous`/`assignment_ambiguous` flags.
Per-finding ambiguity and extras also expose `occurrence_ambiguous`, so the
canonical tie-break cannot silently hide assignment-dependent extras.

Recall is separate for accepted decisions and plain fixes. Empty denominators
give null. Unknown labels suppress ratios rather than inventing denominators.
Without complete semantic coverage, known matches provide only a
`confirmed_recall_lower_bound`; unmatched gold remains unresolved. With full
coverage, an ambiguous canonical nonmatch is `assignment_dependent`, not an
unqualified miss. Rejected-gold relations are reported separately, without
penalizing absence. Every finding unmatched to accepted gold is an extra,
including duplicates and rejected-related findings; extras are not automatically
false positives.

Extras retain individual judgments and model-family labels. A resolved human
adjudication or agreement from at least three declared model families completes
extra validity coverage. Family diversity is an external provenance assertion,
not independently verified model-service evidence. Disagreement has no majority
shortcut: an explicit resolution must supersede conflicting judgments.
Extra-validity judgments supplied for an accepted-gold match remain visible in
`matched_finding_validity`, with the chosen gold ID and explicit diagnostics for
invalid or unresolved validity. These diagnostics do not rewrite semantic edges,
the matching assignment or recall: matching and validity are separate judgments.
Such findings remain matched rather than appearing in the unmatched `extras`.

## Ablations and costs

Optional run `ablations` use unique `id`, explicit `stage`/`passes` (a subset of
the run's passes), their own separate `findings` artifact and optional `input_mode`.
Missing artifacts, including absent pre-adjudication data, are unavailable;
the tool never constructs a cheaper run by filtering a post-adjudication file.
Matching and judgments are scoped independently to every run and ablation.

Optional `token_ledger` is a relative path to a token-ledger report; cost reporting
also requires explicit `invocation_ids`. The report's review-run ID and exact
invocation set must match. Missing/mismatched evidence stays unavailable.
Only allowlisted totals and optional estimated list cost are projected, with the
ledger file digest. No price or quota estimate is inferred from finding counts,
and a finding-only ablation never inherits the parent's cost evidence.

Exit 0: candidates generated (semantic limitation explicit), or fully covered
scoring. Exit 1: incomplete labels, semantic adjudication, extra validity,
requested cost coverage or unavailable ablations. Exit 2: invalid structure,
snapshot/parser mismatch, stale binding or dangling judgment references.
In candidates mode, top-level `run_status: "complete"` describes candidate
generation only. The top-level `limitations` always includes
`semantic_review_not_evaluated`, and includes `ablation_unavailable` when a
declared ablation has no usable separate artifact. Individual scope records
retain their availability reasons and semantic-coverage flags.
No acceptance threshold, default-review change or actual replay is introduced.
