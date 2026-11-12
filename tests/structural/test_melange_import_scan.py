"""Post-import scanner and Gitleaks configuration tests for melange review import."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from _import_fixtures import (
    AWS_KEY,
    FIVE_FORMATS,
    GITLEAKS_CONFIG,
    GOOGLE_KEY,
    HOOK,
    JWT,
    LEGACY_NPM,
    MARKER,
    PEM,
    SCAN_SCRIPT,
    SLACK_TOKEN,
    STRIPE_KEY,
    clean_env,
    do_import,
    load_module,
    make_project,
    run_script,
    tree_snapshot,
)

GITLEAKS = Path.home() / ".local" / "bin" / "gitleaks"


@pytest.fixture
def ctx(tmp_path):
    return make_project(tmp_path)


def scan(ctx, *, cwd=None, env=None):
    return run_script(SCAN_SCRIPT, ["--run-dir", str(ctx.run)], cwd=cwd or ctx.tmp, env=env)


def gitleaks_stdin(text: str) -> int:
    """Run the shipped config over bytes exactly as the importer does; return the exit code."""
    with tempfile.TemporaryDirectory() as empty:
        env = {k: v for k, v in clean_env().items() if not k.startswith("GITLEAKS")}
        proc = subprocess.run(
            [
                str(GITLEAKS), "stdin", "-c", str(GITLEAKS_CONFIG), "--ignore-gitleaks-allow", "-i", empty,
                "--max-decode-depth", "0", "--max-archive-depth", "0", "--redact=100",
                "--report-format", "json", "--report-path", "-", "--exit-code", "20", "--no-banner", "--no-color",
            ],
            input=text.encode(), capture_output=True, env=env, timeout=60,
        )
    assert proc.returncode in (0, 20), proc.stderr.decode()
    return proc.returncode


# ------------------------------------------------------ gitleaks pinning


def test_gitleaks_8_30_1_is_installed_and_required():
    """Fails (never skips) when the pinned scanner is absent."""
    assert GITLEAKS.is_file(), "gitleaks 8.30.1 must be installed at ~/.local/bin/gitleaks"
    proc = subprocess.run([str(GITLEAKS), "version"], capture_output=True, text=True, timeout=30)
    assert proc.stdout.strip() == "8.30.1", proc.stdout


def test_config_exists_without_extend_or_allowlists():
    text = GITLEAKS_CONFIG.read_text()
    assert "[extend]" not in text and "useDefault" not in text
    assert "allowlist" not in text.lower()
    assert "[[rules]]" in text


def test_config_defines_all_named_and_legacy_rules():
    text = GITLEAKS_CONFIG.read_text().lower()
    for fragment in ("aws", "slack", "stripe", "google", "jwt", "private", "npm", "github", "sk-", "bearer", "assigned"):
        assert fragment in text, fragment


# --------------------------------------------- scrubber / scanner agreement

SHOULD_DETECT = {
    **{f"fmt-{k}": v for k, v in FIVE_FORMATS.items()},
    "stripe-test": "sk_" + "test_" + "A1b2C3d4E5f6G7h8I9j0",
    "stripe-rk": "rk_" + "live_" + "A1b2C3d4E5f6G7h8I9j0",
    "aws-asia": "ASIA" + "IOSFODNN7EXAMPLE",
    "slack-xoxp": "xox" + "p-123456789012-abcdefghijkl",
    "npm": LEGACY_NPM,
    "pem": PEM,
    "bearer": "Authorization: Bearer " + "abcdefghijklmnopqrstuvwxyz0123",
    "assigned": "api_key = " + "abcd1234efgh5678",
    "in-sentence": f"The key {AWS_KEY}, rotated.",
    "json-string": json.dumps({"k": SLACK_TOKEN}),
    "url": f"https://x.test/?t={STRIPE_KEY}&u=1",
    "jwt-trailing-dot-space": JWT + ". Next",
    "jwt-in-quotes": f'"{JWT}"',
}

SHOULD_IGNORE = {
    "aws-longer-identifier": "A" + AWS_KEY + "B",
    "aws-prefix-id": "x-" + AWS_KEY,
    "stripe-extended-id": "pre_" + STRIPE_KEY,
    "google-extended": "Z" + GOOGLE_KEY,
    "jwt-four-segments": JWT + ".extra",
    "jwt-dotted-prefix": "a." + JWT,
    "jwt-padding": JWT + "=",
    "marker": MARKER,
    "plain": "no secret here",
    "short-akia": "AKIA1234",
}


@pytest.mark.parametrize("name", sorted(SHOULD_DETECT))
def test_scrubber_and_scanner_both_flag_secrets(name):
    hook = load_module("hook_agree", HOOK)
    text = SHOULD_DETECT[name]
    assert hook.scrub(text) != text, "scrubber missed"
    assert gitleaks_stdin(text) == 20, "scanner missed"
    assert gitleaks_stdin(hook.scrub(text)) == 0, "scrubbed output still flagged"


@pytest.mark.parametrize("name", sorted(SHOULD_IGNORE))
def test_scrubber_and_scanner_both_ignore_non_secrets(name):
    hook = load_module("hook_agree2", HOOK)
    text = SHOULD_IGNORE[name]
    assert hook.scrub(text) == text, "scrubber over-matched"
    assert gitleaks_stdin(text) == 0, "scanner over-matched"


# ------------------------------------------------------------ scanner runs


def test_clean_run_without_imports_exits_0(ctx):
    assert scan(ctx).returncode == 0


def test_clean_run_after_import_exits_0(ctx):
    assert do_import(ctx)[0].returncode == 0
    proc = scan(ctx)
    assert proc.returncode == 0, proc.stderr


def test_scanner_is_read_only(ctx):
    assert do_import(ctx)[0].returncode == 0
    before = tree_snapshot(ctx.project)
    assert scan(ctx).returncode == 0
    assert tree_snapshot(ctx.project) == before


@pytest.mark.parametrize("location", ["melange-state.json", "heat-ledger.jsonl", "round-1-synthesis.md", "notes/extra.txt", ".hidden"])
@pytest.mark.parametrize("name,secret", sorted(FIVE_FORMATS.items()))
def test_residue_anywhere_in_the_run_is_exit_20(ctx, location, name, secret):
    path = ctx.run / location
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    path.write_text(existing + f"\nnote {secret} end\n")
    proc = scan(ctx)
    assert proc.returncode == 20, proc.stderr
    assert secret not in proc.stdout and secret not in proc.stderr


def test_residue_inside_an_imported_bundle_is_exit_20(ctx):
    assert do_import(ctx)[0].returncode == 0
    bundle = next(p for p in ctx.imports.iterdir() if p.is_dir())
    target = bundle / "external-evidence" / "report.redacted.md"
    target.write_text(target.read_text() + f"\n{STRIPE_KEY}\n")
    assert scan(ctx).returncode == 20


def test_residue_in_a_legacy_shape_is_exit_20(ctx):
    (ctx.run / "melange-state.json").write_text(json.dumps({"round": 1, "note": PEM}))
    assert scan(ctx).returncode == 20


def test_escaped_secret_in_json_is_found_through_the_decoded_view(ctx):
    escaped = AWS_KEY[:1] + "\\u004b" + AWS_KEY[2:]
    (ctx.run / "melange-state.json").write_text('{"round": 1, "note": "' + escaped + '"}\n')
    assert AWS_KEY not in (ctx.run / "melange-state.json").read_text()
    assert scan(ctx).returncode == 20


def test_secret_in_a_json_key_is_found(ctx):
    (ctx.run / "melange-state.json").write_text(json.dumps({"round": 1, AWS_KEY: 1}))
    assert scan(ctx).returncode == 20


def test_secret_in_a_jsonl_line_is_found(ctx):
    (ctx.run / "heat-ledger.jsonl").write_text(json.dumps({"id": "a", "claim": f"x {JWT}"}) + "\n")
    assert scan(ctx).returncode == 20


def test_scanner_accepts_the_marker_and_other_scrubbed_text(ctx):
    (ctx.run / "round-1-synthesis.md").write_text(f"found {MARKER} in text\n")
    assert scan(ctx).returncode == 0


def test_scanner_does_not_print_matched_secret_text(ctx):
    (ctx.run / "melange-state.json").write_text(json.dumps({"round": 1, "note": GOOGLE_KEY}))
    proc = scan(ctx)
    assert proc.returncode == 20
    assert GOOGLE_KEY not in proc.stdout + proc.stderr


def test_symlink_in_the_tree_is_exit_22(ctx):
    outside = ctx.tmp / "outside.txt"
    outside.write_text("fine\n")
    (ctx.run / "link.txt").symlink_to(outside)
    assert scan(ctx).returncode == 22


def test_symlinked_directory_in_the_tree_is_exit_22(ctx):
    outside = ctx.tmp / "outside-dir"
    outside.mkdir()
    (ctx.run / "linkdir").symlink_to(outside, target_is_directory=True)
    assert scan(ctx).returncode == 22


def test_fifo_in_the_tree_is_exit_22(ctx):
    os.mkfifo(ctx.run / "pipe")
    assert scan(ctx).returncode == 22


def test_unreadable_file_is_exit_22(ctx):
    if os.geteuid() == 0:
        pytest.skip("root reads everything; unreadable-file semantics unobservable")
    target = ctx.run / "locked.txt"
    target.write_text("x\n")
    target.chmod(0)
    try:
        assert scan(ctx).returncode == 22
    finally:
        target.chmod(0o600)


@pytest.mark.parametrize("break_run", ["no_state", "no_ledger", "outside_tree", "missing"])
def test_invalid_run_is_exit_23(ctx, tmp_path, break_run):
    run = ctx.run
    if break_run == "no_state":
        (run / "melange-state.json").unlink()
    elif break_run == "no_ledger":
        (run / "heat-ledger.jsonl").unlink()
    elif break_run == "outside_tree":
        run = tmp_path / "elsewhere"
        run.mkdir()
        (run / "melange-state.json").write_text("{}\n")
        (run / "heat-ledger.jsonl").write_text("")
    else:
        run = tmp_path / "docs" / "research" / "flux-melange" / "nope"
    assert run_script(SCAN_SCRIPT, ["--run-dir", str(run)], cwd=ctx.tmp).returncode == 23


def test_missing_run_dir_argument_is_exit_2(ctx):
    assert run_script(SCAN_SCRIPT, [], cwd=ctx.tmp).returncode == 2


def test_unknown_option_is_exit_2(ctx):
    assert run_script(SCAN_SCRIPT, ["--run-dir", str(ctx.run), "--fast"], cwd=ctx.tmp).returncode == 2


def test_missing_gitleaks_is_a_scanner_failure_not_a_pass(ctx, tmp_path):
    empty_bin = tmp_path / "nobin"
    empty_bin.mkdir()
    env = {"PATH": str(empty_bin), "HOME": str(tmp_path / "nohome"), "LANG": "C.UTF-8"}
    proc = scan(ctx, env=env)
    assert proc.returncode == 22


def test_a_gitleaks_that_always_succeeds_is_not_trusted_for_a_missing_config(ctx, tmp_path):
    """A stub reporting no leaks must not turn residue into a pass when it ignores the config."""
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    stub = stub_dir / "gitleaks"
    stub.write_text('#!/bin/sh\nif [ "$1" = version ]; then echo 8.30.1; exit 0; fi\ncat >/dev/null\nexit 0\n')
    stub.chmod(0o755)
    (ctx.run / "melange-state.json").write_text(json.dumps({"round": 1, "note": AWS_KEY}))
    env = {"PATH": str(stub_dir), "HOME": str(tmp_path / "nohome"), "LANG": "C.UTF-8"}
    proc = scan(ctx, env=env)
    # Independent fault: the scanner's own pattern check must still catch residue the stub missed.
    assert proc.returncode in (20, 22)


def test_a_wrong_gitleaks_version_is_exit_22(ctx, tmp_path):
    stub_dir = tmp_path / "stub2"
    stub_dir.mkdir()
    stub = stub_dir / "gitleaks"
    stub.write_text('#!/bin/sh\nif [ "$1" = version ]; then echo 8.0.0; exit 0; fi\nexit 0\n')
    stub.chmod(0o755)
    env = {"PATH": str(stub_dir), "HOME": str(tmp_path / "nohome"), "LANG": "C.UTF-8"}
    assert scan(ctx, env=env).returncode == 22


def test_gitleaks_environment_overrides_are_ignored(ctx, tmp_path):
    bogus = tmp_path / "bogus.toml"
    bogus.write_text("title = 'empty'\n")
    (ctx.run / "melange-state.json").write_text(json.dumps({"round": 1, "note": SLACK_TOKEN}))
    env = clean_env({"GITLEAKS_CONFIG": str(bogus), "GITLEAKS_CONFIG_TOML": "title = 'empty'"})
    assert scan(ctx, env=env).returncode == 20


def test_gitleaks_allow_comments_do_not_suppress_residue(ctx):
    (ctx.run / "round-1-synthesis.md").write_text(f"{AWS_KEY} # gitleaks:allow\n")
    assert scan(ctx).returncode == 20


def test_scanner_runs_under_isolated_mode_and_ignores_cwd_decoys(ctx, tmp_path):
    decoys = tmp_path / "decoys"
    decoys.mkdir()
    marker = tmp_path / "decoy-ran"
    for name in ("sanitize_untrusted.py", "json.py", "subprocess.py", "redact_melange_write.py"):
        (decoys / name).write_text(f"open({str(marker)!r}, 'w').write('ran')\n")
    proc = scan(ctx, cwd=decoys, env=clean_env({"PYTHONPATH": str(decoys)}))
    assert proc.returncode == 0, proc.stderr
    assert not marker.exists()


def test_scanner_source_never_uses_a_shell_or_writes():
    source = SCAN_SCRIPT.read_text()
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert "shell=True" not in code and "os.system" not in code
    for banned in ("write_text(", "write_bytes(", "os.rename(", "os.replace(", "shutil.rmtree", "os.remove(", "unlink("):
        assert banned not in code, banned
    assert "spec_from_file_location" in code


def test_scanner_clears_gitleaks_environment_variables(ctx):
    source = SCAN_SCRIPT.read_text()
    assert "GITLEAKS_CONFIG" in source
    assert "--ignore-gitleaks-allow" in source
    assert "--max-decode-depth" in source and "--max-archive-depth" in source
    assert "--redact=100" in source or "--redact" in source


def test_scan_exit_codes_are_defined():
    mod = load_module("scan_codes", SCAN_SCRIPT)
    codes = {getattr(mod, n) for n in dir(mod) if n.startswith("EXIT_") and isinstance(getattr(mod, n), int)}
    assert codes >= {0, 2, 20, 22, 23}


# ------------------------------------------------- review follow-up


def test_escaped_secret_in_markdown_is_residue(ctx):
    (ctx.run / "note.md").write_text("evidence: \\u0041" + AWS_KEY[1:] + "\n")
    assert scan(ctx).returncode == 20


def test_secret_in_an_overwritten_duplicate_json_key_is_residue(ctx):
    escaped = "\\u0041" + AWS_KEY[1:]
    (ctx.run / "dup.json").write_text('{"k": "' + escaped + '", "k": "clean"}\n')
    assert scan(ctx).returncode == 20


def test_scanner_refuses_a_file_swapped_for_a_symlink_after_listing(ctx, monkeypatch):
    mod = load_module("scan_swap", SCAN_SCRIPT)
    target = ctx.run / "note.md"
    target.write_text("clean\n")
    decoy = ctx.tmp / "decoy.md"
    decoy.write_text("clean\n")
    real_open = mod._open_nofollow

    def swap_first(name, dir_fd, flags):
        if name == "note.md":
            os.unlink(target)
            os.symlink(decoy, target)
        return real_open(name, dir_fd, flags)

    monkeypatch.setattr(mod, "_open_nofollow", swap_first)
    with pytest.raises(mod.ScannerFailure):
        list(mod.walk_files(ctx.run))
