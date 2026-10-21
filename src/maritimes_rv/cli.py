"""Command line entry point.

maritimes-rv clean [--raw DIR] [--out DIR]
maritimes-rv index [--clean DIR] [--out DIR] [--convert] [--species CODE ...]
"""
import argparse
from pathlib import Path

from .pipeline import build, build_products, qc_counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="maritimes-rv", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    clean = commands.add_parser("clean", help="build the cleaned tables from the raw DFO files")
    clean.add_argument("--raw", type=Path, default=Path("data/raw"), help="raw data directory (default: data/raw)")
    clean.add_argument("--out", type=Path, default=Path("data/clean"), help="output directory (default: data/clean)")

    idx = commands.add_parser("index", help="build stratified indices and bottom temperature from the cleaned tables")
    idx.add_argument("--clean", type=Path, default=Path("data/clean"), help="cleaned tables (default: data/clean)")
    idx.add_argument("--out", type=Path, default=Path("data/products"), help="output directory (default: data/products)")
    idx.add_argument("--convert", action="store_true",
                     help="apply Fanning (1985) vessel conversion factors to haddock and four flatfish")
    idx.add_argument("--species", type=int, nargs="+", metavar="CODE", help="species codes (default: every taxon)")
    args = parser.parse_args(argv)

    if args.command == "clean":
        tables = build(args.raw, args.out)
        print(f"wrote {len(tables)} tables to {args.out}")
        for name, table in tables.items():
            print(f"  {name:<9}{len(table):>9,} rows")
        print("quality flags:")
        for name, count in qc_counts(tables).items():
            print(f"  {name:<34}{count:>6,}")
    else:
        products = build_products(args.clean, args.out, convert=args.convert, species_codes=args.species)
        print(f"wrote {len(products)} tables to {args.out}")
        for name, table in products.items():
            print(f"  {name:<12}{len(table):>9,} rows")


if __name__ == "__main__":
    main()
