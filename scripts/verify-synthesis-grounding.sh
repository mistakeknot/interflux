#!/usr/bin/env bash
# verify-synthesis-grounding.sh — structural grounding check for synthesized findings (issue #10, C-5)
#
# Synthesis (synthesize.md Step 3.2) delegates ALL collection, dedup, conflict detection,
# and verdict-writing to a single haiku-tier synthesis subagent, and the host is told never
# to read agent output files. Nothing verifies that a finding (ID + severity) in the
# synthesized findings.json traces back to a real agent's machine-parseable Findings Index
# entry. A synthesizer can therefore blend or invent findings ("invented coastline") undetected.
#
# This script is a cheap, deterministic post-synthesis assertion: every finding ID + severity
# in findings.json must be grounded in some agent's Findings Index entry. Ungrounded findings
# are reported; the severity policy below decides the exit code.
#
# Usage: verify-synthesis-grounding.sh <OUTPUT_DIR> [--run-uuid <uuid>] [--strict] [--json]
#
# Grammar (mirrors findings-helper.sh read-indexes grammar + shared-contracts.md §Findings Index):
#   ### Findings Index
#   - SEVERITY | ID | "Section Name" | Title
#   Verdict: safe|needs-changes|risky
# The synthesis-side anchored severity regex matches `^-\s*([Pp][0-9]+)\s*\|`. We match this
# bullet shape directly against each trusted agent file rather than first carving out the
# heading block: the `- P0 | ID | ...` pipe-delimited bullet shape is unique to the Findings
# Index (prose "Issues Found" entries are numbered "1." not `- Pn |`), and matching the bullet
# directly avoids depending on `{2,4}` interval-quantifier awk (unsupported by mawk).
#
# Grounding key: uppercased "<SEVERITY>|<ID>" (e.g. "P0|P0-1"). A synthesized finding is
# grounded iff some agent index entry has the same severity AND id. ID-only match with a
# different severity is reported separately as a severity-mismatch (the synthesizer may have
# legitimately escalated via dedup rule 4 "use highest", so by default this is a warning, not a
# failure, unless --strict).
#
# Quire-mark (issue #6): agent files carry `<!-- run-uuid: {uuid} -->` as the first non-empty
# line. When --run-uuid is supplied (or FLUX_RUN_UUID is set), files whose marker is missing or
# mismatched are treated as Foreign and excluded from the grounding corpus — exactly as
# synthesize.md Step 3.1 does — so a stale prior-run file cannot launder an invented finding.
#
# Failure policy (default): exit 3 if any P0 or P1 synthesized finding is ungrounded; exit 0
# (warn only) if only P2+ findings are ungrounded. Rationale: an ungrounded P0/P1 is a
# fabricated blocking verdict and must fail the run; ungrounded P2 nits are lower-stakes noise.
# With --strict, ANY ungrounded finding (any severity) or any severity-mismatch fails (exit 3).
#
# Exit codes: 0 ok (or warn-only) | 2 invalid invocation / missing inputs | 3 grounding violation
set -euo pipefail

usage() {
  echo "Usage: verify-synthesis-grounding.sh <OUTPUT_DIR> [--run-uuid <uuid>] [--strict] [--json]" >&2
  exit 2
}

output_dir="${1:-}"
[[ -z "$output_dir" ]] && usage
shift || true

run_uuid="${FLUX_RUN_UUID:-}"
strict=0
emit_json=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-uuid) run_uuid="${2:-}"; shift 2 ;;
    --strict)   strict=1; shift ;;
    --json)     emit_json=1; shift ;;
    *) echo "Unknown arg: $1" >&2; usage ;;
  esac
done

if [[ ! -d "$output_dir" ]]; then
  echo "Error: OUTPUT_DIR '$output_dir' not found" >&2
  exit 2
fi

findings_json="$output_dir/findings.json"
if [[ ! -f "$findings_json" ]]; then
  echo "Error: findings.json not found in '$output_dir'" >&2
  exit 2
fi

