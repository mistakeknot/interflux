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

# Five named secret formats. ASCII classes, case-sensitive. A body must not touch
# another identifier character on either side, so longer identifiers are left alone.
# The config/flux-melange/import-gitleaks.toml rules mirror these bodies and
# boundaries for the import scanner.
_ID = r"[A-Za-z0-9_-]"
AWS_KEY = re.compile(rf"(?<!{_ID})(?:AKIA|ASIA)[A-Z0-9]{{16}}(?!{_ID})")
SLACK_TOKEN = re.compile(rf"(?<!{_ID})(?:xoxa|xoxb|xoxp|xoxr|xoxs)-[A-Za-z0-9-]{{10,}}(?!{_ID})")
STRIPE_KEY = re.compile(rf"(?<!{_ID})(?:sk_live|sk_test|rk_live|rk_test)_[A-Za-z0-9_-]{{16,}}(?!{_ID})")
# A JWT is three dot-separated segments. A fourth segment, a dotted prefix or base64
# padding directly after the token means the text is something else. A single regular
# expression would rescan the rest of a long `eyJ-eyJ-` run from every start, so the
# match is made segment by segment in linear time (scrub_jwts). The import scanner's
# Gitleaks rule states the same grammar with no length cap.
_SEGMENT = re.compile(r"[A-Za-z0-9_-]+")
_JWT_START_BEFORE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.")


def _jwt_spans(value: str) -> list[tuple[int, int]]:
    segments = [(m.start(), m.end()) for m in _SEGMENT.finditer(value)]
    spans: list[tuple[int, int]] = []
    index = 0
    while index + 2 < len(segments):
        start, end = segments[index]
        found = -1
        at = value.find("eyJ", start, end)
        while at != -1:
            before = value[at - 1] if at > 0 else ""
            if end - at >= 8 and before not in _JWT_START_BEFORE:
                found = at
                break
            at = value.find("eyJ", at + 1, end)
        if found >= 0:
            (ps, pe), (ss, se) = segments[index + 1], segments[index + 2]
            joined = ps == end + 1 and value[end] == "." and ss == pe + 1 and value[pe] == "."
            if joined and pe - ps >= 8 and se - ss >= 8:
                follow = value[se : se + 2]
                after_dot = value[se + 1] if follow[:1] == "." and len(follow) > 1 else ""
                tail_ok = (
                    follow[:1] != "="
                    and not (follow[:1] == "." and (after_dot == "=" or _SEGMENT.fullmatch(after_dot) is not None))
                )
                if tail_ok:
                    spans.append((found, se))
                    index += 3
                    continue
        index += 1
    return spans


def scrub_jwts(value: str) -> str:
    spans = _jwt_spans(value)
    if not spans:
        return value
    out: list[str] = []
    last = 0
    for start, end in spans:
        out.append(value[last:start])
        out.append(MARKER)
        last = end
    out.append(value[last:])
    return "".join(out)


GOOGLE_KEY = re.compile(rf"(?<!{_ID})AIza[A-Za-z0-9_-]{{35}}(?!{_ID})")


def scrub(value: str) -> str:
    value = PRIVATE_KEY.sub(MARKER, value)
    value = ASSIGNED_SECRET.sub(redact_assignment, value)
    value = TOKEN_SHAPE.sub(MARKER, value)
    value = BEARER.sub(lambda m: m.group(1) + MARKER, value)
    for pattern in (AWS_KEY, SLACK_TOKEN, STRIPE_KEY):
        value = pattern.sub(MARKER, value)
    value = scrub_jwts(value)
    return GOOGLE_KEY.sub(MARKER, value)


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


IMPORT_SCRIPT_FLAGS = {
    "import-melange-review.py": ("--run-dir", "--receipt", "--report", "--report-sha256"),
    "scan-melange-import.py": ("--run-dir",),
}
PLUGIN_ROOT_PREFIX = "${CLAUDE_PLUGIN_ROOT}/scripts/"
UNSAFE_PATH_CHARS = re.compile(r"[$`*?\[\]{}~!]")
LOWER_SHA256 = re.compile(r"[0-9a-f]{64}")


IMPORT_COMMAND_HEAD = re.compile(r'python3 -I "\$\{CLAUDE_PLUGIN_ROOT\}/scripts/[a-z-]+\.py"(?: |$)')


def allowed_import_command(words: list[str], cwd: object = None, raw: str = "") -> bool:
    """Admit only `python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/<import|scan>" --flag value ...`.

    shlex discards quoting, so the raw text is checked too: the script word must be
    the double-quoted expansion (a single-quoted one is a literal relative path in
    Bash), and no single quote or backslash may appear anywhere in the command.
    """
    if not IMPORT_COMMAND_HEAD.match(raw) or "'" in raw or "\\" in raw:
        return False
    if len(words) < 3 or not words[2].startswith(PLUGIN_ROOT_PREFIX):
        return False
    name = words[2].removeprefix(PLUGIN_ROOT_PREFIX)
    flags = IMPORT_SCRIPT_FLAGS.get(name)
    if flags is None or len(words) != 3 + 2 * len(flags):
        return False
    plugin_root = Path(__file__).resolve().parents[1]
    runtime_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if runtime_root and os.path.realpath(runtime_root) != str(plugin_root):
        return False
    script = plugin_root / "scripts" / name
    if os.path.realpath(script) != str(script):
        return False
    values = {}
    for index, flag in enumerate(flags):
        if words[3 + 2 * index] != flag:
            return False
        value = words[4 + 2 * index]
        if not value or value.startswith("-") or UNSAFE_PATH_CHARS.search(value):
            return False
        values[flag] = value
    for flag in flags:
        if flag == "--report-sha256":
            if not LOWER_SHA256.fullmatch(values[flag]):
                return False
        elif ".." in values[flag].replace("\\", "/").split("/"):
            return False
    return is_melange_path(values["--run-dir"], cwd)


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

    # The two review-import scripts: one exact, isolated invocation each. The
    # literal ${CLAUDE_PLUGIN_ROOT}/scripts/<name> prefix is the only expansion,
    # and absolute script paths are not admitted.
    if words[0] == "python3" and len(words) >= 2 and words[1] == "-I":
        return allowed_import_command(words, cwd, command)

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
