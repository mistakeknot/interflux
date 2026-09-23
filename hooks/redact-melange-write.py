#!/usr/bin/env python3
"""Scrub melange artifacts in PreToolUse, before Write/Edit reaches the disk."""

from __future__ import annotations

import json
import os
import posixpath
import re
import shlex
import sys
from pathlib import Path


MARKER = "[REDACTED SECRET]"
MELANGE_PATH = re.compile(r"(?:^|/)docs/research/flux-melange(?:/|$)")
MELANGE_REFERENCE = re.compile(r"docs/research/flux-melange(?:/|\b)")

# Match a whole PEM block, including blocks embedded as escaped newlines in JSON.
PRIVATE_KEY = re.compile(
    r"-----BEGIN ([A-Z ]*PRIVATE KEY)-----.*?-----END \1-----", re.DOTALL
)
ASSIGNED_SECRET = re.compile(
    r"(?i)(?P<prefix>(?:[\"']?)(?:_authToken|api[_-]?key|auth[_-]?token|access[_-]?token|secret[_-]?key)(?:[\"']?)\s*[:=]\s*[\"']?)"
    r"(?P<value>[A-Za-z0-9_./+=:$!@%&~^-]{8,})"
)
TOKEN_SHAPE = re.compile(
    r"\b(?:npm_[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b"
)
BEARER = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]{20,}")


def scrub(value: str) -> str:
    value = PRIVATE_KEY.sub(MARKER, value)
    value = ASSIGNED_SECRET.sub(redact_assignment, value)
    value = TOKEN_SHAPE.sub(MARKER, value)
    return BEARER.sub(lambda m: m.group(1) + MARKER, value)


def redact_assignment(match: re.Match[str]) -> str:
    prefix = match.group("prefix")
    separator = max(prefix.rfind(":"), prefix.rfind("="))
    after_separator = prefix[separator + 1 :]
    # A bare value after a colon may be JSON. The marker must be quoted there.
    if prefix[separator] == ":" and not any(quote in after_separator for quote in ('"', "'")):
        return prefix + json.dumps(MARKER)
    return prefix + MARKER


def is_melange_path(path: object, cwd: object = None) -> bool:
    if not isinstance(path, str):
        return False
    normalized = path.replace("\\", "/")
    if not posixpath.isabs(normalized) and isinstance(cwd, str):
        normalized = posixpath.join(cwd.replace("\\", "/"), normalized)
    return bool(MELANGE_PATH.search(posixpath.normpath(normalized)))


