# Dual-Mode Architecture

interflux supports both standalone (Claude Code marketplace) and integrated (Interverse ecosystem) operation via the interbase SDK.

## Files

- `hooks/interbase-stub.sh` — sources live SDK or falls back to inline no-ops
- `hooks/session-start.sh` — sources stub, emits ecosystem status
- `hooks/hooks.json` — registers SessionStart hook
- `.claude-plugin/integration.json` — declares standalone/integrated feature surface

## How It Works

- **Standalone**: User installs interflux from marketplace. Stub falls back to no-ops. All review/research features work. No ecosystem features (phase tracking, nudges, sprint gates).
- **Integrated**: User has `~/.intermod/interbase/interbase.sh` installed. Stub sources the live SDK. Session-start hook reports `[interverse] beads=... | ic=...`. Nudge protocol suggests missing companions.

## Testing

```bash
# Standalone (no ecosystem)
INTERMOD_LIB=/nonexistent bash hooks/session-start.sh 2>&1
# Expected: no output

# Integrated (with ecosystem)
bash hooks/session-start.sh 2>&1
# Expected: [interverse] beads=active | ic=...
```

## Known Constraints

- **No build step** — pure markdown/JSON/Python/bash plugin
- **Phase tracking is caller's responsibility** — interflux commands do not source lib-gates.sh; Clavain's lfg pipeline handles phase transitions
- **Exa requires API key** — set `EXA_API_KEY` env var; agents degrade gracefully without it
- **qmd must be installed** — semantic search used for knowledge injection; if unavailable, reviews run without knowledge context
