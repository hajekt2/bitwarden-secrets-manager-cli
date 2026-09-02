#!/usr/bin/env python3
"""The former arbitrary secret/destination interface is intentionally disabled."""
import sys

if __name__ == "__main__":
    print(
        "Operation denied. Vercel secret sync requires an approved secret and destination binding in an isolated service.",
        file=sys.stderr,
    )
    raise SystemExit(2)
