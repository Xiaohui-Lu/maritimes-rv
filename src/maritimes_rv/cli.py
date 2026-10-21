"""Command line entry point.

maritimes-rv fetch   [--raw DIR]                       download the source files from DFO
maritimes-rv clean   [--raw DIR] [--out DIR]           build the cleaned tables
maritimes-rv index   [--clean DIR] [--out DIR] [--convert] [--species CODE ...]
maritimes-rv sources [--raw DIR] [--compare FILE]      print the source fingerprint, or compare with a saved one
maritimes-rv release [--tag TAG] [--out DIR]           package a data release
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .fetch import compare_fingerprints, fetch, fingerprint
from .pipeline import build, build_products, qc_counts
from .release import build_release

RAW, CLEAN, PRODUCTS = Path("data/raw"), Path("data/clean"), Path("data/products")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="maritimes-rv", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    get = commands.add_parser("fetch", help="download the source files from DFO's open-data services")
    get.add_argument("--raw", type=Path, default=RAW, help="where to put them (default: data/raw)")

    clean = commands.add_parser("clean", help="build the cleaned tables from the raw DFO files")
    clean.add_argument("--raw", type=Path, default=RAW, help="raw data directory (default: data/raw)")
    clean.add_argument("--out", type=Path, default=CLEAN, help="output directory (default: data/clean)")

    idx = commands.add_parser("index", help="build stratified indices and bottom temperature from the cleaned tables")
    idx.add_argument("--clean", type=Path, default=CLEAN, help="cleaned tables (default: data/clean)")
    idx.add_argument("--out", type=Path, default=PRODUCTS, help="output directory (default: data/products)")
    idx.add_argument("--convert", action="store_true",
                     help="apply Fanning (1985) vessel conversion factors to haddock and four flatfish")
    idx.add_argument("--species", type=int, nargs="+", metavar="CODE", help="species codes (default: every taxon)")

    src = commands.add_parser("sources", help="print the fingerprint of the source files as JSON")
    src.add_argument("--raw", type=Path, default=RAW, help="raw data directory (default: data/raw)")
    src.add_argument("--compare", type=Path, metavar="FILE",
                     help="compare with a saved fingerprint instead; exit status 1 if the sources changed")

    rel = commands.add_parser("release", help="package the cleaned tables and products as a data release")
    rel.add_argument("--tag", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                     help="release name (default: today's date)")
    rel.add_argument("--out", type=Path, default=Path("dist"), help="output directory (default: dist)")
    rel.add_argument("--raw", type=Path, default=RAW)
    rel.add_argument("--clean", type=Path, default=CLEAN)
    rel.add_argument("--products", type=Path, default=PRODUCTS)
    args = parser.parse_args(argv)

    if args.command == "fetch":
        prints = fetch(args.raw)
        print(f"downloaded {len(prints)} source files to {args.raw}")
        for name, digest in prints.items():
            print(f"  {digest[:12]}  {name}")
    elif args.command == "clean":
        tables = build(args.raw, args.out)
        print(f"wrote {len(tables)} tables to {args.out}")
        for name, table in tables.items():
            print(f"  {name:<9}{len(table):>9,} rows")
        print("quality flags:")
        for name, count in qc_counts(tables).items():
            print(f"  {name:<34}{count:>6,}")
    elif args.command == "index":
        products = build_products(args.clean, args.out, convert=args.convert, species_codes=args.species)
        print(f"wrote {len(products)} tables to {args.out}")
        for name, table in products.items():
            print(f"  {name:<12}{len(table):>9,} rows")
    elif args.command == "sources":
        current = fingerprint(args.raw)
        if args.compare is None:
            print(json.dumps(current, indent=2, sort_keys=True))
            return
        changes = compare_fingerprints(json.loads(args.compare.read_text(encoding="utf-8")), current)
        if not changes:
            print("Source data unchanged since the saved fingerprint.")
            return
        print("Source data changed:")
        for change in changes:
            print(f"- {change}")
        sys.exit(1)
    else:
        files = build_release(args.clean, args.products, args.raw, args.out, args.tag)
        print(f"wrote release {args.tag} to {args.out}")
        for path in files:
            print(f"  {path.stat().st_size:>12,} bytes  {path.name}")


if __name__ == "__main__":
    main()
