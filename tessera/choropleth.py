"""Rendering a joined dataset as an SVG choropleth.

Classification matters more than colour here. Quantile bins put an equal count
of regions in each class, which reads well on skewed data; equal-interval bins
split the value range evenly, which is honest about magnitude but can leave
classes empty. Both are offered because the right answer depends on the data,
and picking silently would hide a real editorial decision.

Regions with no data are drawn in a distinct hatch-free grey rather than the
lowest colour class — "no observation" and "a low value" are different claims.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import FeatureCollection, Projection

__all__ = ["Palette", "SEQUENTIAL", "quantile_breaks", "equal_breaks", "render"]


@dataclass(frozen=True)
class Palette:
    name: str
    colours: tuple[str, ...]
    no_data: str = "#e6e8eb"
    stroke: str = "#ffffff"


# Perceptually ordered, and distinguishable in greyscale — a map that only
# works in colour fails the moment someone prints it.
SEQUENTIAL = Palette(
    "sequential",
    ("#eef3f8", "#cfe0ee", "#a7c7e0", "#6fa5cd", "#3a7cb0", "#1d5385"),
)

WARM = Palette(
    "warm",
    ("#fdf1e4", "#fbdcbb", "#f5bd88", "#e89454", "#d16a2b", "#a44515"),
)

PALETTES = {p.name: p for p in (SEQUENTIAL, WARM)}


def quantile_breaks(values: list[float], classes: int = 5) -> list[float]:
    """Upper bounds placing roughly equal counts in each class.

    Duplicate breaks are collapsed, so a dataset where most regions share a
    value produces fewer classes rather than several identical ones.
    """
    if classes < 2:
        raise ValueError("need at least 2 classes")

    ordered = sorted(v for v in values)
    if not ordered:
        return []

    breaks: list[float] = []
    for i in range(1, classes):
        position = i * len(ordered) / classes
        index = min(int(position), len(ordered) - 1)
        breaks.append(ordered[index])

    breaks.append(ordered[-1])

    deduped: list[float] = []
    for value in breaks:
        if not deduped or value > deduped[-1]:
            deduped.append(value)
    return deduped


def equal_breaks(values: list[float], classes: int = 5) -> list[float]:
    """Upper bounds splitting the range into equal-width intervals."""
    if classes < 2:
        raise ValueError("need at least 2 classes")
    if not values:
        return []

    low, high = min(values), max(values)
    if low == high:
        return [high]

    step = (high - low) / classes
    return [low + step * i for i in range(1, classes + 1)]


def _class_of(value: float, breaks: list[float]) -> int:
    for index, upper in enumerate(breaks):
        if value <= upper:
            return index
    return len(breaks) - 1


def _format(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}k"
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def render(
    geometry: FeatureCollection,
    values: dict[str, float],
    *,
    title: str = "",
    subtitle: str = "",
    classes: int = 5,
    method: str = "quantile",
    palette: Palette | str = SEQUENTIAL,
    width: int = 900,
    height: int = 900,
) -> str:
    """Return a complete, standalone SVG document.

    Args:
        method: "quantile" or "equal".
        palette: a Palette or the name of a built-in one.
    """
    if isinstance(palette, str):
        if palette not in PALETTES:
            raise ValueError(f"unknown palette {palette!r}; try {', '.join(PALETTES)}")
        palette = PALETTES[palette]

    present = [v for v in values.values()]
    breaks = (
        quantile_breaks(present, classes)
        if method == "quantile"
        else equal_breaks(present, classes)
    )
    if method not in {"quantile", "equal"}:
        raise ValueError(f"unknown method {method!r}; use 'quantile' or 'equal'")

    projection = Projection(geometry.bbox(), width, height, padding=24)
    header = 54 if title else 12
    # A map where nothing joined still renders — every region grey, legend
    # reduced to the no-data swatch. A failed join should be visible, not a
    # stack trace.
    legend_height = 58 if breaks else 34
    total_height = projection.height + header + legend_height

    shades = palette.colours[: len(breaks)] if breaks else ()

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{projection.width}" '
        f'height="{total_height}" viewBox="0 0 {projection.width} {total_height}" '
        f'font-family="system-ui, -apple-system, Segoe UI, sans-serif">',
        f'<rect width="100%" height="100%" fill="#ffffff"/>',
    ]

    if title:
        parts.append(
            f'<text x="24" y="30" font-size="19" font-weight="600" fill="#12161c">'
            f"{_escape(title)}</text>"
        )
    if subtitle:
        parts.append(
            f'<text x="24" y="47" font-size="12.5" fill="#626b78">{_escape(subtitle)}</text>'
        )

    parts.append(f'<g transform="translate(0,{header})">')

    for feature in geometry:
        value = values.get(feature.name)
        if value is None:
            fill = palette.no_data
            label = "no data"
        else:
            fill = shades[min(_class_of(value, breaks), len(shades) - 1)]
            label = _format(value)

        parts.append(
            f'<path d="{projection.path(feature.rings)}" fill="{fill}" '
            f'stroke="{palette.stroke}" stroke-width="0.7" fill-rule="evenodd">'
            f"<title>{_escape(feature.name)}: {label}</title></path>"
        )

    parts.append("</g>")

    # ------------------------------------------------------------- legend
    legend_y = header + projection.height + 18
    swatch = 26
    parts.append(f'<g transform="translate(24,{legend_y})">')

    for index, colour in enumerate(shades):
        x = index * (swatch + 2)
        upper = breaks[min(index, len(breaks) - 1)]
        lower = breaks[index - 1] if index > 0 else min(present, default=0.0)

        parts.append(f'<rect x="{x}" y="0" width="{swatch}" height="11" fill="{colour}"/>')
        parts.append(
            f'<text x="{x}" y="25" font-size="9.5" fill="#626b78">'
            f"{_format(lower) if index else _format(lower)}</text>"
        )
        if index == len(shades) - 1:
            parts.append(
                f'<text x="{x + swatch}" y="25" font-size="9.5" fill="#626b78" '
                f'text-anchor="end">{_format(upper)}</text>'
            )

    no_data_x = len(shades) * (swatch + 2) + 18
    parts.append(
        f'<rect x="{no_data_x}" y="0" width="{swatch}" height="11" fill="{palette.no_data}"/>'
        f'<text x="{no_data_x}" y="25" font-size="9.5" fill="#626b78">no data</text>'
    )

    parts.append("</g></svg>")
    return "\n".join(parts)


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
