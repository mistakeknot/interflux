#!/usr/bin/env python3
"""team_synthesize.py — orchestration for /interflux:flux-explore --teams.

Two phases (separate CLI subcommands so the slash command can interleave the actual
Claude Code agent-team spawn between them):

  prepare    Cluster specs into max-distance partitions, build the orchestrator-lead
             spawn prompt, write it to a temp file, run pre-flight cost preview.
             Stdout: JSON envelope describing what was prepared (paths, estimated
             cost, status). Exit 0 if ready to spawn, non-zero on fallback.

  finalize   After the orchestrator-lead's debate ends, read the persisted transcript,
             validate synthesis quality, capture per-teammate cost, and write the
             final brainstorm doc with frontmatter. Exit 0 on success.

The Python script DOES NOT drive the agent-team itself — per the agent-teams docs
(https://code.claude.com/docs/en/agent-teams), the orchestrator-lead is a Claude Code
session driven by natural language; only the slash command (running inside Claude Code)
can spawn teammates. This script's job is everything around that spawn — cluster, prompt,
cost — and everything after — transcript validation, cost capture, output writing.

Design decisions (carried from the F1 probe verdicts; see
docs/research/flux-explore-teams-probes/):

* mailbox=mesh → blind-R1 enforced via spawn prompt instruction + post-hoc transcript audit
* TaskCreated (not TaskCompleted) is the round-cap hook (referenced in spawn prompt)
* cost attribution=lead-only → finalize iterates per-teammate session IDs from team config
* ad-hoc spawn supported → no .claude/agents/td-debate-*.md files needed
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from cluster_specs import cluster_specs  # noqa: E402

# Default config — overridable via CLI
DEFAULT_ROUNDS = 2
DEFAULT_THRESHOLD = 0.30
ROLES_PER_TEAM_FULL = 5  # 1 lead + 1 author + 3 debaters + 1 questioner = 6 with lead, but lead is THIS session
ROLES_PER_TEAM_DEGRADED = 4  # when k=2, drop one debater

# Cost preview defaults — informational only
DEFAULT_PER_SESSION_COST_USD = 0.30
DEFAULT_PREVIEW_SLEEP_SEC = 3


def _slug_from_target(target: str) -> str:
    """Mirror the slug derivation flux-explore.md uses (lowercase, hyphenated)."""
    cleaned = "".join(ch.lower() if ch.isalnum() or ch == " " else " " for ch in target)
    return "-".join(cleaned.split())[:60] or "unnamed"


def _load_specs(specs_glob: str) -> list[dict]:
    paths = sorted(glob.glob(specs_glob))
    if not paths:
        raise SystemExit(f"team_synthesize: no specs match {specs_glob}")
    out: list[dict] = []
    for p in paths:
        data = json.loads(Path(p).read_text())
        if isinstance(data, list):
            out.extend(data)
        elif isinstance(data, dict):
            out.append(data)
    return out


def _build_orchestrator_prompt(
    target: str,
    slug: str,
    cluster_result: dict[str, Any],
    rounds: int,
    transcript_dir: Path,
    final_synthesis_path: Path,
) -> str:
    """Construct the natural-language spawn prompt the orchestrator-lead will run.

    The orchestrator is a Sonnet subagent dispatched from flux-explore Step 4c. This
    prompt tells it (a) what the team structure is, (b) what each teammate's role is,
    (c) the round protocol, (d) where to persist the transcript, and (e) the explicit
    discipline rules the F1 probes surfaced (mesh-mailbox blind-R1 contract, TaskCreated
    cap mechanism, no transcript inlining in author handoff).
    """
    transcript_path = transcript_dir / "transcript.md"
    cluster_blocks = []
    for cluster in cluster_result["clusters"]:
        spec_lines = []
        for s in cluster["specs"]:
            name = s.get("name", "fd-unknown")
            domain = s.get("source_domain", "(no domain)")
            isom = s.get("expected_isomorphisms", "")
            if isinstance(isom, list):
                isom = "; ".join(str(x) for x in isom)
            spec_lines.append(f"  - {name} [{domain}]: {isom}")
        cluster_blocks.append(
            f"Cluster {cluster['index']} ({len(cluster['specs'])} specs):\n" + "\n".join(spec_lines)
        )

    debater_count = cluster_result["k"]
    full_team_size = 2 + debater_count + 1  # author + N debaters + questioner; lead is YOU
    return f"""You are the team lead for a cross-domain debate synthesis. You are NOT a
