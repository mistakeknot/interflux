#!/usr/bin/env python3
"""Stub — delegates to intersense/scripts/content-hash.py.

This file is kept for backward compatibility. The canonical version
lives in the intersense plugin.
"""
import importlib.util
import os
import sys
from pathlib import Path

# Find intersense plugin root
_INTERSENSE_CANDIDATES = [
    # Monorepo layout
    Path(__file__).resolve().parent.parent.parent / "intersense" / "scripts" / "content-hash.py",
    # Installed plugin (marketplace cache)
    *sorted(Path.home().glob(".claude/plugins/cache/*/intersense/*/scripts/content-hash.py"), reverse=True),
]

_INTERSENSE_PATH = next((c for c in _INTERSENSE_CANDIDATES if c.exists()), None)

# Re-export symbols from intersense for importability
if _INTERSENSE_PATH is not None:
    _spec = importlib.util.spec_from_file_location("_intersense_content_hash", _INTERSENSE_PATH)
    _real = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_real)
    compute_hash = _real.compute_hash
    discover_files = _real.discover_files

if __name__ == "__main__":
    if _INTERSENSE_PATH is not None:
        os.execv(sys.executable, [sys.executable, str(_INTERSENSE_PATH)] + sys.argv[1:])
    print("intersense plugin not found — run content-hash.py from intersense directly", file=sys.stderr)
    sys.exit(2)