# --- 1. Build the grounded corpus from agent Findings Index lines -------------------------
# Iterate the agent output files (same exclusion set as findings-helper.sh read-indexes:
# synthesis outputs + reaction files are not agent findings). For each trusted file, harvest
# every `- SEVERITY | ID | ...` bullet — the machine-parseable Findings Index grammar.
#
# Quire-mark filter (issue #6): when run_uuid is known, files whose first non-empty line is not
# `<!-- run-uuid: {uuid} -->` are Foreign and excluded — a stale prior-run file cannot launder
# an invented finding into the grounded corpus.
all_index_lines=""
foreign_count=0
for f in "$output_dir"/*.md; do
  [[ -f "$f" ]] || continue
  base=$(basename "$f" .md)
  case "$base" in
    summary|synthesis|findings) continue ;;
    *.reactions|*.reactions.error) continue ;;
  esac
  if [[ -n "$run_uuid" ]]; then
    first_line=$(awk 'NF{print; exit}' "$f")
    if [[ "$first_line" != "<!-- run-uuid: ${run_uuid} -->" ]]; then
      foreign_count=$((foreign_count + 1))
      continue
    fi
  fi
  all_index_lines+=$(cat "$f")$'\n'
done

# grounded_keys: "SEVERITY|ID" ; grounded_ids: bare IDs (for severity-mismatch detection).
# mawk-compatible: [Pp][0-9]+ only, no interval quantifiers.
grounded_keys=$(printf '%s' "$all_index_lines" | awk '
  {
    line = $0
    # Anchored severity at start of an index bullet: ^-\s*([Pp][0-9]+)\s*\|
    if (line ~ /^-[ \t]*[Pp][0-9]+[ \t]*\|/) {
      if (match(line, /[Pp][0-9]+/)) sev = toupper(substr(line, RSTART, RLENGTH)); else next
      nf = split(line, parts, "|")
      if (nf < 2) next
      id = parts[2]
      gsub(/^[ \t]+|[ \t]+$/, "", id)
      if (id == "") next
      print sev "|" id
    }
  }
' | sort -u)

grounded_ids=$(printf '%s' "$grounded_keys" | awk -F'|' 'NF>=2 {print $2}' | sort -u)

# --- 2. Extract synthesized findings (id + severity) from findings.json --------------------
synth_findings=$(jq -r '
  (.findings // [])[]
  | select((.id // "") != "")
  | ((.severity // "") | ascii_upcase) + "|" + (.id|tostring)
' "$findings_json" 2>/dev/null || true)

if [[ -z "$synth_findings" ]]; then
  # No findings to ground — vacuously OK.
  if [[ "$emit_json" -eq 1 ]]; then
    jq -n --argjson foreign "$foreign_count" \
      '{status:"ok", checked:0, ungrounded:[], severity_mismatch:[], foreign_skipped:$foreign}'
  else
    echo "grounding: OK — 0 synthesized findings to verify (${foreign_count} foreign files skipped)"
  fi
  exit 0
fi

# --- 3. Classify each synthesized finding -------------------------------------------------
ungrounded=()          # "SEVERITY|ID" — no index entry with this id at all
sev_mismatch=()        # "SEVERITY|ID" — id exists in some index but with a different severity
checked=0
while IFS= read -r key; do
  [[ -z "$key" ]] && continue
  checked=$((checked + 1))
  sev="${key%%|*}"
  id="${key#*|}"
  if printf '%s\n' "$grounded_keys" | grep -qxF "$key"; then
    continue  # exact severity+id grounded
  fi
  if printf '%s\n' "$grounded_ids" | grep -qxF "$id"; then
    sev_mismatch+=("$key")   # id present, severity differs (possibly escalated by dedup rule 4)
  else
    ungrounded+=("$key")     # id absent from every trusted index — fabricated
  fi
done <<< "$synth_findings"

# --- 4. Apply failure policy --------------------------------------------------------------
violation=0
blocking_ungrounded=()
for key in "${ungrounded[@]:-}"; do
  [[ -z "$key" ]] && continue
  sev="${key%%|*}"
  if [[ "$strict" -eq 1 ]]; then
    violation=1; blocking_ungrounded+=("$key")
  elif [[ "$sev" == "P0" || "$sev" == "P1" ]]; then
    violation=1; blocking_ungrounded+=("$key")
  fi
done
if [[ "$strict" -eq 1 && "${#sev_mismatch[@]}" -gt 0 ]]; then
  violation=1
fi

# --- 5. Report ----------------------------------------------------------------------------
if [[ "$emit_json" -eq 1 ]]; then
  ung_json=$(printf '%s\n' "${ungrounded[@]:-}" | sed '/^$/d' | jq -R . | jq -s .)
  mm_json=$(printf '%s\n' "${sev_mismatch[@]:-}" | sed '/^$/d' | jq -R . | jq -s .)
  status="ok"
  if [[ "$violation" -eq 1 ]]; then
    status="violation"
  elif [[ "${#ungrounded[@]}" -gt 0 || "${#sev_mismatch[@]}" -gt 0 ]]; then
    status="warn"
  fi
  jq -n \
    --arg status "$status" \
    --argjson checked "$checked" \
    --argjson ungrounded "$ung_json" \
    --argjson severity_mismatch "$mm_json" \
    --argjson foreign "$foreign_count" \
    --argjson strict "$strict" \
    '{status:$status, checked:$checked, ungrounded:$ungrounded, severity_mismatch:$severity_mismatch, foreign_skipped:$foreign, strict:($strict==1)}'
else
  if [[ "$violation" -eq 1 ]]; then
    echo "grounding: VIOLATION — synthesized findings not backed by any agent Findings Index entry:" >&2
    for key in "${blocking_ungrounded[@]:-}"; do
      [[ -z "$key" ]] && continue
      echo "  - ungrounded: ${key%%|*} ${key#*|} (no index entry with this id)" >&2
    done
    if [[ "$strict" -eq 1 ]]; then
      for key in "${sev_mismatch[@]:-}"; do
        [[ -z "$key" ]] && continue
        echo "  - severity-mismatch: ${key%%|*} ${key#*|} (id exists in an index under a different severity)" >&2
      done
    fi
  else
    echo "grounding: OK — ${checked} synthesized findings verified against agent indexes (${foreign_count} foreign files skipped)"
  fi
  # Non-fatal advisories
  if [[ "$strict" -eq 0 ]]; then
    for key in "${ungrounded[@]:-}"; do
      [[ -z "$key" ]] && continue
      sev="${key%%|*}"
      [[ "$sev" == "P0" || "$sev" == "P1" ]] && continue
      echo "grounding: warn — ungrounded ${sev} finding ${key#*|} (below blocking threshold)" >&2
    done
    for key in "${sev_mismatch[@]:-}"; do
      [[ -z "$key" ]] && continue
      echo "grounding: warn — ${key%%|*} ${key#*|} grounded by id but severity differs from index (possible dedup escalation)" >&2
    done
  fi
fi

[[ "$violation" -eq 1 ]] && exit 3
exit 0
