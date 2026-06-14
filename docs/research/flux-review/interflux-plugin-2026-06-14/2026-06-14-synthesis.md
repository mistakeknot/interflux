---
artifact_type: review-synthesis
method: flux-review
target: "interflux (whole plugin)"
target_description: "Multi-agent review and research engine — Claude Code plugin"
tracks: 3
track_a_agents: [fd-architecture, fd-quality, fd-correctness, fd-safety]
track_b_agents: [job-scheduler, newsroom-wire-desk, air-traffic-control]
track_c_agents: [medieval-scriptorium, canal-lock-staircase, portolan-cartography]
date: 2026-06-14
---

# Cross-Track Synthesis — interflux deep review

A 10-agent review ran across three tracks at increasing semantic distance: Track A (adjacent domain experts — architecture, quality, correctness, safety), Track B (orthogonal parallel disciplines — distributed job scheduling, newsroom wire-desk, air-traffic control), Track C (distant structural isomorphism — medieval scriptorium, canal lock-staircase, portolan cartography). The striking outcome is that the same handful of structural defects were rediscovered independently by software reviewers, operations professionals, and pre-modern craft analogies alike — and the convergence is concentrated on two meta-patterns: **safeguards that live in prose-to-the-LLM rather than enforced code**, and **convergence/agreement counted without auditing source independence**.

---

## 1. Critical Findings (P0/P1)

Consolidated and de-duplicated across all tracks. Each is the same root cause even where different tracks cite different file:line anchors.

### C-1 [P0] The concurrency cap is documented prose, not an enforced admission control
`skills/flux-engine/phases/launch.md:156-174` (cap definition), `:161` (`MAX_CONCURRENT_AGENTS:-6`)
`MAX_CONCURRENT_AGENTS` is described as a "dispatch loop pattern" the orchestrating LLM is asked to follow in natural language. The job-scheduler track grepped the entire `scripts/` tree and confirmed there is no semaphore, counter, or admission code anywhere — only `flux-watch.sh` *observing* completions after the fact. The harness actively encourages emitting all independent `Agent` calls in one block, so an LLM can breach the cap before any "wait" instruction executes. Canal-lock and ATC tracks add that the cap is also a *fixed* size (6) decoupled from the token/water budget, and that `budget.yaml` has no `dispatch:` section at all — so the documented `dispatch.max_concurrent_agents` resolution tier is a dead/phantom path (`launch.md:164` resolution order vs `config/flux-drive/budget.yaml`, which has no `dispatch:` key).
**Fix:** enforce the cap mechanically. Add a `flux-dispatch.sh` (or extend `flux-watch.sh`) owning a `flock`-guarded token/semaphore file in `{OUTPUT_DIR}` that every dispatch path must acquire a slot from before each `Agent` call; release on observed `.md`. Simplest robust form: dispatch in fixed waves of N and block on `flux-watch.sh {OUTPUT_DIR} {wave_size}` between waves. Also add the missing `dispatch.max_concurrent_agents` key to `budget.yaml`, and ideally derive the cap from budget pressure.

### C-2 [P0] No 429 / rate-limit backpressure — the one guaranteed failure is unhandled
`skills/flux-engine/phases/launch.md:158-161`, `shared-contracts.md:148-154`
The launch doc's own rationale cites "~30% retry-token waste at 16-agent fan-out" — the authors *know* 429s happen — yet `grep -i '429|backoff|rate.limit' scripts/` finds only `cost_capture.sh`'s unrelated DB-grace retry. The only retry that exists is the partial-completion Retry Race Protocol, which (a) does not distinguish "rate-limited and never started" from "crashed" from "slow," and (b) retries synchronously at the same concurrency with no backoff — so a retry storm hits the same wall. A plain 429 leaves no `.md` and no `.partial`, making it invisible until `flux-watch` times out 300s later.
**Fix:** add a transient-failure class. On a rate-limit error: do NOT count as failed; re-enqueue with exponential backoff + jitter; multiplicatively decrease effective concurrency for the rest of the run (TCP / client-go style). This must precede the 300s timeout, not follow it.

