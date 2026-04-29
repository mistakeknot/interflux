"""Shared fixtures for structural tests."""

import json
import sys
from pathlib import Path

import pytest

# Add interverse/ to path so _shared package is importable when this repo is
# checked out inside the broader Interverse workspace. Standalone clones fall
# back to local fixtures below.
_interverse = Path(__file__).resolve().parents[3]
if str(_interverse) not in sys.path:
    sys.path.insert(0, str(_interverse))

PROJECT_ROOT = Path(__file__).resolve().parents[2]

try:
    from _shared.tests.structural.conftest_base import create_structural_fixtures
except ModuleNotFoundError:

    @pytest.fixture(scope="session")
    def project_root():
        return PROJECT_ROOT

    @pytest.fixture(scope="session")
    def plugin_json(project_root):
        return json.loads((project_root / ".claude-plugin" / "plugin.json").read_text())

    @pytest.fixture(scope="session")
    def skills_dir(project_root):
        return project_root / "skills"

    @pytest.fixture(scope="session")
    def commands_dir(project_root):
        return project_root / "commands"

    @pytest.fixture(scope="session")
    def agents_dir(project_root):
        return project_root / "agents"

    @pytest.fixture(scope="session")
    def scripts_dir(project_root):
        return project_root / "scripts"

else:
    fixtures = create_structural_fixtures(PROJECT_ROOT)

    # Register fixtures in this module's namespace so pytest discovers them
    project_root = fixtures["project_root"]
    plugin_json = fixtures["plugin_json"]
    skills_dir = fixtures["skills_dir"]
    commands_dir = fixtures["commands_dir"]
    agents_dir = fixtures["agents_dir"]
    scripts_dir = fixtures["scripts_dir"]
