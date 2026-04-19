# interflux — Git History Analysis for Roadmap Planning

**Analyst:** git-history-analyzer
**Date:** 2026-04-04
**Scope:** `/home/mk/projects/Sylveste/interverse/interflux/` (own git repo, 187 commits, 2026-02-14 to 2026-04-04)

---

### Sources

**Git commands run:**
- `git log --format="%H %ad %s" --date=short` — full chronological timeline (187 commits)
- `git log --oneline | grep "^[a-f0-9]* fix"` — all fix commits (27 total)
- `git log --oneline | grep "^[a-f0-9]* refactor"` — all refactor commits (7 total)
- `git log --oneline | grep -i revert` — regression/revert check
- `git log --all --oneline --name-only --format="" | sort | uniq -c | sort -rn` — file churn ranking
- `git diff --stat HEAD~50 HEAD` — recent 50-commit file diff summary
- Keyword searches: `discourse|sycophancy|hearsay|reaction`, `perf|optim|token`, `security|trust|inject`, `budget|cost|interstat`, `domain|detect|routing|dispatch`, `install|onboard|setup`
- `awk` commit-type frequency count across all 187 commits

**Files read:**
- `/home/mk/projects/Sylveste/interverse/interflux/docs/vision.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/PRD.md` (partial)
- `/home/mk/projects/Sylveste/interverse/interflux/docs/roadmap.md`
- `/home/mk/projects/Sylveste/interverse/interflux/docs/interflux-roadmap.md`
- `/home/mk/projects/Sylveste/interverse/interflux/config/flux-drive/reaction.yaml`
- `/home/mk/projects/Sylveste/interverse/interflux/config/flux-drive/budget.yaml`
- `/home/mk/projects/Sylveste/interverse/interflux/skills/flux-drive/SKILL-compact.md` (partial)
- `/home/mk/projects/Sylveste/interverse/interflux/campaigns/flux-review-token-efficiency/learnings.md`
- `/home/mk/projects/Sylveste/interverse/interflux/CLAUDE.md`

---

### Findings

#### 1. Evolution Trajectory — Three Distinct Phases

The 187-commit history falls into three identifiable phases:

**Phase A — Foundation (2026-02-14 to ~2026-02-20, ~50 commits)**
Extraction from Clavain: 7 review agents, flux-drive skill with phases/slicing/synthesis, 11 domain profiles, domain detection, 93 structural tests. First commit included a nearly-complete system (`feat: initial Interflux plugin — multi-agent review engine extracted from Clavain`). Within 2 days: added flux-research, protocol spec (v1.0.0), budget-aware dispatch, synthesis delegation to intersynth subagent, verdict header contracts, and dual-mode hooks architecture. Commit density was high (11 commits on 2026-02-15, 10 on 2026-02-16). This was a porting sprint, not a build-from-scratch phase.

**Phase B — Hardening and Capability Expansion (2026-02-22 to ~2026-03-15, ~80 commits)**
The heaviest sprint: LLM-based domain detection (replaced heuristics), intermediate finding sharing between parallel agents, AgentDropout redundancy filter, trust multiplier on triage scoring, cognitive lens agents added (fd-systems, fd-decisions, fd-people, fd-resilience, fd-perception), routing override reader (scope/canary/propose), security hardening (trust boundary, gitignore, exempt agents), a 16-change pipeline optimization sprint, and ecosystem delegation (domain detection to intersense, knowledge compounding to interknow). Three major infrastructure items landed in a single day (2026-02-23): routing overrides, agent role mapping, and security boundary. The 15 commits on 2026-02-23 is the single busiest day in the repo's history.

**Phase C — Surface Diversification and Discourse Quality (2026-03-18 to present, ~57 commits)**
Three new commands added: `/flux-explore` (autonomous semantic space exploration), `/flux-review` (dual-track deep review, then upgraded to adaptive multi-track with configurable model routing), and `/flux-gen` capability expansion (prompt mode, severity calibration, LLM-only domain dispatch). Followed immediately by a reaction round engineering campaign (rsj.6–rsj.12): sycophancy detection, Sawyer health monitor, Lorenzen move validation, discourse fixative, hearsay detection, sparse communication topology, convergence gate (formula → Haiku LLM agent). Final integration: convergence gate wired to intercept CLI (2026-04-02). Today's commit (2026-04-04) fixed silent generation failures in flux-gen.

