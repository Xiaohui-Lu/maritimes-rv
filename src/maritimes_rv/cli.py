"""Command line entry point: maritimes-rv clean [--raw DIR] [--out DIR]."""
import argparse
from pathlib import Path

from .pipeline import build, qc_counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="maritimes-rv", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    clean = commands.add_parser("clean", help="build the cleaned tables from the raw DFO files")
    clean.add_argument("--raw", type=Path, default=Path("data/raw"), help="raw data directory (default: data/raw)")
    clean.add_argument("--out", type=Path, default=Path("data/clean"), help="output directory (default: data/clean)")
    args = parser.parse_args(argv)

    tables = build(args.raw, args.out)
    print(f"wrote {len(tables)} tables to {args.out}")
    for name, table in tables.items():
        print(f"  {name:<9}{len(table):>9,} rows")
    print("quality flags:")
    for name, count in qc_counts(tables).items():
        print(f"  {name:<34}{count:>6,}")


if __name__ == "__main__":
    main()
