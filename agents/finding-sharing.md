# Intermediate Finding Sharing

During parallel flux-drive reviews, agents can share high-severity findings via `{OUTPUT_DIR}/peer-findings.jsonl`.

## Severity Levels

- `blocking` — contradicts another agent's analysis (MUST acknowledge)
- `notable` — significant finding that may affect others (SHOULD consider)

## Helper Script

`scripts/findings-helper.sh`
- `write <file> <severity> <agent> <category> <summary> [file_refs...]`
- `read <file> [--severity blocking|notable|all]`

## Synthesis

The synthesis agent reads the findings timeline for convergence tracking and contradiction detection.

## Command

`/interflux:fetch-findings <output_dir> [--severity ...]` — inspect shared findings.
