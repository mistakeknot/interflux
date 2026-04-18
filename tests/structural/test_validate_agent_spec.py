"""Tests for scripts/spec_types.py — AgentSpec validation and normalization.

Covers the LLM-JSON → render_agent boundary gap that produced the anti_overlap
v0.2.58 incident (116 corrupted files). Fixtures fall into four classes:

  1. Wrapper-unwrap: dict-wrapped specs under various keys
  2. Field normalization: paragraph strings, comma domains, quoted numerics
  3. Name validation: path-traversal attempts, Unicode, blank names
  4. Severity examples: malformed structures, bad severities
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from spec_types import (  # noqa: E402
    _normalize_bullet_list,
    _normalize_domains,
    _normalize_severity_examples,
    _unwrap_spec_list,
    validate_agent_spec,
)


# ---------------------------------------------------------------------------
# _unwrap_spec_list
# ---------------------------------------------------------------------------

class TestUnwrapSpecList:
    def test_bare_list_passes_through(self):
        specs, note = _unwrap_spec_list([{"name": "fd-x"}])
        assert specs == [{"name": "fd-x"}]
        assert note is None

    def test_empty_list_passes_through(self):
        specs, note = _unwrap_spec_list([])
        assert specs == []
        assert note is None

    def test_agents_wrapper_unwrapped(self):
        specs, note = _unwrap_spec_list({"agents": [{"name": "fd-x"}, {"name": "fd-y"}]})
        assert specs == [{"name": "fd-x"}, {"name": "fd-y"}]
        assert note is not None and "unwrapped" in note

    def test_specs_wrapper_unwrapped(self):
        specs, note = _unwrap_spec_list({"specs": [{"name": "fd-x"}]})
        assert specs == [{"name": "fd-x"}]
        assert note is not None

    def test_arbitrary_key_name_still_unwrapped(self):
        specs, _ = _unwrap_spec_list({"random_key": [{"name": "fd-x"}]})
        assert specs == [{"name": "fd-x"}]

    def test_dict_with_no_list_entries_returns_empty(self):
        specs, note = _unwrap_spec_list({"metadata": "foo", "version": 1})
        assert specs == []
        assert note and "no list-valued" in note

    def test_dict_with_multiple_list_entries_is_ambiguous(self):
        specs, note = _unwrap_spec_list({"agents": [1], "specs": [2]})
        assert specs == []
        assert note and "ambiguous" in note

    def test_non_list_non_dict_root_rejected(self):
        specs, note = _unwrap_spec_list("a string")
        assert specs == []
        assert note and "str" in note

    def test_null_root_rejected(self):
        specs, note = _unwrap_spec_list(None)
        assert specs == []


# ---------------------------------------------------------------------------
# _normalize_bullet_list
# ---------------------------------------------------------------------------

class TestNormalizeBulletList:
    def test_already_list(self):
        assert _normalize_bullet_list(["one", "two"]) == ["one", "two"]

    def test_paragraph_string_split_on_newline(self):
        assert _normalize_bullet_list("one\ntwo\nthree") == ["one", "two", "three"]

    def test_semicolon_joined_string(self):
        assert _normalize_bullet_list("one; two; three") == ["one", "two", "three"]

    def test_empty_string_returns_empty(self):
        assert _normalize_bullet_list("") == []

    def test_none_returns_empty(self):
        assert _normalize_bullet_list(None) == []

    def test_strips_whitespace_per_item(self):
        assert _normalize_bullet_list(["  one  ", "two"]) == ["one", "two"]

    def test_filters_empty_items(self):
        assert _normalize_bullet_list(["one", "", "  ", "two"]) == ["one", "two"]

    def test_coerces_non_string_list_items(self):
        assert _normalize_bullet_list([1, 2]) == ["1", "2"]


# ---------------------------------------------------------------------------
# _normalize_domains
# ---------------------------------------------------------------------------

class TestNormalizeDomains:
    def test_bare_list(self):
        assert _normalize_domains(["security", "auth"]) == ["security", "auth"]

    def test_comma_joined_string(self):
        assert _normalize_domains("security, auth, data-modeling") == ["security", "auth", "data-modeling"]

    def test_semicolon_joined_string(self):
        assert _normalize_domains("security; auth") == ["security", "auth"]

    def test_list_with_comma_inside_item_still_split(self):
        assert _normalize_domains(["security, auth"]) == ["security", "auth"]

    def test_empty_string_returns_empty(self):
        assert _normalize_domains("") == []

    def test_none_returns_empty(self):
        assert _normalize_domains(None) == []


# ---------------------------------------------------------------------------
# _normalize_severity_examples
# ---------------------------------------------------------------------------

class TestNormalizeSeverityExamples:
    def test_well_formed_examples_pass(self):
        raw = [
            {"severity": "P0", "scenario": "data loss", "condition": "always"},
            {"severity": "P1", "scenario": "quality gate", "condition": ""},
        ]
        out = _normalize_severity_examples(raw)
        assert len(out) == 2
        assert out[0]["severity"] == "P0"
        assert out[0]["condition"] == "always"
        assert "condition" not in out[1]

    def test_non_list_returns_empty(self):
        assert _normalize_severity_examples("not a list") == []
        assert _normalize_severity_examples(None) == []

    def test_drops_non_dict_items(self):
        assert _normalize_severity_examples(["P0: thing"]) == []

    def test_drops_missing_scenario(self):
        out = _normalize_severity_examples([{"severity": "P0"}])
        assert out == []

    def test_drops_invalid_severity(self):
        out = _normalize_severity_examples([{"severity": "P99", "scenario": "x"}])
        assert out == []

    def test_severity_uppercased(self):
        out = _normalize_severity_examples([{"severity": "p0 ", "scenario": "x"}])
        assert out[0]["severity"] == "P0"


# ---------------------------------------------------------------------------
# validate_agent_spec
# ---------------------------------------------------------------------------

class TestValidateAgentSpec:
    def _base_spec(self) -> dict:
        return {"name": "fd-test-reviewer", "focus": "test focus"}

    def test_minimal_valid_spec(self):
        ok, errors, norm = validate_agent_spec(self._base_spec())
        assert ok
        assert errors == []
        assert norm["name"] == "fd-test-reviewer"
        assert norm["focus"] == "test focus"

    def test_missing_name_rejected(self):
        ok, errors, _ = validate_agent_spec({"focus": "x"})
        assert not ok
        assert any("name" in e for e in errors)

    def test_missing_focus_rejected(self):
        ok, errors, _ = validate_agent_spec({"name": "fd-x"})
        assert not ok
        assert any("focus" in e for e in errors)

    def test_name_path_traversal_rejected(self):
        spec = self._base_spec()
        spec["name"] = "fd-../../etc/cron.d/evil"
        ok, errors, _ = validate_agent_spec(spec)
        assert not ok
        assert any("name" in e for e in errors)

    def test_name_missing_fd_prefix_rejected(self):
        spec = self._base_spec()
        spec["name"] = "not-fd-prefix"
        ok, errors, _ = validate_agent_spec(spec)
        assert not ok

    def test_name_with_uppercase_rejected(self):
        spec = self._base_spec()
        spec["name"] = "fd-BadCase"
        ok, _, _ = validate_agent_spec(spec)
        assert not ok

    def test_name_with_underscores_rejected(self):
        spec = self._base_spec()
        spec["name"] = "fd-snake_case"
        ok, _, _ = validate_agent_spec(spec)
        assert not ok

    def test_non_dict_spec_rejected(self):
        ok, errors, _ = validate_agent_spec("not a dict")
        assert not ok
        assert any("expected dict" in e for e in errors)

    def test_review_areas_paragraph_string_normalized(self):
        spec = self._base_spec()
        spec["review_areas"] = "one;two;three"
        ok, _, norm = validate_agent_spec(spec)
        assert ok
        assert norm["review_areas"] == ["one", "two", "three"]

    def test_review_areas_list_preserved(self):
        spec = self._base_spec()
        spec["review_areas"] = ["alpha", "beta"]
        ok, _, norm = validate_agent_spec(spec)
        assert ok
        assert norm["review_areas"] == ["alpha", "beta"]

    def test_anti_overlap_normalized(self):
        spec = self._base_spec()
        spec["anti_overlap"] = ["auth flow", ""]
        ok, _, norm = validate_agent_spec(spec)
        assert ok
        assert norm["anti_overlap"] == ["auth flow"]

    def test_flux_gen_version_int_preserved(self):
        spec = self._base_spec()
        spec["flux_gen_version"] = 6
        ok, _, norm = validate_agent_spec(spec)
        assert ok
        assert norm["flux_gen_version"] == 6

    def test_flux_gen_version_string_coerced(self):
        spec = self._base_spec()
        spec["flux_gen_version"] = "6"
        ok, _, norm = validate_agent_spec(spec)
        assert ok
        assert norm["flux_gen_version"] == 6

    def test_flux_gen_version_invalid_flagged(self):
        spec = self._base_spec()
        spec["flux_gen_version"] = "vSix"
        ok, errors, _ = validate_agent_spec(spec)
        assert not ok
        assert any("flux_gen_version" in e for e in errors)

    def test_severity_examples_normalized(self):
        spec = self._base_spec()
        spec["severity_examples"] = [
            {"severity": "P0", "scenario": "crash"},
            {"severity": "P99", "scenario": "bogus"},  # dropped
        ]
        ok, _, norm = validate_agent_spec(spec)
        assert ok
        assert len(norm["severity_examples"]) == 1
        assert norm["severity_examples"][0]["severity"] == "P0"

    def test_string_field_coerced_from_non_string(self):
        spec = self._base_spec()
        spec["persona"] = 42
        ok, errors, norm = validate_agent_spec(spec)
        assert not ok
        assert any("persona" in e for e in errors)
        assert norm["persona"] == "42"

    def test_unicode_field_preserved(self):
        spec = self._base_spec()
        spec["persona"] = "レビューア"
        ok, _, norm = validate_agent_spec(spec)
        assert ok
        assert norm["persona"] == "レビューア"

    def test_custom_name_pattern_applied(self):
        ok, _, _ = validate_agent_spec(
            {"name": "review-agent", "focus": "x"},
            name_pattern=r"^[a-z]+-[a-z]+$",
        )
        assert ok

    def test_empty_name_string_rejected(self):
        spec = self._base_spec()
        spec["name"] = ""
        ok, _, _ = validate_agent_spec(spec)
        assert not ok

    def test_all_string_fields_round_trip(self):
        spec = {
            "name": "fd-full",
            "focus": "testing",
            "persona": "reviewer",
            "decision_lens": "impact first",
            "task_context": "review X",
            "source_domain": "shipbuilding",
        }
        ok, _, norm = validate_agent_spec(spec)
        assert ok
        for field in spec:
            assert norm[field] == spec[field]
