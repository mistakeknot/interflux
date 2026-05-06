"""Atomic mutate helpers for model-registry.yaml.

Five scripts (fluxbench-{challenger,qualify,drift,sync}.sh + discover-merge.sh)
historically copy-pasted the same flock→cp→python3-heredoc→validate→mv dance with
diverging error handling. This module is the single Python source of truth.

Public API:
    load_registry(path) -> dict
    normalize_models(reg) -> dict  (in-place, returns reg)
    get_model(reg, slug) -> dict | None
    set_model_field(reg, slug, key, value) -> bool  (True if mutation applied)
    validate_and_dump(reg, path) -> None

CLI (used by lib-registry.sh registry_atomic_mutate):
    python3 -m lib_registry set-field           <path> <slug> <key> <value-json>
    python3 -m lib_registry set-field-if-absent <path> <slug> <key> <value-json>
    python3 -m lib_registry merge-fields        <path> <slug> <fields-json>  # shallow merge, creates slug if absent
    python3 -m lib_registry promote             <path> <slug>
    python3 -m lib_registry validate            <path>

Exit codes:
    0  success
    2  registry path missing or unparseable
    3  slug not found (set-field / promote)
    4  invalid input (bad JSON value, missing arg)
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import yaml


def load_registry(path: str) -> dict[str, Any]:
    """Load a registry YAML file. Empty/missing 'models' is normalized to {}."""
    with open(path) as f:
        reg = yaml.safe_load(f) or {}
    if not isinstance(reg, dict):
        raise ValueError(f"registry root must be a mapping, got {type(reg).__name__}")
    normalize_models(reg)
    return reg


def normalize_models(reg: dict[str, Any]) -> dict[str, Any]:
    """Coerce reg['models'] to a dict keyed by slug.

    Accepts the historical list-of-dicts format (each item carrying 'model_id') and
    converts it to the canonical dict format. Idempotent on already-dict input.
    Mutates reg in place; returns reg.
    """
    models = reg.get("models")
    if models is None:
        reg["models"] = {}
    elif isinstance(models, list):
        coerced: dict[str, Any] = {}
        for item in models:
            if not isinstance(item, dict):
                continue
            slug = item.get("model_id") or item.get("slug")
            if slug:
                # Don't carry model_id forward — slug is the dict key now
                coerced[slug] = {k: v for k, v in item.items() if k != "model_id"}
        reg["models"] = coerced
    elif not isinstance(models, dict):
        raise ValueError(
            f"reg['models'] must be a dict or list, got {type(models).__name__}"
        )
    return reg


def get_model(reg: dict[str, Any], slug: str) -> dict[str, Any] | None:
    """Look up a model by slug in either dict-shaped or list-shaped registries."""
    models = reg.get("models")
    if isinstance(models, dict):
        return models.get(slug)
    if isinstance(models, list):
        for item in models:
            if isinstance(item, dict) and item.get("model_id") == slug:
                return item
    return None


def set_model_field(reg: dict[str, Any], slug: str, key: str, value: Any) -> bool:
    """Set a single field on a model. Returns True if the model was found."""
    model = get_model(reg, slug)
    if model is None:
        return False
    model[key] = value
    return True


def set_model_field_if_absent(reg: dict[str, Any], slug: str, key: str, value: Any) -> bool:
    """Set a field only if currently absent or None. Returns True if the model exists.

    Encodes the "preserve existing" semantic used for qualified_baseline in
    fluxbench-qualify — once set, the baseline must not be overwritten by later
    qualification runs.
    """
    model = get_model(reg, slug)
    if model is None:
        return False
    if model.get(key) is None:
        model[key] = value
    return True


def merge_model_fields(reg: dict[str, Any], slug: str, fields: dict[str, Any]) -> bool:
    """Shallow-merge a fields dict into a model (replaces top-level keys).

    Creates the model entry if absent — matches the fluxbench-qualify behavior
    where _update_registry creates a fresh model dict for a slug not yet in the
    registry. Returns True always (caller can preflight with get_model if they
    want to distinguish create-vs-update).
    """
    if not isinstance(fields, dict):
        raise ValueError(f"fields must be a dict, got {type(fields).__name__}")
    normalize_models(reg)
    models = reg["models"]  # always dict after normalize
    model = models.get(slug)
    if model is None:
        model = {}
        models[slug] = model
    for k, v in fields.items():
        model[k] = v
    return True


def promote_model(reg: dict[str, Any], slug: str) -> bool:
    """Mark model as qualified, preserving qualified_via. Returns True if found.

    Encodes the v0.2.x semantic: status='qualified' and qualified_via defaults to
    'unknown' (with stderr warning) when not already set.
    """
    model = get_model(reg, slug)
    if model is None:
        return False
    model["status"] = "qualified"
    qv = model.get("qualified_via") or "unknown"
    model["qualified_via"] = qv
    if qv == "unknown":
        print(
            f"  WARNING: {slug} promoted without qualified_via — was it qualified?",
            file=sys.stderr,
        )
    return True


def validate_and_dump(reg: dict[str, Any], path: str) -> None:
    """Dump to path with the project's YAML conventions; round-trip-validate."""
    with open(path, "w") as f:
        yaml.dump(reg, f, default_flow_style=False, sort_keys=False)
    # Round-trip: reread to confirm parseability before caller does the mv swap
    with open(path) as f:
        yaml.safe_load(f)


