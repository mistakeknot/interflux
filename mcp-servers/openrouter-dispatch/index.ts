import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import * as fs from "node:fs/promises";
import * as path from "node:path";
import * as os from "node:os";

const API_KEY = process.env.OPENROUTER_API_KEY;
if (!API_KEY) {
  console.error(
    "OPENROUTER_API_KEY not set — openrouter-dispatch MCP disabled.",
  );
  console.error(
    "Set OPENROUTER_API_KEY to enable cross-model review dispatch.",
  );
  // Exit 78 (EX_CONFIG) signals a config problem to Claude Code rather than clean shutdown.
  // With exit 0 the MCP appears to "run successfully" in the plugin surface, masking the
  // missing-config state; with 78 it surfaces as a config error in logs.
  process.exit(78);
}

const RATE_LIMIT = parseInt(process.env.OPENROUTER_RATE_LIMIT || "20", 10);
const SPEND_CEILING = parseFloat(
  process.env.OPENROUTER_SPEND_CEILING_USD || "0",
);

// Rate-limit + spend state is persisted so concurrent MCP instances share one
// budget. Without persistence each session saw the full RATE_LIMIT and
// SPEND_CEILING independently — at scale the ceiling became effectively
// unbounded (blueprint §8 risk 4, phase2.3 A-P1-5).
const STATE_DIR = path.join(os.homedir(), ".config", "interflux");
const STATE_FILE = path.join(STATE_DIR, "openrouter-state.json");
const LOCK_FILE = `${STATE_FILE}.lock`;
const LOCK_WAIT_MS = 30_000;
const LOCK_POLL_MS = 25;
const LOCK_STALE_MS = 60_000;

type PersistedState = {
  tokenBucket: number;
  lastRefill: number;
  cumulativeSpendUsd: number;
  updatedAt: string;
};

const refillRate = RATE_LIMIT / 60000; // tokens per ms
let tokenBucket = RATE_LIMIT;
let lastRefill = Date.now();
let cumulativeSpendUsd = 0;

async function acquireLock(): Promise<() => Promise<void>> {
  const deadline = Date.now() + LOCK_WAIT_MS;
  while (true) {
    try {
      // `wx` = O_CREAT | O_EXCL. Fails with EEXIST when another process holds the lock.
      const fh = await fs.open(LOCK_FILE, "wx");
      await fh.writeFile(`${process.pid}\n${Date.now()}\n`);
      await fh.close();
      return async () => {
        try {
          await fs.unlink(LOCK_FILE);
        } catch {
          // Release is best-effort; a stale lockfile is recoverable on next acquire.
        }
      };
    } catch (err: unknown) {
      const code = (err as NodeJS.ErrnoException | undefined)?.code;
      if (code !== "EEXIST") throw err;

      // Break a stale lock whose mtime is older than LOCK_STALE_MS. Prevents
      // a crashed MCP instance from deadlocking future instances.
      try {
        const stat = await fs.stat(LOCK_FILE);
        if (Date.now() - stat.mtimeMs > LOCK_STALE_MS) {
          await fs.unlink(LOCK_FILE);
          continue;
        }
      } catch {
        // Lock disappeared between EEXIST and stat — retry acquire.
      }

      if (Date.now() >= deadline) {
        throw new Error(
          `openrouter-state: lock wait exceeded ${LOCK_WAIT_MS}ms`,
        );
      }
      await new Promise((r) => setTimeout(r, LOCK_POLL_MS));
    }
  }
}

async function loadState(): Promise<void> {
  try {
    const raw = await fs.readFile(STATE_FILE, "utf8");
    const parsed = JSON.parse(raw) as Partial<PersistedState>;
    if (typeof parsed.tokenBucket === "number")
      tokenBucket = Math.min(RATE_LIMIT, parsed.tokenBucket);
    if (typeof parsed.lastRefill === "number") lastRefill = parsed.lastRefill;
    if (typeof parsed.cumulativeSpendUsd === "number")
      cumulativeSpendUsd = parsed.cumulativeSpendUsd;
  } catch (err: unknown) {
    const code = (err as NodeJS.ErrnoException | undefined)?.code;
    if (code !== "ENOENT") {
      console.error(
        `openrouter-state: failed to load ${STATE_FILE} — starting fresh:`,
        err,
      );
    }
    // Missing file is normal on first run; any other error falls back to defaults.
  }
}

