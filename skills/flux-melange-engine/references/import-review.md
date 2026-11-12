# Reference: Importing an Independently Packaged Review

A melange run can take in one independently produced review — a receipt plus a report written by a reviewer outside the run — as a **bundle** under `imports/`. The import is a deterministic, offline file operation. It is not a live mirror of a peer, and the run never talks to the reviewer.

Everything in a bundle is **external evidence**, not a run finding. The importer also derives *finding rows* from the report so the run can look at them, but those rows stay `raw` until a later step verifies the cited ones, and even then they never become run-verified results (see "What imported rows may and may not do").

## Commands

Always run both scripts under isolated mode, with the literal plugin-root prefix. Absolute script paths are not admitted by the melange Bash guard.

```bash
python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/import-melange-review.py" \
  --run-dir <run> --receipt <receipt.json> --report <report.md> \
  --report-sha256 <64 lowercase hex>

python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/scan-melange-import.py" --run-dir <run>
```

The operator supplies `--report-sha256` from the packaged report. The importer re-hashes the report and refuses a mismatch (exit 11), so a report that changed after packaging does not import.

The guard admits each script as one exact invocation. The value list is fixed (`--run-dir`, `--receipt`, `--report`, `--report-sha256` for the importer; `--run-dir` for the scanner), with no shell expansion other than the plugin-root prefix.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Complete import, exact existing import revalidated, or clean scan |
| 2 | Invalid arguments or hash, unsafe path, or input replaced while being read |
| 10 | Receipt missing or invalid, or its basename does not match |
| 11 | Report hash mismatch |
| 12 | Lab admission failure |
| 13 | Unsupported report or extraction failure |
| 14 | Scrub, serialization, structural or provenance failure |
| 15 | Verdict disagreement between receipt and report |
| 16 | Late or second import |
| 20 | Residual secret (scanner) |
| 21 | Busy, conflict or tampered existing bundle |
| 22 | Scanner failure |
| 23 | Invalid run |
| 24 | Report missing or I/O failure |

A non-zero exit leaves no partial bundle. A bundle appears atomically or not at all.

## Bundle layout

`imports/<H>/` where `H` is a hash binding the receipt and report hashes together:

- `manifest.json` — provenance and binding (below)
- `findings.jsonl` — derived finding rows, scrubbed
- `findings/fd-external-review-<H>.md` — a Findings Index in the form `findings-helper.sh` reads
- `external-evidence/receipt.redacted.json` and `external-evidence/report.redacted.md` — scrubbed copies of the inputs

Every artifact is scrubbed **before** the first write (the five named secret formats plus the existing patterns), and the final bytes are checked again before the bundle is published. The post-import scan then checks the whole run tree and fails on residue.

## Provenance and what is claimed

The manifest carries:

- label `coordinator-asserted, receipt-consistent (verdict only)`
- `operator_hash_check: matched` — the operator-supplied report hash matched the report bytes
- `target_check: not-performed` — the importer does not check that the review covered this run's target
- `applicability_note` — the receipt is bound to the work it reviewed; the coordinator must record why it applies to this run (`import_applicability`) before the bundle is assimilated
- `reviewer_effort` and `reviewer_runtime` set to `not in receipt` when the receipt does not carry them
- extraction method `receipt-headings-v2` for a report that carries a FINDINGS line, and `none` for an untagged report (the verdict is still recorded; no rows are derived)

The importer checks that the receipt and the report agree on the verdict and that the reviewer lab is admissible. It does **not** establish that the reviewer ran, that the receipt is authentic, or that the review covered this target. Do not describe an imported review as verified by its receipt.

## Report format contract (advisory)

The importer is conservative: it accepts the heading forms below and rejects what it cannot read. This contract is advisory text for whoever configures the reviewer dispatch, and the importer does not depend on it being followed beyond what it can parse.

> Write each finding as `### P1: Title` or `- P1: Title`, using P0–P3, without emphasis, embedded IDs or severity tables. Cite a real `path:line` or `path:start-end` when known; do not invent one. Use continuation prose for evidence. Omit zero-count breakdown bullets. If supplying FINDINGS, make its counts exact. End after a blank line with exactly VERDICT: PASS, VERDICT: PASS WITH NOTES, or VERDICT: FAIL. Include no fences or HTML comments.

A block-quoted finding line (`> - P1: …`) is rejected with exit 13 by design.

## What imported rows may and may not do

Imported rows carry `source.import`, `taste_kind: null`, status `raw`, and the agent id `fd-external-review-<H>`.

- They are assayed once, with the run's other findings, and keep status `raw` after that.
- Only rows that cite a location are verified, and only within the remaining budget (see `phases/verify.md`). A passed check records evidence on the row; it does not make the row a run finding.
- Imported rows never reach `upheld`, never enter `surfaced.jsonl`, and never become scorer input. They never enter convergence, heat, fusion or Taste computation, and an imported lens is never a fusion parent.
- Synthesis lists them in their own section, "External review findings (unverified)", separate from the run's findings.

## Late and second imports

An import after synthesis has started is refused (exit 16): a `*-synthesis.md`, a `surfaced.jsonl`, or an `import_assimilation` key in `melange-state.json` marks the run as past the point where a new bundle can be assimilated. A second, different import is refused the same way (exit 16) while `imports/` already holds another bundle: a run takes one imported review. The importer checks the late marker again after it publishes. If the marker appeared in between, or if that check fails for any reason, it moves the new bundle back out (or deletes it) so no bundle is left that the snapshot may have missed. If the bundle can be neither moved nor deleted the importer exits 21 and says so; delete it before assimilating. The coordinator writes the marker before it lists bundles, and compares the listing again before the completion scan. Re-running an identical existing import returns 0 after revalidating the bundle; a conflicting bundle returns 21.

Escape sequences in the report (`\uXXXX`, `\UXXXXXXXX`, `\xXX`) are decoded to a fixpoint before scrubbing, so an escaped credential is found at any nesting depth up to 64 (deeper is refused, exit 14). A sequence that cannot be shown as text (a control character, a surrogate or a value beyond U+10FFFF) is written as the visible placeholder `[encoded U+XXXX]` instead of a character: it neither forges line structure nor hides a credential behind a hexadecimal digit.

## Scope and Limitations

- Not a live peer. There is no live mirror, no adaptive loop, no Parley session and no egress proxy. The reviewer ran elsewhere, earlier, and what arrives is files.
- Import does not stage or invoke any external CLI.
- `--peers=off` and ordinary melange runs do not use this path and are unchanged apart from the extended shared scrubber.
- The Workflow entrypoint and its unguarded-write marker are unchanged. This path applies to the coordinator-driven (guarded file tool) mode only.
- Secret handling is limited to five named formats (AWS access keys, Slack tokens, Google API keys, JWTs, Stripe keys) plus the patterns the scrubber already covered. The scan reports residue of those patterns; it is not an exhaustive secret detector.
- Verdict agreement is the only receipt-derived check. Everything else in the report is the reviewer's claim.
