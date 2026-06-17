---
source_domain: The medieval monastic scriptorium — parallel copyists reproducing an exemplar under a master corrector (armarius), with the pecia exemplar-distribution system, rubrication/illumination layers, and colophon attribution.
distance_rationale: Pre-modern manual knowledge-reproduction craft, centuries and modalities removed from LLM orchestration.
expected_isomorphisms: fan-out copying from one exemplar (one prompt → many agents); scribal drift propagating (model error propagation); the corrector's collation pass (synthesis); pecia piecewise distribution (input slicing); colophon attribution (provenance).
---

# Track C — Scriptorium Lens on interflux

A scriptorium and a multi-agent review engine are both systems for reproducing knowledge in parallel and then reconciling the copies. The medieval craft spent four centuries hardening exactly the failure modes interflux now faces — divergence control, drift detection, attribution, and the corrector's authority. Mapped below.

---

**[P1] Correlated scribal drift — no exemplar-diversity guard at the base-model level** — `skills/flux-engine/phases/launch.md:238-247`, `launch.md:224`

The scriptorium's deepest fear was a *corrupted exemplar*: if the master copy from which all scribes worked contained an error, every copy reproduced it faithfully, and the corrector — collating copies against *each other* — could never detect it, because the copies agreed. The defense was the **pecia system + multi-exemplar collation**: critical texts were collated against independent exemplars from different houses precisely so that shared-source errors surfaced as disagreement.

interflux's review agents are all dispatched as Claude subagents (`launch.md:238-247`, "Plugin Agents (interflux): Use the native subagent_type"). They share one base model — one exemplar. interflux's *entire confidence signal is convergence* (track-synthesis.md:36-43: "Findings that appeared independently in 2+ tracks — the highest-confidence signals"). But convergence among copies of one exemplar measures *agreement on the shared prior*, not truth. A blind spot baked into the base model (a class of bug Claude systematically under-flags) produces silent unanimous omission — the scriptorium's corrupted-exemplar failure, invisible precisely because all scribes agree.

interflux *has* the multi-exemplar mechanism — the FluxBench challenger dispatches a non-Claude model via openrouter (`launch.md:210-218`) — but deliberately neuters it as a collation input: "The challenger's output is **NOT included in synthesis** — it runs in shadow only" (`launch.md:224`). This is the corrector being handed a second independent exemplar and told to file it without reading it. **Insight:** the highest-confidence signal interflux reports (cross-track convergence) is structurally incapable of catching base-model-correlated error, and the one mechanism that could — cross-model collation — is explicitly excluded from the verdict. Promoting even one challenger finding into synthesis as a *disagreement flag* (not a verdict vote) would convert shadow-mode into genuine multi-exemplar collation.

---

**[P1] The corrector collates; he does not merely re-bind the quires** — `skills/flux-engine/phases/synthesize.md:110-119`, `skills/flux-review-engine/phases/track-synthesis.md:36-43`

The armarius/corrector's defining act was *collatio*: reading divergent copies line-against-line, reconciling readings, and entering the authoritative variant — not stacking the copies in a pile. A scriptorium that only gathered quires and bound them produced a codex of contradictions.

interflux's synthesis is genuinely a collation pass, not concatenation — and this is a strength worth naming: the 5 dedup rules (`synthesize.md:112-118`) are real *collatio* logic (same locus + same reading → merge and credit all witnesses; same locus + divergent readings → keep both, tag co-located; conflicting severity → take the highest). This maps almost exactly to a textual critic's apparatus. **But** the rules operate on `file:line + issue` tuples (rule 1: "Same file:line + same issue → merge"). Two scribes describing the *same underlying corruption* in different words at *different loci* (rule 3: "Same issue + different locations → keep separate") are kept apart. A corrector recognizes a recurring scribal habit across the whole manuscript as *one* defect; interflux's locus-keyed dedup will surface it as N separate findings, inflating apparent issue count and diluting the convergence signal for what is really one root cause. **Insight:** synthesis collates by locus but not by *root cause*; a "same-defect-class across loci" merge rule (the corrector's recognition of a systematic scribal habit) would tighten the apparatus.

---

**[P0] Colophon integrity — provenance is stamped but the corrector cannot read the variant's pedigree** — `skills/flux-engine/phases/synthesize.md:578-582`, `shared-contracts.md:156-164`, `synthesize.md:27`

The colophon recorded *who* copied a manuscript and *from which exemplar* — and crucially distinguished a reading the scribe *vouched for* from one he merely *transcribed from a doubtful source* (sicut inveni, "as I found it"). interflux has strong run-level provenance — the quire-mark `<!-- run-uuid -->` (`synthesize.md:27`, `launch.md:17`) detects cross-run contamination, a genuine pecia-discipline mechanism preventing a stale copy from another run binding into this codex.

The gap is at the *finding* level. The compounding step's provenance rules (`synthesize.md:578-582`) correctly distinguish "independently confirmed" from "primed confirmation" — the scriptorium's vouched-vs-transcribed distinction — but only the *knowledge entry* carries that flag. The synthesis report's findings (`synthesize.md:386-394`) attribute findings to agents and convergence counts, with no marker for whether a converging agent *independently found* the issue or merely *echoed an injected knowledge entry / a peer finding*. Because reaction-round peer findings (`reaction.md:135-139`) and knowledge context (`launch.md:140` item 3) are injected into agent prompts, an agent can "converge" on a finding it was primed with — the scriptorium's *contaminated witness*, where two manuscripts agree only because one was copied from the other. **Insight:** convergence counts in `findings.json` and the report should be split into *independent witnesses* vs *primed echoes*, exactly as the trust-boundary already does for knowledge entries (`shared-contracts.md:156-164` already treats injected content as untrusted). Without this, the headline confidence metric (convergence) is contaminable by interflux's own injection channels.