participant in the debate — your job is coordination, transcript persistence, and final
handoff. Do not write the synthesis yourself; the author teammate writes it.

# Target

{target}

# Team you will spawn

A team of {full_team_size} teammates ({debater_count} debaters from clusters below + 1 author + 1 questioner).
Spawn each teammate via natural language to your harness — they are ad-hoc roles (no
.claude/agents/*.md file needed). Use Sonnet for each.

## Author teammate
Name: `author-{slug}`
Spawn prompt: "You are the synthesis author for cross-domain debate `{slug}`. After Round
2 ends, the lead will message you with a single transcript path. Use the Read tool to
read that transcript from disk — do NOT accept inlined transcript content from the lead.
Write a synthesis with at least 3 named cross-domain isomorphisms (each citing exactly 2
source domains, one named mechanism per side, the abstract principle they share, and a
mapping to the target). Include a mandatory `## Unresolved Tensions` section listing
contradictions the debate did not resolve. Do not infer beyond the transcript."

## Debater teammates ({debater_count} total)
Each debater speaks for one cluster of source domains. Spawn each separately:

{chr(10).join(cluster_blocks)}

For each cluster N, spawn `debater-cluster-{{N}}` with this prompt template:
"You are the debater for cluster {{N}} of cross-domain debate `{slug}`. Your specs (with
domains and expected_isomorphisms) are listed in the team config under your spawn prompt.

Round 1 (BLIND): post your candidate isomorphisms to the LEAD ONLY. Do not message other
debaters. Each candidate must be a falsifiable claim of form `Domain-X-pattern P maps to
Domain-Y-pattern Q via mechanism M, falsified by observation O.` Post at least one
candidate.

Round 1.5 (CHALLENGES): the questioner will message you a challenge. Reply only after
the lead opens visibility — do not pre-empt.

Round 2 (REPLIES FIRST): reply to every challenge directed at you BEFORE proposing new
combinations or refinements. If a challenge is unanswerable, list it explicitly as
`ORPHANED: <challenge>` rather than ignoring it."

## Questioner teammate
Name: `questioner-{slug}`
Spawn prompt: "You are the questioner for cross-domain debate `{slug}`. You issue
challenges only — do not propose isomorphisms. After the lead opens Round 1.5
visibility, send one challenge to each debater (round-robin). Each challenge must
reference the target debater's specific Round-1 claim by name."

# Protocol you (lead) execute

You run the rounds. You DO NOT inline transcript content into messages — the author reads
from disk.

1. **Spawn all {full_team_size} teammates.** Wait until they all report ready.
2. **Round 1 (blind).** Send each debater a "Round 1: post candidates to me only" prompt.
   Wait for all debater Round-1 messages. DO NOT broadcast Round-1 messages to peer
   debaters — this is a prompt-discipline contract; mailbox topology cannot enforce it,
   so you must not violate it.
3. **Round 1.5 (challenges).** Send the questioner the message "Round 1.5 open. Issue
   one challenge to each debater citing their named Round-1 claim." Optionally
   collate Round-1 candidates into a structured digest the questioner can reference,
   but do NOT broadcast raw debater posts.
4. **Round 2 (replies first).** Send each debater a "Round 2: reply to all challenges
   directed at you, then optionally refine." Validate that each Round-2 post addresses
   each Round-1 challenge by name (or marks it ORPHANED).
5. **Persist transcript.** After Round 2 closes, write the FULL message log
   (timestamps + sender + recipient + body) to `{transcript_path}`. Use Write tool. The
   directory `{transcript_dir}` is writable.
6. **Refuse-to-commit check.** Parse the transcript: count distinct mechanisms cited by
   ≥2 debaters. If 0, message the author "FALLBACK: no convergent mechanisms; produce a
   stub synthesis listing each cluster's Round-2 candidates as appendix and set the
   header to 'No fix; clusters incompatible.'" Otherwise message the author "Synthesis:
   transcript at {transcript_path}. Read with Read tool. Write to {final_synthesis_path}."
7. **Wait for author** to complete writing. After author reports done, mark all tasks
   completed and message the user "Debate complete. Synthesis at {final_synthesis_path}."
8. **Round cap.** A `TaskCreated` hook (if installed via INTERFLUX_TEAMS_ROUND_CAP env var)
   will exit code 2 to block any task whose payload references "Round 3" or higher. Do
   not attempt to create Round-3 tasks; the protocol is bounded to {rounds} rounds.

# Discipline rules

* MESH MAILBOX: any teammate CAN message any other directly. The blind-R1 contract relies
  on debater compliance with their spawn prompt. You must not relax it by broadcasting.
* PATH-ONLY HANDOFF: never paste transcript content into a message. Send only the
  transcript path. The author reads from disk.
* NO NESTED TEAMS: you cannot spawn sub-teams from teammates. Do not try.
* ONE TEAM: you (the lead) own one team for this run. Clean up at the end.

When done, do not leave teammates running — ask each to shut down before you exit.
"""


def _cost_preview(team_size: int, rounds: int, per_session_cost_usd: float) -> dict[str, Any]:
    """Estimate cost. Conservative — used for the pre-flight TTY warning."""
    estimated = team_size * per_session_cost_usd * max(1, rounds)
    return {
        "team_size": team_size,
        "rounds": rounds,
        "per_session_cost_usd_estimate": per_session_cost_usd,
        "estimated_total_usd": round(estimated, 2),
    }


def _maybe_show_cost_preview(preview: dict[str, Any], sleep_override: int | None) -> None:
    """Show preview to stderr; sleep only if interactive AND sleep not overridden to 0."""
    print(
        f"team_synthesize: cost preview team_size={preview['team_size']} rounds={preview['rounds']} "
        f"estimated_total_usd={preview['estimated_total_usd']}",
        file=sys.stderr,
    )
    sleep_sec = sleep_override if sleep_override is not None else DEFAULT_PREVIEW_SLEEP_SEC
    if sleep_sec <= 0:
        return
    if not sys.stdin.isatty():
        return
    print(f"team_synthesize: sleeping {sleep_sec}s — Ctrl-C to abort", file=sys.stderr)
    try:
        import time

        time.sleep(sleep_sec)
    except KeyboardInterrupt:
        print("team_synthesize: aborted by user", file=sys.stderr)
        raise SystemExit(2)


def cmd_prepare(args: argparse.Namespace) -> int:
    target = args.target
    slug = args.slug or _slug_from_target(target)
    transcript_dir = Path(args.transcript_dir)
    transcript_dir.mkdir(parents=True, exist_ok=True)
    final_synthesis = Path(args.output)
    final_synthesis.parent.mkdir(parents=True, exist_ok=True)

    specs = _load_specs(args.specs_glob)
    cluster_result = cluster_specs(
        specs, k=args.k, threshold=args.threshold, seed=args.seed, min_size=args.min_size
    )

    if cluster_result["status"] == "divergent_clusters_too_close":
        envelope = {
            "status": "fallback",
            "fallback_reason": "divergent_clusters",
            "detail": cluster_result["reason"],
            "pairwise_centroid_distances": cluster_result["pairwise_centroid_distances"],
        }
        print(json.dumps(envelope, indent=2))
        return 1

    if cluster_result["status"] in ("empty", "insufficient_specs"):
        envelope = {
            "status": "fallback",
            "fallback_reason": "runtime_failure",
            "detail": f"cluster step returned {cluster_result['status']}: {cluster_result.get('reason', '')}",
        }
        print(json.dumps(envelope, indent=2))
        return 1

    debater_count = cluster_result["k"]
    team_size = 2 + debater_count + 1  # author + N debaters + questioner

    # Cost preview
    preview = _cost_preview(team_size, args.rounds, args.per_session_cost_usd)
    sleep_override = args.preview_sleep_override
    if sleep_override is None and os.environ.get("INTERFLUX_TEAMS_PREVIEW_SLEEP", "").isdigit():
        sleep_override = int(os.environ["INTERFLUX_TEAMS_PREVIEW_SLEEP"])
    _maybe_show_cost_preview(preview, sleep_override)

    # Build orchestrator-lead spawn prompt
    prompt_text = _build_orchestrator_prompt(
        target=target,
        slug=slug,
        cluster_result=cluster_result,
        rounds=args.rounds,
        transcript_dir=transcript_dir,
        final_synthesis_path=final_synthesis,
    )

    # Persist prompt for the slash command to dispatch
    prompt_dir = transcript_dir
    prompt_path = prompt_dir / "orchestrator-spawn-prompt.md"
    prompt_path.write_text(prompt_text)

    envelope = {
        "status": "ready",
        "slug": slug,
        "target": target,
        "team_size": team_size,
        "debater_count": debater_count,
        "cluster_status": cluster_result["status"],
        "pairwise_centroid_distances": cluster_result["pairwise_centroid_distances"],
        "cluster_sizes": cluster_result["sizes"],
        "transcript_dir": str(transcript_dir),
        "transcript_path": str(transcript_dir / "transcript.md"),
        "orchestrator_spawn_prompt_path": str(prompt_path),
        "final_synthesis_path": str(final_synthesis),
        "cost_preview": preview,
        "rounds": args.rounds,
    }
    print(json.dumps(envelope, indent=2))
    return 0


def _read_team_config(team_name: str | None) -> dict[str, Any] | None:
    """Best-effort read of ~/.claude/teams/{team_name}/config.json. Returns None if absent.

    The agent-teams docs (https://code.claude.com/docs/en/agent-teams) describe this path
    and a `members` array. The exact field name for member session IDs is not specified
    verbatim in docs (the docs say "agent ID"); we accept either `agent_id` or `session_id`
    or `id` to be robust.
    """
    if not team_name:
        return None
    candidate = Path.home() / ".claude" / "teams" / team_name / "config.json"
    if not candidate.exists():
        return None
    try:
        return json.loads(candidate.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _extract_member_session_ids(team_config: dict[str, Any]) -> list[str]:
    members = team_config.get("members") or []
    out: list[str] = []
    for m in members:
        if not isinstance(m, dict):
            continue
        for key in ("session_id", "agent_id", "id"):
            v = m.get(key)
            if isinstance(v, str) and v:
                out.append(v)
                break
    return out


def _capture_cost(session_ids: list[str], cost_capture_script: Path) -> dict[str, Any]:
    """Invoke cost_capture.sh with newline-separated session IDs on stdin. Returns parsed JSON."""
    if not session_ids:
        return {"status": "incomplete", "reason": "no session ids available", "total_usd": None}
    if not cost_capture_script.exists():
        return {"status": "incomplete", "reason": f"cost_capture.sh not at {cost_capture_script}", "total_usd": None}
    try:
        result = subprocess.run(
            ["bash", str(cost_capture_script)],
            input="\n".join(session_ids) + "\n",
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return {
                "status": "incomplete",
                "reason": f"cost_capture exited {result.returncode}: {result.stderr.strip()[:200]}",
                "total_usd": None,
            }
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        return {"status": "incomplete", "reason": f"cost_capture error: {e}", "total_usd": None}


def _validate_synthesis(content: str) -> dict[str, Any]:
    """Verify the author wrote ≥3 isomorphism sections + an Unresolved Tensions section."""
    isom_count = sum(
        1
        for line in content.splitlines()
        if line.strip().lower().startswith("## cross-domain isomorphism")
        or line.strip().lower().startswith("# cross-domain isomorphism")
    )
    has_unresolved = any(
        line.strip().lower().startswith("## unresolved tensions")
        or line.strip().lower().startswith("# unresolved tensions")
        for line in content.splitlines()
    )
    issues = []
    if isom_count < 3:
        issues.append(f"expected ≥3 cross-domain isomorphism sections, found {isom_count}")
    if not has_unresolved:
        issues.append("missing required '## Unresolved Tensions' section")
    return {
        "isomorphism_section_count": isom_count,
        "has_unresolved_tensions": has_unresolved,
        "passed": not issues,
        "issues": issues,
    }


def _audit_blind_r1(transcript_text: str) -> dict[str, Any]:
    """Detect blind-R1 contamination: in Round 1, debaters should ONLY message the lead.

    Looks for transcript lines like `[ts] debater-cluster-N → debater-cluster-M` during
    Round 1. Returns a summary with violations (if any).

    Round detection is anchored to control-line structure: the orchestrator-lead's spawn
    prompt instructs it to send messages with explicit "Round 1: begin", "Round 1.5: open",
    "Round 2: begin" cues from the LEAD. We identify round transitions only on lines where
    the LEAD sends a control message containing the round marker — body lines from any
    other sender that happen to mention "round 2" do not flip the state.
    """
    import re

    # A control line looks like: `[ts] lead → recipient: Round X: ...` (case-insensitive).
    lead_control = re.compile(r"^\s*\[[^\]]+\]\s*lead\s*[→\->]+\s*[^:]+:\s*Round\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
    violations: list[str] = []
    in_round_1 = False
    for line in transcript_text.splitlines():
        m = lead_control.match(line)
        if m:
            try:
                round_num = float(m.group(1))
            except ValueError:
                continue
            in_round_1 = round_num == 1.0  # 1.5 and 2.0 both flip OFF
            continue
        if in_round_1 and "debater-cluster-" in line and " → debater-cluster-" in line:
            violations.append(line.strip())
    return {"violations": violations, "passed": not violations}


def cmd_finalize(args: argparse.Namespace) -> int:
    transcript_dir = Path(args.transcript_dir)
    transcript_path = transcript_dir / "transcript.md"
    final_synthesis = Path(args.output)
    if not transcript_path.exists():
        print(
            json.dumps({"status": "fallback", "fallback_reason": "runtime_failure", "detail": f"transcript not at {transcript_path}"}, indent=2)
        )
        return 1
    if not final_synthesis.exists():
        print(
            json.dumps({"status": "fallback", "fallback_reason": "runtime_failure", "detail": f"author did not write {final_synthesis}"}, indent=2)
        )
        return 1

    transcript_text = transcript_path.read_text()
    synthesis_body = final_synthesis.read_text()

    # Strip any pre-existing frontmatter so we can rewrite cleanly
    if synthesis_body.startswith("---\n"):
        end = synthesis_body.find("\n---\n", 4)
        if end != -1:
            synthesis_body = synthesis_body[end + 5 :]

    quality = _validate_synthesis(synthesis_body)
    blind_r1 = _audit_blind_r1(transcript_text)

    # Cost capture
    cost_capture_script = SCRIPT_DIR / "cost_capture.sh"
    team_config = _read_team_config(args.team_name)
    member_ids = _extract_member_session_ids(team_config) if team_config else []
    cost = _capture_cost(member_ids, cost_capture_script)

    # Build frontmatter
    today = _dt.date.today().isoformat()
    fm: dict[str, Any] = {
        "artifact_type": "brainstorm",
        "bead": args.bead or "none",
        "method": "flux-explore",
        "target": args.target,
        "rounds": args.rounds,
        "total_agents": args.total_agents,
        "date": today,
        "teams_used": True,
        "synthesis_quality_check": "pass" if quality["passed"] else "fail",
        "transcript": str(transcript_path.relative_to(Path.cwd())) if transcript_path.is_relative_to(Path.cwd()) else str(transcript_path),
    }
    if not blind_r1["passed"]:
        fm["synthesis_quality_check"] = "fail"
        fm["blind_r1_contamination"] = len(blind_r1["violations"])
    if cost["status"] == "incomplete":
        fm["synthesis_cost_usd"] = "incomplete"
        fm["cost_attribution_gap"] = cost["reason"]
    else:
        # Defensive: cost_capture.sh always sets a numeric total on success, but a malformed
        # JSON payload that still parses could leave total_usd None. Treat that as incomplete
        # rather than emitting `synthesis_cost_usd: null` which violates the frontmatter contract.
        total = cost.get("total_usd")
        if total is None:
            fm["synthesis_cost_usd"] = "incomplete"
            fm["cost_attribution_gap"] = "cost_capture returned status=complete but total_usd missing"
        else:
            fm["synthesis_cost_usd"] = total
    if not quality["passed"]:
        fm["synthesis_quality_issues"] = quality["issues"]

    # Render YAML manually (small and predictable; avoids PyYAML dep)
    fm_lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, bool):
            fm_lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, list):
            fm_lines.append(f"{k}:")
            for item in v:
                fm_lines.append(f"  - {json.dumps(item)}")
        elif v is None:
            fm_lines.append(f"{k}: null")
        elif isinstance(v, (int, float)):
            fm_lines.append(f"{k}: {v}")
        else:
            fm_lines.append(f"{k}: {json.dumps(str(v))}")
    fm_lines.append("---")
    fm_lines.append("")

    final_synthesis.write_text("\n".join(fm_lines) + synthesis_body)

    envelope = {
        "status": "complete",
        "synthesis_path": str(final_synthesis),
        "transcript_path": str(transcript_path),
        "synthesis_quality_check": fm["synthesis_quality_check"],
        "blind_r1_audit": blind_r1,
        "cost": cost,
        "total_member_sessions": len(member_ids),
    }
    print(json.dumps(envelope, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Orchestrate flux-explore --teams synthesis.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prepare", help="Cluster + build orchestrator spawn prompt + cost preview")
    p_prep.add_argument("--target", required=True)
    p_prep.add_argument("--slug", default=None, help="Override slug (default: derived from target)")
    p_prep.add_argument("--specs-glob", required=True)
    p_prep.add_argument("--output", required=True, help="Final synthesis output path (written by finalize)")
    p_prep.add_argument("--transcript-dir", required=True)
    p_prep.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p_prep.add_argument("--k", type=int, default=3)
    p_prep.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    p_prep.add_argument("--min-size", type=int, default=3)
    p_prep.add_argument("--seed", type=int, default=None)
    p_prep.add_argument("--per-session-cost-usd", type=float, default=DEFAULT_PER_SESSION_COST_USD)
    p_prep.add_argument(
        "--preview-sleep-override",
        type=int,
        default=None,
        help="Override sleep seconds (default: 3 if TTY, 0 otherwise; env INTERFLUX_TEAMS_PREVIEW_SLEEP also honored)",
    )
    p_prep.set_defaults(func=cmd_prepare)

    p_fin = sub.add_parser("finalize", help="Read transcript + capture cost + write synthesis frontmatter")
    p_fin.add_argument("--target", required=True)
    p_fin.add_argument("--bead", default=None)
    p_fin.add_argument("--output", required=True)
    p_fin.add_argument("--transcript-dir", required=True)
    p_fin.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    p_fin.add_argument("--total-agents", type=int, default=0)
    p_fin.add_argument(
        "--team-name",
        default=None,
        help="Team name (matches ~/.claude/teams/{team_name}/config.json); used for cost capture",
    )
    p_fin.set_defaults(func=cmd_finalize)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
