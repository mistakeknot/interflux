import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_ESTIMATED_CALL_COST_USD,
  DEFAULT_MAX_TOKENS_CEILING,
  DEFAULT_MODEL_ALLOWLIST,
  DEFAULT_PROMPT_MAX_CHARS,
  DEFAULT_SYSTEM_PROMPT_MAX_CHARS,
  admitAndReserve,
  buildInputSchema,
  loadDispatchConfig,
  mergeCommittedMonotonic,
  newLedger,
  reconcile,
  totalExposureUsd,
} from "./dispatch-core.js";
import { z } from "zod";

// ---------------------------------------------------------------------------
// Config parsing
// ---------------------------------------------------------------------------

test("loadDispatchConfig: defaults when env empty", () => {
  const c = loadDispatchConfig({});
  assert.deepEqual([...c.modelAllowlist], [...DEFAULT_MODEL_ALLOWLIST]);
  assert.equal(c.promptMaxChars, DEFAULT_PROMPT_MAX_CHARS);
  assert.equal(c.systemPromptMaxChars, DEFAULT_SYSTEM_PROMPT_MAX_CHARS);
  assert.equal(c.maxTokensCeiling, DEFAULT_MAX_TOKENS_CEILING);
  assert.equal(c.estimatedCallCostUsd, DEFAULT_ESTIMATED_CALL_COST_USD);
});

test("loadDispatchConfig: allowlist override via env", () => {
  const c = loadDispatchConfig({
    OPENROUTER_MODEL_ALLOWLIST: " foo/bar , baz/qux ",
  });
  assert.deepEqual([...c.modelAllowlist], ["foo/bar", "baz/qux"]);
});

test("loadDispatchConfig: empty allowlist env falls back to defaults", () => {
  const c = loadDispatchConfig({ OPENROUTER_MODEL_ALLOWLIST: "  ,  " });
  assert.deepEqual([...c.modelAllowlist], [...DEFAULT_MODEL_ALLOWLIST]);
});

test("loadDispatchConfig: numeric overrides + bad values fall back", () => {
  const c = loadDispatchConfig({
    OPENROUTER_PROMPT_MAX_CHARS: "1000",
    OPENROUTER_SYSTEM_PROMPT_MAX_CHARS: "-5", // invalid -> fallback
    OPENROUTER_MAX_TOKENS_CEILING: "abc", // invalid -> fallback
    OPENROUTER_ESTIMATED_CALL_COST_USD: "0.25",
  });
  assert.equal(c.promptMaxChars, 1000);
  assert.equal(c.systemPromptMaxChars, DEFAULT_SYSTEM_PROMPT_MAX_CHARS);
  assert.equal(c.maxTokensCeiling, DEFAULT_MAX_TOKENS_CEILING);
  assert.equal(c.estimatedCallCostUsd, 0.25);
});

// ---------------------------------------------------------------------------
// Input schema: allowlist + length caps + max_tokens bound
// ---------------------------------------------------------------------------

test("schema: allowlist rejects unknown model_id", () => {
  const c = loadDispatchConfig({});
  const schema = z.object(buildInputSchema(c));
  const ok = schema.safeParse({
    model_id: "deepseek/deepseek-chat",
    prompt: "hi",
  });
  assert.equal(ok.success, true);

  const bad = schema.safeParse({
    model_id: "openai/o1-pro", // expensive, not in allowlist
    prompt: "hi",
  });
  assert.equal(bad.success, false);
});

test("schema: prompt length cap rejects oversized prompt", () => {
  const c = loadDispatchConfig({ OPENROUTER_PROMPT_MAX_CHARS: "10" });
  const schema = z.object(buildInputSchema(c));
  const bad = schema.safeParse({
    model_id: c.modelAllowlist[0],
    prompt: "x".repeat(11),
  });
  assert.equal(bad.success, false);

  const ok = schema.safeParse({
    model_id: c.modelAllowlist[0],
    prompt: "x".repeat(10),
  });
  assert.equal(ok.success, true);
});

test("schema: empty prompt rejected", () => {
  const c = loadDispatchConfig({});
  const schema = z.object(buildInputSchema(c));
  const bad = schema.safeParse({ model_id: c.modelAllowlist[0], prompt: "" });
  assert.equal(bad.success, false);
});

test("schema: system_prompt length cap rejects oversized", () => {
  const c = loadDispatchConfig({ OPENROUTER_SYSTEM_PROMPT_MAX_CHARS: "5" });
  const schema = z.object(buildInputSchema(c));
  const bad = schema.safeParse({
    model_id: c.modelAllowlist[0],
    prompt: "hi",
    system_prompt: "x".repeat(6),
  });
  assert.equal(bad.success, false);
});

test("schema: max_tokens bounded by ceiling", () => {
  const c = loadDispatchConfig({ OPENROUTER_MAX_TOKENS_CEILING: "5000" });
  const schema = z.object(buildInputSchema(c));

  const tooBig = schema.safeParse({
    model_id: c.modelAllowlist[0],
    prompt: "hi",
    max_tokens: 5001,
  });
  assert.equal(tooBig.success, false);

  const nonInt = schema.safeParse({
    model_id: c.modelAllowlist[0],
    prompt: "hi",
    max_tokens: 1.5,
  });
  assert.equal(nonInt.success, false);

  const negative = schema.safeParse({
    model_id: c.modelAllowlist[0],
    prompt: "hi",
    max_tokens: -1,
  });
  assert.equal(negative.success, false);
});

