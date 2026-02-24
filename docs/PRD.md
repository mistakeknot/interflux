# interflux — Product Requirements Document

**Version:** 0.2.26
**Last updated:** 2026-02-15
**Vision:** [`vision.md`](vision.md)
**Dev guide:** [`AGENTS.md`](../AGENTS.md)

---

## 1. Product Definition

interflux is a multi-agent review and research plugin for Claude Code. It is the companionized implementation of Clavain’s mature review orchestration approach: formal scoring, staged execution, structured outputs, and protocol-driven synthesis.

The plugin turns raw documents, directories, and diffs into disciplined outcomes:

- **Review outcomes**: severity-tagged findings with explicit convergence and verdict
- **Research outcomes**: source-attributed answers with confidence bands and gap tracking
- **Artifact outcomes**: stable outputs consumed by Clavain workflows and future engines

### What interflux Is Not

- Not a GUI product — command-first, artifact-first.
- Not a general framework — no model orchestration API abstraction layer.
- Not autonomous by default — user approval gates are built into expansion and research dispatch.

## 2. Users

| Circle | Who | Deliverable |
|--------|-----|-------------|
| **Inner** | Authors and maintainers using Clavain every day | Faster, consistent review and research without manual agent assembly |
| **Middle** | Plugin consumers and workflow builders | Reusable protocol documents (`docs/spec`) and deterministic contracts |
| **Outer** | Adjacent ecosystems | Reference implementation for multi-agent protocol extraction |

## 3. Problem

Without explicit orchestration, multi-agent review degrades into:
- Agent over-dispatch and token waste
- Inconsistent output formats
- Weak evidence capture
- Undetectable duplicated findings and missed critical issues
- No scalable path for review memory without bias loops

Research suffers the opposite: under-coordination, single-source bias, and no synthesis.

## 4. Solution

Interflux hardens the workflow in three layers: **triage**, **launch**, and **synthesis**.

### 4.1 Component Architecture

| Type | Count | Purpose | Example |
|------|-------|---------|---------|
| **Skills** | 2 | Workflow engines | `flux-drive`, `flux-research` |
| **Agents** | 12 | Specialists | `fd-architecture`, `fd-safety`, `best-practices-researcher`, `repo-research-analyst` |
| **Commands** | 3 | User entry points | `/interflux:flux-drive`, `/interflux:flux-research`, `/interflux:flux-gen` |
| **MCP Servers** | 2 | External knowledge tools | `qmd`, `exa` |

### 4.2 Component Responsibilities

#### 4.2.1 Review Engine (`flux-drive`)

1. Detect project domains and classify input type (file/dir/diff).
2. Score and prioritize review agents using base/domain/project/domain-agent logic.
3. Run Stage 1 and conditional Stage 2 with optional research context.
4. Normalize Findings Indexes and emit deterministic `findings.json` + `summary.md`.

#### 4.2.2 Research Engine (`flux-research`)

1. Profile research intent (`how-to`, `best-practice`, `onboarding`, etc.).
2. Select relevant research agents with domain-aware query directives.
3. Dispatch agents in parallel and synthesize source-attributed answers.
4. Emit a confidence-ranked response and remaining gaps.

#### 4.2.3 Agent Generation (`flux-gen`)

Generates project-specific review agents from detected domain profiles and injects stronger, contextual review criteria back into review triage.

## 5. Key Workflows

### 5.1 `/interflux:flux-drive` — Multi-Agent Review

Input can be a file, directory, or diff. The workflow is:

`input classify → domain detect → project profile → agent scoring → user confirmation → Stage 1 launch → optional Stage 2 expansion → synthesis`

### 5.2 `/interflux:flux-research` — Multi-Agent Research

Input is a freeform question. The workflow is:

`query profile → agent scoring → user confirmation → parallel dispatch → source merging → confidence-ranked answer`

### 5.3 `/interflux:flux-gen` — Domain-Specific Reviewer Generation

Runs detection and profile-based generation of project-specific agents in `.claude/agents/`, which then participate in review triage as project category agents.

## 6. Non-Goals (Current Release)

- No GUI / dashboard in scope for v0.2.0
- No automatic code mutation based on findings
- No proprietary policy for semantic scoring outside documented protocol
- No hard-wired language-specific model tuning at this layer

## 7. Success Metrics

### 7.1 Review Quality

| Metric | Definition | Target (v0.2.0+) |
|--------|------------|-------------------|
| **Findings Index coverage** | Percentage of launched agents that output valid `### Findings Index` | > 95% |
| **Structured synthesis success** | `findings.json` + `summary.md` generated for each completed review | 100% |
| **Convergence transparency** | Critical findings include convergence count and confidence | 100% |
| **Revision precision** | P0/P1 findings in synthesized output are reproducibly located and actionable | > 90% of P0/P1 |

### 7.2 Runtime Efficiency

| Metric | Definition | Target (v0.2.0+) |
|--------|------------|-------------------|
| **Stage-1 time-to-first-signal** | Time from launch to first complete agent index | < 45s for repo-size inputs |
| **Cost control** | % reviews that complete in Stage 1 only when no expansion signal exists | > 50% |
| **Timeout resilience** | Reviews with at least one complete output despite individual agent failure | > 95% |

### 7.3 Research Quality

| Metric | Definition | Target (v0.2.0+) |
|--------|------------|-------------------|
| **Research attribution coverage** | Ratio of claims with source links in synthesis | > 95% |
| **Confidence calibration** | High/medium/low labels correspond to source depth bands | Qualitative review monthly |
| **Coverage of research gaps** | Number of remaining gaps explicitly listed per response | 100% |

## 8. Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Agent noise and false positives | Human fatigue and reduced trust | stricter pre-filters, staged dispatch, domain-aware scoring |
| Protocol drift from spec | Unstable outputs across prompt revisions | strict contract tests and versioned protocol references |
| Query under-specification in research | Over-broad answers, low confidence | explicit query profiling and confidence ranking |
| Bead creation saturation (optional integration) | Too many low-value work items | threshold gates and de-duplication before bead creation |

## 9. Keeping This PRD Current

- Update PRD when component counts, protocol conformance level, or major workflow semantics change.
- Sync roadmap and vision when any phase exit criteria change.
- Align with `docs/spec/README.md` versioning when protocol sections evolve.

---

*This PRD is derived from the plugin manifest version and implementation contracts in
`docs/spec/`, the runtime behavior in `skills/`, and current agent roster in this repository.*