async function saveState(): Promise<void> {
  const payload: PersistedState = {
    tokenBucket,
    lastRefill,
    cumulativeSpendUsd,
    updatedAt: new Date().toISOString(),
  };
  const tmp = `${STATE_FILE}.tmp.${process.pid}`;
  await fs.writeFile(tmp, JSON.stringify(payload, null, 2), { mode: 0o600 });
  await fs.rename(tmp, STATE_FILE);
}

async function withStateLock<T>(fn: () => Promise<T> | T): Promise<T> {
  await fs.mkdir(STATE_DIR, { recursive: true, mode: 0o700 });
  const release = await acquireLock();
  try {
    await loadState();
    const out = await fn();
    await saveState();
    return out;
  } finally {
    await release();
  }
}

function tryAcquireInMemory(): boolean {
  const now = Date.now();
  const elapsed = now - lastRefill;
  tokenBucket = Math.min(RATE_LIMIT, tokenBucket + elapsed * refillRate);
  lastRefill = now;
  if (tokenBucket >= 1) {
    tokenBucket -= 1;
    return true;
  }
  return false;
}

// Prime from disk on startup so a restart inherits the ongoing budget.
await withStateLock(async () => {});

const server = new McpServer({
  name: "openrouter-dispatch",
  version: "0.1.0",
});

server.tool(
  "review_with_model",
  "Dispatch a review prompt to a model via OpenRouter",
  {
    model_id: z
      .string()
      .describe("OpenRouter model ID (e.g., 'deepseek/deepseek-chat')"),
    prompt: z.string().describe("The review prompt to send"),
    system_prompt: z
      .string()
      .optional()
      .describe("System prompt for the model"),
    max_tokens: z
      .number()
      .optional()
      .default(4096)
      .describe("Max tokens in response"),
  },
  async ({ model_id, prompt, system_prompt, max_tokens }) => {
    const acquired = await withStateLock(() => {
      if (SPEND_CEILING > 0 && cumulativeSpendUsd >= SPEND_CEILING) {
        return { ok: false as const, kind: "spend" as const };
      }
      if (!tryAcquireInMemory()) {
        return { ok: false as const, kind: "rate" as const };
      }
      return { ok: true as const };
    });

    if (!acquired.ok && acquired.kind === "rate") {
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              error: "rate_limited",
              message: `Rate limit exceeded (${RATE_LIMIT}/min). Try again shortly.`,
            }),
          },
        ],
        isError: true,
      };
    }

    if (!acquired.ok && acquired.kind === "spend") {
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              error: "spend_ceiling_exceeded",
              message: `Cumulative spend $${cumulativeSpendUsd.toFixed(4)} >= ceiling $${SPEND_CEILING}`,
            }),
          },
        ],
        isError: true,
      };
    }

    const startMs = Date.now();
    const messages: Array<{ role: string; content: string }> = [];
    if (system_prompt)
      messages.push({ role: "system", content: system_prompt });
    messages.push({ role: "user", content: prompt });

    const resp = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${API_KEY}`,
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/sylveste-ai/sylveste",
        "X-Title": "FluxBench Qualification",
      },
      body: JSON.stringify({ model: model_id, messages, max_tokens }),
    });

    const latencyMs = Date.now() - startMs;

    if (!resp.ok) {
      const body = await resp.text();
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              error: `openrouter_${resp.status}`,
              message: body.slice(0, 500),
              latency_ms: latencyMs,
            }),
          },
        ],
        isError: true,
      };
    }

    const data = (await resp.json()) as {
      choices: Array<{ message: { content: string } }>;
      usage?: {
        prompt_tokens: number;
        completion_tokens: number;
        total_cost?: number;
      };
      model: string;
    };

    const tokensUsed =
      (data.usage?.prompt_tokens ?? 0) + (data.usage?.completion_tokens ?? 0);
    if (data.usage?.total_cost) {
      await withStateLock(() => {
        cumulativeSpendUsd += data.usage!.total_cost!;
      });
    }

    return {
      content: [
        {
          type: "text" as const,
          text: JSON.stringify({
            content: data.choices[0]?.message?.content ?? "",
            model: data.model,
            tokens_used: tokensUsed,
            latency_ms: latencyMs,
          }),
        },
      ],
    };
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
