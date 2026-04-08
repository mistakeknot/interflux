#!/usr/bin/env bash
# fluxbench-sync.sh — store-and-forward sync from FluxBench results JSONL to AgMoDB
# Usage: fluxbench-sync.sh [--dry-run]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

results_jsonl="${FLUXBENCH_RESULTS_JSONL:-${SCRIPT_DIR}/../data/fluxbench-results.jsonl}"
agmodb_repo="${AGMODB_REPO_PATH:-${SCRIPT_DIR}/../data/agmodb}"
sync_state_file="$(dirname "$results_jsonl")/.sync-state"

dry_run=false
[[ "${1:-}" == "--dry-run" ]] && dry_run=true

# --- Guard: nothing to sync if JSONL missing or empty ---
if [[ ! -f "$results_jsonl" ]]; then
  echo "No results file found at ${results_jsonl} — nothing to sync."
  exit 0
fi

if [[ ! -s "$results_jsonl" ]]; then
  echo "Results file is empty — nothing to sync."
  exit 0
fi

# --- Load or init sync state ---
if [[ -f "$sync_state_file" ]]; then
  sync_state=$(cat "$sync_state_file")
else
  sync_state='{}'
fi

# --- Collect unsynced entries ---
# Use jq -c to normalize multi-line JSON objects into compact single-line JSONL
pending_lines=()
pending_run_ids=()

while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  run_id=$(echo "$line" | jq -r '.qualification_run_id // empty' 2>/dev/null) || continue
  [[ -z "$run_id" ]] && continue

  # Skip if already committed
  state=$(echo "$sync_state" | jq -r --arg id "$run_id" '.[$id] // empty')
  if [[ "$state" == "committed" ]]; then
    continue
  fi

  pending_lines+=("$line")
  pending_run_ids+=("$run_id")
done < <(jq -c '.' "$results_jsonl" 2>/dev/null)

if [[ ${#pending_lines[@]} -eq 0 ]]; then
  echo "All entries already synced — nothing to sync."
  exit 0
fi

echo "Found ${#pending_lines[@]} unsynced result(s)."

# --- Dry-run: report and exit ---
if $dry_run; then
  for i in "${!pending_run_ids[@]}"; do
    model=$(echo "${pending_lines[$i]}" | jq -r '.model_slug // "unknown"')
    echo "[dry-run] Would sync: ${pending_run_ids[$i]} (${model})"
  done
  exit 0
fi

# --- Phase 1: mark pending in sync state ---
for run_id in "${pending_run_ids[@]}"; do
  sync_state=$(echo "$sync_state" | jq --arg id "$run_id" '. + {($id): "pending"}')
done
echo "$sync_state" > "$sync_state_file"

# --- Phase 2: write AgMoDB files ---
mkdir -p "$agmodb_repo"

for i in "${!pending_lines[@]}"; do
  line="${pending_lines[$i]}"
  run_id="${pending_run_ids[$i]}"
  model_slug=$(echo "$line" | jq -r '.model_slug // "unknown"')
  timestamp=$(echo "$line" | jq -r '.timestamp // empty')
  [[ -z "$timestamp" ]] && timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

  # Extract metrics, stripping null values
  metrics_obj=$(echo "$line" | jq '.metrics // {} | with_entries(select(.value != null))')

  # Build AgMoDB document — merge into existing if file already present (idempotent)
  target_file="${agmodb_repo}/${model_slug}.json"

  agmodb_doc=$(jq -n \
    --arg slug "$model_slug" \
    --argjson scores "$metrics_obj" \
    --arg ts "$timestamp" \
    --arg rid "$run_id" \
    '{
      model_slug: $slug,
      externalBenchmarkScores: {
        fluxbench: $scores
      },
      last_sync: $ts,
      qualification_run_id: $rid
    }')

  echo "$agmodb_doc" > "$target_file"
  echo "Wrote ${target_file}"
done

# --- Phase 3: mark committed ---
for run_id in "${pending_run_ids[@]}"; do
  sync_state=$(echo "$sync_state" | jq --arg id "$run_id" '. + {($id): "committed"}')
done
echo "$sync_state" > "$sync_state_file"

echo "Sync complete: ${#pending_lines[@]} entry/entries written."