### C-3 [P0/P1] OUTPUT_DIR content-address collision races concurrent same-target runs
`skills/flux-engine/SKILL.md:112-117,124-126`, `phases/launch.md:11-16`, plus the wrapper amplification at `skills/flux-engine/SKILL.md:99,108` / `track-synthesis.md:7,83`
OUTPUT_DIR is `docs/research/flux-drive/{INPUT_STEM}-{sha256(INPUT_PATH)[:8]}`, deliberately stable across reruns for prompt-cache hits. Two concurrent runs on the same target resolve to the identical directory; run B's pre-dispatch `find ... -delete` (`launch.md:13-16`) wipes run A's in-flight `.md`/`.partial`/`peer-findings.jsonl`, and both write `.md` for the same agent names — violating the "at most one terminal `.md` per agent per run" invariant which is only enforced *within* a run. The quire-mark (`launch.md:17-24`) only *detects* contamination at synthesis; it does not prevent the destructive pre-clean from racing a live agent. **This is worsened internally by flux-review-engine**, which runs N inner flux-drive reviews on the *same* INPUT_PATH per track, so the tracks deterministically collide with each other even without a second user invocation.
**Fix (converging recommendation across architecture, correctness, scheduling, canal, ATC tracks):** carry FLUX_RUN_UUID in the *filename* (`{agent}.{RUN_UUID}.md`) so synthesis globs only the current run and stale files are structurally unreadable; take an atomic occupancy lock (`mkdir {OUTPUT_DIR}/.run-{UUID}.lock` before the destructive `find -delete`, wait/auto-suffix if held); and have flux-review-engine pass an explicit per-track `--output-dir docs/research/flux-review/{slug}/track-{letter}` to each inner run (the `--output-dir` flag already exists, `SKILL.md:67`). Also switch every completion `mv` to `mv -n`.

### C-4 [P1] Convergence scoring counts correlated same-base-model agreement as independent corroboration
`skills/flux-review-engine/phases/track-synthesis.md:3,36-43`; single-run side `skills/flux-engine/phases/synthesize.md:339-343`; cross-family multiplier exists at `docs/spec/core/synthesis.md:142-162` but is opt-in/rare
The cross-track synthesizer ranks convergent findings "the highest-confidence signal" purely by head-count of tracks that found them, with no field for shared-model correlation. But all track agents share one base model — agreement is correlated error, not corroboration. interflux already gets this right *inside one run* (hearsay detection `convergence_weight_hearsay: 0.0`, cross-family 1.5x multiplier), but that knowledge is dropped at the cross-track tier, and the multiplier no-ops on the common single-family deployment.
**Fix:** pass each track agent's `model_family` into the track-synthesis prompt; down-weight same-family convergence and label it "correlated, treat as ~1 source"; make weighted_convergence (not raw count) drive the confidence *label* so "3/4 agents, all Claude, same slice" never prints as "High"; surface a standing caveat whenever `cross_family_convergence == 1` across the run.

### C-5 [P1] The synthesis subagent is the single un-cross-checked compiler
`skills/flux-engine/phases/synthesize.md:45-108` (esp. `:46-47,66,102-103`)
Step 3.2 delegates ALL collection, dedup, conflict detection, verdict-writing and prose to one haiku-tier intersynth subagent, with the host instructed never to read any agent output file. The summary prose is therefore an asserted-faithful rendering by a single un-verified hand — nothing checks that a P0 in the summary traces to a P0 in an agent file, or that "Key Findings" prose didn't blend two agents into a claim neither made (cartography's "invented coastline"; scriptorium's "corrector who fairs the curve"). The contract has the right primitive — the Findings Index is machine-parseable (`shared-contracts.md:11-16`) — but no structural grounding check exists.
**Fix:** add a cheap structural diff asserting every finding ID and severity in `findings.json` is grounded in a parsed Findings Index line, and flag any summary claim with no backing index entry. This is the cartography track's nominated single highest-leverage fix.

