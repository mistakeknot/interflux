export const meta = {
  name: "flux-melange",
  description:
    "Goal-seeking spice-loop review: seed, heat-steered adaptive rounds, surfacing-first synthesis",
  phases: [
    {
      title: "Seed",
      detail: "design seed lenses, run adjacent+distant probes",
    },
    { title: "Synthesize", detail: "eye of distance over the full ledger" },
    {
      title: "Parley",
      detail:
        "adversarial synthesis exchange across runtimes to epistemic equilibrium",
    },
  ],
};

// ============================================================================
// flux-melange workflow fast-path (Claude Code only).
//
// Dispatched by skills/flux-melange-engine/SKILL.md § Runtime dispatch with
// the resolved charter as `args` (contract: references/workflow-args.md).
// The phase .md files remain the spec; this script is the deterministic
// runtime for the non-interactive path. The controller (heat map, directive
// selection, continue predicate) is plain code — "a pure function over the
// ledger" made literal. Agents keep writing the on-disk ledger and finding
// files so fetch-findings and post-hoc audit see the same artifacts as the
// prose path; the script steers on their schema-validated return values.
//
// In-loop ordering note: per round we run probe → assay → verify → score.
// The prose spec places assay before retarget, but verify's gate and score's
// yield both need assay scores for the round's OWN findings — this ordering
// resolves that (assay.md's "score.md (which also re-assays)" note).
//
// Peer mirrors (references/peer-runtimes.md): when charter passes `peers`,
// the SAME loop runs once per external runtime (codex, hermes) as an
// epistemically independent mirror — own ledger, own lenses, own synthesis,
// zero cross-contamination — with every agent call relayed through a
// transport shim to the external CLI. After all syntheses, the Parley phase
// (phases/parley.md) runs an adversarial exchange between per-runtime
// advocates until a moderator detects fixed point (epistemic equilibrium);
// residual contested items return to the orchestrator for user tie-break.
// ============================================================================

// Some hosts deliver Workflow `args` as a JSON string rather than an object.
const A = typeof args === "string" ? JSON.parse(args) : args;
for (const k of [
  "inputPath",
  "projectRoot",
  "outputRoot",
  "pluginRoot",
  "slug",
  "date",
  "goal",
  "weights",
  "targetDesc",
  "quality",
  "budget",
  "loop",
  "seed",
  "fusion",
  "verify",
]) {
  if (!A || A[k] === undefined)
    throw new Error(
      `flux-melange workflow: missing charter arg "${k}" — dispatch via SKILL.md § Runtime dispatch`,
    );
}
// Optional peer-mirror contract (absent = classic single-runtime run).
const PEERS = Array.isArray(A.peers)
  ? A.peers.filter((p) => p && p.kind && p.invoke)
  : [];
const EX = { maxRounds: 3, ...(A.exchange || {}) };

// Peer contract hardening (references/peer-runtimes.md § Trust boundary):
// kind and model are interpolated into shell command lines by the shim, so
// they are validated HERE at the chokepoint — charter validation alone is
// prose and can drift. invoke templates are trusted config by design, but
// must at least carry the {promptfile} placeholder to be usable at all.
const RT_KIND = /^[a-z][a-z0-9-]{1,15}$/;
const RT_MODEL = /^[A-Za-z0-9._:-]{1,64}$/;
for (const p of PEERS) {
  if (!RT_KIND.test(p.kind))
    throw new Error(
      `flux-melange: invalid peer runtime kind ${JSON.stringify(p.kind)}`,
    );
  if (p.model != null && !RT_MODEL.test(String(p.model)))
    throw new Error(
      `flux-melange: invalid peer model ${JSON.stringify(p.model)} — letters/digits/._:- only`,
    );
  if (!String(p.invoke).includes("{promptfile}"))
    throw new Error(
      `flux-melange: peer invoke template for ${p.kind} lacks {promptfile}`,
    );
}

const Q = A.quality;
const MODEL = {
  designAdjacent: Q === "max" ? "opus" : "sonnet",
  designDistant: Q === "economy" ? "sonnet" : "opus",
  probe: Q === "max" ? "opus" : "sonnet",
  fusedDesign: Q === "economy" ? "sonnet" : "opus",
  assay: Q === "economy" ? "sonnet" : "opus",
  verify: Q === "economy" ? "haiku" : "sonnet",
  synthesis: Q === "economy" ? "sonnet" : "opus",
  shim: "haiku", // transport only — the external model does the thinking
  advocate: Q === "economy" ? "sonnet" : "opus",
  moderator: Q === "economy" ? "sonnet" : "opus",
};

// ---- pure helpers ----------------------------------------------------------
const fmtId = (n) => `f-${String(n).padStart(3, "0")}`;
const heat = (f) => f.novelty * f.risk_product;
const normKey = (loc) =>
  String(loc || "")
    .toLowerCase()
    .replace(/^brainstorm\s+/, "")
    .replace(/:\d+(-\d+)?$/, "")
    .trim();

// Yield qualification, boosted by --weights (score.md § Step 2; triage-grade).
const qualifies = (f) => {
  const t = Math.abs(f.taste || 0);
  if (A.weights === "risk-hunt")
    return f.novelty >= 2 || f.risk_product >= 4 || t >= 2;
  if (A.weights === "taste")
    return f.novelty >= 2 || f.risk_product >= 6 || t >= 1;
  if (A.weights === "novelty")
    return f.novelty >= 1 || f.risk_product >= 6 || t >= 2;
  return f.novelty >= 2 || f.risk_product >= 6 || t >= 2;
};

// ---- run context ------------------------------------------------------------
// One per runtime. The primary (claude) keeps the classic root paths so
// fetch-findings, resume audits, and pre-peer tooling see identical artifacts;
// mirrors nest under mirrors/{kind}/ with a lens-name suffix so generated
// fd-* agent files in the shared .claude/agents/ namespace never collide.
function makeRun(rt) {
  const isPrimary = rt.kind === "claude";
  const base = isPrimary ? A.outputRoot : `${A.outputRoot}/mirrors/${rt.kind}`;
  return {
    rt,
    isPrimary,
    base,
    ledger: `${base}/heat-ledger.jsonl`,
    lensesDir: `${base}/lenses`,
    specTag: isPrimary ? "" : `-${rt.kind}`,
    nameSuffix: isPrimary ? "" : `-${rt.kind.slice(0, 2)}x`,
    pfx: isPrimary ? "" : `${rt.kind} · `,
    slotsRemaining: A.budget.totalSlots,
    nextFindingNum: 1,
    allFindings: [],
    clusters: {},
    lensRecords: {},
    fusedPairs: [],
    resolvedDisagreements: new Set(),
    gainHistory: [],
    spiceTrail: [],
    coverageKeys: new Set(),
    openDisagreements: [],
    adjacentLenses: [],
    distantLenses: [],
    haltReason: null,
    round: 0,
    synth: null,
    failed: null,
  };
}

