source_domain: Distributed-systems batch/job scheduling (Kubernetes Job controller, Airflow DAG executor, Slurm). distance_rationale: Same abstraction level as interflux — orchestrate many parallel workers toward one result — but in production infra, not LLM agents.
expected_isomorphisms: work-queue dispatch, concurrency limits/backpressure, retry & idempotency, partial failure & quorum, straggler/timeout handling, completion detection, result aggregation.

# Track B — Orthogonal: Distributed Batch/Job Scheduling Lens

I read flux-drive's orchestration as a fan-out job controller: triage builds a work set (agents), Phase 2 dispatches them as parallel "pods" (`Agent` Task calls with `run_in_background: true`), each writes a result object to a shared "volume" (`{OUTPUT_DIR}`), completion is signalled by an atomic rename (`.md.partial → .md`), and synthesis is the reduce step. Through the lens of a controller that has to keep thousands of Jobs converging despite a flaky API server and slow nodes, here is where interflux's control loop is thinner than its prose claims.

---

**[P0] The concurrency cap is a comment, not an admission controller — nothing enforces it** — `skills/flux-engine/phases/launch.md:156-174`

The pattern: every real fan-out scheduler enforces parallelism with a hard counter that gates admission. Kubernetes Job has `.spec.parallelism` checked by the controller before it creates the next pod; Airflow has `max_active_tasks` enforced by the scheduler loop; Slurm has `MaxJobsPerUser` enforced by the slurmctld. The limit is a *gate the dispatcher cannot bypass*, not advice.

The gap: `MAX_CONCURRENT_AGENTS` is documented as a "dispatch loop pattern" the orchestrator LLM is asked to follow in natural language ("Track in-flight Task calls… if `in_flight_count >= MAX_CONCURRENT_AGENTS`, wait…"). I grepped the entire `scripts/` tree — there is no semaphore, no counter, no admission code anywhere (`grep MAX_CONCURRENT_AGENTS scripts/` returns nothing; the only enforcement is `flux-watch.sh` *observing* completion after the fact). The cap depends entirely on the model reliably counting its own outstanding background tasks across a long phase, including the Stage-1 / speculative-Stage-2 / Stage-2-batch / reaction-round paths that each fan out separately (`expansion.md:305`, `reaction.md`). An LLM that emits 8 `Agent` tool calls in one turn (which the harness encourages — see "make all independent calls in the same block") has already breached the cap before any "wait" instruction executes. In scheduling terms: there is no admission controller, only a posted speed limit.

The fix: enforce the cap mechanically. Add a `flux-dispatch.sh` (or extend `flux-watch.sh`) that owns a token/semaphore file in `{OUTPUT_DIR}` — the orchestrator must acquire a slot (decrement a counter file under `flock`) before each `Agent` call and the slot is released when `flux-watch` observes the agent's `.md`. Even simpler and robust to LLM non-determinism: dispatch in fixed-size *waves* of `MAX_CONCURRENT_AGENTS` and block on `flux-watch.sh {OUTPUT_DIR} {wave_size}` between waves, rather than trusting in-turn counting. This is the Kubernetes `parallelism` model: never have more than N in flight, replenish as they finish.

---

**[P0] No backpressure or retry on API rate-limit (429) — the one failure the system is guaranteed to hit is unhandled** — `skills/flux-engine/phases/launch.md:158-161`, `phases/shared-contracts.md:148-154`

The pattern: a job controller treats the upstream scheduler/API as a saturable resource. Kubernetes client-go has built-in rate-limiter + exponential backoff with jitter on apiserver 429s; Airflow retries tasks with `retry_exponential_backoff`; Slurm requeues on transient node/controller errors. Backpressure (slow the dispatch rate when the upstream pushes back) is the core survival mechanism of fan-out under a shared limit.