def _cli_set_field(path: str, slug: str, key: str, value_json: str) -> int:
    try:
        value = json.loads(value_json)
    except json.JSONDecodeError as exc:
        print(f"lib_registry: invalid JSON for value: {exc}", file=sys.stderr)
        return 4
    reg = load_registry(path)
    if not set_model_field(reg, slug, key, value):
        print(f"lib_registry: slug '{slug}' not found in {path}", file=sys.stderr)
        return 3
    validate_and_dump(reg, path)
    return 0


def _cli_set_field_if_absent(path: str, slug: str, key: str, value_json: str) -> int:
    try:
        value = json.loads(value_json)
    except json.JSONDecodeError as exc:
        print(f"lib_registry: invalid JSON for value: {exc}", file=sys.stderr)
        return 4
    reg = load_registry(path)
    if not set_model_field_if_absent(reg, slug, key, value):
        print(f"lib_registry: slug '{slug}' not found in {path}", file=sys.stderr)
        return 3
    validate_and_dump(reg, path)
    return 0


def _cli_merge_fields(path: str, slug: str, fields_json: str) -> int:
    try:
        fields = json.loads(fields_json)
    except json.JSONDecodeError as exc:
        print(f"lib_registry: invalid JSON for fields: {exc}", file=sys.stderr)
        return 4
    if not isinstance(fields, dict):
        print(f"lib_registry: fields must be a JSON object", file=sys.stderr)
        return 4
    reg = load_registry(path)
    merge_model_fields(reg, slug, fields)
    validate_and_dump(reg, path)
    return 0


def _cli_promote(path: str, slug: str) -> int:
    reg = load_registry(path)
    if not promote_model(reg, slug):
        print(f"lib_registry: slug '{slug}' not found in {path}", file=sys.stderr)
        return 3
    validate_and_dump(reg, path)
    return 0


def _cli_validate(path: str) -> int:
    load_registry(path)  # raises if unparseable
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: lib_registry <set-field|promote|validate> ...", file=sys.stderr)
        return 4
    op = argv[1]
    try:
        if op == "set-field" and len(argv) == 6:
            return _cli_set_field(argv[2], argv[3], argv[4], argv[5])
        if op == "set-field-if-absent" and len(argv) == 6:
            return _cli_set_field_if_absent(argv[2], argv[3], argv[4], argv[5])
        if op == "merge-fields" and len(argv) == 5:
            return _cli_merge_fields(argv[2], argv[3], argv[4])
        if op == "promote" and len(argv) == 4:
            return _cli_promote(argv[2], argv[3])
        if op == "validate" and len(argv) == 3:
            return _cli_validate(argv[2])
    except FileNotFoundError as exc:
        print(f"lib_registry: {exc}", file=sys.stderr)
        return 2
    except (yaml.YAMLError, ValueError) as exc:
        print(f"lib_registry: parse error in {argv[2] if len(argv) > 2 else '?'}: {exc}", file=sys.stderr)
        return 2
    print(f"lib_registry: invalid invocation: {' '.join(argv[1:])}", file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main(sys.argv))