// ---- shim relay for external runtimes ----------------------------------------
// The shim is a Claude agent used as a PIPE: it executes the task on the
// external CLI and relays the structured output verbatim. Model = haiku by
// construction — any reasoning in the shim would contaminate the mirror's
// epistemic independence. The schema still validates at the shim's tool-call
// layer, so malformed external output retries hit the shim, which re-asks the
// external CLI once before degrading.
function shimWrap(rt, inner, schema) {
  // Templates MAY carry an {outfile} placeholder (e.g. codex `-o`): the CLI writes its final
  // message there, so the shim reads a clean file instead of scraping a noisy stdout stream.
  const usesOutfile = String(rt.invoke).includes("{outfile}");
  const substNote = usesOutfile
    ? ' and your prompt file path with ".out" appended for {outfile}'
    : "";
  const extractStep = usesOutfile
    ? `Read the {outfile} file you substituted — it holds ONLY the external agent's final message. Take the FINAL JSON object from it (the agent may have written prose before it).`
    : `Take the FINAL JSON object from stdout (the CLI may print logs first).`;
  return `You are a TRANSPORT SHIM for the ${rt.kind} CLI${rt.model ? ` (model ${rt.model})` : ""}. You never answer the task yourself — the external model does ALL the thinking. Your only judgment is mechanical: run, extract, relay.

1. mkdir -p ${A.outputRoot}/mirrors/${rt.kind}/tmp and write the task below (the text between <<<TASK and TASK>>>, exclusive) to a uniquely named .md file there (filename: lowercase letters, digits, hyphens only — it is substituted into a shell command). Append this exact final paragraph:
   "End your reply with a single JSON object (no code fence, no prose after it) matching this JSON Schema: ${JSON.stringify(schema)}"
2. Execute it with ONE Bash call (timeout: 600000), substituting your prompt file path for {promptfile}${substNote}:
   ${rt.invoke}
3. ${extractStep} If it does not parse or misses required fields, re-run ONCE with this appended to the prompt file: "Previous output was not parseable. Reply with ONLY the JSON object."
4. Return that JSON verbatim as your structured output. Do not add, drop, merge, rescore, or reword anything in it.
5. If the CLI is missing, fails twice, or times out: return a minimally valid object for the schema (empty arrays; any required string field = "SHIM-FAILURE: <one-line reason>") so the loop degrades gracefully.

The external agent has filesystem access under ${A.projectRoot} and the task MAY ask it to write files there — that is expected; do not do the writing for it.

<<<TASK
${inner}
TASK>>>`;
}

// Every agent call in the loop flows through here: the primary dispatches
// natively; mirrors relay through the shim with the SAME schema.
function dispatch(R, prompt, opts) {
  if (R.isPrimary) return agent(prompt, opts);
  return agent(shimWrap(R.rt, prompt, opts.schema), {
    schema: opts.schema,
    label: `${R.rt.kind}:${opts.label}`,
    phase: opts.phase,
    model: MODEL.shim,
  });
}

// ---- schemas ---------------------------------------------------------------
const SEED_DESIGN_SCHEMA = {
  type: "object",
  required: ["lenses"],
  properties: {
    lenses: {
      type: "array",
      items: {
        type: "object",
        required: ["name", "domain", "axioms", "primitives", "failure_mode"],
        properties: {
          name: { type: "string" },
          domain: { type: "string" },
          axioms: { type: "array", items: { type: "string" } },
          primitives: { type: "array", items: { type: "string" } },
          failure_mode: { type: "array", items: { type: "string" } },
        },
      },
    },
  },
};

const PROBE_SCHEMA = {
  type: "object",
  required: ["findings"],
  properties: {
    findings: {
      type: "array",
      items: {
        type: "object",
        required: ["lens", "slug", "severity", "claim", "location", "evidence"],
        properties: {
          lens: { type: "string" },
          slug: { type: "string" },
          severity: { type: "string", enum: ["P0", "P1", "P2", "P3"] },
          claim: { type: "string" },
          location: { type: "string" },
          evidence: { type: "string" },
          suggestion: { type: "string" },
          taste_flag: { type: "boolean" },
          intersection_justification: { type: ["string", "null"] },
        },
      },
    },
    verdict: { type: "string" },
  },
};

const ASSAY_SCHEMA = {
  type: "object",
  required: ["findings"],
  properties: {
    findings: {
      type: "array",
      items: {
        type: "object",
        required: [
          "id",
          "slug",
          "agents",
          "location",
          "severity",
          "cluster_id",
          "new_cluster",
          "novelty",
          "blast_radius",
          "likelihood",
          "risk_product",
          "taste",
        ],
        properties: {
          id: { type: "string" },
          slug: { type: "string" },
          agents: { type: "array", items: { type: "string" } },
          location: { type: "string" },
          severity: { type: "string" },
          cluster_id: { type: "string" },
          new_cluster: { type: "boolean" },
          novelty: { type: "integer", minimum: 0, maximum: 3 },
          blast_radius: { type: "integer", minimum: 0, maximum: 3 },
          likelihood: { type: "integer", minimum: 0, maximum: 3 },
          risk_product: { type: "integer", minimum: 0, maximum: 9 },
          taste: { type: "integer", minimum: -2, maximum: 2 },
          taste_kind: { type: ["string", "null"] },
          emergent: { type: ["boolean", "null"] },
          claim: { type: "string" },
        },
      },
    },
    disagreements: {
      type: "array",
      items: {
        type: "object",
        required: ["location", "finding_ids"],
        properties: {
          location: { type: "string" },
          finding_ids: { type: "array", items: { type: "string" } },
        },
      },
    },
  },
};

const FUSED_DESIGN_SCHEMA = {
  type: "object",
  required: ["agent_name", "domain", "axioms", "primitives", "failure_mode"],
  properties: {
    agent_name: { type: "string" },
    domain: { type: "string" },
    axioms: { type: "array", items: { type: "string" } },
    primitives: { type: "array", items: { type: "string" } },
    failure_mode: { type: "array", items: { type: "string" } },
  },
};

const VERIFY_SCHEMA = {
  type: "object",
  required: ["results"],
  properties: {
    results: {
      type: "array",
      items: {
        type: "object",
        required: ["id", "status"],
        properties: {
          id: { type: "string" },
          status: { type: "string", enum: ["upheld", "refuted"] },
          emergent_keep: { type: ["boolean", "null"] },
          note: { type: "string" },
        },
      },
    },
  },
};

const SYNTH_SCHEMA = {
  type: "object",
  required: ["synthesis_path", "surfaced_count", "top_finding"],
  properties: {
    synthesis_path: { type: "string" },
    surfaced_count: { type: "integer" },
    top_finding: { type: "string" },
    caveats: { type: "array", items: { type: "string" } },
  },
};

const ADVOCATE_SCHEMA = {
  type: "object",
  required: ["positions", "changed_mind"],
  properties: {
    positions: {
      type: "array",
      items: {
        type: "object",
        required: ["topic", "stance", "argument"],
        properties: {
          topic: { type: "string" },
          stance: {
            type: "string",
            enum: ["concede", "challenge", "affirm", "novel"],
          },
          re_runtime: { type: ["string", "null"] },
          argument: { type: "string" },
          evidence: { type: "string" },
        },
      },
    },
    changed_mind: { type: "boolean" },
  },
};