The gap: the launch doc's own rationale says the cap exists because "Anthropic API rate limits… degrade throughput" and cites "~30% retry-token waste at 16-agent fan-out" — i.e. the authors *know* 429s happen — yet there is no 429/backoff path anywhere. `grep -i '429|backoff|rate.limit' scripts/` finds only `cost_capture.sh`'s unrelated DB-grace retry. The only retry that exists is the *partial-completion* Retry Race Protocol (`shared-contracts.md:83-109`), which fires when an agent left a `.md.partial` — it does NOT distinguish "agent was rate-limited and never started" from "agent crashed" from "agent is just slow," and it retries **synchronously at the same concurrency** with no backoff. If the run hit the rate limit because too many agents fanned out, the retry storm hits the same wall. Worse, the synthetic-refusal path (`launch.md:272-307`) downgrades model tier on a Usage-Policy refusal but a plain 429 leaves no `.md` and no `.partial`, so it's invisible until `flux-watch` times out 300s later.

The fix: add a transient-failure class. When an `Agent` call returns a rate-limit error (or its transcript shows a 429), (1) do NOT count it as failed, (2) re-enqueue it with exponential backoff + jitter (`base * 2^attempt`, capped), and (3) reduce the effective concurrency for the remainder of the run (multiplicative-decrease, like TCP / client-go). This is distinct from the crash retry and must precede the 300s timeout, not follow it.

---

**[P1] No straggler mitigation — one slow agent blocks synthesis for the full 300s timeout × the all-or-nothing wait** — `phases/synthesize.md:5-13`, `phases/launch.md:262-270`

The pattern: stragglers are the dominant tail-latency cause in fan-out (MapReduce backup tasks, Spark speculative execution, Kubernetes `activeDeadlineSeconds` + Job `completions` with a `backoffLimit`). The standard tools are (a) speculative re-execution of a task that is far slower than its cohort, and (b) a *quorum* completion rule so the reducer doesn't wait for the slowest worker.

The gap: synthesis Step 3.0 (`synthesize.md:5-13`) demands "N files (one per launched agent)" and says "If count < N, Phase 2 did not complete properly." Phase 2 monitoring (`launch.md:262`) waits on `flux-watch.sh {OUTPUT_DIR} {N} {TIMEOUT=300}` — a single 5-minute wall for the *whole cohort*. There is no per-agent deadline relative to cohort progress: an agent that is 4× slower than its peers is indistinguishable from a healthy one until the global 300s expires. `STALL_RESCUE` (`flux-watch.sh:73-129`) is the closest mechanism, but it only fires for agents with *neither* `.md` nor `.partial` — an agent stuck mid-write (`.partial` present, never renames) is explicitly excluded (`flux-watch.sh:124`) and rides the full timeout. There's no speculative re-dispatch of a lagging-but-alive agent.

The fix: borrow MapReduce backup tasks. Track per-agent elapsed time in `flux-watch`; when an agent exceeds, say, `2× median(completed cohort)` AND the cohort is ≥ quorum complete, speculatively re-dispatch that agent (cheaper model is fine) and take whichever `.md` lands first — the atomic-rename invariant (`shared-contracts.md:76`) already guarantees at-most-one terminal file, so the loser's late rename harmlessly no-ops. Pair with the quorum rule below so synthesis starts without the straggler at all.

---

**[P1] No quorum / "enough succeeded" threshold — completion is all-or-nothing and a single survivor is treated like a full review** — `phases/synthesize.md:5-13`, `phases/reaction.md:11-14`

The pattern: a robust fan-out job declares success on a *threshold*, not on every worker. Kubernetes Job `completions`/`backoffLimit`, Slurm array-job exit policies, and quorum reads in storage all encode "K of N is enough; below K the result is invalid." This makes partial failure a first-class, reportable outcome rather than a silent degradation.

The gap: interflux has no minimum-success threshold. Synthesis proceeds with whatever `.md` files exist (error stubs and stall stubs included — `synthesize.md:39`, `shared-contracts.md:80-81`), and the reaction round's only count-based guards are `agent_count == 0/1` (`reaction.md:12-14`). There is no concept of "this review is invalid because only 1 of 6 agents produced findings — the other 5 were rate-limited stubs." A run where 5 of 6 agents hit the unhandled 429 path (P0 above) and emit stall stubs will still produce a confident `summary.md` and a `verdict`, computed from one agent, with no signal to the user that the review is statistically empty. Convergence scoring (the system's headline confidence signal) silently collapses because there are no peers to converge with.

