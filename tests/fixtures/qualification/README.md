# Qualification Test Fixtures

Each fixture is a directory containing:
- `document.md` — source code or document to review
- `ground-truth.json` — expected findings with severity, location, description

## ground-truth.json Schema

```json
{
  "fixture_id": "fixture-01-null-check",
  "agent_type": "checker|analytical|judgment",
  "findings": [
    {
      "severity": "P0|P1|P2|P3",
      "location": "file:line or section reference",
      "description": "What the finding is",
      "category": "correctness|security|style|architecture|performance"
    }
  ],
  "annotator": "human|hybrid",
  "annotation_date": "YYYY-MM-DD",
  "notes": "Context about annotation decisions"
}
```

## Agent Type Coverage
- checker: style, naming, test coverage (fixtures 03, 05)
- analytical: architecture, design, dependencies (fixtures 05)
- judgment: security, data integrity, race conditions (fixtures 01, 02, 04)

## Adding Fixtures
1. Create directory `fixture-NN-<slug>/`
2. Add `document.md` with realistic code/doc
3. Add `ground-truth.json` following schema above
4. Annotate severity carefully — P0 auto-fails FluxBench qualification
5. For core gate calibration: require kappa >= 0.7 or dual-annotator agreement on severity