const MODERATOR_SCHEMA = {
  type: "object",
  required: ["agreed", "contested", "changed"],
  properties: {
    agreed: {
      type: "array",
      items: {
        type: "object",
        required: ["topic", "statement"],
        properties: {
          topic: { type: "string" },
          statement: { type: "string" },
          holders: { type: "array", items: { type: "string" } },
        },
      },
    },
    contested: {
      type: "array",
      items: {
        type: "object",
        required: ["topic", "positions"],
        properties: {
          topic: { type: "string" },
          heat: { type: "integer", minimum: 0, maximum: 9 },
          positions: {
            type: "array",
            items: {
              type: "object",
              required: ["runtime", "argument"],
              properties: {
                runtime: { type: "string" },
                argument: { type: "string" },
                evidence: { type: "string" },
              },
            },
          },
        },
      },
    },
    changed: { type: "boolean" },
  },
};

// ---- prompt fragments -------------------------------------------------------
const FINDINGS_FILE_CONTRACT = `
For EACH lens, ALSO write one findings file to the output dir given above, structure:
# {lens-name} — round {N}
## Findings Index
- [P{0-3}] {kebab-slug} — {one-line} (§{target section}) [t]
(append " [t]" ONLY to primarily aesthetic/design-taste findings)
## Findings
### {kebab-slug}
- Severity / Where / What / Evidence / Suggestion
## Verdict
{1-3 sentences}
Create the directory if needed (mkdir -p). Grounded findings (verified against the
actual repo files the target cites) score higher than speculation.`;

const severityRef =
  "Severity: P0 = would corrupt/block the whole design; P1 = must fix before implementing; P2 = degrades quality; P3 = polish.";

function probePrompt(R, directive, k, round) {
  const dir = `${R.base}/round-${round}/probe-${k}`;
  const base = `Run a focused lens-based review probe. Goal (north star): "${A.goal}".
Target: ${A.inputPath}
${severityRef}
Output dir for findings files: ${dir}
${FINDINGS_FILE_CONTRACT}`;
  if (directive.type === "DEEPEN") {
    return `${base}
Apply the lens defined in ${A.projectRoot}/.claude/agents/${directive.lens}.md (read it first).
Focus on: ${directive.target.location}.
You are CONFIRMING OR REFUTING this prior finding: "${directive.target.claim}" (${directive.target.location}).
Rationale: ${directive.rationale}
2-4 findings max; confirmation/refutation of the prior claim must be finding #1.`;
  }
  if (directive.type === "PROBE-DISAGREEMENT") {
    return `${base}
Adjudicate a contradiction between two prior findings at ${directive.target.location}:
(1) "${directive.target.claims[0]}"
(2) "${directive.target.claims[1]}"
Decide which holds, or whether it is an irreducible taste call (elegant vs reckless).
Read the target and any repo files needed to ground the verdict. Return 1-2 findings:
the adjudication itself (location = the disputed location) and optionally one new
insight the contradiction exposed.`;
  }
  if (directive.type === "FUSE") {
    return `${base}
Apply the FUSED lens defined in ${A.projectRoot}/.claude/agents/${directive.lens}.md (read it first;
parents: ${directive.parents.join(", ")}).
HARD CONSTRAINT (also in the agent charter): report a finding ONLY if it requires BOTH
parent perspectives; if either parent alone would catch it, discard it. Every finding
MUST include an intersection_justification naming what each parent contributes.
2-4 findings max.`;
  }
  // STEER-WIDE
  return `${base}
Apply the lens defined in ${A.projectRoot}/.claude/agents/${directive.lens}.md (read it first).
This is a wide exploratory probe from a distant domain — surface structural isomorphisms
the covered regions have NOT already yielded. Avoid re-reporting anything about these
already-hot regions unless you see something genuinely new there: ${directive.avoid.join("; ") || "(none yet)"}.
2-4 findings max; the isomorphism must be mechanistic, not decorative.`;
}

// ---- Phase 1: Seed (per run) --------------------------------------------------
function designRules(R) {
  return `For each agent output: name (fd-{domain}-{concern}${R.nameSuffix ? ` — and every name MUST end with "${R.nameSuffix}"` : ""}), focus, persona, decision_lens,
review_areas (4-6 bullets), severity_examples (2-3 concrete), success_hints (array),
task_context (must include this goal verbatim: "${A.goal}"), anti_overlap (array).
Persona framing: descriptive reviewer-framework ("Apply the perspective of..."), never
first-person "You are a...". Neutral task_context framings only.
Steps: (1) Read the target file. (2) Write the JSON array of specs to the specs path.
(3) Run: python3 ${A.pluginRoot}/scripts/generate-agents.py ${A.projectRoot} --from-specs {specs path} --mode=skip-existing --json
(4) For each lens, write a lens record to ${R.lensesDir}/{name}.json:
{"id","kind":"base","parents":[],"domain","axioms":[3-7 load-bearing assumptions],"primitives":[units it reasons about],"failure_mode":[what it systematically misses],"findings":[]}
(5) Return the structured output: for each lens its name/domain/axioms/primitives/failure_mode.`;
}

