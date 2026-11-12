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
    "jwt-long-header": "ey" + "Jhbgc" + "a" * 1200 + ".abcdefgh12.ABCDEFGH12",
    "jwt-dash-before": "token-" + JWT,
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


NESTED_FORMATS = sorted(FIVE_FORMATS.items())


def _nest(text: str, depth: int) -> str:
    """Escape the first character of `text` as \\u00XX, then escape each backslash `depth` more times."""
    first = "\\u%04x" % ord(text[0])
    for _ in range(depth):
        first = first.replace("\\", "\\u005c")
    return first + text[1:]


@pytest.mark.parametrize("name,secret", NESTED_FORMATS)
def test_a_secret_behind_an_encoded_newline_is_found(ctx, name, secret):
    (ctx.run / "round-1-synthesis.md").write_text("see \\u000a" + secret + "\\u000a end\n")
    assert scan(ctx).returncode == 20


@pytest.mark.parametrize("prefix", ["\\u0000", "\\ud800", "\\U00110000", "\\x1b", "\\u007f", "\\u0085"])
def test_any_undisplayable_escape_before_a_secret_is_found(ctx, prefix):
    (ctx.run / "round-1-synthesis.md").write_text(prefix + AWS_KEY + "\n")
    assert scan(ctx).returncode == 20


@pytest.mark.parametrize("depth", [5, 20, 60])
def test_deeply_nested_escapes_are_resolved(ctx, depth):
    (ctx.run / "round-1-synthesis.md").write_text(_nest(AWS_KEY, depth) + "\n")
    assert scan(ctx).returncode == 20


def test_escapes_nested_beyond_the_decode_limit_are_a_scanner_failure(ctx):
    (ctx.run / "round-1-synthesis.md").write_text(_nest(AWS_KEY, 200) + "\n")
    assert scan(ctx).returncode == 22


def test_a_long_header_jwt_is_found_in_the_run_tree(ctx):
    token = "ey" + "Jhbgc" + "a" * 1200 + ".abcdefgh12.ABCDEFGH12"
    (ctx.run / "round-1-synthesis.md").write_text("t " + token + "\n")
    assert scan(ctx).returncode == 20


# ------------------------------- review follow-up: scanner robustness and long tokens


def _scrub():
    return load_module("hook_for_long_tokens", HOOK).scrub


def _alone(scanner, text):
    """Gitleaks as the only detector: a scrubber that never reports anything."""
    return scanner.bytes_have_residue(lambda value: value, str(GITLEAKS), text.encode(), "x.md")


@pytest.mark.parametrize("header_length", [5000, 60000])
def test_gitleaks_alone_finds_a_long_header_jwt_below_its_read_chunk(header_length):
    scanner = load_module("scan_long_jwt", SCAN_SCRIPT)
    token = "ey" + "Jhbgc" + "a" * header_length + ".abcdefgh12.ABCDEFGH12"
    assert _alone(scanner, "t=" + token + "\n") == (True, False)


@pytest.mark.parametrize("header_length", [150000, 1000000])
def test_the_scrubber_finds_a_jwt_too_long_for_gitleaks_and_gitleaks_is_not_asked(header_length):
    scanner = load_module("scan_huge_jwt", SCAN_SCRIPT)
    token = "ey" + "Jhbgc" + "a" * header_length + ".abcdefgh12.ABCDEFGH12"
    text = ("t=" + token + "\n").encode()
    assert list(scanner.gitleaks_pieces(text)) == []
    assert scanner.bytes_have_residue(_scrub(), str(GITLEAKS), text, "x.md") == (True, False)
    assert _alone(scanner, text.decode()) == (False, False)


@pytest.mark.parametrize("glue", ["\u00e9", "\u00fc", "\u4e2d"])
@pytest.mark.parametrize("token", ["npm_" + "E" * 36, "ghp_" + "E" * 36, "sk-" + "E" * 48])
def test_a_legacy_token_glued_to_a_non_ascii_letter_in_an_oversized_stretch_is_residue(glue, token):
    scanner = load_module("scan_ascii_boundary", SCAN_SCRIPT)
    text = glue + token + "=" * 82000
    # The stretch is too long to cut, so Gitleaks is not asked; the scrubber's own Unicode word
    # boundary does not see the token, Gitleaks' ASCII boundary would.
    assert list(scanner.gitleaks_pieces(text.encode())) == []
    assert _scrub()(text) == text
    assert scanner.bytes_have_residue(_scrub(), str(GITLEAKS), text.encode(), "x.md") == (True, False)


