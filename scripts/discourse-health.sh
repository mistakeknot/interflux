#!/usr/bin/env bash
# discourse-health.sh — Sawyer Flow Envelope diagnostic (rsj.7)
# Standalone tool for computing discourse health metrics from synthesis output.
# The canonical path for findings.json is the synthesis agent (synthesize-review.md).
# This script is for CLI diagnostics and post-hoc analysis.
#
# Usage: discourse-health.sh <OUTPUT_DIR> [--config <sawyer-config.yaml>]
# Output: JSON to stdout + writes {OUTPUT_DIR}/discourse-health.json
set -euo pipefail

output_dir="${1:?Usage: discourse-health.sh <OUTPUT_DIR>}"
shift

# Parse optional config path
config_path=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) config_path="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

findings_file="$output_dir/findings.json"
if [[ ! -f "$findings_file" ]]; then
  echo '{"error":"findings.json not found","flow_state":"unknown"}' | tee "$output_dir/discourse-health.json"
  exit 1
fi

# Default thresholds (match discourse-sawyer.yaml)
gini_max=0.3
novelty_min=0.1
relevance_min=0.7
degraded_gini=0.5
degraded_novelty=0.05
degraded_relevance=0.5

# Override from config if provided
if [[ -n "$config_path" && -f "$config_path" ]]; then
  _read_yaml() { python3 -c "import yaml,sys; d=yaml.safe_load(open('$config_path')); print(d$1)" 2>/dev/null || echo "$2"; }
  gini_max=$(_read_yaml "['flow_envelope']['participation_gini_max']" "$gini_max")
  novelty_min=$(_read_yaml "['flow_envelope']['novelty_rate_min']" "$novelty_min")
  relevance_min=$(_read_yaml "['flow_envelope']['response_relevance_min']" "$relevance_min")
fi

# Compute metrics from findings.json using jq
metrics=$(jq -r '
  .findings as $f |
  # Agent finding counts
  ($f | group_by(.agent) | map({key: .[0].agent, value: length}) | from_entries) as $agent_counts |
  # Participation Gini
  ($agent_counts | to_entries | map(.value) | sort) as $sorted |
  ($sorted | length) as $n |
  (if $n <= 1 then 0
   else
     ($sorted | add) as $total |
     (if $total == 0 then 0
      else
        ([range($n)] | map(. as $i | ($i + 1) * $sorted[$i]) | add) as $weighted |
        ((2 * $weighted) / ($n * $total)) - (($n + 1) / $n)
      end)
   end) as $gini |
  # Novelty rate: findings unique to one agent
  ($f | length) as $total_findings |
  (if $total_findings == 0 then 0
   else
     ($f | map(
       if .convergence_corrected != null then .convergence_corrected
       else .convergence // 1
       end
     ) | map(select(. == 1)) | length) as $novel |
     ($novel / $total_findings)
   end) as $novelty |
  # Response relevance: findings with evidence sources
  (if $total_findings == 0 then 0
   else
     ($f | map(select(.evidence_sources != null and (.evidence_sources | length) > 0)) | length) as $with_evidence |
     ($with_evidence / $total_findings)
   end) as $relevance |
  {
    participation_gini: ($gini * 1000 | round / 1000),
    novelty_rate: ($novelty * 1000 | round / 1000),
    response_relevance: ($relevance * 1000 | round / 1000),
    agent_finding_counts: $agent_counts,
    total_findings: $total_findings,
    metrics_source: "findings.json"
  }
' "$findings_file")

# Determine flow state
gini=$(echo "$metrics" | jq -r '.participation_gini')
novelty=$(echo "$metrics" | jq -r '.novelty_rate')
relevance=$(echo "$metrics" | jq -r '.response_relevance')

flow_state="unhealthy"
warnings='[]'

if python3 -c "exit(0 if $gini <= $gini_max and $novelty >= $novelty_min and $relevance >= $relevance_min else 1)" 2>/dev/null; then
  flow_state="healthy"
elif python3 -c "exit(0 if $gini <= $degraded_gini and $novelty >= $degraded_novelty and $relevance >= $degraded_relevance else 1)" 2>/dev/null; then
  flow_state="degraded"
fi

# Build warnings
warn_parts=()
if python3 -c "exit(0 if $gini > $gini_max else 1)" 2>/dev/null; then
  warn_parts+=("\"participation_gini ($gini) exceeds threshold ($gini_max)\"")
fi
if python3 -c "exit(0 if $novelty < $novelty_min else 1)" 2>/dev/null; then
  warn_parts+=("\"novelty_rate ($novelty) below threshold ($novelty_min)\"")
fi
if python3 -c "exit(0 if $relevance < $relevance_min else 1)" 2>/dev/null; then
  warn_parts+=("\"response_relevance ($relevance) below threshold ($relevance_min)\"")
fi
if [[ ${#warn_parts[@]} -gt 0 ]]; then
  warnings=$(printf '%s\n' "${warn_parts[@]}" | jq -s '.')
fi

# Merge and output
result=$(echo "$metrics" | jq --arg fs "$flow_state" --argjson w "$warnings" '. + {flow_state: $fs, warnings: $w}')
echo "$result" | tee "$output_dir/discourse-health.json"
