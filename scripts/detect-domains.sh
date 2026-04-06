#!/usr/bin/env bash
# detect-domains.sh — Deterministic domain detection from index.yaml signals
# Usage: detect-domains.sh <project_root>
# Output: JSON array of detected domains with confidence scores
# Example: [{"domain":"web-api","confidence":0.45},{"domain":"cli-tool","confidence":0.35}]
#
# Algorithm: For each domain in index.yaml, count matching signals
# (directories, files, frameworks, keywords). Domain is "detected" when
# matched_signals / total_signals >= min_confidence.
#
# Performance: Targets < 5s on repos up to 10K files. Scans maxdepth 2
# for dirs, maxdepth 2 for files, and samples 10 source files for keywords.
set -euo pipefail

PROJECT_ROOT="${1:?Usage: detect-domains.sh <project_root>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INDEX_FILE="${SCRIPT_DIR}/../config/flux-drive/domains/index.yaml"

if [[ ! -f "$INDEX_FILE" ]]; then
    echo "[]"
    exit 0
fi

# We need yq for YAML parsing — fall back gracefully
if ! command -v yq >/dev/null 2>&1; then
    echo "[]"
    exit 0
fi

EXCLUDE=(-not -path '*/.git/*' -not -path '*/node_modules/*' -not -path '*/vendor/*' -not -path '*/__pycache__/*' -not -path '*/.next/*' -not -path '*/target/*' -not -path '*/.beads/*')

# Collect project signals once (cache in temp files for speed)
TMPDIR_WORK=$(mktemp -d)
trap 'rm -rf "$TMPDIR_WORK"' EXIT

# 1. Directories (depth 2, basenames only)
find "$PROJECT_ROOT" -maxdepth 2 -type d "${EXCLUDE[@]}" 2>/dev/null \
    | sed "s|^${PROJECT_ROOT}/||" | tr '[:upper:]' '[:lower:]' > "$TMPDIR_WORK/dirs"

# 2. File basenames (depth 2, unique)
find "$PROJECT_ROOT" -maxdepth 2 -type f "${EXCLUDE[@]}" 2>/dev/null \
    | sed 's|.*/||' | sort -u | tr '[:upper:]' '[:lower:]' > "$TMPDIR_WORK/files"

# 3. Framework detection from build files
{
    if [[ -f "$PROJECT_ROOT/package.json" ]]; then
        python3 -c "
import json
try:
    d=json.load(open('$PROJECT_ROOT/package.json'))
    deps=list((d.get('dependencies',{}) or {}).keys()) + list((d.get('devDependencies',{}) or {}).keys())
    print(' '.join(deps))
except: pass
" 2>/dev/null || true
    fi
    if [[ -f "$PROJECT_ROOT/Cargo.toml" ]]; then
        grep -oE '^[a-z][-a-z0-9_]* *=' "$PROJECT_ROOT/Cargo.toml" 2>/dev/null | sed 's/ *=//' || true
    fi
    if [[ -f "$PROJECT_ROOT/go.mod" ]]; then
        grep -v '^module\|^go \|^$\|^)' "$PROJECT_ROOT/go.mod" 2>/dev/null | grep -oE '[a-z][-a-z0-9]*$' || true
    fi
    for f in "$PROJECT_ROOT/requirements.txt" "$PROJECT_ROOT/pyproject.toml"; do
        [[ -f "$f" ]] && grep -oE '^[a-zA-Z][-a-zA-Z0-9_]*' "$f" 2>/dev/null || true
    done
} | tr '[:upper:]' '[:lower:]' | sort -u > "$TMPDIR_WORK/frameworks"

# 4. Keyword scan — sample 10 source files per language (fast)
KEYWORD_FILES=()
for ext in go rs py ts tsx js jsx rb java kt swift c h sh; do
    while IFS= read -r f; do
        KEYWORD_FILES+=("$f")
    done < <(find "$PROJECT_ROOT" -maxdepth 3 -name "*.${ext}" "${EXCLUDE[@]}" 2>/dev/null | head -10)
done
if [[ ${#KEYWORD_FILES[@]} -gt 0 ]]; then
    grep -ohE '[a-zA-Z_]{4,}' "${KEYWORD_FILES[@]}" 2>/dev/null | sort -u | tr '[:upper:]' '[:lower:]' > "$TMPDIR_WORK/keywords"
else
    touch "$TMPDIR_WORK/keywords"
fi

# Score each domain
DOMAIN_COUNT=$(yq '.domains | length' "$INDEX_FILE")
RESULTS="[]"

for ((i=0; i<DOMAIN_COUNT; i++)); do
    PROFILE=$(yq -r ".domains[$i].profile" "$INDEX_FILE")
    MIN_CONF=$(yq -r ".domains[$i].min_confidence" "$INDEX_FILE")
    total=0
    matched=0

    # Check directories
    while IFS= read -r signal; do
        [[ -z "$signal" ]] && continue
        signal=$(echo "$signal" | tr '[:upper:]' '[:lower:]')
        total=$((total + 1))
        grep -qF "$signal" "$TMPDIR_WORK/dirs" && matched=$((matched + 1))
    done < <(yq -r ".domains[$i].signals.directories[]" "$INDEX_FILE" 2>/dev/null)

    # Check files (pattern matching)
    while IFS= read -r signal; do
        [[ -z "$signal" ]] && continue
        signal=$(echo "$signal" | tr '[:upper:]' '[:lower:]')
        total=$((total + 1))
        pattern=$(echo "$signal" | sed 's/\./\\./g; s/\*/.*/g')
        grep -qE "$pattern" "$TMPDIR_WORK/files" && matched=$((matched + 1))
    done < <(yq -r ".domains[$i].signals.files[]" "$INDEX_FILE" 2>/dev/null)

    # Check frameworks
    while IFS= read -r signal; do
        [[ -z "$signal" ]] && continue
        signal=$(echo "$signal" | tr '[:upper:]' '[:lower:]')
        total=$((total + 1))
        grep -qiw "$signal" "$TMPDIR_WORK/frameworks" && matched=$((matched + 1))
    done < <(yq -r ".domains[$i].signals.frameworks[]" "$INDEX_FILE" 2>/dev/null)

    # Check keywords
    while IFS= read -r signal; do
        [[ -z "$signal" ]] && continue
        signal=$(echo "$signal" | tr '[:upper:]' '[:lower:]')
        total=$((total + 1))
        grep -qF "$signal" "$TMPDIR_WORK/keywords" && matched=$((matched + 1))
    done < <(yq -r ".domains[$i].signals.keywords[]" "$INDEX_FILE" 2>/dev/null)

    # Calculate confidence
    if [[ "$total" -gt 0 ]]; then
        # Use bc for floating point, fall back to awk
        confidence=$(echo "scale=2; $matched / $total" | bc 2>/dev/null || awk "BEGIN{printf \"%.2f\", $matched/$total}")
        meets_threshold=$(echo "$confidence >= $MIN_CONF" | bc 2>/dev/null || awk "BEGIN{print ($confidence >= $MIN_CONF) ? 1 : 0}")
        if [[ "$meets_threshold" == "1" ]]; then
            RESULTS=$(echo "$RESULTS" | jq -c --arg d "$PROFILE" --arg c "$confidence" --argjson m "$matched" --argjson t "$total" \
                '. + [{"domain": $d, "confidence": ($c | tonumber), "matched": $m, "total": $t}]')
        fi
    fi
done

# Sort by confidence descending
echo "$RESULTS" | jq -c 'sort_by(-.confidence)'