test("schema: max_tokens default applied when omitted", () => {
  // Default (4096) must be within the default ceiling so omitting is always valid.
  const c = loadDispatchConfig({});
  const schema = z.object(buildInputSchema(c));
  const defaulted = schema.parse({ model_id: c.modelAllowlist[0], prompt: "hi" });
  assert.equal(defaulted.max_tokens, 4096);
  assert.ok(4096 <= c.maxTokensCeiling);
});

// ---------------------------------------------------------------------------
// Ledger: reservation prevents concurrent overshoot
// ---------------------------------------------------------------------------

test("reservation prevents concurrent overshoot of the ceiling", () => {
  // Ceiling $1.00, estimate $0.50 per call. Without reservation, N concurrent
  // calls would all pass the under-ceiling check and overshoot. With same-lock
  // reservation, only ceil(ceiling/estimate) = 2 calls can be admitted before
  // exposure reaches the ceiling.
  const ledger = newLedger();
  const ceiling = 1.0;
  const estimate = 0.5;

  const admissions: boolean[] = [];
  for (let i = 0; i < 10; i++) {
    const r = admitAndReserve(ledger, ceiling, estimate);
    admissions.push(r.ok);
  }

  const admitted = admissions.filter(Boolean).length;
  assert.equal(admitted, 2, "only 2 concurrent calls admitted");
  // Exposure never exceeds ceiling + one in-flight estimate.
  assert.ok(totalExposureUsd(ledger) <= ceiling + estimate);
  // The 3rd..10th admissions were all rejected.
  assert.deepEqual(admissions, [
    true,
    true,
    false,
    false,
    false,
    false,
    false,
    false,
    false,
    false,
  ]);
});

test("reservation released and actual debited on reconcile", () => {
  const ledger = newLedger();
  const ceiling = 1.0;
  const estimate = 0.5;

  const r = admitAndReserve(ledger, ceiling, estimate);
  assert.equal(r.ok, true);
  assert.equal(ledger.reservedSpendUsd, 0.5);
  assert.equal(ledger.committedSpendUsd, 0);

  // Actual came in cheaper than the estimate.
  reconcile(ledger, estimate, 0.1, true);
  assert.equal(ledger.reservedSpendUsd, 0);
  assert.equal(ledger.committedSpendUsd, 0.1);

  // After reconcile, the freed budget is available again.
  const r2 = admitAndReserve(ledger, ceiling, estimate);
  assert.equal(r2.ok, true);
  assert.equal(totalExposureUsd(ledger), 0.6);
});

test("ceiling disabled (<=0): no reservation, debits still tracked", () => {
  const ledger = newLedger();
  const r = admitAndReserve(ledger, 0, 0.5);
  assert.equal(r.ok, true);
  assert.equal(ledger.reservedSpendUsd, 0, "no reservation when disabled");
  reconcile(ledger, 0.5, 0.2, false);
  assert.equal(ledger.committedSpendUsd, 0.2);
  assert.equal(ledger.reservedSpendUsd, 0);
});

// ---------------------------------------------------------------------------
// Conservative debit on missing total_cost
// ---------------------------------------------------------------------------

test("missing total_cost debits conservatively (estimate), never zero", () => {
  const ledger = newLedger();
  const estimate = 0.5;
  admitAndReserve(ledger, 1.0, estimate);

  reconcile(ledger, estimate, undefined, true);
  assert.equal(
    ledger.committedSpendUsd,
    estimate,
    "undefined cost debits the estimate",
  );
  assert.equal(ledger.reservedSpendUsd, 0);
});

test("NaN / negative total_cost treated as missing -> conservative debit", () => {
  const ledger = newLedger();
  const estimate = 0.5;

  admitAndReserve(ledger, 10, estimate);
  reconcile(ledger, estimate, Number.NaN, true);
  assert.equal(ledger.committedSpendUsd, estimate);

  admitAndReserve(ledger, 10, estimate);
  reconcile(ledger, estimate, -3, true);
  assert.equal(ledger.committedSpendUsd, estimate * 2);
});

test("zero actual cost is honored (not coerced to estimate)", () => {
  const ledger = newLedger();
  const estimate = 0.5;
  admitAndReserve(ledger, 1.0, estimate);
  reconcile(ledger, estimate, 0, true);
  // A genuine reported cost of exactly 0 is a valid debit.
  assert.equal(ledger.committedSpendUsd, 0);
  assert.equal(ledger.reservedSpendUsd, 0);
});

// ---------------------------------------------------------------------------
// Ledger monotonicity
// ---------------------------------------------------------------------------

test("mergeCommittedMonotonic never decreases committed spend", () => {
  const ledger = newLedger();
  ledger.committedSpendUsd = 5;

  // A persisted value LOWER than current must not roll the ledger back.
  mergeCommittedMonotonic(ledger, 2);
  assert.equal(ledger.committedSpendUsd, 5);

  // A persisted value HIGHER (another instance spent more) is adopted.
  mergeCommittedMonotonic(ledger, 9);
  assert.equal(ledger.committedSpendUsd, 9);

  // Garbage persisted value is ignored.
  mergeCommittedMonotonic(ledger, Number.NaN);
  assert.equal(ledger.committedSpendUsd, 9);
});

test("monotonicity defends against a same-user reset-to-zero state file", () => {
  const ledger = newLedger();
  ledger.committedSpendUsd = 12.34;
  // Simulate loadState reading a tampered/rolled-back file with spend 0.
  mergeCommittedMonotonic(ledger, 0);
  assert.equal(ledger.committedSpendUsd, 12.34);
});