async function seedRun(R) {
  log(
    `flux-melange${R.isPrimary ? "" : ` [${R.rt.kind}]`}: ${A.slug} — budget ${R.slotsRemaining} slots, max ${A.loop.maxRounds} rounds, quality ${Q}`,
  );
  const seedDesigns = await parallel([
    () =>
      dispatch(
        R,
        `You design specialized review agents (ADJACENT tier: deep expertise in the target's own
domain and closely adjacent fields — they catch issues requiring specialist knowledge).
Target: ${A.targetDesc}
File: ${A.inputPath}
${severityRef}
Design ${A.seed.adjacent} agents. Specs path: ${A.projectRoot}/.claude/flux-gen-specs/${A.slug}${R.specTag}-seed-adjacent.json
${designRules(R)}`,
        {
          label: "seed-design:adjacent",
          phase: `${R.pfx}Seed`,
          model: MODEL.designAdjacent,
          schema: SEED_DESIGN_SCHEMA,
        },
      ),
    () =>
      dispatch(
        R,
        `You design review agents from DISTANT knowledge domains (structural isomorphisms from
unrelated disciplines). Constraints: no AI-cliche domains (biology, military strategy,
sports, information theory, thermodynamics, ecology, evolutionary biology, game theory,
economic markets, ant colonies, neural networks, immune systems); prefer pre-modern craft
disciplines, physical processes at non-human scales, non-Western knowledge systems,
professional practices with centuries of refinement; no two agents share a parent
discipline. Each spec additionally needs source_domain, distance_rationale,
expected_isomorphisms.
Target: ${A.targetDesc}
File: ${A.inputPath}
${severityRef}
Design ${A.seed.distant} agents. Specs path: ${A.projectRoot}/.claude/flux-gen-specs/${A.slug}${R.specTag}-seed-distant.json
${designRules(R)}`,
        {
          label: "seed-design:distant",
          phase: `${R.pfx}Seed`,
          model: MODEL.designDistant,
          schema: SEED_DESIGN_SCHEMA,
        },
      ),
  ]);

  const tiers = ["adjacent", "distant"];
  seedDesigns.forEach((d, i) => {
    if (!d) return;
    for (const l of d.lenses) R.lensRecords[l.name] = { ...l, tier: tiers[i] };
  });
  R.adjacentLenses = seedDesigns[0]
    ? seedDesigns[0].lenses.map((l) => l.name)
    : [];
  R.distantLenses = seedDesigns[1]
    ? seedDesigns[1].lenses.map((l) => l.name)
    : [];
  if (R.adjacentLenses.length + R.distantLenses.length === 0)
    throw new Error(`seed design produced no lenses (${R.rt.kind})`);

  const seedProbeThunk = (tier, lensNames) => () =>
    dispatch(
      R,
      `Run a lens-based review probe. Goal (north star): "${A.goal}".
Target: ${A.inputPath}
${severityRef}
Apply these ${lensNames.length} lenses one at a time — each is defined in a generated agent file; read all first:
${lensNames.map((n) => `- ${A.projectRoot}/.claude/agents/${n}.md`).join("\n")}
Output dir for findings files: ${R.base}/round-0/${tier}
${FINDINGS_FILE_CONTRACT}
2-5 findings per lens, distinct and specific. Respect each lens's anti_overlap notes.`,
      {
        label: `seed-probe:${tier}`,
        phase: `${R.pfx}Seed`,
        model: MODEL.probe,
        schema: PROBE_SCHEMA,
      },
    );

  const seedProbeResults = (
    await parallel([
      ...(R.adjacentLenses.length
        ? [seedProbeThunk("adjacent", R.adjacentLenses)]
        : []),
      ...(R.distantLenses.length
        ? [seedProbeThunk("distant", R.distantLenses)]
        : []),
    ])
  ).filter(Boolean);
  R.slotsRemaining -= seedProbeResults.length;
  if (!seedProbeResults.length)
    throw new Error(`both seed probes failed (${R.rt.kind})`);
  return seedProbeResults;
}

// ---- per-round machinery ----------------------------------------------------
async function assayRound(R, round, rawFindings, agentsDispatched) {
  if (!rawFindings.length) return [];
  const priorClusters = Object.entries(R.clusters).map(([cid, ids]) => {
    const rep = R.allFindings.find((f) => f.id === ids[0]);
    return {
      cluster_id: cid,
      example: rep ? `${rep.location}: ${rep.claim || rep.slug}` : cid,
    };
  });
  const idStart = R.nextFindingNum;
  const assay = await dispatch(
    R,
    `You are the Assayer for flux-melange round ${round}. You score findings; you never invent them.
Goal context: "${A.goal}". Target: ${A.inputPath}

The round's raw findings (JSON): ${JSON.stringify(rawFindings)}
Lens tier map: ${JSON.stringify(Object.fromEntries(Object.entries(R.lensRecords).map(([k, v]) => [k, v.tier])))}
Prior clusters (for new_cluster judgment): ${JSON.stringify(priorClusters)}

For each finding, assign id f-NNN starting at ${fmtId(idStart)} (input order), then:
1. CLUSTER: deterministic pre-filter — same normalized location (target section / file). Only
   colliding candidates get same-root-cause judgment. Same root cause => shared cluster_id
   ("c-{kebab}"). Reuse a PRIOR cluster_id if it is the same root cause (new_cluster=false);
   else open a new one (new_cluster=true).
2. NOVELTY 0-3 (inverse overlap): 0 = 3+ agents across 2+ tiers; 1 = 2 agents same tier;
   2 = single agent single domain; 3 = only this lens/fusion could see it.
3. RISK: blast_radius (0-3) x likelihood (0-3) = product. Decoupled from severity.
4. TASTE -2..+2 only for taste_flag'd or form-over-function findings (taste_kind in
   {elegance,smell,asymmetry,naming,simplicity,metaphor-leak}); else 0/null.
5. EMERGENCE GATE (only findings with intersection_justification): if either parent lens
   already reported this location+cause in the ledger, emergent=false (demote to convergence);
   if neither parent touched it, or both touched it but neither CONNECTED the causes,
   emergent=true and novelty=3 (floor).
6. DISAGREEMENTS: pairs of findings (this round or vs the ledger) at the same location with
   contradictory claims.

Then APPEND one JSON line per finding to ${R.ledger} (create the file if absent; schema identical to
existing lines: id, round=${round}, source{kind:"lens"|"fusion",agents,parent_lenses,source_domains},
claim, location, severity, novelty, risk{blast_radius,likelihood,product}, taste, taste_kind,
cluster_id, convergence_refs:[], disagreement_refs:[], intersection_justification, evidence,
status:"raw"). Also append each finding's id to the "findings" array of its lens record in
${R.lensesDir}/{lens}.json.

Return the structured output (findings array with scores + disagreements).`,
    {
      label: `assay:r${round}`,
      phase: `${R.pfx}Round ${round}`,
      model: MODEL.assay,
      schema: ASSAY_SCHEMA,
    },
  );
  if (!assay) {
    log(
      `${R.pfx}round ${round}: assayer failed — findings kept unscored, excluded from steering`,
    );
    return [];
  }
  const scored = assay.findings.map((f, i) => ({
    ...f,
    round,
    status: "raw",
    claim: f.claim || (rawFindings[i] ? rawFindings[i].claim : f.slug),
    intersection_justification: rawFindings[i]
      ? rawFindings[i].intersection_justification || null
      : null,
  }));
  for (const f of scored) {
    R.nextFindingNum += 1;
    R.allFindings.push(f);
    (R.clusters[f.cluster_id] = R.clusters[f.cluster_id] || []).push(f.id);
    R.coverageKeys.add(normKey(f.location));
  }
  for (const d of assay.disagreements || []) {
    const key = normKey(d.location);
    if (!R.resolvedDisagreements.has(key))
      R.openDisagreements.push({
        location: d.location,
        finding_ids: d.finding_ids,
      });
  }
  R.spiceTrail.push({
    round,
    event: "assay",
    findings: scored.length,
    agents_dispatched: agentsDispatched,
  });
  return scored;
}

