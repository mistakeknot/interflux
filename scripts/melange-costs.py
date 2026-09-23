#!/usr/bin/env python3
"""Capture flux-melange subagent usage into per-run cost summaries.

The Workflow API returns only an agent's structured payload. Claude Code's
completed subagent transcript is therefore the authoritative usage source.
`SubagentStop` invokes this script with its hook JSON on stdin; only transcripts
whose first user message starts with a flux-melange cost marker are recorded.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Any


MARKER = re.compile(
    r"^\s*<flux-melange-cost>(.*?)</flux-melange-cost>", re.DOTALL
)


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        item.get("text", "")
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    )


def _read_transcript(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    marker = None
    model = None
    usage = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
    }
    first_user_seen = False

    with path.open(encoding="utf-8") as transcript:
        for line in transcript:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = row.get("message")
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            if role == "user" and not first_user_seen:
                first_user_seen = True
                match = MARKER.match(_message_text(message.get("content")))
                if match:
                    try:
                        candidate = json.loads(match.group(1))
                    except json.JSONDecodeError:
                        candidate = None
                    if isinstance(candidate, dict):
                        marker = candidate
            if role != "assistant":
                continue
            if message.get("model"):
                model = str(message["model"])
            turn_usage = message.get("usage")
            if not isinstance(turn_usage, dict):
                continue
            for key in usage:
                value = turn_usage.get(key)
                if isinstance(value, (int, float)):
                    usage[key] += int(value)

    usage["model"] = model
    return marker, usage


def _atomic_write(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    rounds: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for event in events:
        key = event["round"]
        aggregate = rounds.setdefault(
            key,
            {"round": key, "agent_count": 0, "tokens_in": 0, "tokens_out": 0},
        )
        aggregate["agent_count"] += 1
        if event["tokens_in"] is None or event["tokens_out"] is None:
            aggregate["unknown_usage_count"] = (
                aggregate.get("unknown_usage_count", 0) + 1
            )
        else:
            aggregate["tokens_in"] += event["tokens_in"]
            aggregate["tokens_out"] += event["tokens_out"]
    summary = {
        "schema_version": 1,
        "agents": events,
        "rounds": list(rounds.values()),
        "totals": {
            "agent_count": len(events),
            "tokens_in": sum(event["tokens_in"] or 0 for event in events),
            "tokens_out": sum(event["tokens_out"] or 0 for event in events),
        },
    }
    unknown = sum(
        event["tokens_in"] is None or event["tokens_out"] is None
        for event in events
    )
    if unknown:
        summary["totals"]["unknown_usage_count"] = unknown
    return summary


def _markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Flux-melange cost summary",
        "",
        "## Agents",
        "",
        "| Round | Agent | Runtime | Backend | Model | Quota source | Tokens in | Tokens out |",
        "|---|---|---|---|---|---|---:|---:|",
    ]
    for event in summary["agents"]:
        rendered = {
            **event,
            "tokens_in": (
                "unknown" if event["tokens_in"] is None else event["tokens_in"]
            ),
            "tokens_out": (
                "unknown" if event["tokens_out"] is None else event["tokens_out"]
            ),
        }
        lines.append(
            "| {round} | {agent} | {runtime} | {backend} | {model} | "
            "{quota_source} | {tokens_in} | {tokens_out} |".format(**rendered)
        )
    lines.extend(
        [
            "",
            "## Rounds",
            "",
            "| Round | Agents | Tokens in | Tokens out |",
            "|---|---:|---:|---:|",
        ]
    )
    for aggregate in summary["rounds"]:
        lines.append(
            "| {round} | {agent_count} | {tokens_in} | {tokens_out} |".format(
                **aggregate
            )
        )
    totals = summary["totals"]
    lines.extend(
        [
            "",
            f"**Total:** {totals['agent_count']} agents, "
            f"{totals['tokens_in']} tokens in, {totals['tokens_out']} tokens out.",
            "",
        ]
    )
    return "\n".join(lines)


def _record(
    marker: dict[str, Any],
    usage: dict[str, Any],
    agent_id: str | None,
    parent_session_id: str | None,
) -> None:
    required = ("output_dir", "runtime", "agent", "round", "backend", "model")
    if any(not marker.get(key) for key in required):
        return

    output_dir = Path(str(marker["output_dir"])).expanduser().resolve()
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if project_dir and not output_dir.is_relative_to(Path(project_dir).resolve()):
        return
    output_dir.mkdir(parents=True, exist_ok=True)

    event = {
        "agent": str(marker["agent"]),
        "round": str(marker["round"]),
        "runtime": str(marker["runtime"]),
        "backend": str(marker["backend"]),
        "model": str(usage.get("model") or marker["model"]),
        "quota_source": str(marker.get("quota_source") or "unknown"),
        "tokens_in": (
            usage["input_tokens"]
            + usage["cache_creation_input_tokens"]
            + usage["cache_read_input_tokens"]
        ),
        "tokens_out": usage["output_tokens"],
        "input_tokens": usage["input_tokens"],
        "cache_creation_input_tokens": usage["cache_creation_input_tokens"],
        "cache_read_input_tokens": usage["cache_read_input_tokens"],
        "agent_id": agent_id or "unknown",
        "parent_session_id": parent_session_id or "unknown",
    }
    new_events = [event]
    if marker.get("external_backend"):
        new_events.append(
            {
                "agent": str(marker["agent"]),
                "round": str(marker["round"]),
                "runtime": str(marker["runtime"]),
                "backend": str(marker["external_backend"]),
                "model": str(marker.get("external_model") or "unknown"),
                "quota_source": str(
                    marker.get("external_quota_source") or "unknown"
                ),
                "tokens_in": None,
                "tokens_out": None,
                "input_tokens": None,
                "cache_creation_input_tokens": None,
                "cache_read_input_tokens": None,
                "agent_id": agent_id or "unknown",
                "parent_session_id": parent_session_id or "unknown",
                "usage_status": "unknown",
            }
        )

    events_path = output_dir / "cost-events.jsonl"
    lock_path = output_dir / ".cost-summary.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        events: list[dict[str, Any]] = []
        if events_path.exists():
            for line in events_path.read_text(encoding="utf-8").splitlines():
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(existing, dict):
                    events.append(existing)
        identities = {
            (
                item["agent_id"],
                item["agent"],
                item["round"],
                item["backend"],
                item["model"],
            )
            for item in new_events
        }
        events = [
            existing
            for existing in events
            if (
                existing.get("agent_id"),
                existing.get("agent"),
                existing.get("round"),
                existing.get("backend"),
                existing.get("model"),
            )
            not in identities
        ]
        events.extend(new_events)
        _atomic_write(
            events_path,
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in events),
        )
        summary = _summarize(events)
        _atomic_write(
            output_dir / "cost-summary.json",
            json.dumps(summary, indent=2, sort_keys=False) + "\n",
        )
        _atomic_write(output_dir / "cost-summary.md", _markdown(summary))


def hook() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if payload.get("hook_event_name") != "SubagentStop":
        return 0
    transcript_value = payload.get("agent_transcript_path") or payload.get(
        "transcript_path"
    )
    if not transcript_value:
        return 0
    transcript = Path(str(transcript_value)).expanduser()
    try:
        marker, usage = _read_transcript(transcript)
    except OSError:
        return 0
    if marker is not None:
        _record(
            marker,
            usage,
            payload.get("agent_id") or payload.get("session_id"),
            payload.get("session_id"),
        )
    return 0


def main() -> int:
    if sys.argv[1:] != ["hook"]:
        print("usage: melange-costs.py hook", file=sys.stderr)
        return 2
    return hook()


if __name__ == "__main__":
    raise SystemExit(main())
