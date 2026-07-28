"""Command line interface: `python -m tessera <command>`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .choropleth import PALETTES, render
from .geometry import load_geojson
from .join import join_to_geometry
from .table import read_csv


def _load_aliases(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("alias file must be a JSON object of {variant: canonical}")
    return {str(k): str(v) for k, v in data.items()}


def _add_join_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("table", help="CSV of observations")
    parser.add_argument("geometry", help="GeoJSON FeatureCollection of regions")
    parser.add_argument("--name-column", required=True, help="CSV column holding region names")
    parser.add_argument("--value-column", required=True, help="CSV column holding the measure")
    parser.add_argument(
        "--name-property",
        default="name",
        help="GeoJSON property holding region names (default: name)",
    )
    parser.add_argument("--aliases", help="JSON file of {variant: canonical} mappings")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.85,
        help="Minimum similarity for a fuzzy name match (default: 0.85)",
    )
    parser.add_argument(
        "--aggregate",
        choices=("sum", "mean", "max", "min"),
        default="sum",
        help="How to combine multiple rows per region (default: sum)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tessera",
        description="Join tabular data to administrative boundaries and map it.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inspect = sub.add_parser("inspect", help="Summarise a geometry file")
    inspect.add_argument("geometry")
    inspect.add_argument("--name-property", default="name")

    check = sub.add_parser("check", help="Report how well a table joins, without mapping")
    _add_join_args(check)

    render_cmd = sub.add_parser("map", help="Render a choropleth SVG")
    _add_join_args(render_cmd)
    render_cmd.add_argument("--out", default="map.svg", help="Output path (default: map.svg)")
    render_cmd.add_argument("--title", default="")
    render_cmd.add_argument("--subtitle", default="")
    render_cmd.add_argument("--classes", type=int, default=5)
    render_cmd.add_argument("--method", choices=("quantile", "equal"), default="quantile")
    render_cmd.add_argument("--palette", choices=sorted(PALETTES), default="sequential")

    return parser


def _force_utf8_streams() -> None:
    """Make non-ASCII output safe on consoles that default to a legacy codepage.

    Windows terminals still report cp1252, where printing an arrow or a tick
    raises UnicodeEncodeError and takes the whole command down with it. Falling
    back to a replacement character is strictly better than crashing on the
    report the user asked for.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - stream already fixed
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    args = build_parser().parse_args(argv)

    if args.command == "inspect":
        geometry = load_geojson(args.geometry, args.name_property)
        box = geometry.bbox()
        print(f"{len(geometry)} region(s)")
        print(f"bounds  {box.min_lon:.3f},{box.min_lat:.3f} → {box.max_lon:.3f},{box.max_lat:.3f}")
        for name in sorted(geometry.names()):
            print(f"  {name}")
        return 0

    table = read_csv(args.table)
    geometry = load_geojson(args.geometry, args.name_property)

    report = join_to_geometry(
        table,
        geometry,
        name_column=args.name_column,
        value_column=args.value_column,
        aliases=_load_aliases(args.aliases),
        threshold=args.threshold,
        aggregate=args.aggregate,
    )

    print(report.summary(), file=sys.stderr)

    if args.command == "check":
        # Non-zero when anything failed to reconcile, so this drops into CI.
        return 0 if not report.unmatched_rows and not report.uncovered_regions else 1

    svg = render(
        geometry,
        report.values,
        title=args.title,
        subtitle=args.subtitle,
        classes=args.classes,
        method=args.method,
        palette=args.palette,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    print(f"\n✓ wrote {out} ({len(svg):,} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
