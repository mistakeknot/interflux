import { z } from "zod";

// ---------------------------------------------------------------------------
// Configuration parsing
//
// Everything here is pure / dependency-free so it can be unit-tested without
// starting the MCP server (which exits 78 when OPENROUTER_API_KEY is unset).
// ---------------------------------------------------------------------------

/** Default model allowlist — common, reasonably-priced OpenRouter models.
 * Overridable via OPENROUTER_MODEL_ALLOWLIST (comma-separated). This bounds an
 * injection-steered agent from dispatching an arbitrarily expensive model. */
export const DEFAULT_MODEL_ALLOWLIST = [
  "deepseek/deepseek-chat",
  "deepseek/deepseek-r1",
  "openai/gpt-4o-mini",
  "openai/gpt-4o",
  "anthropic/claude-3.5-haiku",
  "anthropic/claude-3.5-sonnet",
  "google/gemini-2.0-flash-001",
  "google/gemini-flash-1.5",
  "meta-llama/llama-3.3-70b-instruct",
  "qwen/qwen-2.5-72b-instruct",
] as const;

/** Length caps for free-text fields. A huge prompt is both a cost vector
 * (tokens billed scale with input length) and an injection surface. */
export const DEFAULT_PROMPT_MAX_CHARS = 200_000;
export const DEFAULT_SYSTEM_PROMPT_MAX_CHARS = 50_000;

/** Upper bound for max_tokens on the response, independent of cost reservation. */
export const DEFAULT_MAX_TOKENS_CEILING = 32_000;

/** Conservative per-call cost estimate (USD) reserved at admission and used as
 * the fallback debit when OpenRouter omits usage.total_cost. Overridable via
 * OPENROUTER_ESTIMATED_CALL_COST_USD. The default is deliberately generous so
 * concurrent admission cannot collectively overshoot the ceiling, and so an
 * un-priced response never drifts the ledger downward to zero. */
export const DEFAULT_ESTIMATED_CALL_COST_USD = 0.5;

export type DispatchConfig = {
  modelAllowlist: readonly string[];
  promptMaxChars: number;
  systemPromptMaxChars: number;
  maxTokensCeiling: number;
  estimatedCallCostUsd: number;
};

