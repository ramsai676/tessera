<div align="center">

# Tessera

**The unglamorous middle of geospatial work, done honestly.**

Join tabular data to administrative boundaries, find out what didn't match,
and render the result as an SVG choropleth. Standard library only.

</div>

---

## The problem nobody warns you about

The interesting parts of a geospatial pipeline are the ends: you have a
spreadsheet of measurements, and you want a map. The part that eats the week is
in between, and it's this:

| Your data says | The boundary file says |
|---|---|
| `NORTHVALE` | `Northvale` |
| `West-ford` | `Westford` |
| `Lakeside District` | `Lakeside` |
| `Stonebrigde` | `Stonebridge` |
| `Grayfell` | `Greyfell` |
| `Ashcombe` | *(doesn't exist)* |

A plain equality join silently drops five of those six and produces a map that
looks finished. Nobody notices until someone asks why Lakeside is blank.

Tessera treats reconciliation as the main event:

```
$ python -m tessera check data/observations.csv data/districts.geojson \
    --name-column district --value-column hectares --name-property district

matched      11 region(s)
coverage     91.7%
fuzzy        2 (review these)
               'West-ford' → 'Westford' (0.8889)
               'Grayfell' → 'Greyfell' (0.875)
unmatched    2 data row(s) dropped
               'Stonebrigde'
               'Ashcombe'
no data      1 region(s)
               'Stonebridge'
```

Exit code 1 — so this drops straight into CI and fails a build when the data
stops reconciling.

---

## How matching works

Three tiers, most trustworthy first:

**Aliases** — an explicit table you maintain. Renames like Mysore → Mysuru or
Madras → Chennai are not typos; no edit-distance threshold recovers them
without inventing matches elsewhere. They belong somewhere a human reviewed.

**Exact, after normalising** — case, accents, punctuation and structural noise
words (`District`, `Taluk`, `Tehsil`, `Mandal`) are stripped, so
`Bengaluru Urban District` and `BENGALURU  (Urban)` collapse to one key.

**Fuzzy, with a margin** — Levenshtein similarity above a threshold, *and*
clearly ahead of the runner-up. The margin is what stops a name sitting halfway
between two real places from being assigned to whichever sorted first.

Anything below that bar is reported as unmatched. **A wrong join is more
expensive than a missing row, because it looks like data.**

```python
from tessera import Matcher

matcher = Matcher(
    ["Bengaluru Urban", "Mysuru", "Belagavi"],
    aliases={"Mysore": "Mysuru"},
    threshold=0.85,
)

matcher.match("BANGALURU URBAN")   # → Bengaluru Urban, "fuzzy", 0.93
matcher.match("Mysore")            # → Mysuru, "alias", 1.0
matcher.match("Atlantis")          # → None, "none"
```

---

## Run it

Needs **Python 3.11+**. Nothing to install — `pytest` is the only optional extra.

```bash
git clone https://github.com/ramsai676/tessera.git && cd tessera

# What's in this boundary file?
python -m tessera inspect data/districts.geojson --name-property district

# How well does my data join?
python -m tessera check data/observations.csv data/districts.geojson \
  --name-column district --value-column hectares --name-property district

# Draw it
python -m tessera map data/observations.csv data/districts.geojson \
  --name-column district --value-column hectares --name-property district \
  --aliases data/aliases.json --threshold 0.80 \
  --title "Cultivated area by district" --out map.svg
```

The bundled sample data is synthetic and deliberately messy — casing drift, a
structural suffix, a typo, a rename, a region that doesn't exist, a quoted
thousands separator, and an unparseable value. It exercises every path.

---

## As a library

```python
from pathlib import Path
from tessera import read_csv, load_geojson, join_to_geometry, render

table = read_csv("observations.csv")
regions = load_geojson("districts.geojson", name_property="district")

report = join_to_geometry(
    table, regions,
    name_column="district",
    value_column="hectares",
    aliases={"Grayfell": "Greyfell"},
    aggregate="sum",          # or mean / max / min
)

print(report.summary())
print(f"{report.coverage:.0%} of regions have data")

Path("map.svg").write_text(
    render(regions, report.values,
           title="Cultivated area",
           method="quantile",   # or "equal"
           classes=5)
)
```

---

## Choices the library refuses to make for you

**Classification.** Quantile bins put equal counts in each class and read well
on skewed data. Equal-interval bins split the range evenly and are honest about
magnitude but can leave classes empty. Which one is right is an editorial
decision about your data, so it's a parameter, not a default buried in code.

**No data ≠ zero.** Regions without an observation are drawn in a distinct grey
and labelled `no data`, never in the lowest colour class. A blank cell in the
source stays absent rather than becoming a zero that drags an average down.

**Fuzzy matches are surfaced, not swallowed.** Every one appears in the report
with its score, because they're the matches most likely to be wrong.

---

## Reading data that fights back

`to_number` handles what spreadsheets actually contain — thousands separators,
currency symbols, percent signs, parenthesised negatives — and returns a
sentinel you choose for anything unparseable, so "absent" and "zero" stay
distinguishable.

`read_csv` strips a UTF-8 BOM (the usual cause of a mystifying `KeyError` on
the first column), skips blank separator rows, pads short rows — and **refuses
to read a row with more populated fields than there are headers**:

```
ValueError: observations.csv line 2: 4 fields but 3 columns.
Is a value containing a comma unquoted? Row starts: Northvale,Rice,1
```

> That guard exists because it caught a real bug while this was being built.
> An unquoted `1,240.5` in the sample data was being read as `1`, and the map
> rendered perfectly — with a number off by three orders of magnitude. Silent
> truncation is how a wrong figure reaches a published chart.

---

## Scope

This is not a GIS library and doesn't pretend to be. It reads `Polygon` and
`MultiPolygon` from GeoJSON, and projects equirectangularly with a cosine
correction on longitude — accurate enough for a district or state map, wrong
for a world map. There is no CRS handling, no topology, no spatial indexing. If
you need those, you need GeoPandas; this is for the case where pulling in a
geospatial stack to draw one map is more trouble than the map is worth.

---

## Tests

```bash
python -m pytest -q     # 59 passed
```

Name normalisation and every matching tier; edit distance properties; number
parsing against contaminated input; the CSV guards; GeoJSON error messages;
join aggregation, coverage, unmatched reporting and alias resolution; quantile
and equal-interval classification including degenerate inputs; and SVG output —
well-formedness, no-data handling, tooltips, and escaping of markup in region
names.

---

## Licence

MIT — see [LICENSE](LICENSE).

Built by [Ram Sai Kandagatla](https://github.com/ramsai676).