The fix: add `min_quorum` to `budget.yaml` (e.g. `max(2, ceil(0.5 * launched))`, with exempt agents `fd-safety`/`fd-correctness` required if launched). If completed-non-stub agents < quorum, mark the run `verdict: incomplete` and surface it prominently in the Step 3.5 report ("Review INVALID: 1/6 agents produced findings; 5 stalled/rate-limited — rerun"). This turns the existing stall/error stubs from cosmetic into actionable.

---

**[P1] At-least-once completion semantics + non-atomic dedup window can let a stale or duplicate result enter the reduce** — `phases/shared-contracts.md:74-111`, `skills/flux-engine/SKILL.md:119-122`

The pattern: completion signalling in job systems must be exactly-once at the *reduce* boundary. Schedulers use generation/UID stamping (Kubernetes `controller-uid` label, pod `ownerReferences`) and idempotent result keys so a re-run worker's late output is recognized and discarded, never double-counted, and a stale result from a prior run is never read.

The gap: interflux is fundamentally *at-least-once* (it can retry/speculate) but its de-duplication of late writes relies on a multi-step, non-atomic dance: the Retry Race Protocol (`shared-contracts.md:83-109`) does `touch .abort` → `mv .partial → .partial.aborted-$ts` → launch retry, betting the original's eventual `mv .partial → .md` "finds no source and fails harmlessly." But the original agent constructs its target name itself and may `mv` a *fresh* `.partial` it re-created, or write directly to `.md`; `mv` without `-n` will clobber (the doc admits this at `shared-contracts.md:76`: "mv itself doesn't refuse to overwrite without `mv -n`"). The cross-run defense is the `run-uuid` quire-mark checked at synthesis (`synthesize.md:27-32`) plus a pre-dispatch `find -delete` (`SKILL.md:119-122`) — but the content-addressed `OUTPUT_DIR` is *deliberately stable across reruns* for cache hits (`SKILL.md:112-117`), so two overlapping runs on the same target share a directory and the only guard against a prior run's slow agent renaming into the new run's findings is that pre-clean `find -delete`, which races the slow agent.

The fix: make the result key carry the run UUID in the *filename*, not just the file body — write `{agent}.{RUN_UUID}.md` and have synthesis glob only the current UUID. This makes a stale prior-run file structurally unreadable (it has a different UUID in its name) and makes the retry/original race a non-issue (retry writes a different name than a stale original). It's the Kubernetes controller-uid pattern applied to the filesystem result store. Also switch every completion `mv` to `mv -n` to make the "harmless no-op" actually enforced rather than asserted.

---

**[P2] No poison-pill / crash-loop protection — an input that deterministically refuses or crashes one model tier will be retried into the next tier, burning budget** — `phases/launch.md:272-307`

The pattern: schedulers cap retries precisely because some failures are *deterministic in the input* — Kubernetes `backoffLimit` exists so a CrashLoopBackOff pod doesn't retry forever; Airflow `retries` is bounded; dead-letter queues exist to quarantine poison messages so one bad record can't stall the queue.

The gap: interflux correctly identifies that the Usage-Policy refusal is *deterministic for a given input* ("retrying identical input will refuse again," `launch.md:305-307`) and so downgrades the tier instead of same-tier retrying — good. But there's no *global* poison-pill cap: a sliced diff chunk that trips the input classifier will refuse at opus → downgrade to sonnet → refuse → downgrade to haiku (`launch.md:285-291`), spending three dispatches per affected agent, and nothing records "this input slice is poison; stop sending it to *any* agent." If the poison is in the shared `REVIEW_FILE` (not an agent-specific slice), every agent in the cohort independently walks the same tier-downgrade ladder. There's also no circuit breaker: if the first 3 dispatched agents all refuse, the controller keeps launching the rest into the same wall.

