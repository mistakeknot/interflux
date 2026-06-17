#!/usr/bin/env python3
"""Sanitize untrusted text before embedding it in a system prompt.

This module is the **single enforced chokepoint** for untrusted content. Every
channel that injects attacker-influenceable text into a downstream system prompt
MUST route through one of the entry points here — never embed raw content at the
call site, and never re-implement the filter set.

Untrusted channels (sinks) routed through this chokepoint:
  1. Peer findings passed into reaction-round prompts
     (reaction.md Step 2.5.3 — `sanitize` / CLI)
  2. LLM-generated agent specs rendered into agent system prompts
     (generate-agents.py render_agent: persona, decision_lens, review_areas,
     task_context, anti_overlap — `sanitize` / `sanitize_list`)
  3. Knowledge context pulled into agent prompts and synthesize.md
     (launch.md Step 2.1 — `sanitize` / CLI)
  4. Domain-profile overlays + interspect overlays
     (launch.md Step 2.1a / 2.1d — `sanitize` / CLI)
  5. Research context injected between stages
     (launch.md Step 2.2a — `sanitize` / CLI)

A bypass in any one channel amplifies across all of them — see Phase 2.2 S1
(Unicode fullwidth bypass), Phase 1 security F2 (LLM output written verbatim
into agent system prompts), blueprint §3 B3, and finding C-6 (sanitization was
advisory-only and bypassable via uncovered sinks).

The contract is enforced two ways:
  - At the Python boundary: `sanitize()` returns a `TrustedContent` value. The
    `TrustedContent` wrapper is the *only* in-process marker that a string has
    passed the filter, so a downstream prompt builder can assert on the type.
  - At the shell boundary: the CLI is the mandatory pipe and stamps a provenance
    comment so a skipped sanitization step is visible in the rendered prompt.
"""
from __future__ import annotations

import html
import re
import unicodedata
from typing import TextIO

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


class TrustedContent(str):
    """A string that has passed through the sanitization chokepoint.

    This is a thin ``str`` subclass — it behaves exactly like the cleaned text
    everywhere a string is expected, so existing callers that already treat the
    return value of ``sanitize()`` as a plain string keep working unchanged.

    Its purpose is to give downstream prompt builders an in-process marker they
    can *assert* on: a string is safe to embed in a system prompt iff
    ``isinstance(value, TrustedContent)``. Constructing one directly is the only
    way to bypass the filter, which makes any such bypass grep-able and explicit
    (search for ``TrustedContent(`` outside this module).

    Use ``assert_trusted(x)`` at a prompt-assembly site to fail loudly if a raw
    string ever reaches it.
    """

    __slots__ = ()


def assert_trusted(value: object) -> "TrustedContent":
    """Enforce the trust boundary at a prompt-assembly site.

    Raises ``TypeError`` if ``value`` did not come from this chokepoint. Use
    this where untrusted content is about to be concatenated into a system
    prompt so a skipped ``sanitize()`` call fails loudly instead of silently
    embedding raw attacker text.
    """
    if not isinstance(value, TrustedContent):
        raise TypeError(
            "untrusted content reached a system-prompt sink without passing "
            "through sanitize_untrusted.sanitize(); got a bare "
            f"{type(value).__name__}. Route it through the chokepoint first."
        )
    return value


def _clean(text: str | None, max_len: int) -> str:
    """Core filter pipeline. Returns a plain ``str`` (no trust marker)."""
    if not text:
        return ""
    if not isinstance(text, str):
        text = str(text)

    text = unicodedata.normalize("NFKC", text)
    text = html.unescape(text)

    # Drop control/format characters FIRST — before any pattern matching. "Cf"
    # (format) includes zero-width joiners and RLO/bidi overrides which an
    # attacker splices into keywords ("ig<ZWSP>nore all previous instructions")
    # precisely so the override/system-tag regexes below miss the directive.
    # Stripping these up front closes that ordering bypass (finding C-6).
    cleaned_chars = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf") and ch not in ("\n", "\t"):
            continue
        cleaned_chars.append(ch)
    text = "".join(cleaned_chars)

    text = _SYSTEM_TAG_PATTERN.sub("", text)
    text = _OVERRIDE_LINE_PATTERN.sub("", text)
    text = _NEW_INSTRUCTIONS_PATTERN.sub("", text)
    text = _CODE_FENCE_PATTERN.sub("[code block stripped]", text)
    text = _BASE64_RUN_PATTERN.sub("[base64-like run stripped]", text)

    # Collapse runs of blank lines left behind by stripping.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if max_len > 0 and len(text) > max_len:
        omitted = len(text) - max_len
        text = f"{text[:max_len]}\n[truncated — {omitted} chars omitted]"

    return text


