# Fixture: fusion pairing (SHARED_HEAT)

`heat-ledger.jsonl` is the finding-location record of a real flux-melange run —
`datum` / `orthophoto-pass-and-address-gauge`, 2026-09-13: 10 lenses, 3 rounds,
33 findings, 45 candidate lens pairs. Trimmed to the four fields the pairing
controller reads (`id`, `round`, `agents`, `location`, `cluster_id`); claims,
scores, evidence and status are dropped.

That run issued **zero** FUSE directives. The cause is in this file: every
`location` is free-form prose naming several files and anchors at once, and the
controller compared whole normalized location strings for equality, so
SHARED_HEAT scored 0 for all 45 pairs in all 3 rounds and the fusion gate never
opened. `test_melange_fusion_pairing.py` pins both halves of that: the old
string-equality method still scores 0 here, and the shipped region-set method
admits pairs.

`target` below is the run's review target, whose own path must not count as a
shared region (every lens reviews it).

    target: docs/brainstorms/2026-09-13-orthophoto-and-address-gauge-brainstorm.md
