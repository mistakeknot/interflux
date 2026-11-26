#!/usr/bin/env python3
"""cross_track_convergence.py - family-aware weighted convergence for flux-review.

Deterministic, zero model tokens. Issue #52 (review finding C-4).

flux-review ranks cross-track convergent findings as its highest-confidence
signal. A raw head-count of tracks overstates that: track agents usually share
one base model family, so their agreement is correlated error, not independent
corroboration. The single-run synthesis already weights cross-family agreement
(docs/spec/core/synthesis.md Step 4, 1.5x); this script carries that to the
cross-track tier and makes same-family agreement count as ~one source.

Inputs
  REVIEW_DIR/cross-track-convergence.json  (written by the synthesis subagent)
      {"clusters": [{"id": "XT-1", "title": "...",
                     "tracks": {"a": [{"agent": "fd-x", "finding_id": "P1-1"}],
                                "c": [{"agent": "fd-y"}]}}]}
  REVIEW_DIR/track-{letter}/findings.json  (written by each inner flux-drive run)
      model_family is read ONLY from here: findings[].provenance[agent].model_family,
      else findings[].model_family when the finding's agent(s) include the agent.
      Any model_family the synthesis subagent writes into the sidecar is ignored:
      provenance is orchestrator dispatch metadata, the sidecar is LLM output.
      An unresolvable agent falls back to `default_model_family` (the family the
      track review models route to) and is marked unresolved - it can never
      manufacture independence.

Weighting (tunables in config/flux-review/defaults.yaml `convergence:`)
  For each cluster, group contributing tracks by model family (a track counts
  once per distinct family among its contributing agents). With n_f tracks in
  family f:
      credit(f)  = 1 + same_family_track_bonus * (n_f - 1)
      weighted   = credit(f1) + cross_family_weight * sum(credit(f) for f != f1)
  where f1 is the family with the highest credit (ties: alphabetical). This is
  the single-run formula `same_family_count + cross_family_bonus * 1.5` with the
  same-family count replaced by its de-correlated credit.

Labels
  families == 1                      -> "Correlated"  (never High, whatever the count)
  weighted >= high_threshold         -> "High"
  weighted >= medium_threshold       -> "Medium"
  otherwise                          -> "Low"
  fewer than 2 tracks                -> "Single-track" (not convergent)

Usage
  cross_track_convergence.py REVIEW_DIR [--config FILE] [--json]
                                        [--write-synthesis SYNTHESIS.md]
  Exit 0 on success, 2 on a bad invocation (missing/unparseable sidecar).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULTS = {
    # Mirrors docs/spec/core/synthesis.md Step 4 cross-family multiplier.
    "cross_family_weight": 1.5,
    # Extra credit per additional same-family track (distinct semantic distance
    # is worth something, but not an independent source).
    "same_family_track_bonus": 0.25,
    "high_threshold": 2.5,
    "medium_threshold": 1.5,
    # flux-review track reviews route to sonnet/opus (track-dispatch.md).
    "default_model_family": "claude",
}

SIDECAR = "cross-track-convergence.json"
BEGIN = "<!-- cross-track-convergence:begin -->"
END = "<!-- cross-track-convergence:end -->"
CAVEAT = (
    "> **Caveat - correlated convergence:** every convergent track in this review "
    "ran on one model family ({family}). Cross-track agreement here is correlated "
    "evidence from a shared base model, not independent corroboration; no "
    "convergent finding is rated High on track count alone."
)


def load_config(path: Path | None) -> dict:
    cfg = dict(DEFAULTS)
    if path is None:
        path = Path(__file__).resolve().parent.parent / "config" / "flux-review" / "defaults.yaml"
    if not path.exists():
        return cfg
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError:
        return cfg
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return cfg
    block = data.get("convergence") if isinstance(data, dict) else None
    if isinstance(block, dict):
        for k in DEFAULTS:
            if k in block and block[k] is not None:
                cfg[k] = type(DEFAULTS[k])(block[k])
    return cfg


def _load_track_findings(review_dir: Path, letter: str) -> list[dict]:
    p = review_dir / f"track-{letter}" / "findings.json"
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return []
    findings = data.get("findings") if isinstance(data, dict) else None
    out = [f for f in (findings or []) if isinstance(f, dict)]
    out += [f for f in (data.get("improvements") or []) if isinstance(f, dict)]
    return out


def _agents_of(finding: dict) -> list[str]:
    agents = finding.get("agents")
    if isinstance(agents, list):
        return [str(a) for a in agents]
    if finding.get("agent"):
        return [str(finding["agent"])]
    return []


def resolve_family(findings: list[dict], agent: str, finding_id: str | None) -> str | None:
    """Return model_family for agent from a track's findings.json, or None."""
    candidates = findings
    if finding_id:
        exact = [f for f in findings if str(f.get("id")) == str(finding_id)]
        candidates = exact + [f for f in findings if f not in exact]
    for f in candidates:
        prov = f.get("provenance")
        if isinstance(prov, dict) and isinstance(prov.get(agent), dict):
            fam = prov[agent].get("model_family")
            if fam:
                return str(fam).strip().lower()
    for f in candidates:
        if agent in _agents_of(f) and f.get("model_family"):
            return str(f["model_family"]).strip().lower()
    return None


def weigh(families_to_tracks: dict[str, set[str]], cfg: dict) -> float:
    if not families_to_tracks:
        return 0.0
    bonus = cfg["same_family_track_bonus"]
    credits = {f: 1.0 + bonus * (len(t) - 1) for f, t in families_to_tracks.items()}
    ordered = sorted(credits.items(), key=lambda kv: (-kv[1], kv[0]))
    head = ordered[0][1]
    rest = sum(c for _, c in ordered[1:])
    return round(head + cfg["cross_family_weight"] * rest, 4)


