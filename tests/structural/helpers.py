"""Shared helpers for structural tests."""

import sys
from pathlib import Path

# Add interverse/ to path so _shared package is importable when present.
_interverse = Path(__file__).resolve().parents[3]
if str(_interverse) not in sys.path:
    sys.path.insert(0, str(_interverse))

try:
    from _shared.tests.structural.helpers import parse_frontmatter
except ModuleNotFoundError:
    import yaml

    def parse_frontmatter(path: Path):
        text = path.read_text()
        if not text.startswith("---\n"):
            return {}, text
        _, frontmatter, body = text.split("---", 2)
        return yaml.safe_load(frontmatter) or {}, body.lstrip("\n")

__all__ = ["parse_frontmatter"]
