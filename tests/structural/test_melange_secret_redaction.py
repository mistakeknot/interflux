"""A melange finding must be scrubbed before the file tool writes it."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "redact-melange-write.py"
WRAPPER = ROOT / "hooks" / "redact-melange-write.sh"
WORKFLOW = ROOT / "skills" / "flux-melange-engine" / "workflow" / "melange-workflow.js"
MARKER = "[REDACTED SECRET]"


def call_hook(tool_name: str, tool_input: dict, *, cwd: str | None = None) -> dict:
    assert HOOK.is_file(), "melange pre-write guard is missing"
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input, "cwd": cwd}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(proc.stdout) if proc.stdout else {}


def updated_input(result: dict, original: dict) -> dict:
    return result.get("hookSpecificOutput", {}).get("updatedInput", original)


def test_fake_npmrc_token_is_redacted_before_probe_finding_write(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    fake_token = "npm_fake_secret_value_for_melange_regression_123456"
    npmrc = home / ".npmrc"
    npmrc.write_text(f"//registry.npmjs.org/:_authToken={fake_token}\n")
    finding = (
        "# npm publish adjudication\n\n"
        "## Evidence\n"
        f"The probe read {npmrc}:\n```\n{npmrc.read_text()}```\n"
    )
    path = tmp_path / "repo" / "docs" / "research" / "flux-melange" / "round-2" / "probe-0" / "npm-publish-adjudication.md"
    original = {"file_path": str(path), "content": finding}

    guarded = updated_input(call_hook("Write", original), original)
    path.parent.mkdir(parents=True)
    path.write_text(guarded["content"])

    written = path.read_text()
    assert MARKER in written
    assert fake_token not in written
    assert "npm publish adjudication" in written


def test_edit_replacement_scrubs_token_and_preserves_other_fields(tmp_path: Path):
    path = tmp_path / "repo" / "docs" / "research" / "flux-melange" / "heat-ledger.jsonl"
    token = "github_" + "pat_FAKEabcdefghijklmnopqrstuvwxyz1234567890"
    original = {"file_path": str(path), "old_string": "raw", "new_string": f"upheld: {token}", "replace_all": False}

    guarded = updated_input(call_hook("Edit", original), original)

    assert guarded["old_string"] == "raw"
    assert guarded["replace_all"] is False
    assert guarded["new_string"] == f"upheld: {MARKER}"


def test_private_key_and_api_key_are_scrubbed_without_breaking_jsonl(tmp_path: Path):
    path = tmp_path / "repo" / "docs" / "research" / "flux-melange" / "heat-ledger.jsonl"
    pem = "-----BEGIN PRIVATE KEY-----\nZmFrZS1rZXktbWF0ZXJpYWw=\n-----END PRIVATE KEY-----"
    line = json.dumps({"evidence": pem, "api_key": "fake_api_key_value_abcdefghijklmnopqrstuvwxyz", "claim": "credential exposed"}) + "\n"
    original = {"file_path": str(path), "content": line}

    guarded = updated_input(call_hook("Write", original), original)
    parsed = json.loads(guarded["content"])

    assert parsed["evidence"] == MARKER
    assert parsed["api_key"] == MARKER
    assert parsed["claim"] == "credential exposed"


def test_unquoted_numeric_secret_field_stays_valid_jsonl(tmp_path: Path):
    path = tmp_path / "docs" / "research" / "flux-melange" / "example" / "heat-ledger.jsonl"
    original = {"file_path": str(path), "content": '{"access_token": 12345678, "claim": "test"}\n'}

    guarded = updated_input(call_hook("Write", original), original)

    assert json.loads(guarded["content"]) == {"access_token": MARKER, "claim": "test"}


def test_ledger_edit_appends_redacted_row_without_rewriting_prior_rows(tmp_path: Path):
    path = tmp_path / "docs" / "research" / "flux-melange" / "example" / "heat-ledger.jsonl"
    path.parent.mkdir(parents=True)
    old_rows = [json.dumps({"id": "f-001", "claim": "first"}), json.dumps({"id": "f-002", "claim": "second"})]
    path.write_text("\n".join(old_rows) + "\n")
    token = "npm_" + "E" * 36
    new_row = json.dumps({"id": "f-003", "evidence": token})
    original = {"file_path": str(path), "old_string": old_rows[-1], "new_string": old_rows[-1] + "\n" + new_row}

    guarded = updated_input(call_hook("Edit", original), original)
    path.write_text(path.read_text().replace(guarded["old_string"], guarded["new_string"], 1))
    rows = path.read_text().splitlines()

    assert rows[:2] == old_rows
    assert json.loads(rows[2]) == {"id": "f-003", "evidence": MARKER}


def test_unrelated_write_is_not_modified(tmp_path: Path):
    path = tmp_path / "repo" / "notes.md"
    original = {"file_path": str(path), "content": "ordinary note"}

    assert updated_input(call_hook("Write", original), original) == original


def test_bare_npm_token_and_relative_melange_path_are_scrubbed():
    token = "npm_" + "A" * 36
    original = {
        "file_path": "docs/research/flux-melange/example/round-1/probe-0/finding.md",
        "content": f"The copied credential was {token}.",
    }

    guarded = updated_input(call_hook("Write", original), original)

    assert guarded["content"] == f"The copied credential was {MARKER}."


def test_path_relative_to_cwd_inside_melange_tree_is_scrubbed(tmp_path: Path):
    token = "npm_" + "C" * 36
    cwd = tmp_path / "docs" / "research" / "flux-melange" / "example"
    original = {"file_path": "round-1/probe-0/finding.md", "content": token}

    guarded = updated_input(call_hook("Write", original, cwd=str(cwd)), original)

    assert guarded["content"] == MARKER


def test_bash_write_into_melange_tree_is_denied():
    command = "cat ~/.npmrc > docs/research/flux-melange/example/round-1/probe-0/finding.md"
    result = call_hook("Bash", {"command": command})

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert command not in json.dumps(result)


def test_bash_guard_normalizes_repeated_path_separators():
    command = "cat ~/.npmrc > docs/research//flux-melange/example/finding.md"

    result = call_hook("Bash", {"command": command})

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_bash_write_from_inside_melange_tree_is_denied(tmp_path: Path):
    cwd = tmp_path / "docs" / "research" / "flux-melange" / "example"
    result = call_hook("Bash", {"command": "cat ~/.npmrc > finding.md"}, cwd=str(cwd))

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_bash_read_outside_melange_tree_is_untouched():
    assert call_hook("Bash", {"command": "rg finding src"}) == {}


def test_bash_allowlist_rejects_shell_expansion_inside_melange_tree():
    command = "mkdir -p docs/research/flux-melange/example/$(python3 writer.py)"

    result = call_hook("Bash", {"command": command})

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_bash_allows_guarded_helper_with_quoted_punctuation(tmp_path: Path):
    findings = tmp_path / "docs" / "research" / "flux-melange" / "example" / "peer-findings.jsonl"
    helper = ROOT / "scripts" / "findings-helper.sh"
    command = f'bash "{helper}" write "{findings}" notable probe secrets "first | second; third & fourth"'

    assert call_hook("Bash", {"command": command}) == {}


def test_bash_allows_plugin_root_helper_form(tmp_path: Path):
    findings = tmp_path / "docs" / "research" / "flux-melange" / "example" / "peer-findings.jsonl"
    command = f'bash "${{CLAUDE_PLUGIN_ROOT}}/scripts/findings-helper.sh" write "{findings}" notable probe secrets "safe summary"'

    assert call_hook("Bash", {"command": command}) == {}


def test_bash_allows_only_the_lens_generator_with_melange_specs(tmp_path: Path):
    specs = tmp_path / "docs" / "research" / "flux-melange" / "example" / "lens-specs" / "seed-adjacent.json"
    generator = ROOT / "scripts" / "generate-agents.py"
    command = f'python3 "{generator}" "{tmp_path}" --from-specs "{specs}" --mode=skip-existing --registry=auto --json'

    assert call_hook("Bash", {"command": command}) == {}
    fusion = specs.with_name("fusion-1-0.json")
    fusion_command = f'python3 "{generator}" "{tmp_path}" --from-specs "{fusion}" --mode=skip-existing --registry=off --json'
    assert call_hook("Bash", {"command": fusion_command}) == {}
    plugin_root_command = command.replace(str(generator), "${CLAUDE_PLUGIN_ROOT}/scripts/generate-agents.py")
    assert call_hook("Bash", {"command": plugin_root_command}) == {}
    arbitrary = f'python3 writer.py "{specs}"'
    assert call_hook("Bash", {"command": arbitrary})["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_bash_allows_simple_reads_and_git_staging_of_melange_artifacts():
    target = "docs/research/flux-melange/example/heat-ledger.jsonl"

    assert call_hook("Bash", {"command": f"cat {target}"}) == {}
    assert call_hook("Bash", {"command": f"git add {target}"}) == {}
    assert call_hook("Bash", {"command": f"rg secret {target}"}) == {}


def test_bash_still_denies_in_place_edits_of_melange_artifacts():
    target = "docs/research/flux-melange/example/heat-ledger.jsonl"
    result = call_hook("Bash", {"command": f"sed -i s/raw/upheld/ {target}"})

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_bash_rejects_git_output_option_into_melange_tree():
    target = "docs/research/flux-melange/example/finding.md"
    result = call_hook("Bash", {"command": f"git diff --output={target}"})

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_findings_helper_scrubs_before_appending_to_melange_file(tmp_path: Path):
    findings = tmp_path / "docs" / "research" / "flux-melange" / "example" / "peer-findings.jsonl"
    findings.parent.mkdir(parents=True)
    token = "npm_" + "B" * 36

    subprocess.run(
        [str(ROOT / "scripts" / "findings-helper.sh"), "write", str(findings), "notable", "probe", "secrets", f"Copied {token}"],
        check=True,
        capture_output=True,
        text=True,
    )

    written = findings.read_text()
    assert MARKER in written
    assert token not in written


def test_findings_helper_scrubs_relative_file_from_melange_cwd(tmp_path: Path):
    cwd = tmp_path / "docs" / "research" / "flux-melange" / "example"
    cwd.mkdir(parents=True)
    token = "npm_" + "D" * 36

    subprocess.run(
        [str(ROOT / "scripts" / "findings-helper.sh"), "write", "peer-findings.jsonl", "notable", "probe", "secrets", token],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )

    assert token not in (cwd / "peer-findings.jsonl").read_text()


def test_workflow_fails_closed_before_any_agent_can_write():
    src = WORKFLOW.read_text()
    skill = (ROOT / "skills" / "flux-melange-engine" / "SKILL.md").read_text()

    assert "WORKFLOW_UNGUARDED_WRITE" in src
    assert src.index("WORKFLOW_UNGUARDED_WRITE") < src.index("const A =")
    assert "Run the prose path for every invocation" in skill
    assert "Do not dispatch Workflow" in skill

    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable for Workflow entry point check")
    script = """
