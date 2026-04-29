"""Tests for plugin structure."""

import sys
from pathlib import Path

# Add interverse/ to path so _shared package is importable when present.
_interverse = Path(__file__).resolve().parents[3]
if str(_interverse) not in sys.path:
    sys.path.insert(0, str(_interverse))

try:
    from _shared.tests.structural.test_base import StructuralTests
except ModuleNotFoundError:

    class StructuralTests:
        """Minimal standalone fallback for clones without Interverse _shared."""

        def test_plugin_manifest_exists(self, project_root):
            assert (project_root / ".claude-plugin" / "plugin.json").exists()

        def test_required_top_level_dirs_exist(self, project_root):
            for name in ("commands", "skills", "agents", "scripts"):
                assert (project_root / name).exists()


class TestStructure(StructuralTests):
    """Structural tests -- inherits shared base, adds plugin-specific checks."""

    def test_plugin_name(self, plugin_json):
        assert plugin_json["name"] == "interflux"
