"""
CLI entry point.

Usage:
    python -m agent.run --query "Is this applicant eligible under 34 CFR 668.32?"
    python -m agent.run --query "..." --applicant examples/applicant_default.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent.graph import build_graph


def _load_applicant(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        print(f"[run] applicant file not found: {path}", file=sys.stderr)
        sys.exit(2)
    return json.loads(p.read_text())


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Eligibility routing agent")
    parser.add_argument("--query", required=True, help="Natural-language eligibility question")
    parser.add_argument("--applicant", help="Path to JSON applicant profile", default=None)
    parser.add_argument("--verbose", action="store_true", help="Print trace and intermediate state")
    args = parser.parse_args()

    state = {
        "query": args.query,
        "applicant": _load_applicant(args.applicant),
    }

    graph = build_graph()
    final = graph.invoke(state)

    if args.verbose:
        print("\n--- TRACE ---")
        for line in final.get("trace", []):
            print(f"  {line}")
        print("\n--- TRACK ---")
        print(f"  {final.get('track')}")
        print("\n--- RETRIEVED RULES ---")
        for r in final.get("retrieved_rules", []):
            print(f"  {r['id']}: {r['text']}")
        print()

    print("--- DECISION ---")
    print(json.dumps(final.get("decision", {}), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