**Confidence: high** — based on full commit log with dates.

---

#### 2. Pain Points — Areas of Highest Churn

Ranked by file modification frequency across all history:

1. **`.claude-plugin/plugin.json` — 67 touches** (most-modified file by wide margin). Persistent declaration drift: hooks, skills, commands, and agents repeatedly had to be re-declared. At least 4 separate fix commits explicitly addressed missing declarations (`fix: declare skills, commands, and agents`, `fix: declare hooks + add graceful MCP server launchers`, `fix: remove redundant hooks declaration and unrecognized agentCapabilities key`, `fix(interflux): move hooks to .claude-plugin/hooks/hooks.json`). The plugin manifest is a structural pain source — every new capability requires manifest surgery.

2. **`skills/flux-drive/phases/launch.md` — 23 touches** and heavily rewritten in the most recent 50-commit diff (605→compressed, 51% reduction). Represents continuous growth pressure: each new feature (routing overrides, Composer dispatch, Stage 2 incremental expansion, reaction round injection) required edits to the orchestration document that is loaded on every invocation.

3. **`skills/flux-drive/SKILL.md` and `SKILL-compact.md` — 20 touches each**. The token-efficiency campaign (validated in `campaigns/flux-review-token-efficiency/`) compressed SKILL.md heavily, and SKILL-compact.md was added as a parallel artifact. Repeated sync failures between the two (`fix(flux-drive): sync SKILL-compact.md and scoring-examples.md`) show that maintaining dual representations creates ongoing drift risk.

4. **`scripts/generate-agents.py` — 10 touches** with significant rewrites. At least 3 fix commits targeted generation: wrapped JSON handling, `_short_title()` bug, and silent failure detection. Generation quality and error visibility remain an active pain area.

5. **`scripts/detect-domains.py`** — 7 touches then eventually deleted (refactored away). The domain detection code went through three architectural revisions: heuristic → LLM-based → fully delegated to intersense. Each revision required test updates (`test_detect_domains.py` was 440 lines and then removed). This represents the highest-magnitude rework in the codebase.

**Confidence: high** — based on file churn counts and fix commit analysis.

---

#### 3. Regressions — What Was Reverted or Reworked

Only one explicit revert in history: `Revert "fix(ci): add actions:read permission for SARIF upload"` — a CI configuration error with no behavioral impact on the plugin itself.

However, three architectural reworks represent functional regressions in disguise:

- **Domain detection — three revisions**. Heuristic detection was added (2026-02-22), then reworked to LLM-based (2026-02-22, same day), then the deterministic fallback was removed (2026-02-25 refactor), then domain detection was delegated to intersense (2026-02-25), then the remaining deterministic code was fully removed from interflux (2026-03-24 refactor). Each step left behind stub files (`detect-domains.py` and `content-hash.py`) that required separate fix commits to make importable without crashing.

- **Dedup boundary disambiguation** — `fix(flux-drive): specify dedup boundary — exact name match only, partial overlap keeps both` (2026-03-23) suggests the dedup logic was too aggressive, suppressing distinct findings. Preceded by `feat: add 5 explicit dedup rules to synthesis spec` (2026-02-18), this was a behavioral correction to a rule that was correct in intent but over-applied in implementation.

- **Research mode agent dispatch** — `fix(flux-drive): research mode dispatch must use general-purpose for project agents` (2026-03-26). When LLM classification + flux-gen dispatch was added for review mode, research mode incorrectly inherited the same dispatch path. A silent bug: no error, wrong agents.

**Confidence: high** — based on explicit revert and commit message analysis.

---

#### 4. Feature Velocity — Recent vs Stalled

**High-velocity areas (last 4 weeks, March–April 2026):**

- Reaction round (Phase 2.5): built from scratch to full deployment in 5 days (rsj.6 on 2026-03-30 through convergence gate activation on 2026-04-02). 7 sub-features: sycophancy detection, Sawyer health monitoring, Lorenzen move validation, discourse fixative, hearsay discounting, sparse topology, LLM convergence gate. This is the fastest sustained feature sprint in the repo.
- flux-review command: zero to multi-track adaptive with model routing in a single day (2026-03-28, 5 commits).
- Token efficiency: pipeline compression campaign with measured results (-16% pipeline instructions, -50% compound SKILL file size). Active as recently as 2026-04-01.