### C-6 [P1] Prompt-injection sanitization is advisory, not enforced, across four sinks
`scripts/sanitize_untrusted.py:1-21`, `skills/flux-engine/phases/reaction.md:71-96`, `shared-contracts.md:156-164`, plus uncovered paths Step 2.2a research context and Step 2.1d overlays
`sanitize()` exists and is good, but for the runtime channels (reaction round, knowledge/research/domain injection) it runs only because a markdown phase doc tells the orchestrating LLM to run it. An LLM that skips the step, or a path that injects content without going through `reaction.md`, embeds raw attacker-controlled text into a downstream system prompt. This is the same meta-pattern as C-1: a safeguard living in prose, not at a code chokepoint. The quality track adds that `sanitize_untrusted.py` — the B3 reference filter guarding four untrusted channels with subtle regexes — has zero unit tests (the promised C3 hypothesis fuzz tests never landed).
**Fix:** route every injection sink through one enforced wrapper (the planned `TrustedContent` NewType), sanitize at the single chokepoint that reads these files, and add `tests/test_sanitize_untrusted.py` covering each bypass class (fullwidth, RLO, fenced code, base64, `NEW INSTRUCTIONS:`) plus negative cases.

### C-7 [P1] openrouter-dispatch spend ceiling: check-then-act overshoot + arbitrary model/prompt
`mcp-servers/openrouter-dispatch/index.ts:157-231` (input bounds), `:176-184,262-268` (check/act window)
The ceiling is checked and a rate token consumed inside one `withStateLock`, but `cumulativeSpendUsd` is incremented in a *separate* lock only after the network call returns. N concurrent calls all pass the under-ceiling check, all hit the API, then all increment — overshooting by up to (in-flight concurrency × per-call cost). The persistence comment at `:27-30` fixed cross-instance *visibility*, not the check/act window. Compounding: `model_id` is a free `z.string()` and `prompt`/`system_prompt` have no length cap, so an injection-steered agent can dispatch the most expensive model with an arbitrarily large prompt; responses lacking `usage.total_cost` are billed but counted as zero, drifting the ceiling upward.
**Fix:** reserve an estimated cost at admission inside the same lock as the check, then reconcile to actual after the call (or serialize near the ceiling); constrain `model_id` to an allowlist; enforce `max_tokens` and prompt-length caps; treat missing `total_cost` as a conservative debit. Also (safety track) treat the persisted spend ledger as monotonic so a local same-user process cannot reset it downward.

### C-8 [P1] `.md` presence treated as completion even for truncated/partial writes
`shared-contracts.md:30-32`, `flux-watch.sh:178-192`, `synthesize.md:5-13,27-40`
The binding completion signal is "`.md` exists, `.partial` does not." The `<!-- flux-drive:complete -->` sentinel is deliberately downgraded to diagnostic-only, and validation checks only the run-uuid first line + `### Findings Index` presence. If an agent crashes after the rename but before flushing its body, a structurally-truncated file is accepted as terminal success and its missing findings silently count as "safe." ATC frames this as a handoff with no positive-control acknowledgement; scheduling frames it as missing integrity gate. **Fix:** require a parseable `Verdict:` line and restore the completion sentinel to load-bearing — absent sentinel on a non-error file → Malformed → error stub.

### C-9 [P1] No quorum / minimum-success threshold — a single survivor is treated like a full review
`skills/flux-engine/phases/synthesize.md:5-13`, `reaction.md:11-14`
Synthesis proceeds with whatever `.md` files exist (error and stall stubs included). A run where 5 of 6 agents hit the unhandled 429 path (C-2) and emit stubs still produces a confident verdict computed from one agent, with convergence scoring silently collapsing for lack of peers. **Fix:** add `min_quorum` to `budget.yaml` (e.g. `max(2, ceil(0.5 × launched))`, with exempt agents required if launched); below quorum, mark `verdict: incomplete` and surface it prominently.

