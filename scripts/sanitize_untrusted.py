#!/usr/bin/env python3
"""Sanitize untrusted text before embedding it in a system prompt.

Untrusted channels today:
  1. Peer findings passed into reaction-round prompts (reaction.md Step 2.5.3)
  2. LLM-generated agent specs rendered into agent system prompts
     (generate-agents.py render_agent: persona, decision_lens, review_areas,
     task_context, anti_overlap)
  3. Knowledge context pulled into synthesize.md
  4. Domain-profile overlays

A bypass in any one channel amplifies across all four — see Phase 2.2 S1
(Unicode fullwidth bypass), Phase 1 security F2 (LLM output written verbatim
into agent system prompts), blueprint §3 B3.

This module is the B3 reference implementation — minimal but conservative.
Epic C3 extends it with hypothesis fuzz tests, homoglyph detection, and a
TrustedContent NewType for mypy enforcement.
"""
from __future__ import annotations

import html
import re
import unicodedata

# XML/HTML-style tags that mimic system prompt boundaries. Stripped outright.
_SYSTEM_TAG_PATTERN = re.compile(
    r"</?(?:system|system-reminder|human|assistant|user|tool_use|function_calls|"
    r"function_call|instruction|instructions|prompt|role)(?:\s+[^>]*)?/?>",
    re.IGNORECASE,
)

# Instruction-override patterns. Match must be anchored to line start (after
# optional whitespace) to avoid false positives inside legitimate prose like
# "we should never ignore the schema".
_OVERRIDE_LINE_PATTERN = re.compile(
    r"(?im)^\s*(?:#+\s*)?"
    r"(?:ignore|override|forget|disregard|skip|bypass|reset)\b"
    r"[^\n]*\b(?:instructions?|rules?|prompt|system|above|previous|prior|all)\b[^\n]*$"
)

# "NEW INSTRUCTIONS:" style prefix (case-insensitive).
_NEW_INSTRUCTIONS_PATTERN = re.compile(
    r"(?im)^\s*(?:#+\s*)?(?:new\s+instructions?|updated\s+instructions?|"
    r"real\s+instructions?|actual\s+task)\s*:.*$"
)

# Fenced code blocks in any language. Stripped outright — reviewers should
# cite file:line rather than embed executable code in findings.
_CODE_FENCE_PATTERN = re.compile(r"```[^\n]*\n.*?\n```", re.DOTALL)

# Long base64-looking runs: 60+ consecutive base64 chars with at least one +/=
# or mixed case+digits. Pure-letter or pure-digit runs of that length exist in
# legitimate text (e.g. reflowed paragraphs, identifier walls) and shouldn't be
# stripped at this confidence level.
_BASE64_RUN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9+/=])"
    r"(?=[A-Za-z0-9+/]{60,}={0,2}(?![A-Za-z0-9+/=]))"
    r"(?=(?:[A-Za-z0-9+/]*[+/])|"
    r"(?:[A-Za-z0-9+/]*[A-Z][A-Za-z0-9+/]*[a-z])|"
    r"(?:[A-Za-z0-9+/]*[a-z][A-Za-z0-9+/]*[A-Z])|"
    r"(?:[A-Za-z0-9+/]*[A-Za-z][A-Za-z0-9+/]*[0-9])|"
    r"(?:[A-Za-z0-9+/]*[0-9][A-Za-z0-9+/]*[A-Za-z]))"
    r"[A-Za-z0-9+/]{60,}={0,2}"
)

_DEFAULT_MAX_LEN = 2000


def sanitize(text: str | None, max_len: int = _DEFAULT_MAX_LEN) -> str:
    """Clean untrusted text for safe embedding in a system prompt.

    Steps:
      1. NFKC normalize — collapses fullwidth/compatibility forms to ASCII
         equivalents. Closes the Phase 2.2 S1 Unicode-fullwidth bypass.
      2. HTML entity decode once, then strip. Re-encoded payloads that
         survive a single decode pass are dropped by step 3.
      3. Remove system-boundary XML tags.
      4. Blank out instruction-override lines.
      5. Strip fenced code blocks (any language).
      6. Strip long base64-looking runs (heuristic).
      7. Collapse control characters except newline/tab.
      8. Truncate to max_len with explicit marker.

    Returns the empty string for None or non-string input. Callers should
    treat the returned text as trusted for prompt embedding; anything that
    would bypass these filters should be added here rather than worked
    around at the call site.
    """
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)

    text = unicodedata.normalize("NFKC", text)
    text = html.unescape(text)

    text = _SYSTEM_TAG_PATTERN.sub("", text)
    text = _OVERRIDE_LINE_PATTERN.sub("", text)
    text = _NEW_INSTRUCTIONS_PATTERN.sub("", text)
    text = _CODE_FENCE_PATTERN.sub("[code block stripped]", text)
    text = _BASE64_RUN_PATTERN.sub("[base64-like run stripped]", text)

    cleaned_chars = []
    for ch in text:
        cat = unicodedata.category(ch)
        # Drop control characters except tab/newline. "Cf" (format) includes
        # zero-width joiners and RLO which can hide instruction-override text.
        if cat in ("Cc", "Cf") and ch not in ("\n", "\t"):
            continue
        cleaned_chars.append(ch)
    text = "".join(cleaned_chars)

    # Collapse runs of blank lines left behind by stripping.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if max_len > 0 and len(text) > max_len:
        omitted = len(text) - max_len
        text = f"{text[:max_len]}\n[truncated — {omitted} chars omitted]"

    return text


def sanitize_list(items, max_item_len: int = _DEFAULT_MAX_LEN) -> list[str]:
    """Sanitize each string in a list; drop entries that collapse to empty."""
    out: list[str] = []
    if not items:
        return out
    if isinstance(items, str):
        items = [items]
    for item in items:
        cleaned = sanitize(item, max_item_len)
        if cleaned:
            out.append(cleaned)
    return out


if __name__ == "__main__":
    import sys

    raw = sys.stdin.read()
    max_len = int(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_MAX_LEN
    sys.stdout.write(sanitize(raw, max_len))