async function verifyRound(R, round, scored) {
  if (A.verify.mode === "off") return;
  const gated = scored.filter(
    (f) =>
      f.status === "raw" &&
      (A.verify.mode === "all" ||
        f.emergent === true ||
        f.novelty >= A.verify.noveltyGate ||
        f.risk_product >= A.verify.riskGate),
  );
  if (!gated.length) return;
  const chunks = [];
  for (let i = 0; i < gated.length; i += 5) chunks.push(gated.slice(i, i + 5));
  const dropped = Math.max(0, chunks.length - Math.max(0, R.slotsRemaining));
  const usable =
    dropped > 0 ? chunks.slice(0, Math.max(0, R.slotsRemaining)) : chunks;
  if (dropped > 0)
    log(
      `${R.pfx}round ${round}: verify budget-clamped — ${dropped * 5} gated findings left raw`,
    );
  const results = (
    await parallel(
      usable.map(
        (chunk) => () =>
          dispatch(
            R,
            `Verify these flux-melange findings against reality. For each: read the exact cited
location (in ${A.inputPath} or the repo file it names) and check whether the evidence supports
the claim. Findings (JSON): ${JSON.stringify(chunk.map((f) => ({ id: f.id, claim: f.claim, location: f.location, emergent: f.emergent || false, intersection_justification: f.intersection_justification })))}

Status rules: "upheld" = the artifact confirms the claim; "refuted" = the artifact contradicts
it OR the location/evidence does not exist. For emergent findings apply THREE checks in order:
(1) is the claimed mechanism actually present? (fused lenses hallucinate plausible interactions
— if absent, refuted, stop); (2) does it truly require both parents? if one parent alone
suffices set emergent_keep=false but status stays upheld; (3) genuine emergent => upheld,
emergent_keep=true.

Then stamp each finding's status in ${R.ledger}: edit its line's
"status":"raw" to the verdict (rewrite only the status field; never edit claims).
Return the structured results.`,
            {
              label: `verify:r${round}`,
              phase: `${R.pfx}Round ${round}`,
              model: MODEL.verify,
              schema: VERIFY_SCHEMA,
            },
          ),
      ),
    )
  ).filter(Boolean);
  R.slotsRemaining -= usable.length;
  const byId = new Map(R.allFindings.map((f) => [f.id, f]));
  for (const r of results)
    for (const v of r.results) {
      const f = byId.get(v.id);
      if (!f) continue;
      f.status = v.status;
      if (v.emergent_keep === false) f.emergent = false;
    }
}

function buildHeatMapAndDirectives(R, round) {
  // regions by yield density (per-round approximation: heat of new-cluster findings this round)
  const lastRound = R.allFindings.filter((f) => f.round === round - 1);
  const regions = {};
  for (const f of lastRound) {
    if (!f.new_cluster) continue;
    const k = normKey(f.location);
    regions[k] = (regions[k] || 0) + heat(f);
  }
  // lens pairs: SHARED_HEAT + COMPLEMENTARITY - REDUNDANCY over all run lenses
  const lensIds = Object.keys(R.lensRecords);
  const findingsByLens = {};
  for (const f of R.allFindings)
    for (const a of f.agents)
      (findingsByLens[a] = findingsByLens[a] || []).push(f);
  const tokenSet = (arr) =>
    new Set(
      (arr || []).flatMap((s) =>
        String(s)
          .toLowerCase()
          .split(/[^a-z0-9]+/)
          .filter((w) => w.length > 3),
      ),
    );
  const pairs = [];
  for (let i = 0; i < lensIds.length; i++)
    for (let j = i + 1; j < lensIds.length; j++) {
      const [a, b] = [lensIds[i], lensIds[j]];
      if (R.fusedPairs.some((p) => p.includes(a) && p.includes(b))) continue;
      const fa = findingsByLens[a] || [],
        fb = findingsByLens[b] || [];
      const keysA = new Set(fa.map((f) => normKey(f.location)));
      const sharedHeat = [
        ...new Set(fb.map((f) => normKey(f.location))),
      ].filter((k) => keysA.has(k)).length;
      if (sharedHeat < A.fusion.sharedHeatGate) continue;
      const ra = R.lensRecords[a],
        rb = R.lensRecords[b];
      const overlap = (xs, ys) => {
        const t = tokenSet(ys);
        return [...tokenSet(xs)].filter((w) => t.has(w)).length > 0 ? 1 : 0;
      };
      const complementarity =
        overlap(ra.primitives, rb.failure_mode) +
        overlap(rb.primitives, ra.failure_mode);
      const clustersA = new Set(fa.map((f) => f.cluster_id));
      const redundancy = [...new Set(fb.map((f) => f.cluster_id))].filter((c) =>
        clustersA.has(c),
      ).length;
      const score = sharedHeat + complementarity - redundancy;
      if (score > 0)
        pairs.push({
          pair: [a, b],
          sharedHeat,
          complementarity,
          redundancy,
          score,
        });
    }
  pairs.sort((x, y) => y.score - x.score);

  // directive selection (priority: PROBE-DISAGREEMENT > DEEPEN > FUSE > STEER-WIDE)
  const directives = [];
  for (const d of R.openDisagreements.slice(0, 1)) {
    const fs = d.finding_ids
      .map((id) => R.allFindings.find((f) => f.id === id))
      .filter(Boolean);
    if (fs.length >= 2)
      directives.push({
        type: "PROBE-DISAGREEMENT",
        target: {
          location: d.location,
          claims: fs.slice(0, 2).map((f) => f.claim),
        },
        rationale: "open contradiction — adjudicate",
        budget_weight: 0.2,
      });
  }
  const unconfirmed = Object.entries(R.clusters)
    .map(([cid, ids]) => {
      const members = ids
        .map((id) => R.allFindings.find((f) => f.id === id))
        .filter(Boolean);
      const maxRisk = Math.max(...members.map((f) => f.risk_product));
      const confirmed = members.some((f) => f.status === "upheld");
      const distinctLenses = new Set(members.flatMap((f) => f.agents)).size;
      return { cid, members, maxRisk, confirmed, distinctLenses };
    })
    .filter((c) => !c.confirmed && c.maxRisk >= 6 && c.distinctLenses < 3)
    .sort((x, y) => y.maxRisk - x.maxRisk);
  for (const c of unconfirmed.slice(0, 2 - directives.length > 0 ? 2 : 1)) {
    const top = c.members.sort((x, y) => heat(y) - heat(x))[0];
    const lens =
      R.adjacentLenses.find((l) => !top.agents.includes(l)) ||
      R.adjacentLenses[0];
    if (lens)
      directives.push({
        type: "DEEPEN",
        target: { location: top.location, cluster_id: c.cid, claim: top.claim },
        rationale: `risk ${c.maxRisk}, unconfirmed — confirm or refute`,
        lens,
        budget_weight: 0.35,
      });
  }
  let fusions = 0;
  for (const p of pairs) {
    if (fusions >= A.fusion.perRoundCap || directives.length >= 4) break;
    directives.push({
      type: "FUSE",
      parents: p.pair,
      rationale: `shared_heat ${p.sharedHeat}, complementarity ${p.complementarity}, redundancy ${p.redundancy}`,
      budget_weight: 0.3,
    });
    fusions += 1;
  }
  const lastGain = R.gainHistory[R.gainHistory.length - 1];
  if (
    lastGain &&
    lastGain.novel_cluster_rate >= A.loop.wideThreshold &&
    directives.length < 4
  ) {
    directives.push({
      type: "STEER-WIDE",
      avoid: [...R.coverageKeys].slice(0, 12),
      rationale: `novel_cluster_rate ${lastGain.novel_cluster_rate.toFixed(2)} >= ${A.loop.wideThreshold} — widening still pays`,
      budget_weight: 0.15,
    });
  }
  return {
    directives: directives.slice(0, 4),
    topRegions: Object.entries(regions)
      .sort((x, y) => y[1] - x[1])
      .slice(0, 5),
  };
}

