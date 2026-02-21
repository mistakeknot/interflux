# interflux Roadmap

**Version:** 0.2.0
**Last updated:** 2026-02-15
**Vision:** [`vision.md`](vision.md)
**PRD:** [`PRD.md`](PRD.md)

---

## Where We Are

interflux is at stable feature-complete breadth (2 skills, 3 commands, 12 agents, 2 MCP servers) and now in a "quality and operations" phase: tightening edge-case behavior, improving observability, and codifying long-term scalability assumptions.

### What’s Working

- Document/file/diff triage, dynamic scoring, and staged dispatch in `flux-drive`.
- Multi-agent research flow in `flux-research` with cost-tiered timeouts and source attribution.
- Domain detection + knowledge injection path wired in review and research.
- Protocol specification in `docs/spec/` with 3 conformance levels.
- Synthesis contracts and completion signaling enforced in generated outputs.
- `/interflux:flux-gen` project-agent generation available for domain depth.
- Skills and commands are aligned to plugin manifest and structural references.

### What’s Not Working Yet

- No active bead queue integration at plugin default level for this repo (workspace is not auto-initialized).
- No universal cross-run cost telemetry in first-party analytics (quality is observable, not yet dashboarded).
- Some domain profiles still have coarse research directives relative to generated reviewer quality.
- Convergence and confidence policies are stable, but not yet benchmarked on long-tail project stacks.

## Phase 1: Contract Tightening (current)

**Theme:** make outcomes deterministic, debuggable, and less brittle.

### P1.1 — Review Contract Reliability

| ID | Item | Description |
|---|---|---|
| IFX-R1 | Findings Index hardening | Validate and normalize agent outputs before synthesis; enforce error stubs for invalid formats. |
| IFX-R2 | Convergence math cleanup | Ensure convergence counts respect sliced inputs and partial completions. |
| IFX-R3 | Completion signal hardening | Verify `.partial` → sentinel → rename flows survive interruption and timeout. |

### P1.2 — Research Confidence and Gaps

| ID | Item | Description |
|---|---|---|
| IFX-R4 | Confidence rubric calibration | Standardize `high/medium/low` semantics across internal/external sources. |
| IFX-R5 | Query scope controls | Improve type inference for hybrid questions and mixed-scope research. |
| IFX-R6 | Source dedupe | Merge duplicate findings across agents with deterministic precedence. |

### P1.3 — Open Bead Feedback Loop

| ID | Item | Description |
|---|---|---|
| IFX-R7 | Bead bridge verification | Confirm `bd`-configured environments can consume output safely and idempotently. |
| IFX-R8 | Finding-to-ticket dedupe | Skip creating duplicate beads from same root finding across runs. |

#### Phase 1 Exit Criteria

- [ ] 0% unparsed agent output reaching synthesis without stub path
- [ ] Convergence calculation includes content-routing context in all stages
- [ ] No user-facing regression in `findings.json` schema
- [ ] Research answers include explicit confidence + gap section in all commands

## Phase 2: Integration and Productization

**Theme:** simplify usage, reduce operational surprises, and align with Clavain workflow expectations.

### P2.1 — Domain Profile Depth

| ID | Item | Description |
|---|---|---|
| IFX-I1 | Research Directives expansion | Add richer directives for high-value domains in `config/flux-drive/domains/*.md` where quality gains are measurable. |
| IFX-I2 | Agent spec refinement | Clarify generated agent anti-overlap and success criteria for domain agents. |

### P2.2 — Developer Experience

| ID | Item | Description |
|---|---|---|
| IFX-I3 | Roadmap artifact completeness | Ensure every run can produce deterministic outputs without manual cleanup. |
| IFX-I4 | Error messaging | Standardize partial/fallback messaging for missing context, timeouts, and empty outputs. |
| IFX-I5 | Command discoverability | Keep command/help text aligned with `name`, argument hints, and argument semantics. |

### P2.3 — Clavain Interop Enhancements