The fix: add a cohort-level circuit breaker — if K agents (e.g. ≥3 or ≥50%) refuse on the *same* shared input, stop dispatching the remainder, quarantine that `REVIEW_FILE` (dead-letter it to `{OUTPUT_DIR}/quarantine/`), and report "input tripped the classifier; sanitize and rerun" once, instead of paying N×3 doomed dispatches.

---

**[P2] No in-flight observability — the controller is blind between dispatch and the 300s timeout** — `phases/launch.md:262-270`, `scripts/flux-watch.sh:42-50`

The pattern: every production scheduler exposes work *in flight*: `kubectl get pods` shows Pending/Running/Completed, Airflow's grid shows running vs queued vs up-for-retry, Slurm `squeue` shows R/PD with elapsed time. Operators (and autoscalers) act on the running set, not just the terminal set.

The gap: `flux-watch.sh` only emits a line when a `.md` *completes* (`report_agent`, lines 42-50) — it reports the terminal transition and nothing about the `writing` or `dispatched` states from the documented state machine (`shared-contracts.md:38-72`). There is no "3 running, 2 not-yet-started, 1 done at 90s" view. The orchestrator cannot tell a stuck agent (`.partial`, no progress) from a busy one until timeout, cannot tell a never-dispatched agent (`dispatched`, no `.partial`) from one about to finish, and the user sees silence for up to 5 minutes between completion lines. This is what makes the straggler (P1) and quorum (P1) gaps hard to act on — you can't mitigate what you can't see.

The fix: have `flux-watch` also watch for `.partial` creation (`-e create` alongside `close_write,moved_to`) and emit state-transition lines: `[dispatched→writing] fd-safety @12s`, `[writing→done] fd-safety @95s`, and on each stall tick print the running/pending/done split. This gives the orchestrator (and the speculative-execution logic) a live view of the running set — the precondition for every other mitigation above.

---

**[P2] Cross-phase fan-out has no global concurrency accounting — Stage 1 + speculative Stage 2 + reaction round can be in flight simultaneously, each capped independently** — `phases/expansion.md:96-127`, `phases/launch.md:166-172`, `skills/flux-review-engine/phases/track-dispatch.md:188-196`

The pattern: a scheduler accounts for *all* in-flight work against one quota, regardless of which control path created it. You don't get a fresh `parallelism` budget per Job phase; the cluster-wide concurrent-pod limit is global.

The gap: the `MAX_CONCURRENT_AGENTS` cap is described as "per flux-drive run" (`launch.md:170`), but the phases that fan out — Stage 1 (`launch.md:184`), *incremental* speculative Stage 2 launched *while Stage 1 is still running* (`expansion.md:96-105`, "max 2 speculative launches" that "do NOT count against the slot ceiling"), Stage 2 batches (`expansion.md:305`), and the reaction round — each reason about concurrency locally. Speculative launches explicitly bypass the slot accounting. At the outer flux-review layer this compounds: `track-dispatch.md:188-196` tries to bound the multiplicative blow-up (4 tracks × 6 = 24) by passing `PER_TRACK_AGENT_CAP=3`, but again only as a *prose instruction* to each inner run — there's still no shared counter, so the real ceiling is `min(tracks,4) × 3` *only if every nested LLM obeys*. The 30%-retry-waste figure the docs cite is exactly the symptom of overshooting a shared limit with uncoordinated dispatchers.

The fix: a single run-scoped (and ideally session-scoped, spanning tracks) semaphore file that *all* dispatch paths acquire from — Stage 1, speculative, Stage 2, reaction, and each track's inner run. This is the "one global quota, all phases draw from it" model. It also makes the speculative-launch "doesn't count against slots" rule safe: it can still skip the *triage* slot ceiling while still acquiring a *concurrency* token, decoupling "how many agents we picked" from "how many may run at once" — the same distinction Kubernetes draws between `completions` and `parallelism`.
