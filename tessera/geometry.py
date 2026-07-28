"""Minimal GeoJSON reading and projection.

Only what a choropleth needs: polygon rings, a bounding box, and a projection
into SVG pixel space. Points, lines and CRS handling are deliberately absent —
this is not a GIS library, and pretending otherwise would be worse than being
explicit about the scope.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Feature", "FeatureCollection", "BBox", "Projection", "load_geojson"]

Ring = list[tuple[float, float]]


@dataclass(frozen=True)
class BBox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float

    @property
    def width(self) -> float:
        return self.max_lon - self.min_lon

    @property
    def height(self) -> float:
        return self.max_lat - self.min_lat

    @property
    def centre_lat(self) -> float:
        return (self.min_lat + self.max_lat) / 2


@dataclass
class Feature:
    """One administrative unit: a name, its rings, and its source properties."""

    name: str
    rings: list[Ring]
    properties: dict = field(default_factory=dict)

    def bbox(self) -> BBox:
        lons = [lon for ring in self.rings for lon, _ in ring]
        lats = [lat for ring in self.rings for _, lat in ring]
        return BBox(min(lons), min(lats), max(lons), max(lats))


@dataclass
class FeatureCollection:
    features: list[Feature]

    def __len__(self) -> int:
        return len(self.features)

    def __iter__(self):
        return iter(self.features)

    def names(self) -> list[str]:
        return [f.name for f in self.features]

    def bbox(self) -> BBox:
        if not self.features:
            raise ValueError("an empty collection has no bounding box")
        boxes = [f.bbox() for f in self.features]
        return BBox(
            min(b.min_lon for b in boxes),
            min(b.min_lat for b in boxes),
            max(b.max_lon for b in boxes),
            max(b.max_lat for b in boxes),
        )


def _rings_from_geometry(geometry: dict) -> list[Ring]:
    kind = geometry.get("type")
    coords = geometry.get("coordinates", [])

    if kind == "Polygon":
        # [ring][point][lon, lat] — the first ring is the exterior.
        return [[(float(p[0]), float(p[1])) for p in ring] for ring in coords]

    if kind == "MultiPolygon":
        rings: list[Ring] = []
        for polygon in coords:
            for ring in polygon:
                rings.append([(float(p[0]), float(p[1])) for p in ring])
        return rings

    raise ValueError(f"unsupported geometry type {kind!r}; expected Polygon or MultiPolygon")


def load_geojson(path: str | Path, name_property: str = "name") -> FeatureCollection:
    """Read a FeatureCollection, taking each feature's label from a property.

    Raises with the offending index rather than a bare KeyError, because a
    boundary file with one malformed feature out of 600 is otherwise painful
    to debug.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    if data.get("type") != "FeatureCollection":
        raise ValueError(f"expected a FeatureCollection, found {data.get('type')!r}")

    features: list[Feature] = []

    for index, raw in enumerate(data.get("features", [])):
        properties = raw.get("properties") or {}
        if name_property not in properties:
            available = ", ".join(sorted(properties)) or "none"
            raise ValueError(
                f"feature {index} has no {name_property!r} property (available: {available})"
            )

        geometry = raw.get("geometry")
        if not geometry:
            raise ValueError(f"feature {index} ({properties[name_property]!r}) has no geometry")

        features.append(
            Feature(
                name=str(properties[name_property]),
                rings=_rings_from_geometry(geometry),
                properties=properties,
            )
        )

    return FeatureCollection(features)


class Projection:
    """Equirectangular projection fitted to a viewport.

    Longitude degrees are scaled by cos(latitude) so a region does not appear
    horizontally stretched. This is accurate enough for a district or state map
    and wrong for a world map — use a real projection library if you need one.
    """

    def __init__(
        self,
        bbox: BBox,
        width: int = 900,
        height: int = 900,
        padding: int = 20,
    ) -> None:
        self.bbox = bbox
        self.padding = padding

        lon_scale = math.cos(math.radians(bbox.centre_lat)) or 1e-9
        geo_width = bbox.width * lon_scale
        geo_height = bbox.height

        if geo_width <= 0 or geo_height <= 0:
            raise ValueError("bounding box has zero extent; cannot project")

        usable_w = width - 2 * padding
        usable_h = height - 2 * padding

        # One scale for both axes preserves shape; the viewport is then
        # shrunk to fit rather than the geometry being distorted.
        self.scale = min(usable_w / geo_width, usable_h / geo_height)
        self._lon_scale = lon_scale

        self.width = round(geo_width * self.scale + 2 * padding)
        self.height = round(geo_height * self.scale + 2 * padding)

    def point(self, lon: float, lat: float) -> tuple[float, float]:
        x = (lon - self.bbox.min_lon) * self._lon_scale * self.scale + self.padding
        # SVG y grows downward; latitude grows upward.
        y = (self.bbox.max_lat - lat) * self.scale + self.padding
        return x, y

    def path(self, rings: list[Ring]) -> str:
        """Render rings as one SVG path, using even-odd fill for holes."""
        parts: list[str] = []
        for ring in rings:
            if len(ring) < 3:
                continue
            points = [self.point(lon, lat) for lon, lat in ring]
            head = f"M{points[0][0]:.1f},{points[0][1]:.1f}"
            tail = " ".join(f"L{x:.1f},{y:.1f}" for x, y in points[1:])
            parts.append(f"{head} {tail} Z")
        return " ".join(parts)
