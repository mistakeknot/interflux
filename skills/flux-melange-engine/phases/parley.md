# Phase 7.5 — Parley (adversarial synthesis exchange to epistemic equilibrium)

Runs ONLY when the charter resolved peer mirrors (`--peers`, references/peer-runtimes.md) and at
least two runtimes produced a synthesis. Where the melange loop steers *probes* toward heat,
Parley steers the *syntheses themselves* into collision: each runtime fields an advocate, the
advocates exchange concessions and challenges over the same evidence, and the exchange repeats
until it reaches a **fixed point** — a round in which no advocate changes its mind, introduces
new evidence, or surfaces a novel insight. That fixed point is the run's *epistemic
equilibrium*. What remains contested at equilibrium is not noise to average away — it is the
run's most valuable residue, and it goes to the **user** for tie-break.

## Why exchange instead of merge

A merge (one agent reads all syntheses and reconciles) launders disagreement: the merging model's
own priors silently win every close call, and cross-model disagreement — the entire reason to run
mirrors — is destroyed at the moment it is most informative. The exchange keeps each runtime's
epistemic position *alive and attributed* until it is either genuinely conceded (evidence, not
authority) or explicitly surfaced as contested.

## Participants

| Role | Who runs it | Model |
|------|-------------|-------|
| Advocate (one per runtime) | primary: native agent; mirrors: shim-relay to the external CLI — the external model argues its own case | `advocate` routing (Opus at balanced) / external model |
| Moderator (one) | always a native agent | `moderator` routing (Opus at balanced) |

The moderator merges and bookkeeps; it never argues, never scores who "won", and never resolves
a contested topic itself. Structural neutrality is what makes the equilibrium claim honest.

## The exchange round

1. **Advocates (parallel).** Each advocate reads all syntheses, the target, and the prior
   consensus table, then emits positions:
   - `concede` — accept a peer claim you missed or contradicted (state what changed your mind)
   - `challenge` — dispute a peer claim (concrete evidence from the target/repo REQUIRED)
   - `affirm` — stand by your claim under challenge (NEW evidence required; repetition is void)
   - `novel` — a genuinely new insight the collision exposed
   plus `changed_mind` (true iff any concession, new evidence, or novel insight this round).
2. **Moderator.** Merges positions into a consensus table: `agreed` (claims all advocates now
   hold, holders recorded) and `contested` (live disputes: every runtime's current argument +
   evidence + a heat score 0–9 for how consequential the disagreement is). Stale repetition
   carries no weight. Sets `changed` = any advocate changed_mind OR the table materially moved.
3. **Fixed-point test.** `changed == false` → equilibrium reached, exchange ends. Otherwise
   loop, up to `exchange.max_rounds` (default 3; ending at the cap with `changed == true` is
   reported as equilibrium NOT reached — an honest "still moving when we stopped").

## Artifacts

- `{OUTPUT_ROOT}/equilibrium.md` — frontmatter (`artifact_type: melange-equilibrium`,
  runtimes, exchange_rounds, equilibrium: true/false) + Consensus / Contested / Exchange-log
  sections. Rewritten each round; the final round's version stands.
- `{OUTPUT_ROOT}/disagreements.jsonl` — one line per contested topic:
  `{"topic","heat","positions":[{"runtime","argument","evidence"}]}`. This is the tie-break
  queue.

## User tie-break (orchestrator, not this phase)

Scripts and subagents cannot `AskUserQuestion`. The workflow returns `equilibrium.contested`
to the orchestrator, which (SKILL.md § Report) presents the top contested topics by heat —
each side's argument attributed by runtime — for the user to rule on. Rulings are appended to
`equilibrium.md` under `## Rulings`. In non-interactive contexts the contested table is simply
surfaced in the report; unruled disagreements remain open and are honest to leave open.

## Degraded modes

- A mirror whose loop failed simply doesn't field an advocate; with < 2 surviving syntheses the
  phase is skipped with a caveat (never an error).
- A failed advocate call drops that runtime from the round; the moderator proceeds with
  survivors and notes the absence.
- A failed moderator call halts the exchange with the last known table (`equilibrium: false`).
