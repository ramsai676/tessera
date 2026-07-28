import json
import xml.etree.ElementTree as ET

import pytest

from tessera import (
    equal_breaks,
    join_to_geometry,
    load_geojson,
    quantile_breaks,
    read_csv,
    render,
    to_number,
)


# --------------------------------------------------------------- fixtures

def _square(x: float, y: float, size: float = 1.0):
    return [[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]


@pytest.fixture
def geometry_file(tmp_path):
    features = [
        {
            "type": "Feature",
            "properties": {"district": name},
            "geometry": {"type": "Polygon", "coordinates": [_square(x, 10.0)]},
        }
        for name, x in [("Alpha", 74.0), ("Beta", 75.0), ("Gamma", 76.0)]
    ]
    path = tmp_path / "regions.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return path


@pytest.fixture
def geometry(geometry_file):
    return load_geojson(geometry_file, "district")


def write_csv(tmp_path, text: str):
    path = tmp_path / "data.csv"
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------- to_number

class TestToNumber:
    def test_parses_plain_numbers(self):
        assert to_number("42") == 42.0
        assert to_number("3.5") == 3.5

    def test_strips_thousands_separators_and_symbols(self):
        assert to_number("1,234.5") == 1234.5
        assert to_number("₹ 2,000") == 2000.0
        assert to_number("87%") == 87.0

    def test_reads_parenthesised_negatives(self):
        assert to_number("(42)") == -42.0

    def test_unparseable_values_use_the_default(self):
        assert to_number("n/a") == 0.0
        assert to_number("n/a", default=None) is None
        assert to_number("", default=None) is None
        assert to_number(None, default=None) is None

    def test_passes_through_real_numbers(self):
        assert to_number(7) == 7.0
        assert to_number(7.5) == 7.5


# ----------------------------------------------------------------- table

class TestReadCsv:
    def test_strips_headers_and_values(self, tmp_path):
        table = read_csv(write_csv(tmp_path, " name , value \n Alpha , 10 \n"))
        assert table.columns == ["name", "value"]
        assert table.rows[0] == {"name": "Alpha", "value": "10"}

    def test_tolerates_a_utf8_bom(self, tmp_path):
        path = tmp_path / "bom.csv"
        path.write_bytes("﻿name,value\nAlpha,10\n".encode("utf-8"))
        assert read_csv(path).columns == ["name", "value"]

    def test_skips_blank_lines(self, tmp_path):
        table = read_csv(write_csv(tmp_path, "name,value\nAlpha,1\n\n\nBeta,2\n"))
        assert len(table) == 2

    def test_pads_short_rows(self, tmp_path):
        table = read_csv(write_csv(tmp_path, "name,value,note\nAlpha,1\n"))
        assert table.rows[0]["note"] == ""

    def test_rejects_a_row_with_an_unquoted_comma(self, tmp_path):
        # Silently truncating turns 1,240.5 into 1 — a wrong number that looks
        # entirely plausible downstream.
        path = write_csv(tmp_path, "name,value\nAlpha,1,240.5\n")
        with pytest.raises(ValueError, match="unquoted"):
            read_csv(path)

    def test_accepts_the_same_value_when_properly_quoted(self, tmp_path):
        table = read_csv(write_csv(tmp_path, 'name,value\nAlpha,"1,240.5"\n'))
        assert to_number(table.rows[0]["value"]) == 1240.5

    def test_missing_columns_are_named_in_the_error(self, tmp_path):
        table = read_csv(write_csv(tmp_path, "name,value\nAlpha,1\n"))
        with pytest.raises(KeyError, match="missing column"):
            table.require("name", "absent")

    def test_group_sum_rolls_up_by_key(self, tmp_path):
        table = read_csv(write_csv(tmp_path, "name,value\nA,10\nA,5\nB,2\n"))
        assert table.group_sum("name", "value") == {"A": 15.0, "B": 2.0}

    def test_pivot_sum_widens_long_data(self, tmp_path):
        table = read_csv(
            write_csv(tmp_path, "region,crop,area\nA,Rice,10\nA,Cotton,5\nB,Rice,2\n")
        )
        wide = table.pivot_sum("region", "crop", "area")
        assert wide.columns == ["region", "Cotton", "Rice"]
        assert wide.rows[0] == {"region": "A", "Cotton": "5", "Rice": "10"}


# -------------------------------------------------------------- geometry

class TestGeometry:
    def test_loads_named_features(self, geometry):
        assert len(geometry) == 3
        assert geometry.names() == ["Alpha", "Beta", "Gamma"]

    def test_computes_a_bounding_box(self, geometry):
        box = geometry.bbox()
        assert box.min_lon == 74.0
        assert box.max_lon == 77.0

    def test_reports_a_missing_name_property_helpfully(self, tmp_path):
        path = tmp_path / "bad.geojson"
        path.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"label": "Alpha"},
                            "geometry": {"type": "Polygon", "coordinates": [_square(0, 0)]},
                        }
                    ],
                }
            )
        )
        with pytest.raises(ValueError, match="available: label"):
            load_geojson(path, "district")

    def test_rejects_a_non_collection(self, tmp_path):
        path = tmp_path / "point.geojson"
        path.write_text(json.dumps({"type": "Point", "coordinates": [0, 0]}))
        with pytest.raises(ValueError, match="FeatureCollection"):
            load_geojson(path)