| ID | Item | Description |
|---|---|---|
| IFX-I6 | Spec reuse contracts | Expose stable outputs for Clavain `interline`/`interwatch` consumers. |
| IFX-I7 | Upstream compatibility checks | Verify plugin behavior against Clavain namespace and version guard expectations. |

#### Phase 2 Exit Criteria

- [ ] Domain-driven prompts consistently include at least one high-signal directive for supported domains
- [ ] No duplicate or malformed run artifacts during repeated command invocations
- [ ] Bead import path tested on a workspace with `bd` configured

## Phase 3: Scale and Evolution

**Theme:** optimize decision quality and move from working stability to adaptive capability.

### P2 — Adaptive Selection and Cost Controls

| ID | Item | Description |
|---|---|---|
| IFX-P1 | Agent topology tuning | Compare small/standard/top-heavy rosters with reproducible outcomes. |
| IFX-P2 | Context-budget controls | Use historical convergence and override signals to tune Stage 1/2 ceilings. |

### P2 — Knowledge Hygiene

| ID | Item | Description |
|---|---|---|
| IFX-P3 | Independent confirmation audits | Verify `independent` vs `primed` tagging remains strict across compounding cycles. |
| IFX-P4 | Archive discipline | Keep decayed entries searchable but excluded from active retrieval until revalidated. |

### Phase 3 Exit Criteria

- [ ] Selection tuning produces measurable reduction in redundant low-severity findings
- [ ] Compounded knowledge improves recall without increasing false-positive cycles
- [ ] Decision policies remain explainable and override-safe

## Open Beads (from workspace query)

Open-item status was checked against the local beads workspace at generation time:

- **Open bead count:** 0
- **Root cause:** no open beads are currently tracked for this workspace

### Open Beads Summary

| Bead | Title | Status |
|------|-------|--------|
| N/A | No open beads available in the tracked workspace | -- |

### Bead-linked Backlog Entries (to add)

| Priority | Candidate | Justification |
|----------|-----------|---------------|
| P1 | IFX-R1 / IFX-R2 | Reduces false synthesis risk and improves determinism |
| P1 | IFX-R7 | Requires stable environment with configured beads workspace |
| P2 | IFX-P1 / IFX-P2 | Needed for cost-aware expansion quality at scale |

## Dependency Graph

```
Phase 1: Contract Tightening
  IFX-R1 (output contracts) ──┬──► IFX-R2 (convergence integrity)
                               └──► IFX-R3 (completion reliability)
  IFX-R7 (beads bridge) ───────► IFX-I6 (interop stability)
  IFX-I1 (domain directives) ───► IFX-P1 (topology tuning)

Phase 2: Integration and Productization
  IFX-I1 (domain depth) ───────► IFX-I2 (agent spec clarity)
  IFX-I3 (artifact consistency) ─► IFX-I4 (user-facing reliability)
  IFX-I6 (interop) ────────────► IFX-I7 (version guard compatibility)

Phase 3: Scale and Evolution
  IFX-P1 (selection tuning) ────► IFX-P2 (cost control)
  IFX-P3 (confirmation audits) ─► IFX-P4 (knowledge hygiene)
```

## Keeping This Roadmap Current

- Move items between phases when exit criteria are met.
- Keep open-bead count visible in this section; add bead IDs when created.
- Record new blockers under explicit dependencies so triage and ordering remain explainable.
- Update this roadmap whenever protocol conformance level or command semantics change.

## From Interverse Roadmap

Items from the [Interverse roadmap](../../../docs/roadmap.json) that involve this module:

- **iv-qjwz** [Next] AgentDropout — dynamic redundancy elimination (blocked by iv-ynbh)
- **iv-905u** [Next] Intermediate result sharing between parallel agents
- **iv-qznx** [Next] Multi-framework interoperability benchmark and scoring harness
- **iv-wz3j** [Next] Role-aware latent memory safety and lifecycle experiments (blocked by iv-jc4j)
