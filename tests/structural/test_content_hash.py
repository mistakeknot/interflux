"""Tests for scripts/content-hash.py content hashing."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

# Import the hyphenated module name via importlib
_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "content-hash.py"
_spec = importlib.util.spec_from_file_location("content_hash", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

compute_hash = getattr(_mod, "compute_hash", None)
discover_files = getattr(_mod, "discover_files", None)

# Skip all tests if intersense is not available (stub-only mode)
pytestmark = pytest.mark.skipif(
    compute_hash is None,
    reason="intersense plugin not available — content-hash.py is a stub",
)

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "content-hash.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_project(tmp_path: Path, files: dict[str, str | bytes]) -> Path:
    """Create a mock project directory with given files.

    Keys are relative paths, values are content strings (or bytes for binary).
    """
    project = tmp_path / "project"
    project.mkdir(parents=True)
    for rel_path, content in files.items():
        filepath = project / rel_path
        filepath.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            filepath.write_bytes(content)
        else:
            filepath.write_text(content, encoding="utf-8")
    return project


# ---------------------------------------------------------------------------
# TestComputeHash
# ---------------------------------------------------------------------------

class TestComputeHash:
    def test_hash_with_readme_and_build(self, tmp_path):
        """Hash computation includes README and build files."""
        project = _create_project(tmp_path, {
            "README.md": "# My Project\n",
            "package.json": '{"name": "test"}',
        })
        files = discover_files(project)
        assert len(files) == 2

        result = compute_hash(project, files)
        assert result.startswith("sha256:")
        assert len(result) == 7 + 64  # "sha256:" + 64 hex chars

    def test_determinism(self, tmp_path):
        """Same files produce the same hash."""
        project = _create_project(tmp_path, {
            "README.md": "# Hello\n",
            "go.mod": "module example.com/test\n",
        })
        files1 = discover_files(project)
        files2 = discover_files(project)

        hash1 = compute_hash(project, files1)
        hash2 = compute_hash(project, files2)
        assert hash1 == hash2

    def test_different_content_different_hash(self, tmp_path):
        """Different content produces different hashes."""
        project_a = _create_project(tmp_path / "a", {
            "README.md": "# Project A\n",
        })
        # Create second project in separate subdir
        project_b = (tmp_path / "b" / "project")
        project_b.mkdir(parents=True)
        (project_b / "README.md").write_text("# Project B\n", encoding="utf-8")

        files_a = discover_files(project_a)
        files_b = discover_files(project_b)

        hash_a = compute_hash(project_a, files_a)
        hash_b = compute_hash(project_b, files_b)
        assert hash_a != hash_b

    def test_file_order_is_deterministic(self, tmp_path):
        """Files are sorted by relative path regardless of discovery order."""
        project = _create_project(tmp_path, {
            "README.md": "# Test\n",
            "package.json": '{"name": "z"}',
            "go.mod": "module z\n",
            "Cargo.toml": "[package]\n",
        })
        files = discover_files(project)
        rel_paths = [str(f.relative_to(project)) for f in files]
        assert rel_paths == sorted(rel_paths)


# ---------------------------------------------------------------------------
# TestDiscoverFiles
# ---------------------------------------------------------------------------

class TestDiscoverFiles:
    def test_finds_readme_md(self, tmp_path):
        """Discovers README.md."""
        project = _create_project(tmp_path, {
            "README.md": "# Hello\n",
        })
        files = discover_files(project)
        names = [f.name for f in files]
        assert "README.md" in names

    def test_finds_readme_rst(self, tmp_path):
        """Discovers README.rst when README.md absent."""
        project = _create_project(tmp_path, {
            "README.rst": "Hello\n=====\n",
        })
        files = discover_files(project)
        names = [f.name for f in files]
        assert "README.rst" in names

    def test_finds_build_files(self, tmp_path):
        """Discovers standard build files."""
        project = _create_project(tmp_path, {
            "package.json": "{}",
            "Makefile": "all:\n\techo hi\n",
        })
        files = discover_files(project)
        names = [f.name for f in files]
        assert "package.json" in names
        assert "Makefile" in names

    def test_finds_source_files_from_src(self, tmp_path):
        """Discovers source files from src/ directory."""
        project = _create_project(tmp_path, {
            "README.md": "# Test\n",
            "src/main.py": "print('hello')\n",
            "src/util.py": "def helper(): pass\n",
            "src/app.py": "class App: pass\n",
            "src/extra.py": "# extra\n",
        })
        files = discover_files(project)
        # Should include README + up to 3 source files
        source_files = [f for f in files if f.suffix == ".py"]
        assert len(source_files) <= 3

    def test_source_files_pick_dominant_extension(self, tmp_path):
        """When multiple extensions exist, picks the most common."""
        project = _create_project(tmp_path, {
            "src/a.py": "# a\n",
            "src/b.py": "# b\n",
            "src/c.py": "# c\n",
            "src/d.go": "package d\n",
        })
        files = discover_files(project)
        # Python is dominant (3 vs 1), so all source files should be .py
        source_files = [f for f in files if f.suffix in (".py", ".go")]
        extensions = {f.suffix for f in source_files}
        assert extensions == {".py"}

    def test_empty_project(self, tmp_path):
        """Empty project returns no files."""
        project = _create_project(tmp_path, {})
        files = discover_files(project)
        assert files == []

    def test_skips_binary_files(self, tmp_path):
        """Binary files (with null bytes) are skipped."""
        project = _create_project(tmp_path, {
            "README.md": b"\x00\x01\x02binary content",
            "package.json": '{"name": "test"}',
        })
        files = discover_files(project)
        names = [f.name for f in files]
        assert "README.md" not in names
        assert "package.json" in names

    def test_skips_large_binary_files(self, tmp_path):
        """Files over 1MB are treated as binary and skipped."""
        project = _create_project(tmp_path, {
            "README.md": "# Normal readme\n",
            "package.json": "x" * (1_048_576 + 1),  # Just over 1MB
        })
        files = discover_files(project)
        names = [f.name for f in files]
        assert "README.md" in names
        assert "package.json" not in names

    def test_fallback_to_root_for_source(self, tmp_path):
        """When no src/ or lib/ exists, scans project root for source files."""
        project = _create_project(tmp_path, {
            "main.py": "print('hello')\n",
            "util.py": "def helper(): pass\n",
        })
        files = discover_files(project)
        source_files = [f for f in files if f.suffix == ".py"]
        assert len(source_files) >= 1


# ---------------------------------------------------------------------------
# TestJsonOutput
# ---------------------------------------------------------------------------

class TestJsonOutput:
    def test_json_flag(self, tmp_path):
        """--json produces valid JSON with hash and files keys."""
        project = _create_project(tmp_path, {
            "README.md": "# Test\n",
            "go.mod": "module test\n",
        })
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project), "--json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "hash" in data
        assert data["hash"].startswith("sha256:")
        assert "files" in data
        assert isinstance(data["files"], list)
        assert "README.md" in data["files"]
        assert "go.mod" in data["files"]

    def test_plain_output(self, tmp_path):
        """Default output is just the hash string."""
        project = _create_project(tmp_path, {
            "README.md": "# Test\n",
        })
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        output = result.stdout.strip()
        assert output.startswith("sha256:")
        assert len(output) == 7 + 64


# ---------------------------------------------------------------------------
# TestCheckMode
# ---------------------------------------------------------------------------

class TestCheckMode:
    def test_check_match(self, tmp_path):
        """--check with correct hash exits 0."""
        project = _create_project(tmp_path, {
            "README.md": "# Test\n",
        })
        # First compute the hash
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project)],
            capture_output=True, text=True, timeout=30,
        )
        expected_hash = result.stdout.strip()

        # Then check against it
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project), "--check", expected_hash],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0

    def test_check_mismatch(self, tmp_path):
        """--check with wrong hash exits 1."""
        project = _create_project(tmp_path, {
            "README.md": "# Test\n",
        })
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project), "--check", "sha256:0000000000000000000000000000000000000000000000000000000000000000"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1

    def test_check_json_match(self, tmp_path):
        """--check --json with correct hash outputs match: true."""
        project = _create_project(tmp_path, {
            "README.md": "# Test\n",
        })
        # Get the hash
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project)],
            capture_output=True, text=True, timeout=30,
        )
        expected_hash = result.stdout.strip()

        # Check with JSON
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project), "--check", expected_hash, "--json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["match"] is True

    def test_check_json_mismatch(self, tmp_path):
        """--check --json with wrong hash outputs match: false."""
        project = _create_project(tmp_path, {
            "README.md": "# Test\n",
        })
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project), "--check", "sha256:bad", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert data["match"] is False
        assert "expected" in data
        assert "actual" in data


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_missing_project_root(self):
        """Nonexistent project root exits 2."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "/nonexistent/path/xyz"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 2

    def test_empty_project_exits_1(self, tmp_path):
        """Project with no hashable files exits 1."""
        project = tmp_path / "empty"
        project.mkdir()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1

    def test_empty_project_json(self, tmp_path):
        """Empty project with --json outputs error JSON."""
        project = tmp_path / "empty"
        project.mkdir()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project), "--json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1
        data = json.loads(result.stdout)
        assert "error" in data

    def test_only_binary_files(self, tmp_path):
        """Project with only binary files exits 1."""
        project = _create_project(tmp_path, {
            "README.md": b"\x00\x01\x02binary",
        })
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(project)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1

    def test_readme_priority_order(self, tmp_path):
        """README.md is preferred over README.rst when both exist."""
        project = _create_project(tmp_path, {
            "README.md": "# Markdown\n",
            "README.rst": "RST\n===\n",
        })
        files = discover_files(project)
        readme_files = [f for f in files if f.name.startswith("README")]
        # Only one README should be included
        assert len(readme_files) == 1
        assert readme_files[0].name == "README.md"

    def test_no_duplicates(self, tmp_path):
        """Files are not duplicated in the output."""
        project = _create_project(tmp_path, {
            "README.md": "# Test\n",
            "package.json": "{}",
            "main.py": "# main\n",
        })
        files = discover_files(project)
        paths = [str(f.resolve()) for f in files]
        assert len(paths) == len(set(paths))