# ------------------------------------------------------------------ join

class TestJoin:
    def test_sums_multiple_rows_per_region(self, tmp_path, geometry):
        table = read_csv(
            write_csv(tmp_path, "district,value\nAlpha,10\nAlpha,5\nBeta,3\nGamma,1\n")
        )
        report = join_to_geometry(
            table, geometry, name_column="district", value_column="value"
        )
        assert report.values == {"Alpha": 15.0, "Beta": 3.0, "Gamma": 1.0}
        assert report.coverage == 1.0

    def test_supports_other_aggregates(self, tmp_path, geometry):
        table = read_csv(write_csv(tmp_path, "district,value\nAlpha,10\nAlpha,20\n"))
        mean = join_to_geometry(
            table, geometry, name_column="district", value_column="value", aggregate="mean"
        )
        assert mean.values["Alpha"] == 15.0

        largest = join_to_geometry(
            table, geometry, name_column="district", value_column="value", aggregate="max"
        )
        assert largest.values["Alpha"] == 20.0

    def test_rejects_an_unknown_aggregate(self, tmp_path, geometry):
        table = read_csv(write_csv(tmp_path, "district,value\nAlpha,1\n"))
        with pytest.raises(ValueError, match="unknown aggregate"):
            join_to_geometry(
                table, geometry, name_column="district", value_column="value", aggregate="median"
            )

    def test_reports_rows_that_matched_nothing(self, tmp_path, geometry):
        table = read_csv(write_csv(tmp_path, "district,value\nAlpha,10\nAtlantis,99\n"))
        report = join_to_geometry(
            table, geometry, name_column="district", value_column="value"
        )
        assert report.unmatched_rows == ["Atlantis"]
        assert "Atlantis" not in report.values

    def test_reports_regions_that_received_no_data(self, tmp_path, geometry):
        table = read_csv(write_csv(tmp_path, "district,value\nAlpha,10\n"))
        report = join_to_geometry(
            table, geometry, name_column="district", value_column="value"
        )
        assert sorted(report.uncovered_regions) == ["Beta", "Gamma"]
        assert report.coverage == pytest.approx(1 / 3)

    def test_flags_fuzzy_matches_for_review(self, tmp_path, geometry):
        # One substitution in five characters scores 0.8; a transposition costs
        # two edits and would fall below the default threshold.
        table = read_csv(write_csv(tmp_path, "district,value\nAlpht,10\n"))
        report = join_to_geometry(
            table, geometry, name_column="district", value_column="value", threshold=0.75
        )
        assert len(report.fuzzy_matches) == 1
        assert report.fuzzy_matches[0].matched == "Alpha"

    def test_aliases_resolve_renames(self, tmp_path, geometry):
        table = read_csv(write_csv(tmp_path, "district,value\nFirst,10\n"))
        report = join_to_geometry(
            table,
            geometry,
            name_column="district",
            value_column="value",
            aliases={"First": "Alpha"},
        )
        assert report.values == {"Alpha": 10.0}
        assert len(report.alias_matches) == 1

    def test_blank_values_do_not_become_zero(self, tmp_path, geometry):
        table = read_csv(write_csv(tmp_path, "district,value\nAlpha,\nBeta,5\n"))
        report = join_to_geometry(
            table, geometry, name_column="district", value_column="value"
        )
        assert "Alpha" not in report.values, "a blank cell is absent, not zero"
        assert report.values["Beta"] == 5.0

    def test_summary_mentions_every_problem_class(self, tmp_path, geometry):
        table = read_csv(write_csv(tmp_path, "district,value\nAlpha,10\nAtlantis,1\n"))
        summary = join_to_geometry(
            table, geometry, name_column="district", value_column="value"
        ).summary()
        assert "unmatched" in summary
        assert "no data" in summary


