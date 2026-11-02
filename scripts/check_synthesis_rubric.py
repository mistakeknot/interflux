#!/usr/bin/env python3
"""check_synthesis_rubric.py - ADVISORY invariant checker for flux-drive syntheses.

Deterministic, zero model tokens. Reads a synthesis/summary markdown file and
emits flags in a report section. It never blocks and never rewrites the input:
flags always exit 0. Only a bad invocation (unreadable file) exits 2.

Checks
  count     headline totals vs. their own severity breakdown, and vs. per-agent rows
            only when the document says the headline is that sum (synthesis dedups);
            rows are table cells shaped P0/P1/P2[/P3].
  ref       file:line references: when --source-root resolves the file, the line
            must exist. Unresolvable references are counted, not flagged.
  dim 2     aggregate backed by evidence: an "A x B = C" product that does not
            compute, or a numeric/aggregate claim in a finding with no evidence.
  dim 3     sizing is causal and de-overlapped: effort or percentage sizing in a
            finding with no stated cause.
  dim 8     fix applies verbatim: a hedged fix ("consider", "either ... or").

The dim 2/3/8 tags are heuristics for a human or the synthesis agent to look at,
not verdicts. Absence of a flag is not proof a finding is sound.

Usage: check_synthesis_rubric.py SYNTHESIS.md [--source-root DIR] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEVS = ("P0", "P1", "P2", "P3")
REF_RE = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.[A-Za-z]{1,6}):(\d+)(?:-(\d+))?\b")
_NUM = r"\d[\d,]*(?:\.\d+)?"
PRODUCT_RE = re.compile(
    rf"(?<![\d.,])({_NUM})\s*(?:[A-Za-z]+\s+)?[x×*]\s*({_NUM})\s*(?:[A-Za-z]+\s+)?=\s*({_NUM})(\+?)")
SUM_OF_ROWS_RE = re.compile(
    r"(sum of (?:the )?(?:per-?agent|agent)|(?:adds?|add up|totals?) (?:up )?(?:across|over|from) (?:the )?(?:per-?agent|agent)"
    r"|raw (?:per-?agent|agent) total|before (?:de-?dup|dedup))", re.I)
FINDING_RE = re.compile(r"^\s*(?:[-*]|#{2,5}|\|)\s*.*?\b(P[0-3])\b")
TOTAL_RE = re.compile(r"\b(\d+)\s+(?:total\s+)?findings?\b", re.I)
BREAKDOWN_RE = re.compile(r"(\d+)\s*(P[0-3])\b")
SLASH_CELL_RE = re.compile(r"^\s*(\d+(?:\s*/\s*\d+){2,3})\s*$")
AGGREGATE_RE = re.compile(
    r"(\d[\d,]*\+?\s*(?:llm\s+calls?|calls?|reviews?|requests?|users?|skus?|per\s+\w+|/\s*(?:day|month|session))"
    r"|\b\d+\s*%)", re.I)
SIZING_RE = re.compile(r"(\b\d+\s*(?:hours?|hrs?|h|min(?:utes?)?|days?)\b|~\s*\d+\s*lines?\b|\b\d+\s*%)", re.I)
CAUSE_RE = re.compile(r"\b(because|since|due to|caused by|which causes|so that|therefore|as a result)\b", re.I)
HEDGE_RE = re.compile(r"\b(consider|might|could also|perhaps|either\b.*\bor\b|e\.g\.|or similar)\b", re.I)
EVIDENCE_RE = re.compile(r"(`[^`]+`|\w+\.\w+:\d+|\bsee\b|\bcited\b)", re.I)


def check_counts(text: str) -> list[dict]:
    flags: list[dict] = []
    total_m = TOTAL_RE.search(text)
    headline_total = int(total_m.group(1)) if total_m else None
    breakdown: dict[str, int] = {}
    if total_m:
        tail = text[total_m.end(): total_m.end() + 120].split("\n")[0]
        paren = re.search(r"\(([^)]*)\)", tail)
        if paren:
            body = paren.group(1)
            for n, sev in BREAKDOWN_RE.findall(body):
                breakdown[sev] = int(n)
            if not breakdown:  # "12/38/30/11" shape
                m = SLASH_CELL_RE.match(body)
                if m:
                    for sev, n in zip(SEVS, re.split(r"\s*/\s*", m.group(1))):
                        breakdown[sev] = int(n)
    if headline_total is not None and breakdown and sum(breakdown.values()) != headline_total:
        flags.append({
            "check": "count", "dim": 2,
            "message": f"headline says {headline_total} findings but its own breakdown "
                       f"{breakdown} adds to {sum(breakdown.values())}"})

    # Per-agent rows: only tables whose header mentions P0.
    rows: list[list[int]] = []
    in_table = False
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if any("P0" in c for c in cells) and not any(SLASH_CELL_RE.match(c) for c in cells):
                in_table = True
                continue
            if in_table and not re.match(r"^[-: ]+$", "".join(cells)):
                if cells and re.match(r"(?i)total", cells[0]):
                    continue
                for c in cells:
                    m = SLASH_CELL_RE.match(c)
                    if m:
                        rows.append([int(x) for x in re.split(r"\s*/\s*", m.group(1))])
                        break
        else:
            in_table = False
    # Synthesis deduplicates, so a headline legitimately differs from raw per-agent
    # totals. Compare them only when the document says the headline is that sum.
    if rows and SUM_OF_ROWS_RE.search(text):
        width = max(len(r) for r in rows)
        sums = [sum(r[i] for r in rows if i < len(r)) for i in range(width)]
        row_total = sum(sums)
        per_sev = dict(zip(SEVS, sums))
        if headline_total is not None and row_total != headline_total:
            flags.append({
                "check": "count", "dim": 2,
                "message": f"headline says {headline_total} findings but {len(rows)} per-agent rows "
                           f"add to {row_total} ({'/'.join(map(str, sums))})"})
        elif breakdown:
            for sev, n in breakdown.items():
                if sev in per_sev and per_sev[sev] != n:
                    flags.append({
                        "check": "count", "dim": 2,
                        "message": f"headline {sev} = {n} but per-agent rows give {per_sev[sev]}"})
    return flags


def check_refs(text: str, source_root: Path | None) -> tuple[list[dict], int, int]:
    flags: list[dict] = []
    resolved = unresolved = 0
    seen: set[tuple[str, int]] = set()
    for m in REF_RE.finditer(text):
        rel, start = m.group(1), int(m.group(2))
        end = int(m.group(3)) if m.group(3) else start
        if (rel, end) in seen:
            continue
        seen.add((rel, end))
        target = (source_root / rel) if source_root else None
        if target is None or not target.is_file():
            unresolved += 1
            continue
        resolved += 1
        try:
            n_lines = len(target.read_text(errors="replace").splitlines())
        except OSError:
            unresolved += 1
            resolved -= 1
            continue
        if end > n_lines or start < 1:
            flags.append({
                "check": "ref", "dim": 2,
                "message": f"{rel}:{m.group(2)}{('-' + m.group(3)) if m.group(3) else ''} "
                           f"does not exist ({rel} has {n_lines} lines)"})
    return flags, resolved, unresolved


def tag_findings(text: str) -> list[dict]:
    flags: list[dict] = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("|") and re.search(r"\d\s*/\s*\d", line):
            continue  # per-agent count rows are handled by check_counts
        m = FINDING_RE.match(line)
        if not m:
            continue
        label = re.sub(r"\s+", " ", line.strip(" |-*#"))[:90]
        for p in PRODUCT_RE.finditer(line):
            a, b, c = (float(p.group(k).replace(",", "")) for k in (1, 2, 3))
            if abs(a * b - c) > 1e-9 * max(1.0, abs(c)):
                flags.append({"check": "tag", "dim": 2, "line": i, "finding": label,
                              "message": f"{a:g} x {b:g} = {a * b:g}, not {p.group(3)}{p.group(4)}"})
        if AGGREGATE_RE.search(line) and not REF_RE.search(line) and not PRODUCT_RE.search(line) \
                and not EVIDENCE_RE.search(line):
            flags.append({"check": "tag", "dim": 2, "line": i, "finding": label,
                          "message": "aggregate claim with no cited evidence"})
        if SIZING_RE.search(line) and not CAUSE_RE.search(line):
            flags.append({"check": "tag", "dim": 3, "line": i, "finding": label,
                          "message": "sizing stated with no cause"})
        if HEDGE_RE.search(line) and re.search(r"\b(fix|add|replace|change|use|remove)\b", line, re.I):
            flags.append({"check": "tag", "dim": 8, "line": i, "finding": label,
                          "message": "hedged fix may not apply verbatim"})
    return flags


def run(text: str, source_root: Path | None = None) -> dict:
    ref_flags, resolved, unresolved = check_refs(text, source_root)
    flags = check_counts(text) + ref_flags + tag_findings(text)
    return {"advisory": True, "flags": flags,
            "refs": {"resolved": resolved, "unresolved": unresolved}}


def render(report: dict) -> str:
    out = ["## Rubric flags (advisory)", "",
           "Deterministic checks; flags are prompts for review, never verdicts.", ""]
    if not report["flags"]:
        out.append("No flags.")
    for f in report["flags"]:
        where = f" (line {f['line']})" if "line" in f else ""
        out.append(f"- [dim {f['dim']}] {f['check']}{where}: {f['message']}")
    r = report["refs"]
    out += ["", f"File references: {r['resolved']} checked, {r['unresolved']} not resolvable."]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("synthesis")
    ap.add_argument("--source-root", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        text = Path(args.synthesis).read_text(errors="replace")
    except OSError as e:
        print(f"check_synthesis_rubric: cannot read input: {e}", file=sys.stderr)
        return 2
    report = run(text, args.source_root)
    print(json.dumps(report, indent=2) if args.json else render(report), end="" if not args.json else "\n")
    return 0  # advisory: flags never change the exit status


if __name__ == "__main__":
    sys.exit(main())
