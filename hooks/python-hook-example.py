#!/usr/bin/env python3
"""Example Python hook using interbase SDK.

Demonstrates the thin Bash wrapper -> Python hook pattern.
The Bash hook file sources interbase-stub.sh then delegates to this script.

Usage from a Bash hook:
    #!/usr/bin/env bash
    source "$(dirname "$0")/interbase-stub.sh"
    python3 "$(dirname "$0")/python-hook-example.py" "$@"
"""
try:
    import interbase
except ImportError:
    # Standalone mode -- no SDK available, exit cleanly
    exit(0)


def main():
    # Guards -- check what's available
    if interbase.in_ecosystem():
        status = interbase.session_status()
        # Use status for conditional hook behavior

    # Actions -- safe to call even without deps
    bead = interbase.get_bead()
    if bead:
        interbase.phase_set(bead, "hook-fired")


if __name__ == "__main__":
    main()
