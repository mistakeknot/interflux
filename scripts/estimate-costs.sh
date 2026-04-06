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

# Validate MODEL before SQL interpolation (SEC-001)
if [[ ! "$MODEL" =~ ^[a-zA-Z0-9_.:-]+$ ]]; then
  echo "Error: invalid model name '$MODEL'" >&2
  exit 1
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
  # Return both billing tokens (input+output, for budget) and total tokens (for context/reporting)
  INTERSTAT_DATA=$(sqlite3 -json "$DB_PATH" "
    SELECT REPLACE(agent_name, 'interflux:', '') as agent_name,
           CAST(ROUND(AVG(COALESCE(input_tokens,0) + COALESCE(output_tokens,0))) AS INTEGER) as est_billing,
           CAST(ROUND(AVG(total_tokens)) AS INTEGER) as est_tokens,
           COUNT(*) as sample_size
    FROM agent_runs
    WHERE (model = '${MODEL}' OR model IS NULL)
      AND total_tokens IS NOT NULL
    GROUP BY REPLACE(agent_name, 'interflux:', '')
    HAVING COUNT(*) >= 3
    ORDER BY agent_name;
  " 2>/dev/null || echo "[]")

  if [[ "$INTERSTAT_DATA" != "[]" && -n "$INTERSTAT_DATA" ]]; then
    ESTIMATES=$(echo "$INTERSTAT_DATA" | jq -c '
      reduce .[] as $row ({};
        . + {($row.agent_name): {est_tokens: $row.est_tokens, est_billing: $row.est_billing, sample_size: $row.sample_size, source: "interstat"}}
      )
    ')
  fi
fi

# --- Fleet registry fallback for agents not in interstat (>= 3 runs) ---
_find_lib_fleet() {
  local candidates=()
  # 1. Explicit env var (highest priority, works in all deployment contexts)
  [[ -n "${CLAVAIN_SOURCE_DIR:-}" ]] && candidates+=("${CLAVAIN_SOURCE_DIR}/scripts/lib-fleet.sh")
  # 2. Plugin cache (deployed context)
  local cache_dir="${HOME}/.claude/plugins/cache"
  if [[ -d "$cache_dir" ]]; then
    local latest
    latest="$(ls -d "$cache_dir"/*/clavain/*/scripts/lib-fleet.sh 2>/dev/null | tail -1)"
    [[ -n "$latest" ]] && candidates+=("$latest")
  fi
  # 3. Monorepo relative path (development context, last resort)
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  candidates+=("$script_dir/../../../os/Clavain/scripts/lib-fleet.sh")
  for f in "${candidates[@]}"; do
    if [[ -f "$f" ]]; then
      echo "$f"
      return 0
    fi
  done
  return 1
}

_FLEET_AVAILABLE=false
LIB_FLEET="$(_find_lib_fleet 2>/dev/null)" || LIB_FLEET=""
if [[ -n "$LIB_FLEET" ]]; then
  # Source lib-fleet.sh; it requires yq which we don't mandate here,
  # so suppress errors and check if it loaded successfully
  source "$LIB_FLEET" 2>/dev/null && _FLEET_AVAILABLE=true || true
fi

if [[ "$_FLEET_AVAILABLE" == true ]]; then
  # Get all agents in registry that aren't already in interstat estimates
  fleet_agents="$(fleet_list 2>/dev/null)" || fleet_agents=""
  while IFS= read -r fleet_agent; do
    [[ -z "$fleet_agent" ]] && continue
    # Skip if already in interstat estimates (>= 3 runs)
    if echo "$ESTIMATES" | jq -e --arg a "$fleet_agent" '.[$a]' >/dev/null 2>&1; then
      continue
    fi
    # Try fleet registry (actual_tokens or cold_start_tokens)
    fleet_est="$(INTERSTAT_DB="$DB_PATH" fleet_cost_estimate_live "$fleet_agent" "$MODEL" 2>/dev/null)" || continue
    if [[ -n "$fleet_est" && "$fleet_est" != "0" ]]; then
      ESTIMATES="$(echo "$ESTIMATES" | jq -c --arg a "$fleet_agent" --argjson t "$fleet_est" \
        '. + {($a): {est_tokens: $t, sample_size: 0, source: "fleet-registry"}}')"
    fi
  done <<< "$fleet_agents"
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