def allowed_bash(command: str, cwd: object = None) -> bool:
    # shlex separates unquoted shell operators while preserving punctuation
    # inside a quoted findings summary. Never permit compound commands.
    if "\n" in command or "\r" in command:
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|><()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        words = list(lexer)
    except ValueError:
        return False
    if any(re.fullmatch(r"[;&|><()]+", word) for word in words):
        return False
    if not words:
        return False
    if words[0] in ("mkdir", "mktemp"):
        return len(words) >= 3 and words[1] == ("-p" if words[0] == "mkdir" else "-d") and not any(
            "$" in word or "`" in word for word in words
        )
    if words[0] in ("cat", "ls", "head", "tail", "wc", "jq", "rg", "grep", "stat"):
        return len(words) >= 2 and not any(
            "$" in word or "`" in word or word.startswith("--pre")
            for word in words
        )
    if words[0] == "git" and len(words) >= 2 and words[1] in ("add", "diff", "status", "log"):
        return not any(
            "$" in word or "`" in word or word in ("-o", "--ext-diff", "--textconv")
            or word.startswith("--output") for word in words
        )

    # The orchestrator may read already-guarded lens specs and generate agent
    # definitions. Match the exact generator invocation; no arbitrary Python
    # command may name a melange artifact.
    if words[0] == "python3" and len(words) == 8:
        script = words[1]
        plugin_root = Path(__file__).resolve().parents[1]
        if script.startswith("${CLAUDE_PLUGIN_ROOT}/"):
            script = str(plugin_root / script.removeprefix("${CLAUDE_PLUGIN_ROOT}/"))
        specs = words[4]
        return (
            os.path.realpath(script) == str(plugin_root / "scripts" / "generate-agents.py")
            and words[3] == "--from-specs"
            and is_melange_path(specs, cwd)
            and "/lens-specs/" in specs.replace("\\", "/")
            and re.fullmatch(
                r"(?:seed-(?:adjacent|distant)|fusion-\d+-\d+|wide-\d+-\d+)\.json",
                posixpath.basename(specs),
            ) is not None
            and words[5] == "--mode=skip-existing"
            and words[6] in ("--registry=auto", "--registry=off")
            and words[7] == "--json"
            and not any("$" in word or "`" in word for word in words[2:])
        )

    script_index = 1 if words[0] in ("bash", "/bin/bash") else 0
    if len(words) <= script_index + 1:
        return False
    plugin_root = Path(__file__).resolve().parents[1]
    script = words[script_index]
    if script.startswith("${CLAUDE_PLUGIN_ROOT}/"):
        script = str(plugin_root / script.removeprefix("${CLAUDE_PLUGIN_ROOT}/"))
    base = cwd if isinstance(cwd, str) else os.getcwd()
    helper = os.path.realpath(os.path.join(base, script))
    if helper != str(plugin_root / "scripts" / "findings-helper.sh"):
        return False
    if words[script_index + 1] not in ("write", "read", "read-indexes", "convergence"):
        return False
    return not any(
        ("$" in word or "`" in word)
        and not (index == script_index and word == "${CLAUDE_PLUGIN_ROOT}/scripts/findings-helper.sh")
        for index, word in enumerate(words)
    )


def hook_result(updated: dict | None = None, *, deny: str | None = None) -> dict:
    specific: dict = {"hookEventName": "PreToolUse"}
    if updated is not None:
        specific["updatedInput"] = updated
    if deny is not None:
        specific["permissionDecision"] = "deny"
        specific["permissionDecisionReason"] = deny
    return {"hookSpecificOutput": specific}


def main() -> None:
    try:
        if sys.argv[1:] == ["--filter"]:
            sys.stdout.write(scrub(sys.stdin.read()))
            return
        event = json.load(sys.stdin)
        tool = event.get("tool_name")
        original = event.get("tool_input")
        if tool == "Bash" and isinstance(original, dict):
            command = original.get("command")
            if not isinstance(command, str):
                raise ValueError("Bash.command is not text")
            command_path_view = re.sub(r"/+", "/", command.replace("\\", "/"))
            if (MELANGE_REFERENCE.search(command_path_view) or is_melange_path(event.get("cwd"))) and not allowed_bash(command, event.get("cwd")):
                print(json.dumps(hook_result(deny="melange shell command blocked; use guarded file tools for writes")))
            return
        if tool not in ("Write", "Edit", "MultiEdit") or not isinstance(original, dict):
            return
        if not is_melange_path(original.get("file_path"), event.get("cwd")):
            return
        updated = original.copy()
        if tool == "Write":
            if not isinstance(updated.get("content"), str):
                raise ValueError("Write.content is not text")
            updated["content"] = scrub(updated["content"])
        elif tool == "Edit":
            if not isinstance(updated.get("new_string"), str):
                raise ValueError("Edit.new_string is not text")
            updated["new_string"] = scrub(updated["new_string"])
        else:
            edits = updated.get("edits")
            if not isinstance(edits, list) or any(
                not isinstance(edit, dict) or not isinstance(edit.get("new_string"), str)
                for edit in edits
            ):
                raise ValueError("MultiEdit.edits is not a text edit list")
            updated["edits"] = [
                {**edit, "new_string": scrub(edit["new_string"])} for edit in edits
            ]
        print(json.dumps(hook_result(updated)))
    except Exception:
        # Never echo tool input or exception text; either can contain the secret.
        print(json.dumps(hook_result(deny="melange redaction failed; write blocked")))


if __name__ == "__main__":
    main()
