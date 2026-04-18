#!/usr/bin/env python3
"""Parse agent task output JSONL for actual token usage.

Usage: token-count.py <subagent_jsonl_path>
Output (JSON): {"input_tokens": N, "output_tokens": N, "cache_creation": N, "cache_read": N, "total": N}

Falls back to chars/4 estimate if JSONL unavailable or unparseable.
Pass --fallback-file <path> to use a file for the chars/4 estimate.
"""

import json
import sys


def sum_usage(path: str) -> dict:
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation": 0,
        "cache_read": 0,
    }
    valid_lines = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Per-line try/except: one malformed JSONL line (partial write, truncation) must
            # not discard accumulated valid counts. The prior single-try pattern fell back
            # to a chars/4 estimate for the whole file on any parse failure.
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = obj.get("message", {})
            if msg.get("role") != "assistant":
                continue
            usage = msg.get("usage", {})
            totals["input_tokens"] += int(usage.get("input_tokens") or 0)
            totals["output_tokens"] += int(usage.get("output_tokens") or 0)
            totals["cache_creation"] += int(usage.get("cache_creation_input_tokens") or 0)
            totals["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
            valid_lines += 1
    totals["total"] = totals["input_tokens"] + totals["output_tokens"]
    # Only treat as "successful parse" if at least one line was valid. A file of all-
    # malformed lines returns zeroes; caller can detect via total == 0 and input_tokens == 0.
    totals["_valid_lines"] = valid_lines
    return totals


def fallback(file_path: str | None) -> dict:
    chars = 0
    if file_path:
        try:
            with open(file_path) as f:
                chars = len(f.read())
        except OSError:
            pass
    est = chars // 4
    return {
        "input_tokens": 0,
        "output_tokens": est,
        "cache_creation": 0,
        "cache_read": 0,
        "total": est,
        "estimated": True,
    }


def main():
    args = sys.argv[1:]
    fallback_file = None

    if "--fallback-file" in args:
        idx = args.index("--fallback-file")
        fallback_file = args[idx + 1]
        args = args[:idx] + args[idx + 2 :]

    if not args:
        print("Usage: token-count.py [--fallback-file <path>] <subagent_jsonl_path>", file=sys.stderr)
        sys.exit(2)

    jsonl_path = args[0]

    try:
        result = sum_usage(jsonl_path)
        json.dump(result, sys.stdout)
        print()
    except (OSError, json.JSONDecodeError, KeyError) as e:
        result = fallback(fallback_file)
        json.dump(result, sys.stdout)
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
