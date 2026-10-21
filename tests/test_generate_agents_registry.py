from __future__ import annotations

import json
import os
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "generate-agents.py"
WORKFLOW = (
    REPO_ROOT
    / "skills"
    / "flux-melange-engine"
    / "workflow"
    / "melange-workflow.js"
)
SEED_PHASE = (
    REPO_ROOT / "skills" / "flux-melange-engine" / "phases" / "seed.md"
)
TRACK_DISPATCH = (
    REPO_ROOT / "skills" / "flux-review-engine" / "phases" / "track-dispatch.md"
)
SHARED_CONTRACTS = (
    REPO_ROOT / "skills" / "flux-engine" / "phases" / "shared-contracts.md"
)
REGISTRY_ID = "gen:fd-registry-match@aaaaaaaa"


def _write_fixture_registry(root: Path) -> None:
    generated = root / "data" / "generated"
    lenses = generated / "lenses"
    lenses.mkdir(parents=True)
    record = {
        "id": REGISTRY_ID,
        "name": "fd-registry-match",
        "summary": "registry match",
        "cluster": {"head": True, "id": "cluster-a"},
        "cohort": {"siblings": ["fd-registry-match"]},
        "corrupt": False,
        "body_path": f"generated/lenses/{REGISTRY_ID}.md",
        "spec_path": None,
    }
    (generated / "index.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    (lenses / f"{REGISTRY_ID}.md").write_text(
        "---\n"
        "name: fd-registry-match\n"
        "description: Canonical registry reviewer\n"
        "generated_by: flux-gen-prompt\n"
        "tier: generated\n"
        "---\n"
        "# Canonical registry body\n",
        encoding="utf-8",
    )


def _write_specs(
    path: Path,
    *,
    name: str = "fd-registry-match",
    focus: str = "Registry match.",
) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "name": name,
                    "focus": focus,
                    "review_areas": ["Check registry reuse."],
                }
            ]
        ),
        encoding="utf-8",
    )


def _write_existing_agent(project: Path) -> Path:
    target = project / ".claude" / "agents" / "fd-registry-match.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "---\n"
        "name: fd-registry-match\n"
        "generated_by: flux-gen-prompt\n"
        "flux_gen_version: 6\n"
        "tier: generated\n"
        "---\n"
        "# Stale local copy\n",
        encoding="utf-8",
    )
    return target


def _run_generator(
    project: Path,
    specs: Path,
    registry_root: Path,
    *extra: str,
    home: Path | None = None,
) -> tuple[dict, subprocess.CompletedProcess[str]]:
    if "--registry=off" not in extra and (registry_root / "data" / "generated" / "index.jsonl").is_file():
        source = os.environ.get("LINSENKASTEN_PACKAGE_ROOT")
        if not (source and (Path(source) / "linsenkasten" / "resolve.py").is_file()):
            try:
                installed = importlib.util.find_spec("linsenkasten.resolve") is not None
            except ModuleNotFoundError:
                installed = False
            if not installed:
                pytest.skip("Linsenkasten source package is unavailable for integration tests")
    env = os.environ.copy()
    env["LINSENKASTEN_ROOT"] = str(registry_root)
    env["LINSENKASTEN_OLLAMA_URL"] = "http://127.0.0.1:1"
    env.pop("LINSENKASTEN_OLLAMA_FALLBACK_URL", None)
    if home is not None:
        env["HOME"] = str(home)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(project),
            "--from-specs",
            str(specs),
            "--mode=skip-existing",
            "--json",
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout), result


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end])