# ------------------------------------------------------------ classifying

class TestBreaks:
    def test_quantile_breaks_split_the_distribution(self):
        breaks = quantile_breaks([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], classes=5)
        assert breaks[-1] == 10
        assert breaks == sorted(breaks)

    def test_quantile_breaks_collapse_duplicates(self):
        # Mostly-identical data should yield fewer classes, not repeated ones.
        breaks = quantile_breaks([5, 5, 5, 5, 9], classes=5)
        assert len(breaks) == len(set(breaks))

    def test_equal_breaks_are_evenly_spaced(self):
        breaks = equal_breaks([0, 100], classes=4)
        assert breaks == [25.0, 50.0, 75.0, 100.0]

    def test_a_constant_series_yields_one_class(self):
        assert equal_breaks([7, 7, 7], classes=5) == [7]

    def test_too_few_classes_is_rejected(self):
        with pytest.raises(ValueError):
            quantile_breaks([1, 2, 3], classes=1)


# ---------------------------------------------------------------- render

class TestRender:
    def test_produces_well_formed_svg(self, geometry):
        svg = render(geometry, {"Alpha": 10.0, "Beta": 20.0, "Gamma": 30.0})
        root = ET.fromstring(svg)
        assert root.tag.endswith("svg")

    def test_draws_one_path_per_region(self, geometry):
        svg = render(geometry, {"Alpha": 10.0, "Beta": 20.0, "Gamma": 30.0})
        root = ET.fromstring(svg)
        paths = [e for e in root.iter() if e.tag.endswith("path")]
        assert len(paths) == 3

    def test_regions_without_data_use_the_no_data_colour(self, geometry):
        svg = render(geometry, {"Alpha": 10.0})
        root = ET.fromstring(svg)
        titles = [e.text for e in root.iter() if e.tag.endswith("title")]
        assert any("no data" in t for t in titles)

    def test_each_region_carries_a_tooltip(self, geometry):
        svg = render(geometry, {"Alpha": 1500.0, "Beta": 20.0, "Gamma": 30.0})
        root = ET.fromstring(svg)
        titles = [e.text for e in root.iter() if e.tag.endswith("title")]
        assert "Alpha: 1.5k" in titles

    def test_escapes_markup_in_region_names(self, tmp_path):
        path = tmp_path / "x.geojson"
        path.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "<script>alert(1)</script>"},
                            "geometry": {"type": "Polygon", "coordinates": [_square(0, 0)]},
                        }
                    ],
                }
            )
        )
        svg = render(load_geojson(path), {})
        assert "<script>" not in svg
        ET.fromstring(svg)  # still parses — escaping did not break the document

    def test_rejects_an_unknown_palette(self, geometry):
        with pytest.raises(ValueError, match="unknown palette"):
            render(geometry, {"Alpha": 1.0}, palette="chartreuse")
