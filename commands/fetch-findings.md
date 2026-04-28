---
name: fetch-findings
description: Fetch peer findings from a flux-drive review — inspect what agents have shared during a parallel review.
allowed-tools: Bash, Read
---

# Fetch Peer Findings

Retrieve findings from a flux-drive intermediate findings file.

## Usage

`/interflux:fetch-findings <output_dir> [--severity blocking|notable|all]`

## Execution

1. Parse arguments:
   - `output_dir` (required): The flux-drive output directory
   - `severity` (optional, default "all"): Filter by severity level

2. Run the helper:
   ```bash
   bash ${CLAUDE_PLUGIN_ROOT}/scripts/findings-helper.sh read "{output_dir}/peer-findings.jsonl" {severity}
   ```

3. Parse the JSON output and present in a readable table:
   ```
   ## Peer Findings ({count} total)

   | Time | Agent | Severity | Category | Summary |
   |------|-------|----------|----------|---------|
   | ... | ... | ... | ... | ... |
   ```

4. If no findings exist, report: "No peer findings shared yet."