def test_registry_auto_materializes_before_skip_existing_and_records_reuse(tmp_path):
    registry_root = tmp_path / "registry"
    project = tmp_path / "project"
    specs = tmp_path / "specs.json"
    home = tmp_path / "home"
    home.mkdir()
    project.mkdir()
    _write_fixture_registry(registry_root)
    _write_specs(specs)
    target = _write_existing_agent(project)

    report, _ = _run_generator(project, specs, registry_root, home=home)

    assert report["generated"] == []
    assert report["skipped"] == []
    assert report["reused"] == [
        {
            "name": "fd-registry-match",
            "registry_id": REGISTRY_ID,
            "score": 1.0,
            "method": "lexical",
            "embed_tier": "lexical",
        }
    ]
    frontmatter = _frontmatter(target)
    assert frontmatter["tier"] == "registry"
    assert frontmatter["registry_id"] == REGISTRY_ID
    assert "Canonical registry body" in target.read_text(encoding="utf-8")

    reuse_log = tmp_path / "home" / ".local" / "share" / "linsenkasten" / "reuse-log.jsonl"
    row = json.loads(reuse_log.read_text(encoding="utf-8").splitlines()[-1])
    assert row["registry_id"] == REGISTRY_ID
    assert row["consumer"] == "flux-gen"
    assert row["project"] == str(project.resolve())
    assert row["target"] == str(target)


def test_registry_off_renders_normally(tmp_path):
    registry_root = tmp_path / "registry"
    project = tmp_path / "project"
    specs = tmp_path / "specs.json"
    project.mkdir()
    _write_fixture_registry(registry_root)
    _write_specs(specs)

    report, _ = _run_generator(project, specs, registry_root, "--registry=off")

    assert report["generated"] == ["fd-registry-match"]
    assert report["reused"] == []
    target = project / ".claude" / "agents" / "fd-registry-match.md"
    assert _frontmatter(target)["tier"] == "generated"
    assert not (registry_root / "data" / "generated" / "reuse-log.jsonl").exists()


def test_registry_auto_without_available_root_renders_normally(tmp_path):
    registry_root = tmp_path / "missing-registry"
    isolated_home = tmp_path / "empty-home"
    project = tmp_path / "project"
    specs = tmp_path / "specs.json"
    isolated_home.mkdir()
    project.mkdir()
    _write_specs(specs)

    report, _ = _run_generator(
        project,
        specs,
        registry_root,
        home=isolated_home,
    )

    assert report["generated"] == ["fd-registry-match"]
    assert report["reused"] == []
    assert report["errors"] == []
    target = project / ".claude" / "agents" / "fd-registry-match.md"
    assert _frontmatter(target)["tier"] == "generated"


def test_registry_auto_without_match_renders_normally(tmp_path):
    registry_root = tmp_path / "registry"
    project = tmp_path / "project"
    specs = tmp_path / "specs.json"
    project.mkdir()
    _write_fixture_registry(registry_root)
    _write_specs(
        specs,
        name="fd-quantum-braid",
        focus="Quantum braid invariants.",
    )

    report, _ = _run_generator(project, specs, registry_root)

    assert report["generated"] == ["fd-quantum-braid"]
    assert report["reused"] == []
    assert report["errors"] == []
    target = project / ".claude" / "agents" / "fd-quantum-braid.md"
    assert _frontmatter(target)["tier"] == "generated"


def test_registry_auto_epoch_drift_renders_fresh(tmp_path):
    registry_root = tmp_path / "registry"
    project = tmp_path / "project"
    specs = tmp_path / "specs.json"
    project.mkdir()
    _write_fixture_registry(registry_root)
    _write_specs(specs)
    epochs = registry_root / "epochs"
    epochs.mkdir()
    digest = "sha256:" + "a" * 64
    (epochs / "current.json").write_text(json.dumps({"epoch": digest}), encoding="utf-8")
    (epochs / f"{'a' * 12}.json").write_text(
        json.dumps({"epoch_digest": digest, "bound": {}}), encoding="utf-8"
    )

    report, _ = _run_generator(project, specs, registry_root)

    assert report["generated"] == ["fd-registry-match"]
    assert report["reused"] == []
    assert report["errors"] == []
    assert _frontmatter(project / ".claude" / "agents" / "fd-registry-match.md")["tier"] == "generated"