async function probeDirectives(R, round, directives) {
  const raw = [];
  let dispatched = 0;
  const thunks = directives.map((d, k) => async () => {
    if (d.type === "FUSE") {
      const [pa, pb] = d.parents.map((p) => R.lensRecords[p]);
      const fusionIdx = R.fusedPairs.length;
      const design = await dispatch(
        R,
        `Design ONE fused review lens combining two parents (flux-melange fusion charter).
PARENT A — ${d.parents[0]} (${pa.domain}): axioms ${JSON.stringify(pa.axioms)}; reasons about ${JSON.stringify(pa.primitives)}.
PARENT B — ${d.parents[1]} (${pb.domain}): axioms ${JSON.stringify(pb.axioms)}; reasons about ${JSON.stringify(pb.primitives)}.
Name the tension between them; do NOT resolve it — the fused lens INVESTIGATES where it lives.
The fused primitive is the cross-product of the parents' concerns.
HARD CONSTRAINT to encode in the spec: report a finding ONLY if it requires BOTH parent
perspectives; every finding must include an intersection_justification.
Target: ${A.targetDesc} (${A.inputPath})
Write a 1-element JSON spec array (same fd-* spec fields as other agents; name fd-fused-{concern}${R.nameSuffix ? ` ending with "${R.nameSuffix}"` : ""})
to ${A.projectRoot}/.claude/flux-gen-specs/${A.slug}${R.specTag}-fusion-${fusionIdx}.json, run
python3 ${A.pluginRoot}/scripts/generate-agents.py ${A.projectRoot} --from-specs ${A.projectRoot}/.claude/flux-gen-specs/${A.slug}${R.specTag}-fusion-${fusionIdx}.json --mode=skip-existing --json
then write the lens record (kind:"fusion", parents:${JSON.stringify(d.parents)}) to ${R.lensesDir}/{name}.json.
Return the structured output.`,
        {
          label: `fuse-design:${d.parents.map((s) => s.replace(/^fd-/, "")).join("x")}`,
          phase: `${R.pfx}Round ${round}`,
          model: MODEL.fusedDesign,
          schema: FUSED_DESIGN_SCHEMA,
        },
      );
      if (!design) return null;
      R.lensRecords[design.agent_name] = {
        domain: design.domain,
        axioms: design.axioms,
        primitives: design.primitives,
        failure_mode: design.failure_mode,
        tier: "fusion",
        parents: d.parents,
      };
      R.fusedPairs.push([...d.parents]);
      d.lens = design.agent_name;
    }
    if (d.type === "STEER-WIDE") {
      const design = await dispatch(
        R,
        `Design ONE new distant-domain review lens (flux-melange STEER-WIDE). Same constraints as
distant seed design (no AI-cliche domains; prefer pre-modern craft/physical/non-Western
disciplines) AND maximally distant from these already-covered domains: ${Object.values(
          R.lensRecords,
        )
          .map((r) => r.domain)
          .join("; ")}.
Target: ${A.targetDesc} (${A.inputPath}). Goal: "${A.goal}".
Write a 1-element JSON spec array (fd-* fields${R.nameSuffix ? `; name ends with "${R.nameSuffix}"` : ""}) to ${A.projectRoot}/.claude/flux-gen-specs/${A.slug}${R.specTag}-wide-${round}.json, run
python3 ${A.pluginRoot}/scripts/generate-agents.py ${A.projectRoot} --from-specs ${A.projectRoot}/.claude/flux-gen-specs/${A.slug}${R.specTag}-wide-${round}.json --mode=skip-existing --json
then write the lens record to ${R.lensesDir}/{name}.json. Return the structured output.`,
        {
          label: `wide-design:r${round}`,
          phase: `${R.pfx}Round ${round}`,
          model: MODEL.designDistant,
          schema: FUSED_DESIGN_SCHEMA,
        },
      );
      if (!design) return null;
      R.lensRecords[design.agent_name] = {
        domain: design.domain,
        axioms: design.axioms,
        primitives: design.primitives,
        failure_mode: design.failure_mode,
        tier: "distant",
      };
      d.lens = design.agent_name;
    }
    dispatched += 1;
    const res = await dispatch(R, probePrompt(R, d, k, round), {
      label: `probe:r${round}:${d.type.toLowerCase()}`,
      phase: `${R.pfx}Round ${round}`,
      model: MODEL.probe,
      schema: PROBE_SCHEMA,
    });
    if (d.type === "PROBE-DISAGREEMENT")
      R.resolvedDisagreements.add(normKey(d.target.location));
    return res ? { directive: d, findings: res.findings } : null;
  });
  const results = (await parallel(thunks)).filter(Boolean);
  R.slotsRemaining -= dispatched;
  for (const r of results) {
    for (const f of r.findings) {
      if (r.directive.type === "FUSE" && !f.intersection_justification)
        continue; // charter violation — drop
      raw.push(f);
    }
  }
  const failed = directives.length - results.length;
  if (failed > 0)
    log(
      `${R.pfx}round ${round}: ${failed} probe(s) failed — proceeding with survivors`,
    );
  R.spiceTrail.push({
    round,
    event: "probe",
    directives: directives.map((d) => ({
      type: d.type,
      rationale: d.rationale,
      lens: d.lens || null,
    })),
    findings: raw.length,
    failed,
  });
  return raw;
}

function scoreRound(R, round, scored) {
  const newClusters = new Set(
    scored.filter((f) => f.new_cluster).map((f) => f.cluster_id),
  ).size;
  const roundYield = scored.filter(
    (f) => f.status === "upheld" && f.new_cluster && qualifies(f),
  ).length;
  const rate = scored.length ? newClusters / scored.length : 0;
  R.gainHistory.push({
    round,
    yield: roundYield,
    novel_cluster_rate: Number(rate.toFixed(2)),
  });
  R.openDisagreements = R.openDisagreements.filter(
    (d) => !R.resolvedDisagreements.has(normKey(d.location)),
  );
  // continue predicate — halt precedence: BUDGET > DRY > CEILING (score.md § Step 4)
  if (R.slotsRemaining < A.budget.roundCostFloor) R.haltReason = "BUDGET";
  else if (
    round + 1 > A.loop.minRounds &&
    roundYield <= A.loop.diminishingThreshold
  )
    R.haltReason = "DRY";
  else if (round + 1 > A.loop.maxRounds) R.haltReason = "CEILING";
  log(
    `${R.pfx}round ${round}: yield ${roundYield}, novel_cluster_rate ${rate.toFixed(2)}, slots left ${R.slotsRemaining}${R.haltReason ? ` — HALT ${R.haltReason}` : ""}`,
  );
  return R.haltReason === null;
}

