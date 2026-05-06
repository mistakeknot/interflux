"""Unit tests for scripts/lib_registry.py.

Run from the interflux plugin root:
    python3 -m pytest scripts/tests/test_lib_registry.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# Make scripts/ importable regardless of cwd
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import lib_registry as lr  # noqa: E402

LIB_PY = str(ROOT / "scripts" / "lib_registry.py")


# --- normalize_models ------------------------------------------------------


def test_normalize_models_none() -> None:
    reg: dict = {"models": None}
    lr.normalize_models(reg)
    assert reg["models"] == {}


def test_normalize_models_missing_key() -> None:
    reg: dict = {}
    lr.normalize_models(reg)
    assert reg["models"] == {}


def test_normalize_models_empty_dict() -> None:
    reg: dict = {"models": {}}
    lr.normalize_models(reg)
    assert reg["models"] == {}


def test_normalize_models_dict_passthrough() -> None:
    reg = {"models": {"slug-a": {"provider": "x"}, "slug-b": {"provider": "y"}}}
    lr.normalize_models(reg)
    assert reg["models"]["slug-a"] == {"provider": "x"}
    assert reg["models"]["slug-b"] == {"provider": "y"}


def test_normalize_models_list_to_dict() -> None:
    reg = {
        "models": [
            {"model_id": "slug-a", "provider": "x"},
            {"model_id": "slug-b", "provider": "y"},
        ]
    }
    lr.normalize_models(reg)
    assert isinstance(reg["models"], dict)
    assert reg["models"]["slug-a"] == {"provider": "x"}
    assert "model_id" not in reg["models"]["slug-a"]


def test_normalize_models_list_skips_non_dicts() -> None:
    reg: dict = {"models": [{"model_id": "ok", "provider": "x"}, "garbage", 42]}
    lr.normalize_models(reg)
    assert reg["models"] == {"ok": {"provider": "x"}}


def test_normalize_models_list_skips_missing_id() -> None:
    reg: dict = {"models": [{"provider": "no-id-here"}, {"model_id": "ok"}]}
    lr.normalize_models(reg)
    assert "ok" in reg["models"]
    assert len(reg["models"]) == 1


def test_normalize_models_idempotent() -> None:
    reg = {"models": {"a": {"x": 1}}}
    lr.normalize_models(reg)
    lr.normalize_models(reg)
    assert reg["models"] == {"a": {"x": 1}}


def test_normalize_models_rejects_scalar() -> None:
    with pytest.raises(ValueError, match="must be a dict or list"):
        lr.normalize_models({"models": "not-a-collection"})


# --- get_model -------------------------------------------------------------


def test_get_model_dict_hit() -> None:
    reg = {"models": {"slug-a": {"provider": "x"}}}
    assert lr.get_model(reg, "slug-a") == {"provider": "x"}


def test_get_model_dict_miss() -> None:
    reg = {"models": {"slug-a": {}}}
    assert lr.get_model(reg, "missing") is None


def test_get_model_list_hit() -> None:
    reg = {"models": [{"model_id": "slug-a", "provider": "x"}]}
    model = lr.get_model(reg, "slug-a")
    assert model is not None
    assert model.get("provider") == "x"


def test_get_model_list_miss() -> None:
    reg = {"models": [{"model_id": "slug-a"}]}
    assert lr.get_model(reg, "other") is None


def test_get_model_none_models() -> None:
    assert lr.get_model({"models": None}, "anything") is None


def test_get_model_missing_models_key() -> None:
    assert lr.get_model({}, "anything") is None


# --- set_model_field -------------------------------------------------------


def test_set_field_existing() -> None:
    reg = {"models": {"a": {"status": "candidate"}}}
    assert lr.set_model_field(reg, "a", "status", "qualified") is True
    assert reg["models"]["a"]["status"] == "qualified"


def test_set_field_new_key() -> None:
    reg = {"models": {"a": {}}}
    assert lr.set_model_field(reg, "a", "shadow_runs", 5) is True
    assert reg["models"]["a"]["shadow_runs"] == 5


def test_set_field_missing_slug() -> None:
    reg = {"models": {}}
    assert lr.set_model_field(reg, "missing", "x", 1) is False


def test_set_field_complex_value() -> None:
    reg = {"models": {"a": {}}}
    payload = {"recall": 0.9, "precision": 0.85}
    lr.set_model_field(reg, "a", "qualification", payload)
    assert reg["models"]["a"]["qualification"] == payload


# --- set_model_field_if_absent --------------------------------------------


def test_set_field_if_absent_creates() -> None:
    reg = {"models": {"a": {}}}
    assert lr.set_model_field_if_absent(reg, "a", "qualified_baseline", {"recall": 0.9}) is True
    assert reg["models"]["a"]["qualified_baseline"] == {"recall": 0.9}


def test_set_field_if_absent_preserves_existing() -> None:
    reg = {"models": {"a": {"qualified_baseline": {"recall": 0.7}}}}
    lr.set_model_field_if_absent(reg, "a", "qualified_baseline", {"recall": 0.99})
    assert reg["models"]["a"]["qualified_baseline"] == {"recall": 0.7}


def test_set_field_if_absent_treats_none_as_absent() -> None:
    reg = {"models": {"a": {"qualified_baseline": None}}}
    lr.set_model_field_if_absent(reg, "a", "qualified_baseline", {"new": 1})
    assert reg["models"]["a"]["qualified_baseline"] == {"new": 1}


def test_set_field_if_absent_missing_slug() -> None:
    reg = {"models": {}}
    assert lr.set_model_field_if_absent(reg, "missing", "x", 1) is False


# --- merge_model_fields ----------------------------------------------------


def test_merge_fields_existing_model() -> None:
    reg = {"models": {"a": {"status": "candidate", "old_key": "kept"}}}
    lr.merge_model_fields(reg, "a", {"status": "qualified", "new_key": 5})
    assert reg["models"]["a"]["status"] == "qualified"
    assert reg["models"]["a"]["old_key"] == "kept"
    assert reg["models"]["a"]["new_key"] == 5


def test_merge_fields_creates_model_if_absent() -> None:
    reg: dict = {"models": {}}
    lr.merge_model_fields(reg, "newslug", {"status": "candidate", "provider": "openrouter"})
    assert reg["models"]["newslug"] == {"status": "candidate", "provider": "openrouter"}


def test_merge_fields_normalizes_list_models() -> None:
    reg = {"models": [{"model_id": "a", "status": "x"}]}
    lr.merge_model_fields(reg, "a", {"status": "qualified"})
    assert isinstance(reg["models"], dict)
    assert reg["models"]["a"]["status"] == "qualified"


def test_merge_fields_shallow_replaces_nested_dict() -> None:
    """Shallow merge: a nested dict in fields replaces the existing nested dict entirely."""
    reg = {"models": {"a": {"fluxbench": {"old_metric": 1, "preserved": 99}}}}
    lr.merge_model_fields(reg, "a", {"fluxbench": {"new_metric": 2}})
    # Shallow: 'preserved' is gone because the whole 'fluxbench' was replaced
    assert reg["models"]["a"]["fluxbench"] == {"new_metric": 2}


def test_merge_fields_rejects_non_dict() -> None:
    reg: dict = {"models": {}}
    with pytest.raises(ValueError, match="must be a dict"):
        lr.merge_model_fields(reg, "a", "not-a-dict")  # type: ignore[arg-type]


# --- promote_model ---------------------------------------------------------


def test_promote_existing_with_qualified_via(capsys: pytest.CaptureFixture) -> None:
    reg = {"models": {"a": {"status": "candidate", "qualified_via": "v0.2.59"}}}
    assert lr.promote_model(reg, "a") is True
    assert reg["models"]["a"]["status"] == "qualified"
    assert reg["models"]["a"]["qualified_via"] == "v0.2.59"
    assert "WARNING" not in capsys.readouterr().err


def test_promote_existing_without_qualified_via(capsys: pytest.CaptureFixture) -> None:
    reg = {"models": {"a": {"status": "candidate"}}}
    assert lr.promote_model(reg, "a") is True
    assert reg["models"]["a"]["status"] == "qualified"
    assert reg["models"]["a"]["qualified_via"] == "unknown"
    assert "WARNING" in capsys.readouterr().err


def test_promote_missing_slug() -> None:
    reg: dict = {"models": {}}
    assert lr.promote_model(reg, "x") is False


# --- load + dump round-trip ------------------------------------------------


def test_load_registry_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {"a": {"status": "candidate"}}, "providers": {"claude": {}}}))
    reg = lr.load_registry(str(p))
    assert reg["models"]["a"]["status"] == "candidate"
    assert reg["providers"]["claude"] == {}


def test_load_registry_normalizes_list(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": [{"model_id": "a", "status": "candidate"}]}))
    reg = lr.load_registry(str(p))
    assert reg["models"] == {"a": {"status": "candidate"}}


def test_load_registry_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text("")
    reg = lr.load_registry(str(p))
    assert reg == {"models": {}}


def test_load_registry_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text("not: yaml: : :")
    with pytest.raises(yaml.YAMLError):
        lr.load_registry(str(p))


def test_load_registry_non_mapping_root(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump([1, 2, 3]))
    with pytest.raises(ValueError, match="root must be a mapping"):
        lr.load_registry(str(p))


def test_validate_and_dump_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    reg = {"models": {"a": {"status": "qualified"}}}
    lr.validate_and_dump(reg, str(p))
    reread = lr.load_registry(str(p))
    assert reread["models"]["a"]["status"] == "qualified"


# --- CLI -------------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, LIB_PY, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_set_field_success(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {"a": {"status": "candidate"}}}))
    rc = _run_cli("set-field", str(p), "a", "status", '"qualified"').returncode
    assert rc == 0
    reg = yaml.safe_load(p.read_text())
    assert reg["models"]["a"]["status"] == "qualified"


def test_cli_set_field_missing_slug(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {}}))
    result = _run_cli("set-field", str(p), "missing", "x", "1")
    assert result.returncode == 3
    assert "not found" in result.stderr


def test_cli_set_field_complex_json(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {"a": {}}}))
    payload = json.dumps({"recall": 0.9, "precision": 0.85})
    rc = _run_cli("set-field", str(p), "a", "qualification", payload).returncode
    assert rc == 0
    reg = yaml.safe_load(p.read_text())
    assert reg["models"]["a"]["qualification"] == {"recall": 0.9, "precision": 0.85}


def test_cli_set_field_if_absent_creates(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {"a": {}}}))
    rc = _run_cli("set-field-if-absent", str(p), "a", "qualified_baseline", '{"recall":0.9}').returncode
    assert rc == 0
    reg = yaml.safe_load(p.read_text())
    assert reg["models"]["a"]["qualified_baseline"] == {"recall": 0.9}


def test_cli_set_field_if_absent_preserves(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {"a": {"qualified_baseline": {"recall": 0.7}}}}))
    rc = _run_cli("set-field-if-absent", str(p), "a", "qualified_baseline", '{"recall":0.99}').returncode
    assert rc == 0
    reg = yaml.safe_load(p.read_text())
    assert reg["models"]["a"]["qualified_baseline"] == {"recall": 0.7}


def test_cli_merge_fields_existing(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {"a": {"status": "candidate"}}}))
    payload = json.dumps({"status": "qualified", "qualified_via": "v0.2.61"})
    rc = _run_cli("merge-fields", str(p), "a", payload).returncode
    assert rc == 0
    reg = yaml.safe_load(p.read_text())
    assert reg["models"]["a"]["status"] == "qualified"
    assert reg["models"]["a"]["qualified_via"] == "v0.2.61"


def test_cli_merge_fields_creates_model(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {}}))
    rc = _run_cli("merge-fields", str(p), "new", '{"status":"candidate"}').returncode
    assert rc == 0
    reg = yaml.safe_load(p.read_text())
    assert reg["models"]["new"]["status"] == "candidate"


def test_cli_merge_fields_rejects_non_object(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {"a": {}}}))
    result = _run_cli("merge-fields", str(p), "a", '"a string not an object"')
    assert result.returncode == 4
    assert "must be a JSON object" in result.stderr


def test_cli_promote_success(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {"a": {"qualified_via": "v0.2.61"}}}))
    rc = _run_cli("promote", str(p), "a").returncode
    assert rc == 0
    reg = yaml.safe_load(p.read_text())
    assert reg["models"]["a"]["status"] == "qualified"
    assert reg["models"]["a"]["qualified_via"] == "v0.2.61"


def test_cli_promote_warns_without_qualified_via(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {"a": {}}}))
    result = _run_cli("promote", str(p), "a")
    assert result.returncode == 0
    assert "WARNING" in result.stderr


def test_cli_validate_pass(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {"a": {}}}))
    assert _run_cli("validate", str(p)).returncode == 0


def test_cli_validate_fail(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(":\n  unbalanced: [")
    result = _run_cli("validate", str(p))
    assert result.returncode == 2
    assert "parse error" in result.stderr


def test_cli_missing_file() -> None:
    result = _run_cli("validate", "/nonexistent/path/reg.yaml")
    assert result.returncode == 2


def test_cli_invalid_json_value(tmp_path: Path) -> None:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.dump({"models": {"a": {}}}))
    result = _run_cli("set-field", str(p), "a", "x", "not-json{")
    assert result.returncode == 4
    assert "invalid JSON" in result.stderr


def test_cli_unknown_op() -> None:
    result = _run_cli("teleport", "x")
    assert result.returncode == 4


def test_cli_no_args() -> None:
    result = _run_cli()
    assert result.returncode == 4
