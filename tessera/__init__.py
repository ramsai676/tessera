"""Tessera — join tabular data to administrative boundaries and map it.

A small, dependency-free toolkit for the unglamorous middle of geospatial
work: reconciling place names that disagree, rolling values up to
administrative units, reporting honestly on what failed to match, and
rendering the result as a self-contained SVG choropleth.

    from tessera import read_csv, load_geojson, join_to_geometry, render

    table = read_csv("data/observations.csv")
    regions = load_geojson("data/districts.geojson", name_property="district")

    report = join_to_geometry(
        table, regions, name_column="district", value_column="hectares"
    )
    print(report.summary())

    Path("map.svg").write_text(
        render(regions, report.values, title="Cultivated area by district")
    )
"""

from .choropleth import PALETTES, SEQUENTIAL, WARM, Palette, equal_breaks, quantile_breaks, render
from .geometry import BBox, Feature, FeatureCollection, Projection, load_geojson
from .join import JoinReport, join_to_geometry
from .names import Matcher, MatchResult, edit_distance, normalise, similarity
from .table import Table, read_csv, to_number

__version__ = "0.1.0"

__all__ = [
    "BBox",
    "Feature",
    "FeatureCollection",
    "JoinReport",
    "Matcher",
    "MatchResult",
    "PALETTES",
    "Palette",
    "Projection",
    "SEQUENTIAL",
    "Table",
    "WARM",
    "edit_distance",
    "equal_breaks",
    "join_to_geometry",
    "load_geojson",
    "normalise",
    "quantile_breaks",
    "read_csv",
    "render",
    "similarity",
    "to_number",
]
