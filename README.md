# interflux

Multi-agent review and research engine for Claude Code.

## What this does

interflux is the review infrastructure behind Clavain's `/flux-drive` and `/flux-research` commands. Point it at a document or codebase and it runs a scored triage to figure out which domain agents are relevant, slices the content so each agent only sees what it needs, injects project-specific knowledge, and synthesizes the results.

There are 12 review agents (7 technical: architecture, safety, correctness, performance, quality, game design, user/product; 5 cognitive: systems thinking, decision quality, human systems, adaptive capacity, sensemaking) and 5 research agents (best practices, framework docs, git history, learnings, repo research). The triage step means you don't pay for all of them on every review: only the relevant ones fire.

The engine also powers `flux-research`, which dispatches research agents in parallel and synthesizes their findings. Useful when you need to understand a topic from multiple angles before making a design decision.

## Installation

First, add the [interagency marketplace](https://github.com/mistakeknot/interagency-marketplace) (one-time setup):

```bash
/plugin marketplace add mistakeknot/interagency-marketplace
```

Then install the plugin:

```bash
/plugin install interflux
```

## Usage

Review a document or codebase:

```
/flux-drive
```

Research a topic with parallel agents:

```
/flux-research "best practices for SQLite WAL mode in Go CLI tools"
```

Generate project-specific review agents:

```
/flux-gen
```

## Architecture

```
agents/          12 review agents + 5 research agents
skills/          flux-drive, flux-research
commands/        flux-drive, flux-research, flux-gen
docs/spec/       Full flux-drive protocol specification (9 documents)
```

Two MCP servers: `qmd` for semantic search (embeddings-based document retrieval) and `exa` for web search (progressive enhancement: falls back gracefully if `EXA_API_KEY` isn't set).

## Design decisions

- Technical agents auto-detect language from the code under review
- Cognitive agents review documents only (plans, PRDs, strategies)
- Triage scoring prevents unnecessary agent launches
- Exa is progressive: falls back to Context7 + WebSearch when unavailable
- The full protocol spec lives in `docs/spec/` and is versioned independently
