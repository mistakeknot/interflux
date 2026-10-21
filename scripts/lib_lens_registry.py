"""Interflux materialization adapter for the Linsenkasten resolver.

Resolution and reuse lineage belong to ``linsenkasten.resolve``. Interflux owns only
registry discovery and rendering a matched lens as a generated agent.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

_INDEX_PATH = Path("data/generated/index.jsonl")
_NAME_PATTERN = re.compile(r"^fd-[a-z0-9]+(?:-[a-z0-9]+)*$")
_GENERATE_AGENTS_MODULE: ModuleType | None = None
_RESOLVER: ModuleType | None = None


def _cache_version_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    return tuple((0, int(part)) if part.isdigit() else (1, part.lower())
                 for part in re.findall(r"\d+|\D+", path.name))


def find_registry_root() -> Path | None:
    """Find an indexed Linsenkasten checkout or installed plugin."""
    home = Path.home()
    candidates = []
    if configured := os.environ.get("LINSENKASTEN_ROOT"):
        candidates.append(Path(configured).expanduser())
    candidates.extend((home / "projects" / "linsenkasten",
                       home / "projects" / "Sylveste" / "interverse" / "linsenkasten",
                       home / "projects" / "Sylveste" / "interverse" / "interlens"))
    cache = home / ".claude" / "plugins" / "cache" / "interagency-marketplace" / "linsenkasten"
    if cache.is_dir():
        candidates.extend(sorted((p for p in cache.iterdir() if p.is_dir()),
                                 key=_cache_version_key, reverse=True))
    return next((p for p in candidates if (p / _INDEX_PATH).is_file()), None)


def _resolver_module() -> ModuleType | None:
    """Import the sibling package when present; absent package means fresh generation."""
    global _RESOLVER
    if _RESOLVER is not None:
        return _RESOLVER
    roots = []
    if configured := os.environ.get("LINSENKASTEN_PACKAGE_ROOT"):
        roots.append(Path(configured).expanduser())
    if registry := find_registry_root():
        roots.append(registry)
    roots.append(Path.home() / "projects" / "linsenkasten")
    for root in roots:
        source = root / "linsenkasten" / "resolve.py"
        if source.is_file():
            spec = importlib.util.spec_from_file_location("linsenkasten.resolve", source)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                _RESOLVER = module
                return module
    try:
        _RESOLVER = importlib.import_module("linsenkasten.resolve")
    except ImportError:
        return None
    return _RESOLVER


def load(root: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    registry = root or find_registry_root()
    resolver = _resolver_module()
    return resolver.load(registry) if resolver and registry is not None else []


def resolve(spec: dict[str, Any]) -> dict[str, Any] | None:
    """Reuse only a typed match; every other outcome renders a fresh lens."""
    root = find_registry_root()
    resolver = _resolver_module()
    if root is None or resolver is None:
        return None
    result = resolver.resolve(spec, root=root, epoch="active")
    return result if result.get("outcome") == "match" else None


def _record_path(root: Path, record: dict[str, Any], field: str, default: Path) -> Path:
    raw = record.get(field)
    relative = Path(str(raw)) if raw else default
    data_root = (root / "data").resolve()
    if relative.is_absolute():
        path = relative.resolve()
    elif relative.parts and relative.parts[0] == "data":
        path = (root / relative).resolve()
    else:
        path = (data_root / relative).resolve()
    if path != data_root and data_root not in path.parents:
        raise ValueError(f"registry {field} escapes data root: {relative}")
    return path


def _spec_path(root: Path, record: dict[str, Any]) -> Path | None:
    if "spec_path" in record and record["spec_path"] is None:
        return None
    return _record_path(root, record, "spec_path", Path("generated/specs") / f"{record['id']}.json")


def _body_path(root: Path, record: dict[str, Any]) -> Path:
    return _record_path(root, record, "body_path", Path("generated/lenses") / f"{record['id']}.md")


def _load_generate_agents() -> ModuleType:
    global _GENERATE_AGENTS_MODULE
    if _GENERATE_AGENTS_MODULE is not None:
        return _GENERATE_AGENTS_MODULE

    module_path = Path(__file__).with_name("generate-agents.py")
    module_spec = importlib.util.spec_from_file_location("_interflux_generate_agents", module_path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot import render_agent from {module_path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    _GENERATE_AGENTS_MODULE = module
    return _GENERATE_AGENTS_MODULE


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("agent file has unterminated YAML frontmatter")
    parsed = yaml.safe_load(text[4:end]) or {}
    if not isinstance(parsed, dict):
        raise ValueError("agent YAML frontmatter is not an object")
    return parsed, text[end + len("\n---\n") :]


def _render_with_frontmatter(text: str, overrides: dict[str, Any], drop: tuple[str, ...] = ()) -> str:
    frontmatter, body = _split_frontmatter(text)
    for key in drop:
        frontmatter.pop(key, None)
    frontmatter.update(overrides)
    rendered = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip()
    return f"---\n{rendered}\n---\n{body}"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def materialize(
    match: dict[str, Any],
    agents_dir: str | os.PathLike[str],
    spec: dict[str, Any],
) -> Path:
    """Materialize a registry match under the current spec's filename."""
    name = spec.get("name") if isinstance(spec, dict) else None
    if not isinstance(name, str) or not _NAME_PATTERN.fullmatch(name):
        raise ValueError("spec name must be a safe fd-* identifier")

    root_value = match.get("_registry_root")
    root = Path(root_value) if root_value else find_registry_root()
    if root is None:
        raise FileNotFoundError("Linsenkasten registry is unavailable")

    registry_spec_path = _spec_path(root, match)
    registry_spec: dict[str, Any] | None = None
    current_spec_file = spec.get("source_spec_file") or spec.get("source_spec")
    generator = _load_generate_agents()
    if registry_spec_path is not None and registry_spec_path.is_file():
        raw_registry_spec = json.loads(registry_spec_path.read_text(encoding="utf-8"))
        spec_for_validation = (
            {**raw_registry_spec, "name": name}
            if isinstance(raw_registry_spec, dict)
            else raw_registry_spec
        )
        is_valid, validation_errors, registry_spec = generator.validate_agent_spec(
            spec_for_validation,
            name_pattern=_NAME_PATTERN.pattern,
        )
        if not is_valid:
            details = "; ".join(validation_errors)
            raise ValueError(f"invalid registry spec {registry_spec_path}: {details}")
        generated = generator.render_agent(
            {**registry_spec, "name": name},
            source_spec_file=str(current_spec_file) if current_spec_file else None,
        )
    else:
        if match.get("corrupt"):
            raise ValueError("refusing to copy a corrupt registry body without a spec")
        generated = _body_path(root, match).read_text(encoding="utf-8")

    description_candidates = (
        [registry_spec.get("focus")] if registry_spec else [match.get("summary")]
    )
    description_candidates.extend(
        [spec.get("description"), spec.get("focus"), f"Registry lens {name}"]
    )
    description = next(
        (
            cleaned
            for candidate in description_candidates
            if (cleaned := generator.sanitize(candidate))
        ),
        generator.sanitize(f"Registry lens {name}"),
    )

    overrides: dict[str, Any] = {
        "name": name,
        "description": str(description).strip(),
        "generated_by": "flux-gen-prompt",
        "tier": "registry",
        "registry_id": match.get("registry_id") or match["id"],
        "reused_at": datetime.now(timezone.utc).date().isoformat(),
        "cohort_siblings": _cohort_siblings(match),
    }
    if current_spec_file:
        overrides["source_spec"] = str(current_spec_file)

    # A copied body carries the registry record's own provenance; none of it describes this reuse.
    stale = ("source_spec", "use_count", "last_used", "generated_at", "registry_id", "reused_at")
    target = Path(agents_dir) / f"{name}.md"
    _atomic_write(target, _render_with_frontmatter(generated, overrides, drop=stale))
    return target


def _cohort_siblings(match: dict[str, Any]) -> list[str]:
    explicit = match.get("cohort_siblings")
    if isinstance(explicit, list):
        return [str(item) for item in explicit]
    cohort = match.get("cohort")
    if isinstance(cohort, dict):
        siblings = cohort.get("siblings")
        return [str(item) for item in siblings] if isinstance(siblings, list) else []
    if isinstance(cohort, list):
        return [str(item) for item in cohort]
    return []


def record_reuse(match: dict[str, Any], *, name: str, consumer: str, project: str, target: str) -> Path:
    """Let Linsenkasten log its own match and lineage outside tracked data."""
    resolver = _resolver_module()
    if resolver is None:
        raise RuntimeError("Linsenkasten resolver is unavailable")
    return resolver.record_reuse(match, name=name, consumer=consumer, project=project, target=target)
