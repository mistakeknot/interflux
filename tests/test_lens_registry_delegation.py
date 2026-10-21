"""The Interflux adapter must only reuse a Linsenkasten match."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "lib_lens_registry.py"


@pytest.fixture
def adapter():
    spec = importlib.util.spec_from_file_location("interflux_lens_adapter", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("outcome,reason", [
    ("unavailable", "epoch-drift"),
    ("unavailable", "embedder-unreachable"),
    ("indeterminate", "near-threshold"),
    ("miss", "below-threshold"),
])
def test_nonmatch_outcomes_render_fresh(tmp_path, monkeypatch, adapter, outcome, reason):
    registry = tmp_path / "registry"
    (registry / "data" / "generated").mkdir(parents=True)
    (registry / "data" / "generated" / "index.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setenv("LINSENKASTEN_ROOT", str(registry))
    seen = []

    def fake_resolve(spec, *, root, epoch):
        seen.append((spec, root, epoch))
        return {"outcome": outcome, "reason": reason, "registry_id": None}

    monkeypatch.setattr(adapter, "_resolver_module", lambda: SimpleNamespace(resolve=fake_resolve))
    assert adapter.resolve({"name": "fd-fresh"}) is None
    assert seen == [({"name": "fd-fresh"}, registry, "active")]


def test_match_is_passed_through_with_lineage(tmp_path, monkeypatch, adapter):
    registry = tmp_path / "registry"
    (registry / "data" / "generated").mkdir(parents=True)
    (registry / "data" / "generated" / "index.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setenv("LINSENKASTEN_ROOT", str(registry))
    result = {"outcome": "match", "registry_id": "gen:fd-example@abcd", "backend": "linsenkasten"}
    monkeypatch.setattr(adapter, "_resolver_module", lambda: SimpleNamespace(resolve=lambda *a, **k: result))
    assert adapter.resolve({"name": "fd-example"}) is result


def test_unavailable_package_renders_fresh(tmp_path, monkeypatch, adapter):
    registry = tmp_path / "registry"
    (registry / "data" / "generated").mkdir(parents=True)
    (registry / "data" / "generated" / "index.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setenv("LINSENKASTEN_ROOT", str(registry))
    monkeypatch.setattr(adapter, "_resolver_module", lambda: None)
    assert adapter.resolve({"name": "fd-fresh"}) is None


def test_reuse_log_delegates_match_to_linsenkasten(tmp_path, monkeypatch, adapter):
    match = {"outcome": "match", "registry_id": "gen:fd-example@abcd", "backend": "linsenkasten"}
    calls = []

    def record(result, **fields):
        calls.append((result, fields))
        return tmp_path / "reuse-log.jsonl"

    monkeypatch.setattr(adapter, "_resolver_module", lambda: SimpleNamespace(record_reuse=record))
    path = adapter.record_reuse(match, name="fd-example", consumer="flux-gen", project="demo", target="agent.md")
    assert path == tmp_path / "reuse-log.jsonl"
    assert calls == [(match, {"name": "fd-example", "consumer": "flux-gen", "project": "demo", "target": "agent.md"})]