// ---- Phase 7: synthesize (per run) --------------------------------------------
async function synthesizeRun(R) {
  const frontier = R.allFindings
    .filter((f) => f.status !== "refuted")
    .sort((x, y) => heat(y) - heat(x))
    .slice(0, 10);
  const convergence = {};
  for (const [cid, ids] of Object.entries(R.clusters)) {
    if (ids.length < 2) continue;
    const lenses = new Set(
      ids.flatMap(
        (id) =>
          (R.allFindings.find((f) => f.id === id) || { agents: [] }).agents,
      ),
    );
    if (lenses.size >= 2) convergence[cid] = ids;
  }
  const fusionStats = {
    attempted: R.fusedPairs.length,
    emergent: R.allFindings.filter(
      (f) => f.emergent === true && f.status !== "refuted",
    ).length,
  };

  const synth = await dispatch(
    R,
    `You are writing the synthesis for a flux-melange spice-loop review — the eye of distance.

Target: ${A.targetDesc}    File: ${A.inputPath}
Goal: ${A.goal}    Weights: ${A.weights}
The loop ran ${R.round + 1} rounds (0-${R.round}) and halted: ${R.haltReason}.

Read the full ledger at ${R.ledger} and the lens records in ${R.lensesDir}/.
Controller state (script-computed; the on-disk ledger rows carry empty ref arrays in workflow mode):
- clusters: ${JSON.stringify(R.clusters)}
- cross-lens convergent clusters: ${JSON.stringify(convergence)}
- open disagreements at halt: ${JSON.stringify(R.openDisagreements)}
- gain history: ${JSON.stringify(R.gainHistory)}
- spice trail: ${JSON.stringify(R.spiceTrail)}
- fusion stats: ${JSON.stringify(fusionStats)}
- frontier (triage-grade): ${JSON.stringify(frontier.map((f) => f.id))}

First, RE-SCORE the merged ledger yourself — the per-round scores were fast triage estimates.
Then produce these five views (surface the spice; do NOT sort by severity):

## 1. Novelty×Risk Frontier
The Pareto FRONT (not a single sort) of upheld findings on (novelty, risk.product): surface a
max-novelty/mid-risk finding AND a mid-novelty/max-risk finding — both lead. For each: the
claim, lens(es), the risk decomposition (blast × likelihood), and severity FOR REFERENCE ONLY.

## 2. Top Fusions
Emergent findings no single lens could produce. Rank by novelty×risk. For each: the parent
pair, the intersection_justification, and the evidence. Report zero-emergent fusions as
negative results ("A × B: independent here").

## 3. Taste Calls
Top +taste elegance to preserve and top -taste smells to fix (may be empty). Name taste_kind.

## 4. Convergence Spine
High-convergence findings = high confidence, LOW novelty (commodity you can trust). One
section, not the headline.

## 5. Live Disagreements
Contradictions still open at halt — primary signal, often unresolved taste calls.

Then an appendix:

## Spice Trail
Per round: yield, novel_cluster_rate, the directives chosen and WHY, what steered where, and
the halt reason.

Optionally a single "If you read one thing" = argmax(heat), |taste| tiebreaker.

Write direct technical prose. Name lenses when attributing. Rank by HEAT (novelty × risk).

Write the report to ${R.base}/${A.date}-synthesis.md with YAML frontmatter:
artifact_type: melange-synthesis / method: flux-melange / target / target_description / goal /
weights / rounds_run: ${R.round + 1} / halt_reason: ${R.haltReason} / total_fusions: ${fusionStats.attempted} /
emergent_findings: ${fusionStats.emergent} / runtime: ${R.rt.kind} / date: ${A.date}
Include caveats (failed probes, budget-clamped verification, regions never reached).

ALSO write ${R.base}/surfaced.jsonl — one JSON line per finding appearing in ANY of the
five views: {"id","views":[subset of frontier|fusion|taste|convergence|disagreement|if-you-read-one-thing],"novelty","risk":{"product"},"taste","claim","location","status"}. The surfaced set is the UNION
of the five views; refuted findings never appear.

AND write ${R.base}/run-manifest.json: {"runtime":"${R.rt.kind}","rounds","halt_reason","gain_history","spice_trail","slots_spent":${A.budget.totalSlots - R.slotsRemaining},"directive_history"} from the controller state above.

Return the structured output.`,
    {
      label: "synthesis",
      phase: `${R.pfx}Synthesize`,
      model: MODEL.synthesis,
      schema: SYNTH_SCHEMA,
    },
  );
  R.synth = synth;
  R.frontierTop = frontier[0] || null;
  R.fusionStats = fusionStats;
}

// ---- full loop for one runtime ------------------------------------------------
async function runMelange(R) {
  const seedProbeResults = await seedRun(R);
  const seedRaw = seedProbeResults.flatMap((r) => r.findings);
  const seedScored = await assayRound(R, 0, seedRaw, seedProbeResults.length);
  await verifyRound(R, 0, seedScored);
  scoreRound(R, 0, seedScored);

  while (R.haltReason === null) {
    R.round += 1;
    if (R.round > A.loop.maxRounds) {
      R.haltReason = "CEILING";
      break;
    }
    const { directives } = buildHeatMapAndDirectives(R, R.round);
    if (!directives.length) {
      R.haltReason = "DRY";
      log(`${R.pfx}round ${R.round}: controller found no directives — DRY`);
      break;
    }
    log(
      `${R.pfx}round ${R.round}: directives — ${directives.map((d) => d.type).join(", ")}`,
    );
    const raw = await probeDirectives(R, R.round, directives);
    const scored = await assayRound(R, R.round, raw, directives.length);
    await verifyRound(R, R.round, scored);
    if (!scoreRound(R, R.round, scored)) break;
  }

  await synthesizeRun(R);
  return R;
}

// ---- Phases 1..7: run all runtimes (primary + independent mirrors) --------------
phase("Seed");
const runs = [makeRun({ kind: "claude" }), ...PEERS.map((p) => makeRun(p))];
if (PEERS.length)
  log(
    `peer mirrors: ${PEERS.map((p) => `${p.kind}${p.model ? ` (${p.model})` : ""}`).join(", ")} — independent loops, no cross-contamination until Parley`,
  );

await parallel(
  runs.map(
    (R) => () =>
      runMelange(R).catch((e) => {
        R.failed = String((e && e.message) || e);
        return R;
      }),
  ),
);

const primary = runs[0];
if (primary.failed)
  throw new Error(`primary (claude) melange loop failed: ${primary.failed}`);
const mirrorCaveats = runs
  .slice(1)
  .filter((R) => R.failed)
  .map((R) => `${R.rt.kind} mirror failed: ${R.failed}`);