def test_registry_auto_unreachable_embedder_renders_fresh(tmp_path):
    registry_root = tmp_path / "registry"
    project = tmp_path / "project"
    specs = tmp_path / "specs.json"
    project.mkdir()
    _write_fixture_registry(registry_root)
    _write_specs(specs, name="fd-new", focus="unrelated")

    report, _ = _run_generator(project, specs, registry_root)

    assert report["generated"] == ["fd-new"]
    assert report["reused"] == []
    assert report["errors"] == []


def test_registry_materialization_failure_falls_back_to_normal_generation(tmp_path):
    registry_root = tmp_path / "registry"
    project = tmp_path / "project"
    specs = tmp_path / "specs.json"
    project.mkdir()
    _write_fixture_registry(registry_root)
    _write_specs(specs)
    (registry_root / "data" / "generated" / "lenses" / f"{REGISTRY_ID}.md").unlink()

    report, _ = _run_generator(project, specs, registry_root)

    assert report["generated"] == ["fd-registry-match"]
    assert report["reused"] == []
    assert len(report["errors"]) == 1
    assert report["errors"][0].startswith(
        "Registry reuse failed for 'fd-registry-match':"
    )
    target = project / ".claude" / "agents" / "fd-registry-match.md"
    assert _frontmatter(target)["tier"] == "generated"


def test_registry_auto_dry_run_reports_reuse_without_materializing(tmp_path):
    registry_root = tmp_path / "registry"
    project = tmp_path / "project"
    specs = tmp_path / "specs.json"
    project.mkdir()
    _write_fixture_registry(registry_root)
    _write_specs(specs)

    report, _ = _run_generator(project, specs, registry_root, "--dry-run")

    assert report["generated"] == []
    assert len(report["reused"]) == 1
    assert report["reused"][0]["registry_id"] == REGISTRY_ID
    target = project / ".claude" / "agents" / "fd-registry-match.md"
    assert not target.exists()
    assert not (registry_root / "data" / "generated" / "reuse-log.jsonl").exists()


def test_melange_routes_registry_by_creative_intent():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    seed = workflow.split("async function seedRun(R) {", 1)[1].split(
        "const tiers =", 1
    )[0]
    adjacent = seed.split("ADJACENT tier:", 1)[1].split(
        'label: "seed-design:adjacent"', 1
    )[0]
    distant = seed.split("DISTANT knowledge domains", 1)[1].split(
        'label: "seed-design:distant"', 1
    )[0]
    directives = workflow.split("async function probeDirectives(R, round, directives) {", 1)[1]
    fuse = directives.split('if (d.type === "FUSE") {', 1)[1].split(
        'if (d.type === "STEER-WIDE") {', 1
    )[0]
    wide = directives.split('if (d.type === "STEER-WIDE") {', 1)[1].split(
        "dispatched += 1", 1
    )[0]

    assert '${designRules(R, "auto")}' in adjacent
    assert '${designRules(R, "off")}' in distant
    assert "--registry=off" in fuse
    assert "--registry=off" in wide


def test_phase_docs_route_registry_by_creative_intent():
    seed = SEED_PHASE.read_text(encoding="utf-8")
    track_dispatch = TRACK_DISPATCH.read_text(encoding="utf-8")

    assert "Seed adjacent" in seed
    assert "--registry=auto" in seed
    assert "Seed distant" in seed
    assert "--registry=off" in seed
    assert "Tracks A and B" in track_dispatch
    assert "--registry=auto" in track_dispatch
    assert "Tracks C and D" in track_dispatch
    assert "--registry=off" in track_dispatch


def test_shared_contract_lists_every_sanitized_agent_spec_field():
    contracts = SHARED_CONTRACTS.read_text(encoding="utf-8")

    assert (
        "focus, persona, decision_lens, task_context, review_areas, "
        "severity_examples, anti_overlap, success_hints"
    ) in contracts