**Stalled or deferred areas:**

- **Per-finding sycophancy detection** is explicitly flagged as a future enhancement in `reaction.yaml`: `# Per-finding sycophancy (vs per-agent) is a future enhancement.` The current detection is per-agent across a finding population, not per-finding across agents — a coarser signal.
- **Cross-model diversity dispatch**: vision.md acknowledges this is designed for but notes that today interflux dispatches same-model subagents. The comment says: `cross-model dispatch is a configuration change, not an architecture change` — the path is clear but the work has not been done.
- **Role-aware latent memory**: bead `iv-wz3j` (`[interflux] Role-aware latent memory architecture experiments`) is open and listed in the roadmap as the only Open Item. No commits reference this bead.
- **Install failure investigation**: bead `iv-zzo4` (`Investigate interflux install failure on new computer`) was listed as In Progress but no commits reference it; the install-hardening commits from 2026-02-24 may have resolved the symptoms without formally closing it.
- **RSJ items 1–5 and 8, 10**: RSJ bead has sub-items rsj.6, rsj.7, rsj.9, rsj.11, rsj.12 completed but rsj.1–rsj.5, rsj.8, and rsj.10 are absent from commit messages — either never started, out of scope, or renumbered.

**Confidence: medium** — stalled areas inferred from roadmap docs + commit absence; RSJ gap is based on numbered sequence inference.

---

#### 5. Integration Evolution — How Integration Points Changed

The plugin started as a self-contained extract from Clavain. By April 2026 it has become a coordinator of a small ecosystem:

- **interknow** absorbed knowledge compounding (2026-02-25) — interflux now delegates to it.
- **intersense** absorbed domain detection (2026-02-25) — interflux deferred the LLM domain call.
- **interstat** feeds real-time budget signals to triage (2026-02-20) — always-on budget signal from interstat interband.
- **interwatch** monitors compact file drift via PostToolUse hook (2026-03-24).
- **interspect** has an overlay injection point for Type 1 overlays (2026-02-18) — quality gate integration.
- **intercept** now receives convergence gate output (2026-04-02) — reaction round decisions route through intercept CLI.
- **Composer** dispatch is consumed as authoritative when available (2026-03-03) — Ockham integration surface.
- **Exa MCP** added for external search augmentation, with graceful fallback if `EXA_API_KEY` is absent.
- **fleet registry** added as cost estimation fallback when interstat has insufficient data (2026-03-01).

The trajectory is clear: interflux is moving from self-contained engine to thin coordinator. Each capability that stabilizes gets extracted to a companion plugin or delegated to an ecosystem service.

**Confidence: high** — based on explicit delegation refactors and integration commit trail.

---

#### 6. Gaps in the Trajectory — Natural Next Steps the History Suggests

**Gap A: Per-finding sycophancy detection**
The reaction round's sycophancy detection operates at the agent population level (fraction of agents agreeing). The config explicitly defers per-finding detection. This is a meaningful quality gap: an agent can independently discover the same finding as peers for different reasons (genuine convergence) vs. all agents raising a finding because one influential agent mentioned it first. Per-finding weighted convergence scoring — tracking evidence diversity per finding, not just agent headcount — is the natural next step after the reaction round stabilizes.

**Gap B: Cross-model dispatch**
vision.md explicitly states cross-model diversity is a config-only change and calls it a design bet. The contracts are ready. No commits have moved toward enabling it. The reaction round's hearsay and sycophancy detection were specifically designed for this case (same model = higher sycophancy risk). The history shows the infrastructure was built with this in mind but the switch was never flipped. This is the single highest-leverage gap given the vision's emphasis on disagreement as the primary quality signal.

**Gap C: Manifest declaration maintenance**
67 touches to `plugin.json` across 187 commits (36% of commits touched the manifest). At least 8 commits were fix-type manifest corrections. A code-generation or validation step that auto-derives plugin.json from directory structure (skills, agents, commands, hooks) would eliminate this entire class of bugs. The structural tests already validate counts — adding manifest generation would close the loop.

