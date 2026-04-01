# Learnings: flux-review-token-efficiency

## Validated Insights

- **Inline examples are the biggest token waste** — JSON schema blocks, bash code samples, and verbose prompt templates accounted for ~40% of total phase file tokens. Replacing with compact specs preserved all logic while cutting 50-73% per file.
  - Evidence: synthesize-review.md 4,230→1,125 (-73%), slicing.md 3,270→1,079 (-67%), reaction.md ~1,391→~417 (-70%)

- **Extract-and-reference beats inline** — Moving the agent prompt template (1,553 tokens) and expansion logic (1,680 tokens) to separate files cut launch.md by 51% while preserving the complete algorithms as conditional-load references.
  - Evidence: launch.md 7,350→3,235 total across experiments 1-4 and 10

- **Compression compounds** — Each file's compression independently improves the composite, and the compound effect across all files is larger than any single change. SKILL.md + launch.md + slicing.md + reaction.md + synthesis agent combined: 21,561→10,693 (-50%).

## Dead Ends

- **Conditional loading of slicing.md from SKILL.md** — Behaviorally correct but the benchmark regression (+1,162) from newly counting shared_contracts.md meant the metric couldn't capture the real savings. The conditional loading instruction itself added more text than it saved in the SKILL.md.

## Patterns (generalizable)

- **Prompt-based instruction files** should be treated as code: every token costs real money per invocation. Audit instruction file sizes quarterly.
- **"Read X for details" references** are cheaper than inline content — the orchestrator only loads the reference when it reaches that step.
- **Phase files loaded unconditionally** (SKILL.md, launch.md) deserve the most aggressive compression. Conditionally-loaded files (slicing.md, reaction.md, expansion.md) matter less per invocation but still benefit from compression.
- **Agent definition files** (702 tokens avg) are already lean — compression ROI is low. Focus on orchestrator and synthesis files instead.
