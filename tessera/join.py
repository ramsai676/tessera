"""Joining tabular data to administrative geometry.

The output of a join is not just the matched rows. It is also — and more
importantly for anyone who has to trust the result — the list of things that
did not match, and how confidently the rest did.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import FeatureCollection
from .names import Matcher, MatchResult
from .table import Table

__all__ = ["JoinReport", "join_to_geometry"]


@dataclass
class JoinReport:
    """The result of a join, including everything that failed to join."""

    values: dict[str, float] = field(default_factory=dict)
    matches: list[MatchResult] = field(default_factory=list)
    unmatched_rows: list[str] = field(default_factory=list)
    uncovered_regions: list[str] = field(default_factory=list)

    @property
    def matched_count(self) -> int:
        return len(self.values)

    @property
    def fuzzy_matches(self) -> list[MatchResult]:
        return [m for m in self.matches if m.method == "fuzzy"]

    @property
    def alias_matches(self) -> list[MatchResult]:
        return [m for m in self.matches if m.method == "alias"]

    @property
    def coverage(self) -> float:
        """Share of regions that received a value, 0–1."""
        total = self.matched_count + len(self.uncovered_regions)
        return self.matched_count / total if total else 0.0

    def summary(self) -> str:
        lines = [
            f"matched      {self.matched_count} region(s)",
            f"coverage     {self.coverage * 100:.1f}%",
        ]
        if self.alias_matches:
            lines.append(f"via alias    {len(self.alias_matches)}")
        if self.fuzzy_matches:
            lines.append(f"fuzzy        {len(self.fuzzy_matches)} (review these)")
            for match in self.fuzzy_matches[:10]:
                lines.append(f"               {match.query!r} → {match.matched!r} ({match.score})")
        if self.unmatched_rows:
            lines.append(f"unmatched    {len(self.unmatched_rows)} data row(s) dropped")
            for name in self.unmatched_rows[:10]:
                lines.append(f"               {name!r}")
        if self.uncovered_regions:
            lines.append(f"no data      {len(self.uncovered_regions)} region(s)")
            for name in self.uncovered_regions[:10]:
                lines.append(f"               {name!r}")
        return "\n".join(lines)


def join_to_geometry(
    table: Table,
    geometry: FeatureCollection,
    *,
    name_column: str,
    value_column: str,
    aliases: dict[str, str] | None = None,
    threshold: float = 0.85,
    aggregate: str = "sum",
) -> JoinReport:
    """Resolve each row's region name against the geometry and roll up values.

    Args:
        aggregate: "sum" (default), "mean", "max" or "min" — how to combine
            multiple rows landing on the same region.

    Rows whose region cannot be resolved are reported, never silently dropped.
    """
    from .table import to_number

    table.require(name_column, value_column)

    if aggregate not in {"sum", "mean", "max", "min"}:
        raise ValueError(f"unknown aggregate {aggregate!r}")

    matcher = Matcher(geometry.names(), aliases=aliases, threshold=threshold)
    report = JoinReport()

    buckets: dict[str, list[float]] = {}
    seen_queries: set[str] = set()

    for row in table:
        raw_name = row[name_column]
        if not raw_name:
            continue

        if raw_name not in seen_queries:
            seen_queries.add(raw_name)
            result = matcher.match(raw_name)
            report.matches.append(result)
        else:
            result = next(m for m in report.matches if m.query == raw_name)

        if not result.ok:
            if raw_name not in report.unmatched_rows:
                report.unmatched_rows.append(raw_name)
            continue

        value = to_number(row[value_column], default=None)
        if value is None:
            continue

        buckets.setdefault(result.matched, []).append(value)

    for region, values in buckets.items():
        if aggregate == "sum":
            report.values[region] = sum(values)
        elif aggregate == "mean":
            report.values[region] = sum(values) / len(values)
        elif aggregate == "max":
            report.values[region] = max(values)
        else:
            report.values[region] = min(values)

    report.uncovered_regions = [n for n in geometry.names() if n not in report.values]

    return report
