# interflux Philosophy

## Purpose
Multi-agent review and research with scored triage, domain detection, content slicing, and knowledge injection. 17 agents (12 review + 5 research), 3 commands, 2 skills, 2 MCP servers. Companion plugin for Clavain.

## North Star
Maximize signal density in multi-agent review/research: triage quality, domain fit, and synthesis quality at controlled context cost.

## Working Priorities
- Triage precision
- Domain fit
- Synthesis quality

## Brainstorming Doctrine
1. Start from outcomes and failure modes, not implementation details.
2. Generate at least three options: conservative, balanced, and aggressive.
3. Explicitly call out assumptions, unknowns, and dependency risk across modules.
4. Prefer ideas that improve clarity, reversibility, and operational visibility.

## Planning Doctrine
1. Convert selected direction into small, testable, reversible slices.
2. Define acceptance criteria, verification steps, and rollback path for each slice.
3. Sequence dependencies explicitly and keep integration contracts narrow.
4. Reserve optimization work until correctness and reliability are proven.

## Decision Filters
- Does this reduce ambiguity for future sessions?
- Does this improve reliability without inflating cognitive load?
- Is the change observable, measurable, and easy to verify?
- Can we revert safely if assumptions fail?
