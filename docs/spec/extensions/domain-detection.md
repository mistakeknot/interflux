# Domain Detection

> flux-drive-spec 1.0 | Conformance: Extension

## Overview

Domain detection classifies a project into one or more domains (e.g., game-simulation, web-api, ml-pipeline) by scanning its structure for signal patterns. When domains are detected, the orchestrator enriches agent scoring with domain-specific boosts and injects domain-specific review criteria into agent prompts. This is entirely optional — a flux-drive implementation works fine without it, just with less targeted reviews.

## Specification

### Signal Types

Domain detection uses four categories of signals, each with a configurable weight:

| Signal Type | Default Weight | What It Matches |
|-------------|---------------|-----------------|
| Directories | 0.3 | Directory names in the project tree (e.g., `game/`, `simulation/`, `ecs/`) |
| Files | 0.2 | File name patterns using glob syntax (e.g., `*.gd`, `project.godot`, `balance.yaml`) |
| Frameworks | 0.3 | Build system dependencies — package names from manifest files (e.g., `bevy`, `django`, `pytorch`) |
| Keywords | 0.2 | Identifiers in source files — variable names, function calls, constants (e.g., `tick_rate`, `delta_time`, `behavior_tree`) |

> **Why this works:** The weights reflect signal reliability. Frameworks (0.3) and directories (0.3) are strong structural indicators — a project with a `game/` directory and `bevy` in Cargo.toml is almost certainly a game. Files (0.2) and keywords (0.2) are supporting evidence — they're more common across domains and can produce false positives. The 0.3/0.2/0.3/0.2 split sums to 1.0, making confidence scores directly interpretable as percentages.

### Domain Index

Domains are defined in a structured index file. Each domain entry specifies:

```yaml
domains:
  - profile: game-simulation
    min_confidence: 0.3
    signals:
      directories: [game, simulation, ecs, tick, storyteller, ...]
      files: ["*.gd", "project.godot", "balance.yaml", ...]
      frameworks: [godot, unity, bevy, pygame, ...]
      keywords: [tick_rate, delta_time, behavior_tree, ...]

  - profile: web-api
    min_confidence: 0.3
    signals:
      directories: [api, routes, controllers, middleware, ...]
      files: [openapi.yaml, swagger.json, ...]
      frameworks: [express, fastapi, django, gin, ...]
      keywords: [endpoint, middleware, cors, rate_limit, ...]
```

Each domain has a `min_confidence` threshold — the minimum weighted score required for the domain to be considered "detected."

### Confidence Scoring Algorithm

For each domain, compute a confidence score:

```
confidence = (dir_matches / dir_total) * W_DIR
           + (file_matches / file_total) * W_FILE
           + (framework_matches / fw_total) * W_FRAMEWORK
           + (keyword_matches / kw_total) * W_KEYWORD
```

Where `*_matches` is the count of signals that matched and `*_total` is the total signals defined for that domain in that category. Categories with zero defined signals are excluded from the calculation (their weight is redistributed).

A domain is **detected** when `confidence >= min_confidence`.

> **Why this works:** Normalizing by total signals per category prevents domains with more signals from having an unfair advantage. A domain with 20 directory signals and 5 matches gets the same directory score (0.25 * 0.3 = 0.075) as a domain with 4 signals and 1 match (0.25 * 0.3 = 0.075). This makes cross-domain comparisons meaningful.

### Multi-Domain Classification

A project can match multiple domains simultaneously. Common combinations:

- Game server → `game-simulation` + `web-api`
- ML-powered API → `ml-pipeline` + `web-api`
- Desktop app with embedded database → `desktop-tauri` + `data-pipeline`

All detected domains contribute to agent scoring and review criteria. The domain with the highest confidence is marked `primary: true`.

When injecting domain-specific review criteria into agent prompts:
- Inject criteria from ALL detected domains (not just primary)
- Order by confidence (primary first)
- Cap at 3 domains to prevent prompt bloat
- If a domain profile has no criteria for a particular agent, skip silently

### Signal Matching Details

**Directories:** Case-insensitive substring match against directory names in the project tree. Scan only top-level and second-level directories (not recursive) for performance. The signal `ai/behavior` matches a nested path.

**Files:** Glob pattern matching against file names. Scan only the project root and common subdirectories (`src/`, `lib/`, `app/`, `cmd/`). Patterns like `*.gd` match any Godot script; specific names like `project.godot` match exactly.

