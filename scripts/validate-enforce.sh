#!/usr/bin/env bash
# validate-enforce.sh — pre-flight check before activating enforce mode
# Returns 0 if safe to activate, 1 with reason if not
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="${SCRIPT_DIR}/../config/flux-drive/model-registry.yaml"
BUDGET="${SCRIPT_DIR}/../config/flux-drive/budget.yaml"
THRESHOLDS="${SCRIPT_DIR}/../config/flux-drive/fluxbench-thresholds.yaml"

# Check 1: calibrated thresholds exist
if [[ ! -f "$THRESHOLDS" ]]; then
  echo "FAIL: fluxbench-thresholds.yaml not found. Run fluxbench-calibrate.sh first." >&2
  exit 1
fi

export _VE_THRESHOLDS="$THRESHOLDS"
source_check=$(python3 -c "import yaml, os; t=yaml.safe_load(open(os.environ['_VE_THRESHOLDS'])); print(t.get('source',''))" 2>/dev/null) || source_check=""
if [[ "$source_check" != "claude-baseline" ]]; then
  echo "FAIL: thresholds source is '$source_check' (need 'claude-baseline'). Run fluxbench-calibrate.sh in real mode." >&2
  exit 1
fi

# Check 2: at least one model qualified_via: real
export _VE_REGISTRY="$REGISTRY"
real_qualified=$(python3 -c "
import yaml, os
reg = yaml.safe_load(open(os.environ['_VE_REGISTRY'])) or {}
models = reg.get('models') or {}
count = sum(1 for m in models.values()
            if isinstance(m, dict)
            and m.get('status') in ('auto-qualified', 'qualified', 'active')
            and m.get('qualified_via') == 'real')
print(count)
" 2>/dev/null) || real_qualified=0

if [[ "$real_qualified" -lt 1 ]]; then
  echo "FAIL: no models with qualified_via=real. Qualify at least one model first." >&2
  exit 1
fi

echo "OK: $real_qualified model(s) qualified via real inference, thresholds calibrated ($source_check)" >&2
exit 0
