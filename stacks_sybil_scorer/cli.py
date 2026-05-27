from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import pretty_print, score_addresses
from .fixtures import DEMO_FACTS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score Stacks addresses for AIBTC sybil-likelihood.")
    parser.add_argument("addresses", nargs="*", help="Stacks addresses to score")
    parser.add_argument("--seed", action="append", default=[], help="Known sybil seed address; repeatable")
    parser.add_argument("--seed-file", help="Text file containing seed addresses, one per line")
    parser.add_argument("--cache-dir", help="Optional directory for public API response cache")
    parser.add_argument("--demo", action="store_true", help="Run bundled offline demo fixtures")
    parser.add_argument("--pretty", action="store_true", help="Print a concise human-readable report")
    parser.add_argument("--output", help="Write JSON report to this path")
    args = parser.parse_args(argv)

    seeds = list(args.seed)
    if args.seed_file:
        seeds.extend(read_lines(args.seed_file))

    if args.demo:
        report = score_addresses([], seeds=seeds, offline_facts=DEMO_FACTS)
    else:
        if not args.addresses:
            parser.error("provide at least one address or use --demo")
        report = score_addresses(args.addresses, seeds=seeds, cache_dir=args.cache_dir)

    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(encoded + "\n", encoding="utf-8")

    if args.pretty:
        print(pretty_print(report))
    else:
        print(encoded)
    return 0


def read_lines(path: str) -> list[str]:
    return [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


if __name__ == "__main__":
    raise SystemExit(main())
