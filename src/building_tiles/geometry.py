from __future__ import annotations

import hashlib
import re

import geopandas as gpd
import pandas as pd
from shapely import normalize as canonicalize_geometry
from shapely import wkb
from shapely.geometry import (
    LinearRing,
    LineString,
    MultiLineString,
    MultiPolygon,
    Polygon,
)
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, transform, unary_union

from .config import MAX_IMAGE_SIDE, TARGET_CRS
from .models import BoundingBox, TileJob


def ensure_target_crs(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        raise ValueError(
            f"Input layer has no CRS; expected a CRS convertible to {TARGET_CRS}."
        )
    if gdf.crs.to_string().upper() != TARGET_CRS:
        return gdf.to_crs(TARGET_CRS)
    return gdf


def _year_from_date_series(series: pd.Series) -> pd.Series:
    numeric_dates = pd.to_numeric(series, errors="coerce")
    return (numeric_dates // 10000).astype("Int64")


def clean_cadastre_records(
    buildings: gpd.GeoDataFrame,
    start_field: str,
    end_field: str,
) -> gpd.GeoDataFrame:
    if start_field not in buildings.columns or end_field not in buildings.columns:
        return buildings.copy()

    start_year = _year_from_date_series(buildings[start_field])
    end_dates = pd.to_numeric(buildings[end_field], errors="coerce")
    end_year = (end_dates // 10000).astype("Int64")
    open_ended = end_dates == 99999999
    end_year = end_year.where(~open_ended, 9999)

    same_year = (
        (~open_ended) & start_year.notna() & end_year.notna() & (start_year == end_year)
    )
    invalid_order = start_year.notna() & end_year.notna() & (end_year < start_year)
    keep = ~(same_year | invalid_order)

    cleaned = buildings.loc[keep].copy()
    cleaned["__start_year"] = start_year[keep]
    cleaned["__end_year"] = end_year[keep]
    return cleaned


def filter_cadastre_by_year(
    buildings: gpd.GeoDataFrame,
    year: int,
    start_field: str,
    end_field: str,
) -> gpd.GeoDataFrame:
    if "__start_year" in buildings.columns and "__end_year" in buildings.columns:
        start_year = buildings["__start_year"]
        end_year = buildings["__end_year"]
    elif start_field in buildings.columns and end_field in buildings.columns:
        start_year = _year_from_date_series(buildings[start_field])
        end_dates = pd.to_numeric(buildings[end_field], errors="coerce")
        end_year = (end_dates // 10000).astype("Int64")
        end_year = end_year.where(end_dates != 99999999, 9999)
    else:
        return buildings.copy()

    start_year = start_year.reindex(buildings.index).fillna(-9999)
    end_year = end_year.reindex(buildings.index).fillna(9999)
    return buildings.loc[(start_year < year) & (year < end_year)].copy()


def clip_buildings(buildings: gpd.GeoDataFrame, area: BaseGeometry) -> gpd.GeoDataFrame:
    try:
        candidate_indexes = list(buildings.sindex.intersection(area.bounds))
        candidates = buildings.iloc[candidate_indexes]
    except (AttributeError, ImportError):
        min_x, min_y, max_x, max_y = area.bounds
        candidates = buildings.cx[min_x:max_x, min_y:max_y]
    return candidates[candidates.geometry.intersects(area)].copy()


def polygon_parts(geometry: BaseGeometry | None) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty]
    if hasattr(geometry, "geoms"):
        parts: list[Polygon] = []
        for part in geometry.geoms:
            parts.extend(polygon_parts(part))
        return parts
    return []


def cadastre_feature_id(row: pd.Series) -> str:
    for field in ("localId", "LOCALID", "gml_id", "GML_ID", "ID", "id"):
        if field in row and pd.notna(row[field]):
            digits = re.sub(r"\D+", "", str(row[field]))
            if digits:
                return digits
    return ""


def explode_building_parts(
    buildings: gpd.GeoDataFrame,
    clip_geometry: BaseGeometry | None = None,
) -> gpd.GeoDataFrame:
    rows = []
    id_counts: dict[str, int] = {}
    for fallback_id, (_, row) in enumerate(buildings.iterrows(), start=1):
        source_id = cadastre_feature_id(row)
        geometry = (
            row.geometry.intersection(clip_geometry)
            if clip_geometry is not None
            else row.geometry
        )
        for part in polygon_parts(geometry):
            base_id = source_id or str(fallback_id)
            id_counts[base_id] = id_counts.get(base_id, 0) + 1
            new_row = row.copy()
            new_row.geometry = part
            new_row["source_feature_id"] = source_id
            new_row["feature_part"] = id_counts[base_id]
            new_row["output_base_id"] = f"{base_id}_{id_counts[base_id]}"
            rows.append(new_row)

    if not rows:
        raise ValueError(
            "No polygonal building parts remain after exploding geometries."
        )
    return gpd.GeoDataFrame(rows, crs=buildings.crs).reset_index(drop=True)


def line_to_polygon(geometry: BaseGeometry) -> BaseGeometry:
    if isinstance(geometry, LineString):
        coordinates = list(geometry.coords)
        if len(coordinates) < 3:
            return geometry
        if coordinates[0] != coordinates[-1]:
            coordinates.append(coordinates[0])
        polygon = Polygon(coordinates)
        return polygon.buffer(0) if not polygon.is_valid else polygon
    if isinstance(geometry, MultiLineString):
        polygons = []
        remaining_lines = []
        for line in geometry.geoms:
            converted = line_to_polygon(line)
            if isinstance(converted, (Polygon, MultiPolygon)):
                polygons.append(converted)
            else:
                remaining_lines.append(line)
        if polygons:
            return unary_union(polygons).buffer(0)
        polygonized = list(polygonize(unary_union(remaining_lines)))
        if polygonized:
            return unary_union(polygonized).buffer(0)
    return geometry


def polygonal_union(gdf: gpd.GeoDataFrame) -> BaseGeometry:
    converted = [
        line_to_polygon(geometry)
        for geometry in gdf.geometry
        if geometry is not None and not geometry.is_empty
    ]
    polygons = [
        geometry.buffer(0)
        for geometry in converted
        if isinstance(geometry, (Polygon, MultiPolygon)) and not geometry.is_empty
    ]
    valid_polygons = [
        geometry for geometry in polygons if geometry.is_valid and not geometry.is_empty
    ]
    if valid_polygons:
        return unary_union(valid_polygons).buffer(0)

    lines = [
        geometry
        for geometry in converted
        if isinstance(geometry, (LineString, MultiLineString))
    ]
    polygonized = list(polygonize(unary_union(lines))) if lines else []
    if polygonized:
        return unary_union(polygonized).buffer(0)
    raise ValueError(
        "Boundary file does not contain polygonal or closed-line geometry."
    )


def _round_geometry(geometry: BaseGeometry, precision: int) -> BaseGeometry:
    def round_coordinates(x, y, z=None):
        if z is None:
            return round(x, precision), round(y, precision)
        return round(x, precision), round(y, precision), round(z, precision)

    return transform(round_coordinates, geometry)


def normalize_geometry(geometry: BaseGeometry, precision: int = 3) -> BaseGeometry:
    rounded = _round_geometry(geometry, precision)
    if isinstance(rounded, Polygon):
        oriented = orient(rounded, sign=1.0)
        rings = sorted(
            oriented.interiors,
            key=lambda ring: LinearRing(ring).envelope.area,
            reverse=True,
        )
        polygon = Polygon(
            oriented.exterior.coords, [list(ring.coords) for ring in rings]
        )
        return canonicalize_geometry(polygon)
    if isinstance(rounded, MultiPolygon):
        parts = [normalize_geometry(part, precision) for part in rounded.geoms]
        parts.sort(
            key=lambda part: (
                -part.area,
                round(part.centroid.x, 6),
                round(part.centroid.y, 6),
            )
        )
        return canonicalize_geometry(MultiPolygon(parts))
    return canonicalize_geometry(rounded)


def geometry_hash_id(
    geometry: BaseGeometry, precision: int = 3, digest_size: int = 12
) -> str:
    normalized = normalize_geometry(geometry, precision)
    geometry_bytes = wkb.dumps(normalized, hex=False, byte_order=1, include_srid=False)
    return hashlib.blake2b(geometry_bytes, digest_size=digest_size).hexdigest()


def bbox_with_margin(geometry: BaseGeometry, margin_meters: float) -> BoundingBox:
    min_x, min_y, max_x, max_y = geometry.bounds
    return (
        min_x - margin_meters,
        min_y - margin_meters,
        max_x + margin_meters,
        max_y + margin_meters,
    )


def image_size(
    bbox: BoundingBox, meters_per_pixel: float, max_pixels: int = MAX_IMAGE_SIDE
) -> tuple[int, int]:
    min_x, min_y, max_x, max_y = bbox
    width = max(1, round((max_x - min_x) / meters_per_pixel))
    height = max(1, round((max_y - min_y) / meters_per_pixel))
    scale = max(width / max_pixels, height / max_pixels, 1.0)
    return int(width / scale), int(height / scale)


def create_tile_jobs(
    buildings: gpd.GeoDataFrame,
    meters_per_pixel: float,
    margin_meters: float,
) -> list[TileJob]:
    jobs = []
    for geometry in buildings.geometry:
        if geometry is None or geometry.is_empty:
            continue
        bbox = bbox_with_margin(geometry, margin_meters)
        width, height = image_size(bbox, meters_per_pixel)
        jobs.append(TileJob(geometry_hash_id(geometry), geometry, bbox, width, height))
    return jobs
