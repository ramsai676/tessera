"""Loading and reshaping tabular data.

Government and enterprise CSVs are rarely clean: numbers arrive with thousands
separators, blanks mean different things in different columns, and headers
carry stray whitespace. These helpers make those problems explicit instead of
letting them turn into silent zeros.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

__all__ = ["Table", "read_csv", "to_number"]

Row = dict[str, str]


def to_number(value: str | float | int | None, *, default: float | None = 0.0) -> float | None:
    """Parse a spreadsheet number, tolerating the usual contamination.

    Handles thousands separators, currency symbols, percent signs, whitespace,
    and parenthesised negatives. Returns `default` for anything unparseable so
    a caller can distinguish "absent" from "zero" by passing `default=None`.

    >>> to_number("1,234.5")
    1234.5
    >>> to_number("(42)")
    -42.0
    >>> to_number("n/a", default=None) is None
    True
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return default

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]

    cleaned = "".join(ch for ch in text if ch.isdigit() or ch in ".-")
    if cleaned in ("", "-", ".", "-."):
        return default

    try:
        number = float(cleaned)
    except ValueError:
        return default

    return -number if negative else number


@dataclass
class Table:
    """A list of rows with a known column order."""

    columns: list[str]
    rows: list[Row]

    def __len__(self) -> int:
        return len(self.rows)

    def __iter__(self) -> Iterator[Row]:
        return iter(self.rows)

    def require(self, *columns: str) -> None:
        """Raise if any column is missing, naming what is available."""
        missing = [c for c in columns if c not in self.columns]
        if missing:
            raise KeyError(
                f"missing column(s): {', '.join(missing)}. "
                f"Available: {', '.join(self.columns)}"
            )

    def distinct(self, column: str) -> list[str]:
        self.require(column)
        seen: dict[str, None] = {}
        for row in self.rows:
            seen.setdefault(row[column], None)
        return list(seen)

    def filter(self, predicate) -> "Table":
        return Table(self.columns, [r for r in self.rows if predicate(r)])

    def group_sum(self, key: str, value: str) -> dict[str, float]:
        """Sum `value` per distinct `key`. Unparseable values count as zero."""
        self.require(key, value)
        totals: dict[str, float] = defaultdict(float)
        for row in self.rows:
            totals[row[key]] += to_number(row[value]) or 0.0
        return dict(totals)

    def pivot_sum(self, row_key: str, column_key: str, value: str) -> "Table":
        """Long → wide: one row per `row_key`, one column per `column_key`."""
        self.require(row_key, column_key, value)

        categories = sorted(self.distinct(column_key))
        buckets: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

        for row in self.rows:
            buckets[row[row_key]][row[column_key]] += to_number(row[value]) or 0.0

        out_rows: list[Row] = []
        for name in sorted(buckets):
            record: Row = {row_key: name}
            for category in categories:
                record[category] = f"{buckets[name].get(category, 0.0):g}"
            out_rows.append(record)

        return Table([row_key, *categories], out_rows)

    def write_csv(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.columns)
            writer.writeheader()
            writer.writerows(self.rows)


def read_csv(path: str | Path) -> Table:
    """Read a CSV, stripping whitespace from headers and values.

    A BOM-prefixed header is the single most common cause of a mysterious
    KeyError on the first column, so `utf-8-sig` is used unconditionally.
    """
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = [h.strip() for h in next(reader)]
        except StopIteration:
            return Table([], [])

        rows: list[Row] = []
        for line_number, raw in enumerate(reader, start=2):
            if not any(cell.strip() for cell in raw):
                continue  # skip blank separator lines

            # A row with more populated fields than there are headers means the
            # file is malformed — almost always an unquoted comma inside a
            # value, e.g. a thousands separator. Truncating silently would turn
            # "1,240.5" into 1, which is the kind of error that survives all
            # the way into a published figure.
            if len(raw) > len(header) and any(cell.strip() for cell in raw[len(header):]):
                # ASCII only: an exception can surface in a traceback on any
                # console, including ones that cannot encode punctuation dashes.
                raise ValueError(
                    f"{Path(path).name} line {line_number}: {len(raw)} fields but "
                    f"{len(header)} columns. Is a value containing a comma unquoted? "
                    f"Row starts: {','.join(raw[:3])}"
                )

            padded = list(raw) + [""] * (len(header) - len(raw))
            rows.append({header[i]: padded[i].strip() for i in range(len(header))})

    return Table(header, rows)


def rows_to_table(rows: Iterable[Row], columns: list[str]) -> Table:
    return Table(columns, list(rows))
