# Reference: Per-run Cost Capture

Every flux-melange subagent prompt begins with one machine-readable line:

```text
<flux-melange-cost>{"output_dir":"...","runtime":"claude","agent":"probe:r1:deepen","round":"round-1","backend":"claude","model":"sonnet","quota_source":"unknown"}</flux-melange-cost>
```

The workflow fast-path adds this marker in its single `dispatch()` chokepoint.
On the prose path, prefix every `Agent` prompt with the same marker, substituting
the run's `OUTPUT_ROOT`, logical agent label, round, requested backend/model, and
quota source. Use `unknown` instead of inferring a quota source.

The plugin's `SubagentStop` hook reads the completed transcript, deduplicates
repeated content-block rows by `message.id`, replaces the requested model alias
with the actual transcript model when present, and sums:

- `tokens_in` = uncached input + cache creation input + cache-read input;
- `tokens_out` = output tokens;
- the individual input/cache fields, retained for audit.

It updates these files under the run output directory while holding a lock:

- `cost-events.jsonl` — append-oriented per-agent evidence;
- `cost-summary.json` — per-agent rows, per-round aggregates, and run totals;
- `cost-summary.md` — the same summary for humans.

Duplicate hook delivery for the same completed `agent_id`, label, round, backend,
and model is idempotent. A re-executed agent receives a fresh `agent_id` and is
recorded as a distinct attempt.

Peer runtimes have two billable components: the Claude transport shim and the
external CLI. The shim's transcript yields exact Claude tokens. The external
backend/model receives its own row; when its CLI does not expose stable
input/output usage to the hook, those fields remain `unknown` and the totals
report `unknown_usage_count` instead of silently treating them as zero.