def label(n_tracks: int, n_families: int, weighted: float, cfg: dict) -> str:
    if n_tracks < 2:
        return "Single-track"
    if n_families <= 1:
        return "Correlated"
    if weighted >= cfg["high_threshold"]:
        return "High"
    if weighted >= cfg["medium_threshold"]:
        return "Medium"
    return "Low"


def score(review_dir: Path, sidecar: dict, cfg: dict) -> dict:
    track_cache: dict[str, list[dict]] = {}
    active_tracks = sorted(
        p.name.split("-", 1)[1] for p in review_dir.glob("track-*") if p.is_dir()
    )
    results = []
    for cluster in sidecar.get("clusters") or []:
        if not isinstance(cluster, dict):
            continue
        tracks = cluster.get("tracks") or {}
        fam_tracks: dict[str, set[str]] = {}
        contributors = []
        unresolved = []
        for letter, entries in sorted(tracks.items()):
            letter = str(letter).lower()
            if letter not in track_cache:
                track_cache[letter] = _load_track_findings(review_dir, letter)
            if isinstance(entries, dict):
                entries = [entries]
            if not entries:
                continue
            for e in entries:
                agent = str(e.get("agent", "")) if isinstance(e, dict) else str(e)
                fid = e.get("finding_id") if isinstance(e, dict) else None
                fam = resolve_family(track_cache[letter], agent, fid)
                if fam is None:
                    fam = cfg["default_model_family"]
                    unresolved.append(f"{letter}:{agent}")
                fam_tracks.setdefault(fam, set()).add(letter)
                contributors.append({"track": letter, "agent": agent, "model_family": fam})
        n_tracks = len({c["track"] for c in contributors})
        n_fam = len(fam_tracks)
        w = weigh(fam_tracks, cfg)
        results.append({
            "id": cluster.get("id"),
            "title": cluster.get("title", ""),
            "raw_tracks": n_tracks,
            "track_count_of": len(active_tracks) or n_tracks,
            "model_families": sorted(fam_tracks),
            "cross_family_convergence": n_fam,
            "weighted_convergence": w,
            "confidence": label(n_tracks, n_fam, w, cfg),
            "contributors": contributors,
            "family_unresolved": unresolved,
        })
    convergent = [r for r in results if r["raw_tracks"] >= 2]
    convergent.sort(key=lambda r: (-r["weighted_convergence"], -r["raw_tracks"], str(r["id"])))
    singles = [r for r in results if r["raw_tracks"] < 2]
    run_families = sorted({f for r in convergent for f in r["model_families"]})
    single_family = len(run_families) == 1
    return {
        "config": cfg,
        "clusters": convergent + singles,
        "convergent_count": len(convergent),
        "convergent_model_families": run_families,
        "single_family": single_family,
        "caveat": CAVEAT.format(family=run_families[0]) if single_family else None,
    }


def render_markdown(result: dict) -> str:
    lines = [BEGIN, "### Weighted convergence (computed by scripts/cross_track_convergence.py)", ""]
    if result["caveat"]:
        lines += [result["caveat"], ""]
    if not result["convergent_count"]:
        lines += ["No finding converged across 2+ tracks.", "", END]
        return "\n".join(lines)
    lines += [
        "| ID | Finding | Tracks | Model families | Weighted | Confidence |",
        "|----|---------|--------|----------------|----------|------------|",
    ]
    for r in result["clusters"]:
        if r["raw_tracks"] < 2:
            continue
        fams = ", ".join(r["model_families"])
        if r["family_unresolved"]:
            fams += " (unresolved: default assumed)"
        title = str(r["title"]).replace("|", "\\|")
        lines.append(
            f"| {r['id']} | {title} | {r['raw_tracks']}/{r['track_count_of']} | {fams} "
            f"| {r['weighted_convergence']:g} | {r['confidence']} |"
        )
    lines += ["", END]
    return "\n".join(lines)


HEADING_RE = re.compile(r"^## Cross-Track Convergence[^\n]*\n", re.M)


def write_synthesis(path: Path, block: str) -> None:
    text = path.read_text()
    if BEGIN in text and END in text:
        pre, rest = text.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        text = pre + block + post
    else:
        m = HEADING_RE.search(text)
        if m:
            text = text[: m.end()] + "\n" + block + "\n" + text[m.end():]
        else:
            text = text.rstrip("\n") + "\n\n## Cross-Track Convergence\n\n" + block + "\n"
    path.write_text(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("review_dir", type=Path)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    ap.add_argument("--write-synthesis", type=Path, default=None,
                    help="insert/replace the weighted block in this synthesis file")
    args = ap.parse_args(argv)

    sidecar_path = args.review_dir / SIDECAR
    try:
        sidecar = json.loads(sidecar_path.read_text())
    except (OSError, ValueError) as exc:
        print(f"cross_track_convergence: cannot read {sidecar_path}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(sidecar, dict):
        print(f"cross_track_convergence: {sidecar_path} is not a JSON object", file=sys.stderr)
        return 2

    result = score(args.review_dir, sidecar, load_config(args.config))
    (args.review_dir / "cross-track-convergence.scored.json").write_text(
        json.dumps(result, indent=2) + "\n")
    block = render_markdown(result)
    if args.write_synthesis:
        write_synthesis(args.write_synthesis, block)
    print(json.dumps(result, indent=2) if args.json else block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
