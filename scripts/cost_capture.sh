#!/usr/bin/env bash
# cost_capture.sh — sum interstat session-cost across teammate session IDs.
#
# Reads newline-separated session IDs from stdin. For each, calls
# `interstat session-cost --session=<id>` and sums `cost_usd`.
#
# Per F1.3 probe verdict (lead-only attribution): each teammate has its own session_id,
# so we MUST iterate per-teammate. There is no parent-aggregated path.
#
# Transient-empty handling (P1 from plan review):
# * If any session returns zero rows, retry once after 5s grace.
# * If still zero after retry, mark the run incomplete — do NOT silently sum what's
#   available and present it as final.
#
# Stdout: one JSON object:
#   {
#     "status": "complete" | "incomplete",
#     "reason": "..." (only when status=incomplete),
#     "total_usd": <number> | null,
#     "per_session": [{"session_id": "...", "cost_usd": <num>, "rows": <int>}, ...]
#   }
#
# Stderr: human-readable progress + warnings.

set -u

GRACE_SEC="${INTERFLUX_TEAMS_COST_GRACE_SEC:-5}"
INTERSTAT_SCRIPT="${INTERSTAT_SCRIPT:-/home/mk/projects/Sylveste/interverse/interstat/scripts/cost-query.sh}"

if [[ ! -f "$INTERSTAT_SCRIPT" ]]; then
    cat <<EOF
{
  "status": "incomplete",
  "reason": "interstat cost-query.sh not found at $INTERSTAT_SCRIPT",
  "total_usd": null,
  "per_session": []
}
EOF
    exit 0
fi

# Read session IDs from stdin, drop blanks
mapfile -t session_ids < <(grep -v '^[[:space:]]*$' || true)

if [[ "${#session_ids[@]}" -eq 0 ]]; then
    cat <<EOF
{
  "status": "incomplete",
  "reason": "no session ids supplied on stdin",
  "total_usd": null,
  "per_session": []
}
EOF
    exit 0
fi

total=0
gap_reason=""
per_session_json="["
first=1

query_one() {
    local sid="$1"
    bash "$INTERSTAT_SCRIPT" session-cost --session="$sid" 2>/dev/null
}

for sid in "${session_ids[@]}"; do
    # Validate format. Record an explicit per_session entry on rejection so the caller
    # can see attribution gaps without having to compare input vs output cardinality.
    if [[ ! "$sid" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        gap_reason="invalid session_id format: $sid"
        sid_safe=${sid//\"/\\\"}
        [[ $first -eq 0 ]] && per_session_json+=","
        per_session_json+="{\"session_id\":\"$sid_safe\",\"rows\":0,\"cost_usd\":null,\"reason\":\"invalid_format\"}"
        first=0
        continue
    fi
    # Initial query
    out=$(query_one "$sid")
    rows=$(echo "$out" | jq -r '.[0].agent_runs // 0' 2>/dev/null || echo 0)
    cost=$(echo "$out" | jq -r '.[0].cost_usd // 0' 2>/dev/null || echo 0)

    # Retry once after grace if rows == 0
    if [[ "$rows" == "0" ]]; then
        echo "cost_capture: session $sid returned 0 rows; retrying after ${GRACE_SEC}s grace..." >&2
        sleep "$GRACE_SEC"
        out=$(query_one "$sid")
        rows=$(echo "$out" | jq -r '.[0].agent_runs // 0' 2>/dev/null || echo 0)
        cost=$(echo "$out" | jq -r '.[0].cost_usd // 0' 2>/dev/null || echo 0)
        if [[ "$rows" == "0" ]]; then
            gap_reason="session $sid still 0 rows after retry — log not flushed"
        fi
    fi

    # Append per-session record
    [[ $first -eq 0 ]] && per_session_json+=","
    per_session_json+="{\"session_id\":\"$sid\",\"rows\":$rows,\"cost_usd\":$cost}"
    first=0

    # Sum (numeric add via awk to be safe with floats)
    total=$(awk "BEGIN { printf \"%.4f\", $total + $cost }")
done

per_session_json+="]"

if [[ -n "$gap_reason" ]]; then
    cat <<EOF
{
  "status": "incomplete",
  "reason": "$gap_reason",
  "total_usd": null,
  "per_session": $per_session_json
}
EOF
else
    cat <<EOF
{
  "status": "complete",
  "total_usd": $total,
  "per_session": $per_session_json
}
EOF
fi