def sanitize(text: str | None, max_len: int = _DEFAULT_MAX_LEN) -> TrustedContent:
    """Clean untrusted text for safe embedding in a system prompt.

    Steps:
      1. NFKC normalize — collapses fullwidth/compatibility forms to ASCII
         equivalents. Closes the Phase 2.2 S1 Unicode-fullwidth bypass.
      2. HTML entity decode once, then strip. Re-encoded payloads that
         survive a single decode pass are dropped by later steps.
      3. Drop control/format characters (except newline/tab) — done BEFORE
         pattern matching so zero-width/RLO-split keywords cannot evade the
         override and system-tag filters (finding C-6).
      4. Remove system-boundary XML tags.
      5. Blank out instruction-override lines.
      6. Strip "NEW INSTRUCTIONS:"-style override headers.
      7. Strip fenced code blocks (any language).
      8. Strip long base64-looking runs (heuristic).
      9. Truncate to max_len with explicit marker.

    Returns a :class:`TrustedContent` (a ``str`` subclass) for None or
    non-string input it returns an empty ``TrustedContent``. The return type is
    the in-process trust marker — see :func:`assert_trusted`. Callers should
    treat the returned text as trusted for prompt embedding; anything that would
    bypass these filters should be added here rather than worked around at the
    call site.
    """
    return TrustedContent(_clean(text, max_len))


def sanitize_list(items, max_item_len: int = _DEFAULT_MAX_LEN) -> list[TrustedContent]:
    """Sanitize each string in a list; drop entries that collapse to empty."""
    out: list[TrustedContent] = []
    if not items:
        return out
    if isinstance(items, str):
        items = [items]
    for item in items:
        cleaned = sanitize(item, max_item_len)
        if cleaned:
            out.append(cleaned)
    return out


def sanitize_stream(
    stream: TextIO, max_len: int = _DEFAULT_MAX_LEN
) -> TrustedContent:
    """Read an entire text stream and sanitize it.

    This is the chokepoint for shell sinks that pipe untrusted content on
    stdin. ``<sink> | python3 sanitize_untrusted.py [max_len]`` routes through
    here. Returns :class:`TrustedContent`.
    """
    return sanitize(stream.read(), max_len)


def sanitize_file(path, max_len: int = _DEFAULT_MAX_LEN) -> TrustedContent:
    """Read a file and sanitize its contents.

    Chokepoint for sinks that hand off untrusted content as a file (peer
    findings blocks, domain-profile fragments, overlay files, research-context
    dumps). Missing/unreadable files sanitize to empty rather than raising, so
    a skipped upstream step degrades to "no injected content" instead of a
    crash. Returns :class:`TrustedContent`.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return sanitize(fh.read(), max_len)
    except (OSError, ValueError):
        return TrustedContent("")


def _provenance_header(source: str | None) -> str:
    """Render the provenance marker stamped onto CLI output.

    Makes a successful pass through the chokepoint visible in the rendered
    prompt. A sink that skips sanitization will be missing this marker, which is
    detectable in review of an assembled prompt.
    """
    label = source or "untrusted"
    return f"<!-- sanitized:{label} via sanitize_untrusted -->"


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "Single enforced chokepoint for untrusted content. Pipe a sink's "
            "content on stdin (or pass --file); emits sanitized text safe for "
            "system-prompt embedding."
        )
    )
    parser.add_argument(
        "max_len",
        nargs="?",
        type=int,
        default=_DEFAULT_MAX_LEN,
        help=f"max characters before truncation (default {_DEFAULT_MAX_LEN}; 0 = no cap)",
    )
    parser.add_argument(
        "--file",
        help="read untrusted content from this file instead of stdin",
    )
    parser.add_argument(
        "--source",
        help="provenance label for the sink (e.g. peer-findings, knowledge, overlay)",
    )
    parser.add_argument(
        "--mark",
        action="store_true",
        help="prepend a provenance comment so the pass through the chokepoint is visible in the prompt",
    )
    args = parser.parse_args()

    if args.file:
        cleaned = sanitize_file(args.file, args.max_len)
    else:
        cleaned = sanitize_stream(sys.stdin, args.max_len)

    if args.mark and cleaned:
        sys.stdout.write(_provenance_header(args.source) + "\n")
    sys.stdout.write(cleaned)
