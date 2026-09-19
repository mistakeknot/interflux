#!/usr/bin/env python3
"""Resolve Interflux reviewer profiles without duplicating routing in a shell."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "flux-melange" / "defaults.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--purpose", choices=("bulk", "validation"), required=True)
    parser.add_argument("--producer", help="producer identity as kind/model or kind:model")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    return parser.parse_args()


def parse_producer(value: str) -> tuple[str, str]:
    value = value.strip().lower()
    separator = "/" if "/" in value else ":"
    if separator not in value:
        raise ValueError("--producer must be kind/model or kind:model")
    kind, model = value.split(separator, 1)
    if not kind or not model:
        raise ValueError("--producer must include both kind and model")
    return kind, model


def model_identity(model: str, aliases: dict[str, str]) -> str:
    """Conservative family identity; unknown symbolic aliases are not evidence."""
    model = re.sub(r"\[(?:1m|200k)\]$", "", model.strip().lower())
    model = re.sub(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$", "", model)
    seen = set()
    while model in aliases:
        if model in seen:
            raise ValueError(f"cyclic model identity alias: {model}")
        seen.add(model)
        model = aliases[model]
    if not model.startswith(("gpt-", "claude-", "kimi-", "kimi/")):
        raise ValueError(f"unknown model identity: {model}; provide the resolved model ID")
    return model


BULK_PROFILE = "peers.runtimes.codex"


def resolve_bulk(config: dict) -> dict:
    """Bulk mirrors resolve from the peer table, not the reviewer profiles.

    A mirror is an independent second opinion with no producer to be separated
    from, so producer-relative routing has nothing to say about it. Reading
    `peers.runtimes` here keeps this selector and the charter's own resolution
    (flag > project yaml > plugin defaults) from answering the same question
    differently.
    """
    runtime = dict(config["peers"]["runtimes"]["codex"])
    if not runtime.get("model") or not runtime.get("invoke"):
        raise ValueError("peers.runtimes.codex must define both model and invoke")
    return {
        "purpose": "bulk",
        "producer_identity": None,
        "candidates": [{"profile": BULK_PROFILE, "kind": "codex", **runtime}],
        "excluded": [],
        "validator_relationship": None,
    }


def resolve(config: dict, purpose: str, producer: str | None) -> dict:
    if purpose == "bulk":
        return resolve_bulk(config)

    routing = config["reviewer_routing"]
    profiles = routing["profiles"]
    aliases = routing.get("model_aliases", {})

    if not producer:
        raise ValueError("--producer is required for validation routing")
    producer_kind, producer_model = parse_producer(producer)
    producer_model = model_identity(producer_model, aliases)
    # Provider aliases must not change the route selected for one model.
    producer_kind = "codex" if producer_model.startswith("gpt-") else "claude" if producer_model.startswith("claude-") else "kimi"
    validation = routing["routes"]["validation"]
    references = validation.get("producer_model", {}).get(producer_model)
    if references is None:
        references = validation.get("producer_kind", {}).get(
            producer_kind, validation["default"]
        )
    producer_identity = {"kind": producer_kind, "model": producer_model, "model_identity": producer_model, "reported": producer}

    candidates = []
    excluded = []
    for reference in references:
        profile = dict(profiles[reference])
        identity = model_identity(profile["model"], aliases)
        profile["model_identity"] = identity
        if identity == producer_identity["model_identity"]:
            excluded.append({"profile": reference, **profile, "reason": "producer_model_conflict"})
            continue
        candidates.append({"profile": reference, **profile})

    if not candidates:
        raise ValueError("routing produced no reviewer distinct from the producer model")

    return {
        "purpose": purpose,
        "producer_identity": producer_identity,
        "candidates": candidates,
        "excluded": excluded,
        "validator_relationship": "different-model",
    }


def main() -> int:
    args = parse_args()
    try:
        config = yaml.safe_load(args.config.read_text())
        payload = resolve(config, args.purpose, args.producer)
    except (KeyError, OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"select-review-route: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