import { readFileSync } from 'node:fs';
const source = readFileSync(process.argv[1], 'utf8').replace('export const meta =', 'const meta =');
let calls = 0;
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = new AsyncFunction('agent', source);
try {
  await workflow(() => { calls++; });
  process.exitCode = 1;
} catch (error) {
  if (!String(error.message).includes('WORKFLOW_UNGUARDED_WRITE') || calls !== 0)
    process.exitCode = 1;
}
"""
    result = subprocess.run(
        [node, "--input-type=module", "-e", script, str(WORKFLOW)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_prose_probes_use_guarded_agent_tools_without_nested_dispatch():
    probe = (ROOT / "skills" / "flux-melange-engine" / "phases" / "probe.md").read_text()
    seed = (ROOT / "skills" / "flux-melange-engine" / "phases" / "seed.md").read_text()
    worker = (ROOT / "agents" / "melange-worker.md").read_text()
    manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())

    assert "subagent_type: interflux:melange-worker" in probe
    assert "must use Write to create" in probe
    assert "interflux:flux-engine" not in probe
    assert "tools: Read, Grep, Glob, Write, Edit" in worker
    assert "./agents/melange-worker.md" in manifest["agents"]
    assert "subagent_type: interflux:melange-worker" in seed
    assert "flux-drive-style" not in seed
    assert "track-dispatch.md" not in seed


def test_missing_python_blocks_melange_write_but_not_unrelated_write():
    def exit_code(path: str) -> int:
        event = {"tool_name": "Write", "tool_input": {"file_path": path, "content": "ordinary text"}}
        return subprocess.run(
            ["/bin/bash", str(WRAPPER)],
            input=json.dumps(event),
            text=True,
            capture_output=True,
            env={"PATH": ""},
        ).returncode

    assert exit_code("/tmp/docs/research/flux-melange/x/finding.md") == 2
    assert exit_code("/tmp/unrelated.md") == 0


def test_shell_wrapper_forwards_melange_write_to_scrubber():
    token = "npm_" + "F" * 36
    event = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/tmp/docs/research/flux-melange/x/finding.md",
            "content": token,
        },
    }
    proc = subprocess.run(
        ["/bin/bash", str(WRAPPER)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(proc.stdout)["hookSpecificOutput"]["updatedInput"]["content"] == MARKER


# --- Five named secret formats (bead mk-shn5e) -------------------------------
# Credential-shaped strings are assembled from fragments so this file never
# contains a literal that a scanner would flag.

AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"
AWS_SESSION_KEY = "ASIA" + "IOSFODNN7EXAMPLE"
SLACK_TOKEN = "xox" + "b-123456789012-abcdefghijkl"
STRIPE_KEY = "sk_" + "live_" + "A1b2C3d4E5f6G7h8I9j0"
STRIPE_RESTRICTED = "rk_" + "test_" + "A1b2C3d4E5f6G7h8I9j0"
GOOGLE_KEY = "AI" + "za" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p67"
JWT = "ey" + "J" + "hbGci." + "abcdefgh12." + "ABCDEFGH12"

FORMATS = {
    "aws": AWS_KEY,
    "aws-session": AWS_SESSION_KEY,
    "slack": SLACK_TOKEN,
    "stripe": STRIPE_KEY,
    "stripe-restricted": STRIPE_RESTRICTED,
    "google": GOOGLE_KEY,
    "jwt": JWT,
}


def hook_filter(text: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(HOOK), "--filter"],
        input=text,
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout


@pytest.mark.parametrize("name", sorted(FORMATS))
@pytest.mark.parametrize(
    "template",
    [
        "{s}",
        "value {s} end",
        "name={s}",
        "name: {s}",
        '{{"name": "{s}"}}',
        "https://example.test/x?token={s}&y=1",
        "X-Token: {s}",
        "Authorization: Bearer {s}",
        "see ({s}).",
        "quoted '{s}' text",
    ],
)
def test_named_formats_are_scrubbed_in_every_context(name, template):
    secret = FORMATS[name]
    scrubbed = hook_filter(template.format(s=secret))
    assert secret not in scrubbed
    assert MARKER in scrubbed


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
def test_named_formats_are_scrubbed_by_every_write_tool(tool, tmp_path: Path):
    path = tmp_path / "docs" / "research" / "flux-melange" / "r" / "heat-ledger.jsonl"
    text = " | ".join(FORMATS.values())
    if tool == "Write":
        original = {"file_path": str(path), "content": text}
        key = lambda d: d["content"]
    elif tool == "Edit":
        original = {"file_path": str(path), "old_string": "x", "new_string": text}
        key = lambda d: d["new_string"]
    else:
        original = {"file_path": str(path), "edits": [{"old_string": "x", "new_string": text}]}
        key = lambda d: d["edits"][0]["new_string"]
    guarded = key(updated_input(call_hook(tool, original), original))
    for secret in FORMATS.values():
        assert secret not in guarded
    assert guarded.count(MARKER) == len(FORMATS)


def test_named_format_boundaries_avoid_identifier_over_redaction():
    # Longer identifier-like runs and glued prefixes are not credentials.
    for glued in ("x" + AWS_KEY, AWS_KEY + "Z", "my_" + STRIPE_KEY):
        assert hook_filter(glued) == glued
    # Too-short bodies are not credentials.
    assert hook_filter("AKIA" + "SHORT") == "AKIA" + "SHORT"
    assert hook_filter("xox" + "b-short") == "xox" + "b-short"
    assert hook_filter("AI" + "za" + "tooshort") == "AI" + "za" + "tooshort"


def test_jwt_boundaries():
    # '=' directly before a token is an assignment, so it is redacted.
    assert MARKER in hook_filter("jwt=" + JWT)
    assert MARKER in hook_filter("id_token==" + JWT)
    # Sentence-final dot and surrounding punctuation still redact.
    assert hook_filter("it was " + JWT + ".") == "it was " + MARKER + "."
    assert hook_filter("(" + JWT + ")") == "(" + MARKER + ")"
    # A token inside a longer dotted chain is not a JWT.
    assert hook_filter("x." + JWT) == "x." + JWT
    assert hook_filter(JWT + ".extra4th") == JWT + ".extra4th"
    # Base64 padding after the last segment is not a JWT boundary.
    assert hook_filter(JWT + "=") == JWT + "="
    # Alphanumeric text touching either side is not a JWT.
    assert hook_filter("a" + JWT) == "a" + JWT


def test_named_format_scrub_is_idempotent_and_keeps_legacy_order():
    text = "api_key=" + AWS_KEY + " and " + SLACK_TOKEN + " Bearer " + "A" * 24
    once = hook_filter(text)
    assert hook_filter(once) == once
    assert AWS_KEY not in once and SLACK_TOKEN not in once
    assert once.count(MARKER) == 3
    # Existing formats keep their behavior.
    legacy = "npm_" + "E" * 36
    assert hook_filter(legacy) == MARKER


def test_scrub_function_exposes_module_for_importer():
    spec_name = "melange_redactor_probe"
    import importlib.util

    spec = importlib.util.spec_from_file_location(spec_name, HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.scrub(AWS_KEY) == MARKER
    assert module.MARKER == MARKER


# --- Bash admission for the two import scripts ------------------------------

RUN = "/tmp/proj/docs/research/flux-melange/example-run"
RECEIPT = "/tmp/out/receipt.json"
REPORT = "/tmp/out/report.md"
HASH = "a" * 64
IMPORT_SCRIPT = '"${CLAUDE_PLUGIN_ROOT}/scripts/import-melange-review.py"'
SCAN_SCRIPT = '"${CLAUDE_PLUGIN_ROOT}/scripts/scan-melange-import.py"'


def import_cmd(**over) -> str:
    parts = {
        "script": IMPORT_SCRIPT,
        "run": f'"{RUN}"',
        "receipt": f'"{RECEIPT}"',
        "report": f'"{REPORT}"',
        "hash": f'"{HASH}"',
    }
    parts.update(over)
    return (
        f'python3 -I {parts["script"]} --run-dir {parts["run"]} '
        f'--receipt {parts["receipt"]} --report {parts["report"]} --report-sha256 {parts["hash"]}'
    )


def scan_cmd(run: str = f'"{RUN}"') -> str:
    return f"python3 -I {SCAN_SCRIPT} --run-dir {run}"


def bash_decision(command: str, *, env: dict | None = None, cwd: str = "/tmp/proj") -> str:
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )
    if not proc.stdout.strip():
        return "allow"
    return json.loads(proc.stdout)["hookSpecificOutput"].get("permissionDecision", "allow")


def test_import_and_scan_commands_are_admitted_in_their_exact_form():
    assert bash_decision(import_cmd()) == "allow"
    assert bash_decision(scan_cmd()) == "allow"
    # Unquoted arguments are equivalent after shell word splitting.
    assert bash_decision(import_cmd(hash=HASH, run=RUN)) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        # Absolute script paths are not admitted; only the literal plugin-root form.
        import_cmd(script="/opt/plugin/scripts/import-melange-review.py"),
        scan_cmd().replace('"${CLAUDE_PLUGIN_ROOT}/scripts/scan-melange-import.py"', "/opt/plugin/scripts/scan-melange-import.py"),
        # No isolated mode.
        import_cmd().replace("python3 -I ", "python3 "),
        # Env prefix, wrapper interpreter and other scripts.
        "FOO=1 " + import_cmd(),
        import_cmd().replace("python3", "python"),
        import_cmd(script='"${CLAUDE_PLUGIN_ROOT}/scripts/other.py"'),
        import_cmd(script='"${CLAUDE_PLUGIN_ROOT}/scripts/../scripts/import-melange-review.py"'),
        # Extra, duplicate and reordered flags.
        import_cmd() + " --extra",
        import_cmd() + f' --run-dir "{RUN}"',
        f'python3 -I {IMPORT_SCRIPT} --receipt "{RECEIPT}" --run-dir "{RUN}" --report "{REPORT}" --report-sha256 {HASH}',
        # Hash must be lowercase 64-hex.
        import_cmd(hash='"' + "A" * 64 + '"'),
        import_cmd(hash='"' + "a" * 63 + '"'),
        import_cmd(hash='"' + "a" * 65 + '"'),
        # Operators, redirects, newlines and substitution.
        import_cmd() + " && echo x",
        import_cmd() + " > /tmp/x",
        import_cmd() + " | cat",
        import_cmd() + "\necho x",
        import_cmd(report='"$(cat /etc/passwd)"'),
        import_cmd(report='"`id`"'),
        import_cmd(report='"$HOME/report.md"'),
        import_cmd(receipt='"/tmp/*.json"'),
        import_cmd(receipt='"~/receipt.json"'),
        import_cmd(receipt='"/tmp/{a,b}.json"'),
        import_cmd(run=f'"{RUN}/../other"'),
        scan_cmd() + " --extra",
        scan_cmd(run=f'"{RUN}/$(pwd)"'),
        scan_cmd() + " && true",
    ],
)
def test_import_and_scan_commands_outside_the_exact_form_are_denied(command):
    assert bash_decision(command) == "deny"


def test_bash_admission_rejects_a_conflicting_runtime_plugin_root(tmp_path: Path):
    other = tmp_path / "other-plugin"
    (other / "scripts").mkdir(parents=True)
    env = {"PATH": "/usr/bin:/bin", "CLAUDE_PLUGIN_ROOT": str(other)}
    assert bash_decision(import_cmd(), env=env) == "deny"
    own = {"PATH": "/usr/bin:/bin", "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    assert bash_decision(import_cmd(), env=own) == "allow"