**Frameworks:** String matching against dependency names extracted from build manifests:
- `package.json` → `dependencies` + `devDependencies` keys
- `Cargo.toml` → `[dependencies]` section
- `go.mod` → `require` block module names
- `pyproject.toml` → `[project.dependencies]` or `[tool.poetry.dependencies]`
- `requirements.txt` → package names (before `==` or `>=`)
- `Gemfile` → `gem` names

**Keywords:** Case-insensitive search within source files. Scan files with recognized source extensions (`.py`, `.go`, `.rs`, `.ts`, `.js`, `.java`, `.kt`, `.swift`, `.c`, `.cpp`, `.h`, `.gd`, `.dart`). Sample up to 50 source files for performance — prioritize files in directories that matched directory signals.

### Caching

Detection results are cached to avoid re-scanning on every review. The cache format:

```yaml
# Auto-detected by flux-drive. Edit to override.
cache_version: 1
structural_hash: "sha256:abc123..."
detected_at: "2026-02-14T17:00:00+00:00"
domains:
  - profile: web-api
    confidence: 0.72
    primary: true
  - profile: data-pipeline
    confidence: 0.45
```

Cache location: `{PROJECT_ROOT}/.claude/flux-drive.yaml`

**Manual override:** If the cache contains `override: true`, never re-detect. The user has manually set their domains and doesn't want automatic detection to overwrite them.

### Staleness Detection

A three-tier strategy determines when to re-scan, completing in <100ms for the common (fresh) case:

**Tier 1 — Structural hash (<100ms):**
Compute a deterministic hash of "structural files" — build manifests (`package.json`, `Cargo.toml`, `go.mod`, etc.) and framework indicators. If the hash matches the cached hash, the cache is fresh. If it differs, the cache is stale.

> **Why this works:** Structural files rarely change. When they do change, it almost always means new dependencies (framework signals) or a different project type. The hash is fast to compute (just SHA-256 a dozen small files) and catches the most important staleness signal.

**Tier 2 — Git log (<500ms):**
If Tier 1 is inconclusive (hash missing from cache or git unavailable), check `git log --since={detected_at}` for changes to structural files or files with structural extensions (`.gd`, `.tscn`, `.unity`, `.uproject`). Skipped for shallow clones (unreliable history).

**Tier 3 — File mtime (<1s):**
Fallback when git is unavailable. Compare the modification time of structural files against the cache's `detected_at` timestamp. Any structural file modified after detection triggers a re-scan.

### Integration with Scoring

When domains are detected, they affect the scoring algorithm (see `core/scoring.md`):

1. **Domain boost (+0/+1/+2):** Each agent is checked against each detected domain's profile. The injection criteria bullet count determines the boost.
2. **Domain agent bonus (+1):** Project-specific agents generated for a detected domain get an extra point.
3. **Pre-filter exceptions:** The game filter exempts the game-design agent when `game-simulation` is detected.

### Integration with Agent Prompts

During Phase 2 (Launch), the orchestrator:
1. Reads each detected domain's profile file
2. Extracts per-agent injection criteria (under `## Injection Criteria > ### fd-{agent-name}`)
3. Injects these as additional review bullets in each agent's prompt
4. Orders by confidence (primary domain first), caps at 3 domains

## Interflux Reference

In Interflux, domain detection is implemented in `scripts/detect-domains.py` (713 lines). Domain definitions live in `config/flux-drive/domains/index.yaml` (454 lines). Domain profiles with injection criteria are in `config/flux-drive/domains/*.md` — 11 profiles: game-simulation, ml-pipeline, web-api, cli-tool, mobile-app, embedded-systems, library-sdk, data-pipeline, claude-code-plugin, tui-app, desktop-tauri.

The script is invoked by the orchestrator during Phase 1, Step 1.0.1. Cache is written atomically (temp file + rename). Staleness is checked via `--check-stale` flag. Re-detection uses `--no-cache --json`.

## Conformance

An implementation conforming to this extension:

- **MUST** support weighted signal scoring with at least 2 signal types
- **MUST** support multi-domain classification (a project can match multiple domains)
- **MUST** define a minimum confidence threshold per domain
- **SHOULD** implement caching with staleness detection
- **SHOULD** support all 4 signal types (directories, files, frameworks, keywords)
- **SHOULD** integrate detected domains with the scoring algorithm (domain boost)
- **MAY** use different signal weights (0.3/0.2/0.3/0.2 is the reference default)
- **MAY** use different staleness detection strategies
- **MAY** support manual override of detected domains