@pytest.mark.parametrize("glue", ["\u00e9", "\u0663"])
def test_bearer_context_before_an_oversized_stretch_is_kept(glue):
    scanner = load_module("scan_ascii_bearer", SCAN_SCRIPT)
    text = glue + "Bearer " + "A1b2C3d4" * 4 + "=" * 82000
    assert scanner.bytes_have_residue(_scrub(), str(GITLEAKS), text.encode(), "x.md") == (True, False)


@pytest.mark.parametrize("text", ["Beareré" + "a" * 82000, "api_keyé=" + "a" * 82000])
def test_a_filler_does_not_invent_whitespace_syntax_in_a_harmless_stretch(text):
    scanner = load_module("scan_ascii_filler", SCAN_SCRIPT)
    assert scanner.bytes_have_residue(_scrub(), str(GITLEAKS), text.encode(), "x.md") == (False, False)


def test_a_non_ascii_oversized_stretch_without_a_token_is_not_residue():
    scanner = load_module("scan_ascii_boundary_clean", SCAN_SCRIPT)
    text = "\u00e9" + "word" + "=" * 82000
    assert scanner.bytes_have_residue(_scrub(), str(GITLEAKS), text.encode(), "x.md") == (False, False)


@pytest.mark.parametrize("tail", ["=", ".fourthpart", ".="])
def test_a_rejected_jwt_shape_in_a_huge_run_is_not_residue(tail):
    scanner = load_module("scan_rejected_shape", SCAN_SCRIPT)
    text = "ey" + "Jaaaaa" + ".abcdefgh12." + "a" * 150000 + tail
    assert scanner.bytes_have_residue(_scrub(), str(GITLEAKS), text.encode(), "x.md") == (False, False)


@pytest.mark.parametrize("separator", [" ", ",", ";", "|", ")", '"', "a="])
@pytest.mark.parametrize("pad", [45000, 120000])
def test_a_rejected_shape_cannot_be_carried_across_a_gitleaks_chunk(separator, pad):
    scanner = load_module("scan_chunk_shape", SCAN_SCRIPT)
    unit = "a=" if separator == "a=" else "a" + separator
    text = unit * pad + "ey" + "Jaaaaa" + ".abcdefgh12." + "b" * 3000 + "="
    # "a=" has no break character: it is an oversized stretch and Gitleaks is not asked.
    assert scanner.bytes_have_residue(_scrub(), str(GITLEAKS), text.encode(), "x.md") == (False, False)
    assert _alone(scanner, text) == (False, False)


@pytest.mark.parametrize("before", [" ", "-", "(", "="])
def test_the_scrubber_finds_a_huge_jwt_after_each_admissible_boundary(before):
    scanner = load_module("scan_huge_boundaries", SCAN_SCRIPT)
    token = "ey" + "Jhbgc" + "a" * 150000 + ".abcdefgh12.ABCDEFGH12"
    text = "b" * 5000 + "-" + token if before == "-" else before + token
    assert scanner.bytes_have_residue(_scrub(), str(GITLEAKS), text.encode(), "x.md") == (True, False)


@pytest.mark.parametrize("before", [".", "_"])
def test_neither_detector_invents_a_huge_jwt_start_after_a_dot_or_underscore(before):
    scanner = load_module("scan_huge_refused", SCAN_SCRIPT)
    token = "ey" + "Jhbgc" + "a" * 150000 + ".abcdefgh12.ABCDEFGH12"
    assert scanner.bytes_have_residue(_scrub(), str(GITLEAKS), (before + token).encode(), "x.md") == (False, False)


