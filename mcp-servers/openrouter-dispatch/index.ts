import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const API_KEY = process.env.OPENROUTER_API_KEY;
if (!API_KEY) {
  console.error("OPENROUTER_API_KEY not set — openrouter-dispatch MCP disabled.");
  process.exit(0);
}

const RATE_LIMIT = parseInt(process.env.OPENROUTER_RATE_LIMIT || "20", 10);
const SPEND_CEILING = parseFloat(process.env.OPENROUTER_SPEND_CEILING_USD || "0");

// Token-bucket rate limiter
let tokenBucket = RATE_LIMIT;
let lastRefill = Date.now();
const refillRate = RATE_LIMIT / 60000; // tokens per ms

function tryAcquire(): boolean {
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

let cumulativeSpendUsd = 0;

const server = new McpServer({
  name: "openrouter-dispatch",
  version: "0.1.0",
});

server.tool(
  "review_with_model",
  "Dispatch a review prompt to a model via OpenRouter",
  {
    model_id: z.string().describe("OpenRouter model ID (e.g., 'deepseek/deepseek-chat')"),
    prompt: z.string().describe("The review prompt to send"),
    system_prompt: z.string().optional().describe("System prompt for the model"),
    max_tokens: z.number().optional().default(4096).describe("Max tokens in response"),
  },
  async ({ model_id, prompt, system_prompt, max_tokens }) => {
    if (!tryAcquire()) {
      return {
        content: [{ type: "text" as const, text: JSON.stringify({
          error: "rate_limited",
          message: `Rate limit exceeded (${RATE_LIMIT}/min). Try again shortly.`,
        })}],
        isError: true,
      };
    }

    if (SPEND_CEILING > 0 && cumulativeSpendUsd >= SPEND_CEILING) {
      return {
        content: [{ type: "text" as const, text: JSON.stringify({
          error: "spend_ceiling_exceeded",
          message: `Cumulative spend $${cumulativeSpendUsd.toFixed(4)} >= ceiling $${SPEND_CEILING}`,
        })}],
        isError: true,
      };
    }

    const startMs = Date.now();
    const messages: Array<{role: string; content: string}> = [];
    if (system_prompt) messages.push({ role: "system", content: system_prompt });
    messages.push({ role: "user", content: prompt });

    const resp = await fetch("https://openrouter.ai/api/v1/chat/completions", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${API_KEY}`,
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
        content: [{ type: "text" as const, text: JSON.stringify({
          error: `openrouter_${resp.status}`,
          message: body.slice(0, 500),
          latency_ms: latencyMs,
        })}],
        isError: true,
      };
    }

    const data = await resp.json() as {
      choices: Array<{ message: { content: string } }>;
      usage?: { prompt_tokens: number; completion_tokens: number; total_cost?: number };
      model: string;
    };

    const tokensUsed = (data.usage?.prompt_tokens ?? 0) + (data.usage?.completion_tokens ?? 0);
    if (data.usage?.total_cost) cumulativeSpendUsd += data.usage.total_cost;

    return {
      content: [{ type: "text" as const, text: JSON.stringify({
        content: data.choices[0]?.message?.content ?? "",
        model: data.model,
        tokens_used: tokensUsed,
        latency_ms: latencyMs,
      })}],
    };
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);
