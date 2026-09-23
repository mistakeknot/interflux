"""A melange finding must be scrubbed before the file tool writes it."""

import json
import subprocess
import sys
from pathlib import Path


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


def test_workflow_requires_guarded_file_tools_and_rejects_unguarded_mirrors():
    src = WORKFLOW.read_text()

    assert "Use Write or Edit for every artifact under" in src
    assert "Use Edit on the final existing ledger line" in src
    assert "peer mirrors are disabled until their writes can be scrubbed before disk" in src


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
