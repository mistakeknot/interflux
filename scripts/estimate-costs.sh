#!/usr/bin/env bash
# estimate-costs.sh — Query interstat for per-agent token cost estimates
# Usage: estimate-costs.sh [--model MODEL] [--slicing]
# Output: JSON object mapping agent_name -> estimated_tokens
# Requires: sqlite3, jq, budget.yaml

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUDGET_FILE="${PLUGIN_DIR}/config/flux-drive/budget.yaml"
DB_PATH="${HOME}/.claude/interstat/metrics.db"

MODEL=""
SLICING=false

# Check required binaries
for cmd in jq; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Warning: $cmd not found, using hardcoded defaults" >&2
    echo '{"estimates":{},"defaults":{"review":40000,"cognitive":35000,"research":15000,"oracle":80000,"generated":40000},"slicing_multiplier":1.0}'
    exit 0
  fi
done

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --slicing) SLICING=true; shift ;;
    *) shift ;;
  esac
done

# Default model if not specified
if [[ -z "$MODEL" ]]; then
  MODEL="claude-opus-4-6"
fi

# Read default estimates from budget.yaml using simple grep (no yq dependency)
get_default() {
  local agent_type="$1"
  local default_val="40000"
  local line
  line=$(grep "^  ${agent_type}:" "$BUDGET_FILE" 2>/dev/null || echo "")
  if [[ -n "$line" ]]; then
    default_val=$(echo "$line" | sed 's/.*: *//' | sed 's/ *#.*//' | tr -d '[:space:]')
  fi
  echo "$default_val"
}

get_slicing_multiplier() {
  local line
  line=$(grep "^slicing_multiplier:" "$BUDGET_FILE" 2>/dev/null || echo "")
  if [[ -n "$line" ]]; then
    echo "$line" | sed 's/.*: *//' | tr -d '[:space:]'
  else
    echo "0.5"
  fi
}

# Classify agent into type for default lookup
classify_agent() {
  local name="$1"
  case "$name" in
    fd-systems|fd-decisions|fd-people|fd-resilience|fd-perception) echo "cognitive" ;;
    *-researcher|*-analyzer|*-analyst) echo "research" ;;
    oracle*) echo "oracle" ;;
    fd-*) echo "review" ;;
    *) echo "generated" ;;
  esac
}

# Query interstat for historical averages
ESTIMATES="{}"
if [[ -f "$DB_PATH" ]]; then
  # Query agents with >= 3 runs for reliable estimates
  INTERSTAT_DATA=$(sqlite3 -json "$DB_PATH" "
    SELECT agent_name, CAST(ROUND(AVG(COALESCE(input_tokens,0) + COALESCE(output_tokens,0))) AS INTEGER) as est_tokens, COUNT(*) as sample_size
    FROM agent_runs
    WHERE (model = '${MODEL}' OR model IS NULL)
      AND (input_tokens IS NOT NULL OR output_tokens IS NOT NULL)
    GROUP BY agent_name
    HAVING COUNT(*) >= 3
    ORDER BY agent_name;
  " 2>/dev/null || echo "[]")

  if [[ "$INTERSTAT_DATA" != "[]" && -n "$INTERSTAT_DATA" ]]; then
    ESTIMATES=$(echo "$INTERSTAT_DATA" | jq -c '
      reduce .[] as $row ({};
        . + {($row.agent_name): {est_tokens: $row.est_tokens, sample_size: $row.sample_size, source: "interstat"}}
      )
    ')
  fi
fi

# Apply slicing multiplier if active
MULTIPLIER="1.0"
if [[ "$SLICING" == "true" ]]; then
  MULTIPLIER=$(get_slicing_multiplier)
fi

# Output JSON with estimates (interstat data + defaults for unknown agents)
# The caller will merge this with the list of selected agents
echo "$ESTIMATES" | jq -c --arg mult "$MULTIPLIER" \
  --arg review_default "$(get_default review)" \
  --arg cognitive_default "$(get_default cognitive)" \
  --arg research_default "$(get_default research)" \
  --arg oracle_default "$(get_default oracle)" \
  --arg generated_default "$(get_default generated)" \
  '{
    estimates: .,
    defaults: {
      review: ($review_default | tonumber),
      cognitive: ($cognitive_default | tonumber),
      research: ($research_default | tonumber),
      oracle: ($oracle_default | tonumber),
      generated: ($generated_default | tonumber)
    },
    slicing_multiplier: ($mult | tonumber)
  }'