### C-10 [P1] Documentation / manifest drift from the flux-drive→flux-engine rename and undocumented openrouter MCP
`AGENTS.md:17,108-112,216,229,147`; `CLAUDE.md:7,20,24`; `agents/architecture.md:8`; `scripts/README.md:174`; `.claude-plugin/plugin.json:53-71`
Canonical docs describe a plugin that no longer exists: "1 skill" (actual 2: `flux-engine`, `flux-review-engine`), "1 MCP server" (actual 2: exa + openrouter-dispatch), paths under `skills/flux-drive/` (renamed to `flux-engine`). CLAUDE.md self-contradicts (line 7 says 2 MCP servers, line 24's validation asserts `['exa']`). `validate-roster.sh` hardcodes the dead `skills/flux-drive/SKILL.md` path and a renamed header, so it always exits 1. The *undocumented* server is precisely openrouter-dispatch — the one with real outbound-spend surface (C-7), so reviewers under-account for the live attack surface. **Fix:** one-pass re-sync of AGENTS.md / CLAUDE.md / agents/architecture.md / scripts/README.md to the real two-skill / two-MCP / `flux-engine` layout; repoint and CI-wire `validate-roster.sh`; derive counts in CI rather than hand-maintaining in three places.

### C-11 [P1] Convergence/severity regex misclassifies multi-digit severities
`scripts/findings-helper.sh:119` — unanchored `/[Pp][0-2]/` matches the `P1` inside `P10` and matches a `P0` anywhere in a title as the severity. Since convergence drives expansion decisions and overlap ratios, a misread can trigger spurious Stage-2 expansion or skew the verdict. **Fix:** anchor to the index grammar `^-\s*([Pp][0-9]+)\s*\|`, capture the full digit run, range-check.

---

## 2. Cross-Track Convergence (ranked by independent-track count)

These are the highest-confidence signals because they were discovered through independent reasoning paths at different semantic distances. Note the recurring meta-caveat (C-4): all reviewers share a base model, so convergence here is itself partly correlated — but the fact that *orthogonal-domain* and *distant-domain* lenses (which reason from scheduling theory, journalism, hydraulics, and manuscript craft rather than from the code) landed on the same defects materially raises confidence beyond same-model agreement.

**[Convergence 9/10 tracks] OUTPUT_DIR content-address collision (C-3).** Surfaced by: fd-architecture (P2, "all tracks reviewing the same INPUT_PATH resolve to the identical dir and race"), fd-correctness (P1, "second run's find -delete wipes the first run's completed outputs"), job-scheduler (P1, "make the result key carry the run UUID in the filename"), canal-lock (P1, "two boats in a single-width pound"), ATC (P3, "two aircraft cleared to the same runway"), and implicitly by fd-safety (path-traversal note confirming content-addressing) and newsroom (foreign-file dedup). Five tracks independently proposed the *same* fix (UUID in filename + occupancy lock). The distant tracks reframed it most vividly (single-width pound deadlock; one-runway occupancy clearance) but the recommendation is identical. **Highest convergence in the review.**

**[Convergence 8/10] Concurrency cap is unenforced prose (C-1).** Surfaced by: job-scheduler (P0, the definitive grep-confirmed analysis), ATC (P1, "throttle but no queue discipline"), canal-lock (P0 summit-pound + P1 fixed-lock-size), fd-architecture (P3, experimental subsystems threaded into hot path) and fd-correctness (empty-pool/dispatch boundary). The orthogonal/distant tracks supplied the enforcement mechanism (semaphore/wave dispatch from Kubernetes parallelism; summit-budget governor) that the adjacent tracks only gestured at.

**[Convergence 7/10] Convergence counted without checking source independence (C-4).** This is the marquee distant-track contribution. Surfaced by: newsroom ("two outlets running the same wire copy are one source"), scriptorium ("corrupted exemplar — copies agree but all wrong"; P1), cartography ("convoy bias" P1 + "shared compass-rose drift" P1), and the single-run analogs noted by fd-correctness/fd-quality via the hearsay machinery. Three completely different distant domains independently identified that interflux's *headline confidence metric* is structurally blind to correlated error — none of the adjacent code-reviewers raised it as a first-class finding. This is the clearest case of semantic distance paying off.

**[Convergence 6/10] Safeguards live in prose-to-the-LLM, not enforced code (meta-pattern).** This is the connective tissue under C-1 (concurrency cap), C-6 (sanitization), and the knowledge-redaction gap. Surfaced explicitly by fd-safety (P1, "advisory not enforced across four sinks"; P2 knowledge redaction), job-scheduler ("a posted speed limit, not an admission controller"), ATC ("a NOTAM, not a lock"; "the safety net defaults off"), canal-lock ("a NOTAM, not a lock"), scriptorium ("the corrector handed a second exemplar and told to file it without reading it"). The phrase "documented but not enforced" appears nearly verbatim in five tracks. The single most important structural theme of the whole review.

**[Convergence 6/10] No 429/rate-limit backpressure (C-2).** Surfaced by: job-scheduler (P0, definitive), ATC (P1 "go-around storm"), canal-lock (P0 summit drawdown), fd-correctness (spend-ceiling check/act window, the code-level sibling). The operations tracks (scheduling/ATC) own this one — it is exactly the kind of failure-under-saturation that adjacent code review tends to miss because it isn't visible in any single file.

**[Convergence 5/10] The single un-cross-checked synthesizer (C-5).** Surfaced by: cartography (P0, "invented coastline," nominated highest-leverage), scriptorium (P1, "the corrector collates, he does not merely re-bind"), newsroom (byline/provenance not surfaced in report), and the structural-grounding gap echoed by fd-quality (tests assert counts not invariants). The distant tracks named the mechanism (chart-of-charts; collatio vs concatenation) that the adjacent quality track only sensed as a coverage gap.

**[Convergence 5/10] Stall-rescue / quorum defaults off — all-or-nothing failure (C-9 family).** Surfaced by: job-scheduler (P1 quorum + P1 straggler), ATC (P3 "the safety net defaults off"), canal-lock (P2 "a lock-keeper would never run with overflow valves disabled"), fd-correctness (stall double/under-count edge). Strong agreement that `STALL_RESCUE=1` should be the default.

**[Convergence 4/10] Documentation/manifest drift (C-10).** Surfaced by: fd-architecture (P1), fd-quality (three separate P1s), fd-safety (P3, the security framing — undocumented openrouter MCP hides attack surface). Unanimous among the adjacent track; the distant tracks did not reach it (it requires code/doc familiarity, not structural reasoning — the inverse of C-4).

**[Convergence 3/10] Conflicting recommendations preserved but never adjudicated or surfaced.** Surfaced by: newsroom (P1, "sources differ standfirst"), cartography (P2, "two coastlines and ships into the gap"), and the spec's own Rule 5. The journalism and chartmaking lenses both want factual contradictions escalated to their own finding, not shelved.

---

## 3. Domain-Expert Insights (Track A)

Grouped by theme. These required code-level familiarity that the orthogonal/distant tracks could not supply.

**Entropy and drift, not coupling, is the dominant architectural defect.** fd-architecture's framing is the review's best one-line diagnosis: "the bones are good; the connective tissue has rotted faster than the docs." Concrete instances: `SKILL-compact.md` is a stale 16KB orphaned parallel copy whose drift-detection manifest hash already mismatches its source (`543f82…` recorded vs `80983b…` actual) and which nothing in the runtime references (P1); dangling cross-repo contract links escape the repo root to a nonexistent `docs/contracts/` (`SKILL.md:196,256`, P1); the script directory has 40 files against ~14 documented (P3); `launch.md`/`synthesize.md` have accreted ~15 optional integrations into god-files burying the mandatory path (P2).

**Concrete correctness defects beyond the convergent ones.** fd-correctness surfaced code-specific bugs no distant lens could see: `cmd_record` lost-update on `use_count`/tier promotion under concurrent reviews (`flux-agent.py:615-663`, P2 — can stick an agent one review short of `proven`); `token-count.py` returns `total:0` instead of the intended chars/4 fallback for an all-malformed transcript (P3); temp-file cleanup glob can delete a concurrent run's `/tmp` files (P3).

**The executable code quality is genuinely high — the problem is everything around it.** fd-quality explicitly praises `mcp-servers/openrouter-dispatch/index.ts` (atomic write+rename, O_EXCL locking with stale-break, `0o600`/`0o700`, no `any`, deliberate EX_CONFIG exit) as "the quality bar the rest of the repo should match," and `sanitize_untrusted.py` as conservative and idiomatic. The flagged defects are drift, dead validation (`validate-roster.sh` always exits 1, P1), agent-section skew (3 of 7 technical agents lack "What NOT to Flag"/"Focus Rules", P2), and untested security-critical Python (P2).

**Security engineering is above-average; residual risk is in enforcement gaps.** fd-safety verified and cleared the things that usually bite (path traversal via agent name and SLUG, command injection in helpers, SSRF, committed secrets, state-file perms) and concentrated its findings on the *enforcement* meta-pattern, the openrouter spend/abuse surface, and the auto-`npm ci && npm run build` at MCP startup (`launch-openrouter.sh:19-23`, P1 supply-chain — should ship prebuilt `dist/` or use `--ignore-scripts`).

---

## 4. Parallel-Discipline Insights (Track B)

Operational patterns from professions that run fan-out-under-saturation for a living.

- **Kubernetes `parallelism` / wave dispatch (job-scheduling → C-1).** The transfer: an admission controller is a gate the dispatcher *cannot bypass*, not advice. Practical form for interflux: dispatch in fixed waves of N, block on `flux-watch.sh {OUTPUT_DIR} {wave_size}` between waves — robust to LLM non-determinism in a way in-turn counting can never be.

- **client-go exponential backoff + multiplicative-decrease (job-scheduling → C-2).** The transfer: on 429, re-enqueue with backoff+jitter AND reduce effective concurrency for the rest of the run (TCP congestion control). A distinct failure class from the crash retry, which interflux currently conflates.

- **MapReduce backup tasks / quorum reads (job-scheduling → C-9).** The transfer: declare success on a threshold (K of N), and speculatively re-dispatch an agent exceeding `2× median(completed cohort)` once quorum is reached — the atomic-rename invariant already makes the loser's late write a harmless no-op.

- **EFC holding-stack queue discipline (ATC → C-1 refinement).** The transfer: the throttle currently specifies *when* to wait but not *which* pending agent claims a freed slot. Make it FIFO-by-merit with a monotonic guarantee — "never re-rank an already-queued agent below a newly-arrived one" — so a low-listed agent can't be perpetually starved.

- **Positive-control handoff manifest (ATC → C-8).** The transfer: a handoff isn't complete until the receiver acknowledges ("radar contact"). Emit an explicit Phase-2 manifest of `{agent, terminal_state ∈ completed|stalled|refused|errored, run_uuid}` that Phase 3 validates against, rather than counting `.md` blips that a stub, an aborted partial, and a real completion all satisfy identically.

- **Role-aware minimum-safe-altitude floor (ATC → safety floor).** The transfer: the `min_agents: 2` floor's exempt agents (fd-safety, fd-correctness) are themselves pre-filtered out for plain document inputs, so a budget-collapsed plan review can degrade to two narrow lenses with no cross-cutting reviewer. Always retain at least one domain-general agent (fd-architecture/fd-quality) in the floor.

- **"Sources differ" standfirst + byline accountability (newsroom → conflict surfacing).** The transfer: route Rule-5 recommendation conflicts into the Conflicts section as first-class "sources differ" entries with a one-line reconciliation note; add a model_family/convergence "Source" column and a "Verify independently" badge to the user-facing report so a scary P0 from a cheap single source is visibly marked. The provenance data already exists in `findings.json`; it dies at the last mile.

- **Quality spike + house-style byline contract (newsroom → research agents).** The transfer: research agents don't emit the `### Sources / ### Findings / ### Confidence / ### Gaps` + sentinel sections that synthesis Step 3.1 validates for, so they fall to prose fallback losing structured attribution. Either fix the agent definitions or relax the validator — don't let validator and reporters disagree on house style. And add a synthesis-time "spike" gate for completed-but-evidence-free filings.

---

## 5. Structural Insights (Track C)

Mechanisms from distant fields that revealed something the code's own vocabulary obscured.

- **Corrupted-exemplar invisibility (scriptorium).** Mechanism: a corrector collating copies *against each other* can never detect an error present in the shared exemplar, because the copies agree. interflux *has* the multi-exemplar mechanism (the FluxBench challenger dispatches a non-Claude model) but deliberately excludes it from synthesis ("runs in shadow only," `launch.md:224`) — the corrector handed an independent exemplar and told to file it unread. Promoting even one challenger finding into synthesis as a *disagreement flag* (not a verdict vote) converts shadow-mode into genuine multi-exemplar collation. **Concrete improvement.**

- **Convoy bias / shared compass-rose drift (cartography).** Mechanism: two ships in convoy sharing one lookout produce one observation wearing two hats; if every pilot used the same miscalibrated compass, all bearings agree and all are wrong by the same angle — convergence is highest exactly where systematic error is shared. This is the structural root of C-4 and the strongest argument that single-family convergence should print as *suspicious*, not "High confidence."

- **Vouched-vs-transcribed witness / primed echo (scriptorium + cartography).** Mechanism: a colophon distinguished a reading the scribe vouched for from one transcribed "as I found it." interflux's compounding step already makes this distinction for *knowledge entries* (independent vs primed confirmation, `synthesize.md:578-583`) but the synthesis *report's* convergence counts do not — an agent can "converge" on a finding it was primed with via reaction-round peer findings or injected knowledge. Split convergence counts into independent witnesses vs primed echoes. **Concrete improvement** that reuses an existing primitive.

- **Pecia per-piece pre-correction (scriptorium).** Mechanism: each rented piece was verified against the master before circulation, so a scribe copying piece 7 in isolation still produced globally-faithful text. interflux's slicing tags out-of-scope *discoveries* but has no symmetric check for out-of-scope *refutations* — a sliced agent can flag an issue that is actually resolved in a section it only saw summarized. Open question / candidate: a synthesis-time re-check of each sliced finding against the full document.

- **Summit-pound water budget (canal-lock).** Mechanism: the scarcest *shared* reservoir gates the whole staircase regardless of per-lock size. The named insight: actual peak concurrency is `tracks × per_track_cap + Σ(speculative expansion) + Σ(research escalations) + challenger shadows` — additive against one API reservoir but governed by independent per-lock caps, with no component computing total drawdown. Argues for one run-global (ideally session-global) summit-budget semaphore that *every* dispatch path decrements. Reinforces C-1 at the architectural rather than code level.

- **Open-loop process-health monitoring (scriptorium).** Mechanism: a scriptorium's praepositus watched for a deteriorating hand and corrected *future* copying. interflux's discourse-fixative (Participation Gini, novelty/herd-drift detection) is an independent reinvention of this — a genuine strength — but the loop is open: a Gini-imbalance detected at synthesis has no path back to re-dispatch a balanced roster. Surfacing the fixative envelope as a first-class report line ("this verdict came from a herd-converged round") lets the human apply the discipline the engine detected but cannot enact.

(Three structural mechanisms — synthesis `collatio` rules, the run-uuid quire-mark, and the discourse-fixative — turned out to be independent reinventions of scriptorium disciplines, confirming the isomorphism is real rather than metaphorical, and that interflux's gaps cluster exactly where it trusts agreement without auditing independence.)

---

## 6. Synthesis Assessment

**Overall quality.** interflux is a mature, genuinely well-engineered orchestration engine with a sound core decomposition, exemplary MCP-server code, and above-average security thinking — whose two systemic weaknesses are that its operational safeguards live as instructions to an LLM rather than enforced code, and that its headline confidence metric (convergence) is structurally blind to the correlated error of a shared base model.

**Highest-leverage single improvement.** Move the safeguards from prose to enforced code chokepoints — concretely, a single run-scoped `flock`-guarded semaphore + UUID-in-filename + occupancy lock that simultaneously fixes the concurrency cap (C-1), the OUTPUT_DIR collision (C-3), and gives 429 backpressure (C-2) a place to live. This one mechanism resolves the three highest-convergence findings at once. (The cartography track's structural-grounding check on the synthesizer, C-5, is the strongest *single-finding* fix; the semaphore is the strongest *leverage* fix because it collapses three convergent P0s.)

**Most surprising finding.** That interflux's confidence signal is self-undermining: it injects peer findings and knowledge into agent prompts, then counts the resulting agreement as convergence — so the engine can manufacture the very corroboration it reports as high-confidence (scriptorium's "contaminated witness," cartography's "convoy bias"). No single track operating from inside the code would have framed the headline metric as a *liability*; it took the manuscript and chartmaking lenses, which treat agreement-without-independence as the cardinal sin of their craft.

**Did semantic distance pay off?** Decisively yes, and asymmetrically. The adjacent track (A) owned the findings that require code familiarity — documentation drift (C-10), the specific concurrency/regex/lost-update bugs, the spend-ceiling check/act window, the auto-build supply-chain risk — that no distant lens could have found. But the distant track (C) contributed the qualitatively *different* class of insight: the convergence-independence critique (C-4), the corrupted-exemplar/shared-compass blindness, the un-cross-checked-compiler hazard (C-5), and the primed-echo contamination — none of which any adjacent reviewer raised as a first-class finding. The orthogonal track (B) sat productively in between: it supplied the *enforcement mechanisms* (Kubernetes parallelism, client-go backoff, MapReduce quorum, ATC positive-control handoff) for problems the adjacent track only diagnosed. The three tracks were complementary rather than redundant — A found the bugs, B found the missing controls, C found the wrong assumptions — and the strongest signals are exactly the few findings all three independently reached.
