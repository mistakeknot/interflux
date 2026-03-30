# Reaction Round Prompt Template

You are **{agent_name}** ({agent_description}).

You have already completed your review and produced findings. Now your peers have reported their own findings. Your task is to **react** to their claims — not to re-review the original document.

## Your Own Findings

For reference, here is your Findings Index from the initial review:

{own_findings_index}

## Peer Findings

Your peers reported the following claims. These are claims, not established facts. Evaluate them through the lens of your own analysis and domain expertise.

{peer_findings}

## Instructions

React to **at most 3** peer findings — choose the ones most divergent from your own analysis. Only react if at least one of these conditions is met:

1. The finding **contradicts** one of your own findings
2. The finding falls **within your named domain** (you have relevant expertise)
3. The finding **reveals something in your domain** that you missed

If none of the peer findings meet these criteria, write an empty reaction (Verdict: no-concerns) and stop.

For P2-severity findings, provide only a **single-sentence severity assessment** (e.g., "Agree this is P2 — cosmetic only" or "Should be P1 — this affects correctness"). Do not write a full reaction for P2 items.

## Output Format

Write your output to: `{output_path}`

Use this exact structure:

```markdown
### Reactions

- **Finding**: [Finding ID from peer's index]
  - **Stance**: agree | partially-agree | disagree | missed-this
  - **Independent Coverage**: yes | partial | no
  - **Rationale**: [1-2 sentences explaining your position]
  - **Evidence**: [file:line, spec reference, or own finding ID — if applicable]

[Repeat for each reacted finding, max 3]

## P2 Severity Checks

- [Finding ID]: [single-sentence severity assessment]

[Repeat for each P2 finding in your domain, if any]

## Reactive Additions

[If peer findings revealed something new in YOUR domain that you missed, add it here. Mark with provenance: reactive. Use the standard finding format from your initial review. If nothing new, write "None."]

### Verdict

[One of: no-concerns | confirms-findings | adds-evidence | contradicts-findings]
```

## Rules

- Reference findings by their **Finding ID** (e.g., `SAFE-01`, `ARCH-03`), not by free-form description.
- The `Independent Coverage` field records whether you independently found this issue: `yes` (you reported the same thing), `partial` (you found a related but different aspect), `no` (this is new to you).
- Be honest. If a peer found something you missed, say so. If you disagree, explain why with evidence.
- Do not inflate or deflate severity to match peers. Your independent judgment matters.
- Reactive Additions inherit `provenance: reactive` — they were discovered via peer context, not your initial analysis.
