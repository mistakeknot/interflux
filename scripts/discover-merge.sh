#!/usr/bin/env bash
# discover-merge.sh — merge interrank query results into model-registry.yaml
# Usage: discover-merge.sh <results-json-file>
# Called by orchestrator after executing interrank MCP queries from discover-models.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY_FILE="${MODEL_REGISTRY:-${SCRIPT_DIR}/../config/flux-drive/model-registry.yaml}"
BUDGET_FILE="${SCRIPT_DIR}/../config/flux-drive/budget.yaml"
RESULTS_FILE="${1:-}"

[[ -n "$RESULTS_FILE" && -f "$RESULTS_FILE" ]] || { echo "Usage: discover-merge.sh <results.json>" >&2; exit 1; }

export _DM_BUDGET="$BUDGET_FILE"
MIN_CONFIDENCE=$(python3 -c "import yaml, os; print(yaml.safe_load(open(os.environ['_DM_BUDGET'])).get('model_discovery',{}).get('min_confidence', 0.5))" 2>/dev/null)
TODAY=$(date +%Y-%m-%d)

# Parse results, filter by confidence, merge into registry (UNDER FLOCK)
export _DM_REGISTRY="$REGISTRY_FILE"
export _DM_RESULTS="$RESULTS_FILE"
export _DM_MIN_CONF="$MIN_CONFIDENCE"
export _DM_TODAY="$TODAY"

# flock -w 30 bounds the wait if a concurrent fluxbench-{qualify,challenger,drift}
# holds the registry lock. Without timeout, discover-merge deadlocks indefinitely.
# Exit 3 inside the subshell signals timeout; otherwise non-zero is a real failure.
_dm_flock_rc=0
(
flock -w 30 -x 201 || exit 3

python3 -c "
import yaml, json, os, sys, re

VALID_SLUG = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9/_.-]{0,127}$')

reg_path = os.environ['_DM_REGISTRY']
results_path = os.environ['_DM_RESULTS']
min_conf = float(os.environ['_DM_MIN_CONF'])
today = os.environ['_DM_TODAY']

with open(reg_path) as f:
    reg = yaml.safe_load(f) or {}

if 'models' not in reg or reg['models'] is None:
    reg['models'] = {}

with open(results_path) as f:
    results = json.load(f)

added = 0
skipped = 0
for candidate in results.get('candidates', []):
    slug = candidate.get('model_id', '')
    if not slug or not VALID_SLUG.match(slug):
        print(f'  SKIP: invalid slug format: {repr(slug)}', file=sys.stderr)
        skipped += 1
        continue
    confidence = candidate.get('confidence', 0)
    if confidence < min_conf:
        skipped += 1
        continue
    if slug in reg['models']:
        print(f'  Duplicate: {slug} already in registry, skipping', file=sys.stderr)
        skipped += 1
        continue

    reg['models'][slug] = {
        'provider': 'openrouter',
        'model_family': candidate.get('family', 'unknown'),
        'eligible_tiers': candidate.get('tiers', ['checker']),
        'status': 'candidate',
        'discovered': today,
        'interrank_score': candidate.get('score', 0),
        'interrank_confidence': confidence,
        'cost_per_mtok': candidate.get('cost_per_mtok', 0),
        'qualified_via': None,
        'prompt_content_policy': 'fixtures_only',
        'qualification': {
            'shadow_runs': 0,
            'format_compliance': None,
            'finding_recall': None,
            'severity_accuracy': None,
            'qualified_date': None,
        },
        'fluxbench': None,
        'qualified_baseline': None,
    }
    added += 1
    print(f'  Added: {slug} (score={candidate.get(\"score\",0):.2f}, cost=\${candidate.get(\"cost_per_mtok\",0):.2f}/MTok)', file=sys.stderr)

reg['last_discovery'] = today
reg['last_discovery_source'] = results.get('source', 'interrank')

with open(reg_path, 'w') as f:
    yaml.dump(reg, f, default_flow_style=False, sort_keys=False)

print(f'Discovery complete: {added} added, {skipped} skipped', file=sys.stderr)
"

) 201>"${REGISTRY_FILE}.lock" || _dm_flock_rc=$?

if [[ $_dm_flock_rc -eq 3 ]]; then
  echo "discover-merge: lock timeout after 30s on ${REGISTRY_FILE}.lock" >&2
  exit 1
elif [[ $_dm_flock_rc -ne 0 ]]; then
  echo "discover-merge: registry write failed (rc=$_dm_flock_rc)" >&2
  exit 1
fi

echo "Registry updated: $REGISTRY_FILE" >&2