---

**[P2] The pecia system — interflux distributes pieces but never validates them against the whole exemplar** — `skills/flux-engine/phases/slicing.md:68-94`, `slicing.md:91`

The *pecia* system let many scribes copy one expensive exemplar simultaneously by renting it out in numbered, independently-corrected *pieces (peciae)*. Its genius was that each piece was individually verified against the master before circulation, so a scribe copying piece 7 in isolation still produced text faithful to the whole. The risk it managed: a scribe given only fragments produces locally-plausible but globally-wrong text (a sentence that reads fine but contradicts a passage in a piece he never saw).

interflux's document/diff slicing (`slicing.md:68-94`) is precisely pecia distribution: each agent gets *priority* sections in full plus *context* summaries of the rest, so it can copy its assigned piece without the whole exemplar. interflux correctly guards the *cross-cutting* texts (fd-architecture, fd-quality always get the full manuscript — `slicing.md:9-14`), the scriptorium's instinct to never fragment the table-of-contents/rubric scribe's exemplar. And it discounts convergence from agents that only saw a summary (`slicing.md:91`: "Only count agents that saw content in full"). **The unaddressed pecia risk:** a sliced agent flags an issue in its priority section that is *actually resolved* in a section it only saw as a summary — a locally-correct, globally-wrong finding. interflux tags out-of-scope *discoveries* (`slicing.md:92`) but has no symmetric check for out-of-scope *refutations*. The pecia answer was per-piece pre-correction against the master; interflux's analog would be a synthesis-time pass that re-checks each sliced finding against the full document before it reaches the verdict.

---

**[P2] Drift-fixative as the corrector's scriptorium discipline, not a verdict input** — `skills/flux-engine/phases/reaction.md:56-67`

A well-run scriptorium had standing disciplines independent of any one manuscript: enforced silence, the *praepositus* watching for a scribe whose hand was deteriorating, and rotation to prevent one dominant scribe's idiosyncrasies from coloring a whole volume. interflux's discourse-fixative (`reaction.md:56-67`) is a remarkably direct analog: **Participation Gini** detects one agent dominating the findings (the scriptorium's dominant-hand problem), **Novelty estimate** detects convergence-collapse (all scribes producing the identical reading — herd drift), and the unconditional **Drift** injection is a standing discipline that "always fires." This is a genuine structural match and a design strength — interflux has independently reinvented the scriptorium's *process-health monitoring separate from text-quality judgment*.

**Insight/risk:** in the scriptorium these disciplines governed *future* copying behavior — they corrected the process, then the corrected scribes re-copied. In interflux the fixative only injects context into the *reaction round* (`reaction.md:137`); a Gini-imbalance or novelty-collapse detected at synthesis time has no path back to *re-dispatch* a more balanced roster. The health signal is computed but the loop is open. Surfacing the fixative envelope as a first-class line in the user report (it currently lives in `findings.json` discourse_health, `synthesize.md:351`) — "this verdict came from a herd-converged / single-dominated round, treat convergence with suspicion" — would let the human corrector apply the discipline the engine detected but cannot itself enact.

---

**[P3] Rubrication ordering — synthesis adds the rubric after collation, the safe order** — `skills/flux-engine/phases/synthesize.md:180-218`, `reaction.md:67`

Scriptorium production was strictly layered: the scribe wrote the black text first, *then* the rubricator added headings/initials in red, *then* the illuminator. Reversing the order — illuminating before the text was collated and corrected — meant gilding errors that then could not be cheaply removed. interflux respects this ordering: findings are collected and deduplicated (the black text) *before* `findings.json` severity verdicts and the section heat-map are computed (`synthesize.md:180-218` — the rubric), and the reaction round enforces a hard sequencing constraint that fixative computation must complete before reaction dispatch (`reaction.md:67`: "Step 2.5.2b MUST complete before Step 2.5.3 begins — do not parallelize"). This is the correct rubrication discipline and warrants no change. **Minor risk:** beads creation (`synthesize.md:445-477`) — the most expensive-to-reverse "illumination," since it writes tracked work items into an external system — happens *after* the report but with no human gate in default (non-interactive) mode. The scriptorium never illuminated unattended. A converged-but-base-model-correlated false P0 (see the first finding) auto-illuminates into a bead. Gating bead creation on the same confidence-disaggregation suggested above would prevent gilding a corrupted-exemplar error.

---

## Semantic-distance note

The scriptorium lens earns its distance: its most load-bearing insights (corrupted-exemplar invisibility to convergence; vouched-vs-transcribed witness contamination; pecia per-piece pre-correction) are *failure modes of agreement and provenance* that are nearly invisible from inside software, where "more agents agreed" reflexively reads as "more confident." Three of interflux's mechanisms (synthesis collatio rules, the quire-mark, the discourse-fixative) turn out to be independent reinventions of scriptorium disciplines — confirming the isomorphism is real, not metaphorical — and the gaps cluster exactly where interflux trusts agreement without auditing its independence.