**Gap D: flux-gen reliability**
Two fix commits in the last 2 weeks targeted flux-gen: broken section headers (2026-03-29) and silent generation failures (2026-04-04). The generate-agents.py script has had 10 touches and three separate bug-fix sessions. The silent failure mode (`fix(flux-gen): detect and report silent generation failures`) indicates generation was failing without error — a correctness gap in the most dynamic part of the system (the part that creates new agents at runtime). Comprehensive generation contract testing (schema validation, output completeness checks) would reduce regression risk here.

**Gap E: flux-review observability**
flux-review was added 2026-03-28 and upgraded twice in the same day. The token-efficiency campaign measured flux-drive carefully. No equivalent campaign exists for flux-review. The `campaigns/flux-review-token-efficiency/` directory name suggests work was planned or started — `results.jsonl` is there but only 14 lines. Multi-track reviews are potentially expensive; without baseline measurements, cost behavior is unknown.

**Gap F: RSJ sub-feature gap**
The reaction round bead (sylveste-rsj) completed items rsj.6, rsj.7, rsj.9, rsj.11, rsj.12. Items rsj.1–rsj.5, rsj.8, and rsj.10 are absent from commit messages. This either means they are pending, were descoped, or the numbering is non-sequential by design. The numbered gaps (especially rsj.8 and rsj.10 within a completed sequence) are most likely pending work items.

**Gap G: Role-aware memory architecture**
Bead `iv-wz3j` is the only open roadmap item in the formal roadmap doc. Knowledge compounding was delegated to interknow, but that is a different capability — compounding learnings across runs. Role-aware memory would let agents carry prior-session findings into new sessions in a way that is tagged by agent role (fd-architecture findings persist to future architecture reviews). Zero commits reference this bead, suggesting it is planned but unstarted.

**Confidence: high for A, B, C, D** (explicit in source code or commit messages); **medium for E, F, G** (inferred from absence and partial evidence).

---

### Confidence

| Finding | Confidence | Basis |
|---------|-----------|-------|
| 1. Three-phase evolution | High | Full commit log with dates |
| 2. plugin.json churn as #1 pain | High | File frequency count (67 touches), 8 fix commits |
| 3. Three architectural reworks | High | Explicit commit sequence analysis |
| 4. Reaction round velocity | High | Commit dates and timestamps |
| 4. Stalled cross-model dispatch | Medium | Vision doc + commit absence |
| 4. RSJ gap rsj.1-5, 8, 10 | Medium | Numbered sequence inference |
| 5. Integration delegation trajectory | High | Explicit refactor commit trail |
| 6. Gap A: per-finding sycophancy | High | Explicit future-enhancement comment in reaction.yaml |
| 6. Gap B: cross-model dispatch | High | Explicit vision.md statement + zero commits |
| 6. Gap C: manifest auto-generation | High | 67 touch count + 8 fix commits |
| 6. Gap D: flux-gen reliability | High | Two recent fix commits, 10 total touches |
| 6. Gap E: flux-review observability | Medium | Empty campaign data, no measurement commits |
| 6. Gap F: RSJ pending items | Medium | Numbered sequence gap inference |
| 6. Gap G: role-aware memory | Medium | Bead exists, zero commits |

---

### Gaps

**What could not be determined from history alone:**

1. **RSJ sub-items 1–5, 8, 10** — whether these were descoped, renumbered, or represent genuine pending work. The bead tracker (`bd list sylveste-rsj` or similar) would answer this definitively.

2. **Actual token cost of flux-review runs** — the campaign directory exists but has minimal data (14 results.jsonl lines). Real cost behavior of multi-track review is unknown from this analysis.

3. **Install failure status** (bead `iv-zzo4`) — the bead is listed as In Progress but no commits reference it. Unknown whether the hardening commits (2026-02-24) resolved it or if it remains active.

4. **Intersense and interknow stability** — interflux delegated domain detection and knowledge compounding to these plugins. Their reliability now directly affects interflux quality, but their git histories are outside this analysis scope.

5. **User-reported vs. author-discovered bugs** — fix commits don't distinguish between bugs users encountered in production vs. bugs the author found during development. The silent failure in flux-gen (2026-04-04) has a bead reference (sylveste-co5) suggesting user-reported, but other fixes lack this context.

<!-- flux-research:complete -->