function parsePositiveFloat(
  value: string | undefined,
  fallback: number,
): number {
  if (value === undefined) return fallback;
  const n = Number.parseFloat(value);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

function parsePositiveInt(value: string | undefined, fallback: number): number {
  if (value === undefined) return fallback;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

/** Build the dispatch config from process.env (or a provided env map for tests). */
export function loadDispatchConfig(
  env: NodeJS.ProcessEnv = process.env,
): DispatchConfig {
  const rawList = env.OPENROUTER_MODEL_ALLOWLIST;
  const modelAllowlist = rawList
    ? rawList
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s.length > 0)
    : [...DEFAULT_MODEL_ALLOWLIST];

  return {
    modelAllowlist:
      modelAllowlist.length > 0 ? modelAllowlist : [...DEFAULT_MODEL_ALLOWLIST],
    promptMaxChars: parsePositiveInt(
      env.OPENROUTER_PROMPT_MAX_CHARS,
      DEFAULT_PROMPT_MAX_CHARS,
    ),
    systemPromptMaxChars: parsePositiveInt(
      env.OPENROUTER_SYSTEM_PROMPT_MAX_CHARS,
      DEFAULT_SYSTEM_PROMPT_MAX_CHARS,
    ),
    maxTokensCeiling: parsePositiveInt(
      env.OPENROUTER_MAX_TOKENS_CEILING,
      DEFAULT_MAX_TOKENS_CEILING,
    ),
    estimatedCallCostUsd: parsePositiveFloat(
      env.OPENROUTER_ESTIMATED_CALL_COST_USD,
      DEFAULT_ESTIMATED_CALL_COST_USD,
    ),
  };
}

// ---------------------------------------------------------------------------
// Input schema
// ---------------------------------------------------------------------------

export type DispatchInput = {
  model_id: string;
  prompt: string;
  system_prompt?: string;
  max_tokens: number;
};

/** Build the zod raw-shape for the review_with_model tool, constrained by config.
 * model_id is restricted to the allowlist; prompt/system_prompt are length-capped;
 * max_tokens is bounded by the configured ceiling. */
export function buildInputSchema(config: DispatchConfig) {
  // z.enum requires a non-empty tuple of string literals. The allowlist is
  // validated non-empty by loadDispatchConfig.
  const allowed = config.modelAllowlist as readonly [string, ...string[]];

  return {
    model_id: z
      .enum(allowed)
      .describe(
        `OpenRouter model ID. Must be one of the allowlisted models: ${config.modelAllowlist.join(", ")}`,
      ),
    prompt: z
      .string()
      .min(1)
      .max(config.promptMaxChars)
      .describe(`The review prompt to send (max ${config.promptMaxChars} chars)`),
    system_prompt: z
      .string()
      .max(config.systemPromptMaxChars)
      .optional()
      .describe(
        `System prompt for the model (max ${config.systemPromptMaxChars} chars)`,
      ),
    max_tokens: z
      .number()
      .int()
      .positive()
      .max(config.maxTokensCeiling)
      .optional()
      .default(4096)
      .describe(`Max tokens in response (1..${config.maxTokensCeiling})`),
  };
}

// ---------------------------------------------------------------------------
// Spend ledger: reservation + reconciliation + monotonicity
//
// The ledger is split into two committed counters:
//   - committedSpendUsd: actual debits reconciled from completed calls.
//   - reservedSpendUsd:  estimates held for in-flight calls, not yet reconciled.
//
// Admission checks (committed + reserved) against the ceiling INSIDE the lock,
// and immediately reserves the estimate in the same lock. This closes the
// check/act window: N concurrent calls cannot all pass the under-ceiling check,
// because each reservation is visible to the next admission.
//
// On completion the reservation is released and the actual cost debited. A
// response lacking usage.total_cost is debited conservatively (the estimate),
// never zero.
//
// committedSpendUsd is treated as MONOTONIC across loads: a same-user local
// process cannot reset the persisted ledger downward.
// ---------------------------------------------------------------------------

export type Ledger = {
  committedSpendUsd: number;
  reservedSpendUsd: number;
};

export function newLedger(): Ledger {
  return { committedSpendUsd: 0, reservedSpendUsd: 0 };
}

/** Total spend visible to the ceiling: committed plus outstanding reservations. */
export function totalExposureUsd(ledger: Ledger): number {
  return ledger.committedSpendUsd + ledger.reservedSpendUsd;
}

/** Merge a freshly-loaded persisted committed value into the in-memory ledger
 * monotonically: never decrease committedSpendUsd. This prevents a local
 * same-user process (or a tampered/rolled-back state file) from lowering the
 * ledger to win more budget. Reservations are process-local and not merged. */
export function mergeCommittedMonotonic(
  ledger: Ledger,
  persistedCommitted: number,
): void {
  if (
    Number.isFinite(persistedCommitted) &&
    persistedCommitted > ledger.committedSpendUsd
  ) {
    ledger.committedSpendUsd = persistedCommitted;
  }
}

export type AdmitResult = { ok: true } | { ok: false; kind: "spend" };

/** Attempt to admit a call against the ceiling and, on success, reserve the
 * estimate in the same step. MUST be called inside the state lock.
 *
 * spendCeiling <= 0 disables the ceiling (no reservation needed).
 * Returns ok:false without reserving when admitting would meet/exceed ceiling. */
export function admitAndReserve(
  ledger: Ledger,
  spendCeiling: number,
  estimate: number,
): AdmitResult {
  if (spendCeiling > 0) {
    if (totalExposureUsd(ledger) >= spendCeiling) {
      return { ok: false, kind: "spend" };
    }
    ledger.reservedSpendUsd += estimate;
  }
  return { ok: true };
}

/** Release a previously-held reservation and debit the actual cost.
 * MUST be called inside the state lock, with the SAME estimate passed to
 * admitAndReserve. `actualCost === undefined` means OpenRouter omitted the
 * cost: debit the (conservative) estimate instead of zero. */
export function reconcile(
  ledger: Ledger,
  estimate: number,
  actualCost: number | undefined,
  ceilingEnabled: boolean,
): void {
  if (ceilingEnabled) {
    ledger.reservedSpendUsd = Math.max(0, ledger.reservedSpendUsd - estimate);
  }
  const debit =
    typeof actualCost === "number" &&
    Number.isFinite(actualCost) &&
    actualCost >= 0
      ? actualCost
      : estimate;
  ledger.committedSpendUsd += debit;
}
