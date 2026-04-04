#!/usr/bin/env bash
# findings-helper.sh — read/write helpers for flux-drive intermediate findings
# Usage:
#   findings-helper.sh write <findings_file> <severity> <agent> <category> <summary> [file_refs...]
#   findings-helper.sh read <findings_file> [--severity blocking|notable|all]
#   findings-helper.sh read-indexes <output_dir>
#   findings-helper.sh convergence <output_dir>
set -euo pipefail

cmd="${1:-}"
shift || true

case "$cmd" in
  write)
    findings_file="$1"; shift
    severity="$1"; shift
    agent="$1"; shift
    category="$1"; shift
    summary="$1"; shift
    # Remaining args are file_refs
    refs="[]"
    if [[ $# -gt 0 ]]; then
      refs=$(printf '%s\n' "$@" | jq -R . | jq -s .)
    fi
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    # Build JSON line in memory, then write under flock to serialize concurrent appends.
    # Note: echo >> is NOT atomic on regular files (PIPE_BUF only applies to pipes).
    line=$(jq -n -c \
      --arg sev "$severity" \
      --arg agt "$agent" \
      --arg cat "$category" \
      --arg sum "$summary" \
      --arg ts "$timestamp" \
      --argjson refs "$refs" \
      '{severity:$sev, agent:$agt, category:$cat, summary:$sum, file_refs:$refs, timestamp:$ts}')
    (
      flock -x 200
      echo "$line" >> "$findings_file"
    ) 200>"${findings_file}.lock"
    ;;
  read)
    findings_file="$1"; shift
    filter="${1:-all}"
    if [[ ! -f "$findings_file" ]]; then
      echo "[]"
      exit 0
    fi
    # Safe read: filter out incomplete trailing lines before parsing
    safe_content=$(grep -a '^{' "$findings_file" || true)
    if [[ -z "$safe_content" ]]; then
      echo "[]"
      exit 0
    fi
    case "$filter" in
      blocking) echo "$safe_content" | jq -s '[.[] | select(.severity == "blocking")]' ;;
      notable)  echo "$safe_content" | jq -s '[.[] | select(.severity == "notable")]' ;;
      all)      echo "$safe_content" | jq -s '.' ;;
      *)        echo "$safe_content" | jq -s '.' ;;
    esac
    ;;
  read-indexes)
    # Extract Findings Index blocks from all agent .md files in a directory
    # Usage: findings-helper.sh read-indexes <output_dir>
    output_dir="$1"; shift
    if [[ ! -d "$output_dir" ]]; then
      echo "Error: directory '$output_dir' not found" >&2
      exit 1
    fi
    for f in "$output_dir"/*.md; do
      [[ -f "$f" ]] || continue
      base=$(basename "$f" .md)
      # Skip synthesis outputs and reaction files
      case "$base" in
        summary|synthesis|findings) continue ;;
        *.reactions|*.reactions.error) continue ;;
      esac
      # Extract between "## Findings Index" (any heading depth 2-4, case-insensitive) and next heading
      awk '
        /^#{2,4}[[:space:]]+[Ff]indings[[:space:]]+[Ii]ndex/ { found=1; next }
        found && /^#{2,4}[[:space:]]/ { exit }
        found { print }
      ' "$f" | while IFS= read -r line; do
        if [[ -n "$line" ]]; then echo "$base	$line"; fi
      done || true
    done
    ;;
  convergence)
    # Compute overlap ratio for convergence gate
    # Usage: findings-helper.sh convergence <output_dir>
    # Output: overlap_ratio<TAB>total_findings<TAB>overlapping_findings<TAB>agent_count
    output_dir="$1"; shift
    if [[ ! -d "$output_dir" ]]; then
      echo "Error: directory '$output_dir' not found" >&2
      exit 1
    fi

    # Collect all P0/P1 findings with agent attribution via read-indexes
    raw=$("$0" read-indexes "$output_dir")
    if [[ -z "$raw" ]]; then
      printf '0.0\t0\t0\t0\n'
      exit 0
    fi

    # Parse: agent<TAB>- SEVERITY | ID | "Section" | Title
    # Extract severity and normalized title, count agents per finding
    awk -F'\t' '
    {
      agent = $1
      line = $2
      # Extract severity (P0, P1, etc.)
      if (match(line, /[Pp][0-2]/)) {
        sev = toupper(substr(line, RSTART, RLENGTH))
      } else {
        next
      }
      # Only count P0 and P1
      if (sev != "P0" && sev != "P1") next

      # Normalize title: strip severity/ID prefix, lowercase, strip punctuation
      # Preserve hyphens as spaces to avoid colliding unrelated titles (RXN-04)
      title = line
      gsub(/^-[[:space:]]*/, "", title)
      gsub(/[Pp][0-9]+[[:space:]]*\|[[:space:]]*[A-Za-z]+-[0-9]+[[:space:]]*\|[[:space:]]*"[^"]*"[[:space:]]*\|[[:space:]]*/, "", title)
      gsub(/-/, " ", title)
      gsub(/[^a-zA-Z0-9 ]/, "", title)
      title = tolower(title)
      gsub(/[[:space:]]+/, " ", title)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", title)

      # Track agents per normalized title
      key = title
      if (!(key SUBSEP agent in seen)) {
        seen[key SUBSEP agent] = 1
        agent_count[key]++
      }
      if (!(agent in agents)) {
        agents[agent] = 1
        total_agents++
      }
      if (!(key in findings)) {
        findings[key] = 1
        total_findings++
      }
    }
    END {
      overlapping = 0
      for (k in findings) {
        if (agent_count[k] >= 2) overlapping++
      }
      if (total_findings > 0) {
        ratio = overlapping / total_findings
      } else {
        ratio = 0.0
      }
      printf "%.4f\t%d\t%d\t%d\n", ratio, total_findings, overlapping, total_agents
    }
    ' <<< "$raw"
    ;;
  *)
    echo "Usage: findings-helper.sh {write|read|read-indexes|convergence} <findings_file|output_dir> ..." >&2
    exit 1
    ;;
esac
