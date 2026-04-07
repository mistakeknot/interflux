#!/usr/bin/env bash
# discover-models.sh — Query interrank MCP for Pareto-efficient model candidates
# Usage: discover-models.sh [--force] [--dry-run]
#
# Reads task_queries from budget.yaml model_discovery section,
# calls interrank recommend_model and cost_leaderboard for each tier,
# merges results into model-registry.yaml as candidates.
#
# Progressive enhancement: exits 0 with no changes if interrank unavailable.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BUDGET_FILE="${PLUGIN_DIR}/config/flux-drive/budget.yaml"
REGISTRY_FILE="${PLUGIN_DIR}/config/flux-drive/model-registry.yaml"

FORCE=false
DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) FORCE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) shift ;;
    esac
done

# Check prerequisites
for cmd in jq yq; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "discover-models: $cmd not found, skipping" >&2
        exit 0
    fi
done

# Check refresh interval
if [[ "$FORCE" != true && -f "$REGISTRY_FILE" ]]; then
    last_discovery=$(yq -r '.last_discovery // ""' "$REGISTRY_FILE" 2>/dev/null)
    if [[ -n "$last_discovery" && "$last_discovery" != "null" ]]; then
        interval=$(yq -r '.model_discovery.refresh_interval // "weekly"' "$BUDGET_FILE" 2>/dev/null)
        case "$interval" in
            daily)  max_age=86400 ;;
            weekly) max_age=604800 ;;
            *)      echo "discover-models: refresh_interval=$interval, use --force to override" >&2; exit 0 ;;
        esac
        last_epoch=$(date -d "$last_discovery" +%s 2>/dev/null || echo 0)
        now_epoch=$(date +%s)
        age=$((now_epoch - last_epoch))
        if [[ "$age" -lt "$max_age" ]]; then
            echo "discover-models: last discovery ${age}s ago (< ${max_age}s), skipping. Use --force to override." >&2
            exit 0
        fi
    fi
fi

# Read config
BUDGET_FILTER=$(yq -r '.model_discovery.budget_filter // "low"' "$BUDGET_FILE" 2>/dev/null)
MIN_CONFIDENCE=$(yq -r '.model_discovery.min_confidence // "0.5"' "$BUDGET_FILE" 2>/dev/null)

# Read task queries per tier
CHECKER_TASK=$(yq -r '.model_discovery.task_queries.checker // ""' "$BUDGET_FILE" 2>/dev/null)
ANALYTICAL_TASK=$(yq -r '.model_discovery.task_queries.analytical // ""' "$BUDGET_FILE" 2>/dev/null)
JUDGMENT_TASK=$(yq -r '.model_discovery.task_queries.judgment // ""' "$BUDGET_FILE" 2>/dev/null)

if [[ -z "$CHECKER_TASK" && -z "$ANALYTICAL_TASK" && -z "$JUDGMENT_TASK" ]]; then
    echo "discover-models: no task_queries in budget.yaml, skipping" >&2
    exit 0
fi

# Check if interrank MCP is available (try via claude CLI tool call)
# This script is designed to be called FROM a Claude Code session where
# interrank MCP tools are available. It outputs the MCP tool calls
# that the orchestrator should make, not calling them directly.
#
# Output format: one JSON object per line with the MCP call parameters.
# The orchestrator reads these and makes the actual MCP calls.

echo "discover-models: generating interrank queries for ${BUDGET_FILTER} budget tier" >&2

CANDIDATES="[]"
TODAY=$(date +%Y-%m-%d)

for tier in checker analytical judgment; do
    eval task="\$${tier^^}_TASK"
    [[ -z "$task" ]] && continue

    # Output the interrank query for the orchestrator to execute
    query=$(jq -n \
        --arg task "$task" \
        --arg budget "$BUDGET_FILTER" \
        --arg tier "$tier" \
        '{
            tool: "mcp__plugin_interrank_interrank__recommend_model",
            params: {task: $task, budget: $budget, limit: 5},
            tier: $tier
        }')

    echo "$query"
done

# Also query cost_leaderboard for coding domain (Pareto frontier)
jq -n '{
    tool: "mcp__plugin_interrank_interrank__cost_leaderboard",
    params: {domain: "coding", limit: 10},
    tier: "pareto_coding"
}'

# And agentic domain
jq -n '{
    tool: "mcp__plugin_interrank_interrank__cost_leaderboard",
    params: {domain: "agentic", limit: 10},
    tier: "pareto_agentic"
}'

echo "discover-models: 5 queries generated. Orchestrator should execute and merge results." >&2