def test_a_jwt_whose_payload_holds_many_header_looking_starts_is_found():
    scanner = load_module("scan_repeated_starts", SCAN_SCRIPT)
    head = "ey" + "Jaaaaa"
    text = head + "." + ("a" * 100 + "-" + head) * 2000 + ".ABCDEFGH12"
    assert scanner.bytes_have_residue(_scrub(), str(GITLEAKS), text.encode(), "x.md") == (True, False)


def test_the_unsplit_view_really_trips_gitleaks_at_a_chunk_end():
    # Guards the test above against passing vacuously: with no splitting, this shape is flagged.
    scanner = load_module("scan_unsplit", SCAN_SCRIPT)
    text = ("a " * 45000 + "ey" + "Jaaaaa" + ".abcdefgh12." + "b" * 3000 + "=").encode()
    assert scanner.gitleaks_flags(str(GITLEAKS), text) is True


@pytest.mark.parametrize("pad", [44000, 45000, 90000])
def test_a_real_jwt_is_still_found_after_a_long_run_of_short_words(pad):
    scanner = load_module("scan_words_then_jwt", SCAN_SCRIPT)
    token = "ey" + "Jhbgcd" + ".abcdefgh12.ABCDEFGH12"
    assert _alone(scanner, "a " * pad + token) == (True, False)


def test_nothing_is_transformed_so_no_rule_boundary_can_change():
    scanner = load_module("scan_untransformed", SCAN_SCRIPT)
    for view in (b"", b"abc", b"a b\n" * 30000, b"xox" + b"b-" + b"a" * 5000 + b"_", b"a," * 100000, b"a " * 70000):
        pieces = list(scanner.gitleaks_pieces(view))
        assert b"".join(pieces) == view
        assert all(len(piece) <= scanner.PIECE_MAX for piece in pieces)


@pytest.mark.parametrize("last", ["_", "a", "-"])
def test_a_long_slack_shape_is_judged_whole(last):
    scanner = load_module("scan_run_end", SCAN_SCRIPT)
    text = "xox" + "b-" + "a" * 5000 + last
    residue, failed = _alone(scanner, text)
    assert failed is False
    assert residue is (last != "_")


def test_an_underscore_inside_a_long_run_still_disqualifies_the_slack_shape():
    scanner = load_module("scan_run_inside", SCAN_SCRIPT)
    assert _alone(scanner, "xox" + "b-" + "a" * 4100 + "_" + "a" * 1000) == (False, False)


def test_a_header_that_ends_short_of_the_minimum_is_not_lengthened():
    scanner = load_module("scan_short_header", SCAN_SCRIPT)
    text = "a" * 5000 + "-ey" + "Jaaaa" + ".abcdefgh12.ABCDEFGH12"
    assert scanner.bytes_have_residue(_scrub(), str(GITLEAKS), text.encode(), "x.md") == (False, False)


def test_a_scratch_directory_fault_is_a_scanner_failure_not_a_crash(monkeypatch):
    scanner = load_module("scan_scratch_fault", SCAN_SCRIPT)

    def broken(prefix=None):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(scanner.tempfile, "TemporaryDirectory", broken)
    assert scanner.bytes_have_residue(lambda value: value, str(GITLEAKS), b"plain text", "x.md") == (False, True)


def test_a_json_surrogate_before_a_secret_is_residue_not_a_crash(ctx):
    (ctx.run / "findings.json").write_text('{"a": "\\ud800' + AWS_KEY + '"}\n')
    result = scan(ctx)
    assert result.returncode == 20
    assert "Traceback" not in result.stderr


def test_a_secret_free_surrogate_file_does_not_stop_the_scan(ctx):
    (ctx.run / "a-surrogate.json").write_text('{"a": "\\ud800 plain"}\n')
    (ctx.run / "z-later.md").write_text("key " + AWS_KEY + "\n")
    result = scan(ctx)
    assert result.returncode == 20
    assert "z-later.md" in result.stdout + result.stderr


def test_json_nested_too_deeply_is_a_scanner_failure_not_a_crash(ctx):
    (ctx.run / "deep.json").write_text("[" * 10000 + "]" * 10000 + "\n")
    result = scan(ctx)
    assert result.returncode == 22
    assert "Traceback" not in result.stderr
