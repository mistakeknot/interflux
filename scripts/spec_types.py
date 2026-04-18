"""Shared types and spec validation for agent generation.

This module is the type-safety layer between LLM-authored agent specs and
the filesystem-written agent files. The anti_overlap incident (v0.2.58, 116
corrupted files) confirmed that the LLM-JSON → render_agent boundary needs
structural validation, not just ad-hoc normalization scattered across
generate-agents.py and flux-agent.py.

Two sources of truth it consolidates:

  1. The wrapper-dict unwrap pattern (duplicated in generate-agents.py:452-458
     and flux-agent.py:667-669) — LLMs often return specs as
     {"agents": [...]} or {"specs": [...]} instead of the bare list.

  2. Bullet-list normalization — LLMs sometimes return list-shaped fields as
     paragraph strings; iterating a string yields characters, producing
     char-exploded bullets downstream.

Blueprint §3 B2. Depends on sanitize_untrusted.py (B3) for security
boundary on LLM-authored text.
"""
from __future__ import annotations

from typing import Any, TypedDict


class SeverityExample(TypedDict, total=False):
    """A single severity-calibration scenario rendered into the agent's
    ## Severity Calibration section."""

    severity: str  # e.g. "P0", "P1"
    scenario: str
    condition: str


class AgentSpec(TypedDict, total=False):
    """An LLM-authored agent specification.

    All fields are optional at the type level; validate_agent_spec() enforces
    which are required at runtime. total=False lets the dict match LLM output
    that omits some keys rather than forcing a .get()-heavy dance.
    """

    name: str
    focus: str
    persona: str
    decision_lens: str
    task_context: str
    review_areas: list[str]
    anti_overlap: list[str]
    success_hints: list[str]
    severity_examples: list[SeverityExample]
    source_domain: str
    flux_gen_version: int


_REQUIRED_FIELDS = ("name", "focus")
_STRING_FIELDS = ("name", "focus", "persona", "decision_lens", "task_context", "source_domain")
_LIST_FIELDS = ("review_areas", "anti_overlap", "success_hints")
_ALLOWED_SEVERITIES = frozenset({"P0", "P1", "P2", "P3"})


def _unwrap_spec_list(specs: Any) -> tuple[list[Any], str | None]:
    """Unwrap common LLM wrapper patterns to a bare list.

    Accepts:
      - list[Any] — returned unchanged
      - dict with exactly one list-valued entry — that list is extracted
      - anything else — returns ([], reason) so the caller can error cleanly

    Returns (specs_list, note). `note` is None on clean input, otherwise a
    short human-readable explanation suitable for logging.
    """
    if isinstance(specs, list):
        return specs, None

    if isinstance(specs, dict):
        candidates = [v for v in specs.values() if isinstance(v, list)]
        if len(candidates) == 1:
            keys = list(specs.keys())
            return candidates[0], f"unwrapped dict with key(s) {keys} → {len(candidates[0])} specs"
        if len(candidates) == 0:
            return [], f"dict has no list-valued entries (keys: {list(specs.keys())})"
        return [], f"dict has {len(candidates)} list-valued entries — ambiguous (keys: {list(specs.keys())})"

    return [], f"specs root is {type(specs).__name__}, not a list or dict"


def _normalize_bullet_list(value: Any) -> list[str]:
    """Normalize a bullet-list field to a list of non-empty strings.

    LLMs sometimes return list-shaped fields as strings (paragraph,
    semicolon-joined, or newline-joined). Iterating a string yields
    characters, which produces character-exploded bullet output. This
    helper handles all three shapes plus already-correct lists.
    """
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = value.replace(";", "\n").split("\n")
        return [p.strip() for p in parts if p.strip()]
    return [str(value).strip()]


def _normalize_severity_examples(value: Any) -> list[SeverityExample]:
    """Normalize severity_examples to a list of well-formed dicts.

    Drops entries that lack severity or scenario, normalizes severity to
    uppercase-stripped form, and discards entries whose severity is not
    in {P0, P1, P2, P3}. Non-dict items are skipped.
    """
    out: list[SeverityExample] = []
    if not isinstance(value, list):
        return out

    for item in value:
        if not isinstance(item, dict):
            continue
        sev = str(item.get("severity", "")).strip().upper()
        scenario = str(item.get("scenario", "")).strip()
        condition = str(item.get("condition", "")).strip()
        if sev not in _ALLOWED_SEVERITIES or not scenario:
            continue
        example: SeverityExample = {"severity": sev, "scenario": scenario}
        if condition:
            example["condition"] = condition
        out.append(example)
    return out


def _normalize_domains(value: Any) -> list[str]:
    """Normalize a domains field that may arrive as list, comma/semicolon
    string, or scalar. LLMs frequently emit 'security, auth' as a single
    string; wrapping it as [domains] produced a single "security, auth"
    bucket downstream."""
    if not value:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            for part in str(item).replace(";", ",").split(","):
                token = part.strip()
                if token:
                    out.append(token)
        return out
    if isinstance(value, str):
        return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    return [str(value).strip()]


def validate_agent_spec(spec: Any, name_pattern: str | None = None) -> tuple[bool, list[str], AgentSpec]:
    """Validate and normalize an agent spec.

    Returns (is_valid, errors, normalized). Errors are per-field and do not
    abort — the normalizer does what it can so callers get a best-effort
    spec alongside the error list for reporting.

    Does NOT sanitize untrusted content — that is sanitize_untrusted.py's
    responsibility, applied at render_agent() time. This layer only enforces
    structure and type.
    """
    errors: list[str] = []
    normalized: AgentSpec = {}

    if not isinstance(spec, dict):
        return False, [f"spec is {type(spec).__name__}, expected dict"], normalized

    for field in _REQUIRED_FIELDS:
        raw = spec.get(field)
        if not isinstance(raw, str) or not raw.strip():
            errors.append(f"missing or empty required field '{field}'")

    import re as _re

    name = spec.get("name", "")
    if isinstance(name, str) and name:
        pattern = _re.compile(name_pattern) if name_pattern else _re.compile(r"^fd-[a-z0-9]+(?:-[a-z0-9]+)*$")
        if not pattern.fullmatch(name):
            errors.append(
                f"name '{name}' does not match {pattern.pattern} "
                "(required to prevent filesystem path traversal)"
            )
        else:
            normalized["name"] = name

    for field in _STRING_FIELDS:
        raw = spec.get(field)
        if raw is None:
            continue
        if not isinstance(raw, str):
            errors.append(f"field '{field}' is {type(raw).__name__}, expected str — coercing")
            raw = str(raw)
        normalized[field] = raw  # type: ignore[literal-required]

    for field in _LIST_FIELDS:
        if field not in spec:
            continue
        normalized[field] = _normalize_bullet_list(spec[field])  # type: ignore[literal-required]

    if "severity_examples" in spec:
        normalized["severity_examples"] = _normalize_severity_examples(spec["severity_examples"])

    flux_gen_version = spec.get("flux_gen_version")
    if flux_gen_version is not None:
        try:
            normalized["flux_gen_version"] = int(flux_gen_version)
        except (TypeError, ValueError):
            errors.append(f"flux_gen_version '{flux_gen_version!r}' is not coercible to int")

    is_valid = not errors
    return is_valid, errors, normalized