// ---- Phase 7.5: Parley — adversarial exchange to epistemic equilibrium ---------
// Spec: phases/parley.md. Each surviving runtime fields an ADVOCATE (native for
// the primary, shim-relayed for mirrors — the external model argues its own
// case). A native MODERATOR merges positions after each exchange round and
// detects the fixed point: a round in which no advocate concedes, introduces
// new evidence, or surfaces a novel synthesis. Residual contested items are
// returned for user tie-break (the orchestrator owns AskUserQuestion).
let equilibrium = null;
const parties = runs.filter(
  (R) => !R.failed && R.synth && R.synth.synthesis_path,
);
if (runs.length > 1 && parties.length > 1) {
  phase("Parley");
  const eqPath = `${A.outputRoot}/equilibrium.md`;
  const disPath = `${A.outputRoot}/disagreements.jsonl`;
  let table = null;
  let exRound = 0;
  let changed = true;
  while (changed && exRound < EX.maxRounds) {
    exRound += 1;
    const positions = (
      await parallel(
        parties.map((R) => () => {
          const others = parties.filter((x) => x !== R);
          const prompt = `You are the ${R.rt.kind} ADVOCATE in an adversarial synthesis exchange (round ${exRound} of at most ${EX.maxRounds}).
Independent review loops examined the same target; each produced its own synthesis.
Your synthesis (your prior positions): ${R.synth.synthesis_path}
Peer syntheses: ${others.map((x) => `${x.rt.kind}: ${x.synth.synthesis_path}`).join("; ")}
Target under review: ${A.inputPath} (read it and any repo files needed to ground arguments).
Prior consensus table from the moderator: ${table ? JSON.stringify(table) : "none — first exchange round"}

Read all syntheses. For every materially disputed or unique claim across them, output a position:
- "concede": you now accept a peer claim your synthesis missed or contradicted — say what changed your mind
- "challenge": you dispute a peer claim — MUST cite concrete evidence from the target/repo
- "affirm": you stand by your claim against a challenge — MUST introduce NEW evidence, never repetition
- "novel": a genuinely new insight the collision of syntheses exposed
Rules: a position without evidence is void; rhetorical repetition is void; concede when the
evidence goes against you. This exchange seeks EPISTEMIC EQUILIBRIUM, not victory — an advocate
that concedes a weak claim strengthens its credibility on the strong ones.
Set changed_mind=true iff this round you conceded anything, introduced new evidence, or found a novel insight.`;
          return dispatch(R, prompt, {
            label: `advocate:r${exRound}`,
            phase: "Parley",
            model: MODEL.advocate,
            schema: ADVOCATE_SCHEMA,
          }).then((res) => (res ? { runtime: R.rt.kind, ...res } : null));
        }),
      )
    ).filter(Boolean);

    if (!positions.length) {
      changed = false;
      break;
    }

    table = await agent(
      `You are the MODERATOR of an adversarial synthesis exchange (flux-melange Parley, round ${exRound}).
You merge positions; you never invent arguments or take sides.
This round's advocate positions (JSON): ${JSON.stringify(positions)}
Prior consensus table: ${table ? JSON.stringify(table) : "none — first round"}
Syntheses for reference: ${parties.map((x) => `${x.rt.kind}: ${x.synth.synthesis_path}`).join("; ")}

1. AGREED: claims all advocates now hold (including via concession this round). Merge into one
   statement each; record holders.
2. CONTESTED: claims still under live dispute. For each: every runtime's current argument +
   evidence, and a heat score 0-9 (how consequential the disagreement is for the target).
   Positions that are pure repetition of a prior round carry no weight — note them as stale.
3. changed: true iff any advocate reported changed_mind=true OR the table materially differs
   from the prior table (new agreed items, new/retired contested items, or new evidence).
   changed=false means the exchange has reached its fixed point (epistemic equilibrium).

Write ${eqPath} (overwrite): YAML frontmatter (artifact_type: melange-equilibrium / date: ${A.date} /
runtimes: ${JSON.stringify(parties.map((x) => x.rt.kind))} / exchange_rounds: ${exRound} / equilibrium: {true iff changed=false})
then sections: ## Consensus (agreed, with holders), ## Contested (per topic: each side's argument
and evidence, heat, ordered by heat desc), ## Exchange log (one line per round: concessions,
new evidence, novel insights).
Write ${disPath} (overwrite): one JSON line per contested topic: {"topic","heat","positions":[{"runtime","argument","evidence"}]}.
Return the structured output.`,
      {
        label: `moderator:r${exRound}`,
        phase: "Parley",
        model: MODEL.moderator,
        schema: MODERATOR_SCHEMA,
      },
    );

    if (!table) {
      log(
        `parley round ${exRound}: moderator failed — halting exchange with last known state`,
      );
      changed = false;
      break;
    }
    changed = table.changed;
    log(
      `parley round ${exRound}: ${table.agreed.length} agreed, ${table.contested.length} contested${changed ? "" : " — EQUILIBRIUM"}`,
    );
  }
  equilibrium = {
    rounds: exRound,
    reached: !changed,
    agreed_count: table ? table.agreed.length : 0,
    contested: table ? table.contested : [],
    equilibrium_path: eqPath,
    disagreements_path: disPath,
    parties: parties.map((x) => x.rt.kind),
  };
} else if (runs.length > 1) {
  mirrorCaveats.push("parley skipped — fewer than 2 surviving syntheses");
}

// ---- report ---------------------------------------------------------------------
const runReport = (R) => ({
  runtime: R.rt.kind,
  model: R.rt.model || null,
  failed: R.failed,
  rounds_run: R.failed ? null : R.round + 1,
  halt_reason: R.haltReason,
  slots_spent: A.budget.totalSlots - R.slotsRemaining,
  findings_total: R.allFindings.length,
  upheld: R.allFindings.filter((f) => f.status === "upheld").length,
  refuted: R.allFindings.filter((f) => f.status === "refuted").length,
  fusions: R.fusionStats || { attempted: R.fusedPairs.length, emergent: 0 },
  synthesis_path: R.synth ? R.synth.synthesis_path : null,
  ledger_path: R.ledger,
});

return {
  slug: A.slug,
  rounds_run: primary.round + 1,
  halt_reason: primary.haltReason,
  slots_spent: A.budget.totalSlots - primary.slotsRemaining,
  findings_total: primary.allFindings.length,
  upheld: primary.allFindings.filter((f) => f.status === "upheld").length,
  refuted: primary.allFindings.filter((f) => f.status === "refuted").length,
  fusions: primary.fusionStats,
  gain_history: primary.gainHistory,
  top_finding: primary.synth
    ? primary.synth.top_finding
    : primary.frontierTop
      ? `${primary.frontierTop.id}: ${primary.frontierTop.claim}`
      : null,
  synthesis_path: primary.synth ? primary.synth.synthesis_path : null,
  surfaced_count: primary.synth ? primary.synth.surfaced_count : 0,
  caveats: [
    ...(primary.synth
      ? primary.synth.caveats || []
      : [
          "synthesis agent failed — ledger is intact; rerun synthesis from heat-ledger.jsonl",
        ]),
    ...mirrorCaveats,
  ],
  ledger_path: primary.ledger,
  peers: PEERS.length ? runs.slice(1).map(runReport) : undefined,
  equilibrium,
};
