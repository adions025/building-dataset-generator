from __future__ import annotations

import re
from pathlib import Path

import fiona
import geopandas as gpd
from shapely.geometry.base import BaseGeometry

from .config import GROUND_TRUTH_DIR, PROJECT_ROOT
from .geometry import ensure_target_crs, polygon_parts, polygonal_union


def resolve_existing_file(path: Path, additional_directory: Path | None = None) -> Path:
    candidates = [path]
    if additional_directory is not None:
        candidates.append(additional_directory / path)
    if not path.is_absolute():
        candidates.extend((Path.cwd() / path, PROJECT_ROOT / path))

    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file():
            return resolved
    raise FileNotFoundError(f"Input file not found: {path}")


def load_buildings_file(path: Path) -> gpd.GeoDataFrame:
    return ensure_target_crs(gpd.read_file(resolve_existing_file(path)))


def load_boundary_file(path: Path) -> tuple[BaseGeometry, Path]:
    resolved = resolve_existing_file(path)
    boundary = gpd.read_file(resolved)
    return polygonal_union(ensure_target_crs(boundary)), resolved


def load_ground_truth(
    path: Path, layer: str | None = None
) -> tuple[gpd.GeoDataFrame, Path, str]:
    resolved = resolve_existing_file(path, GROUND_TRUTH_DIR)
    selected_layer = layer or fiona.listlayers(resolved)[0]
    source = ensure_target_crs(gpd.read_file(resolved, layer=selected_layer))
    if "id" not in source.columns:
        raise ValueError(
            f"Ground-truth layer '{selected_layer}' has no 'id' column: {resolved}"
        )

    rows = []
    for _, row in source[
        source.geometry.notna() & ~source.geometry.is_empty
    ].iterrows():
        source_id = re.sub(r"\D+", "", str(row["id"]))
        if not source_id:
            continue
        parts = polygon_parts(row.geometry)
        for part_number, part in enumerate(parts, start=1):
            new_row = row.copy()
            new_row.geometry = part
            new_row["source_feature_id"] = source_id
            new_row["feature_part"] = part_number
            new_row["output_base_id"] = (
                source_id if len(parts) == 1 else f"{source_id}_{part_number}"
            )
            rows.append(new_row)

    return (
        gpd.GeoDataFrame(rows, crs=source.crs).reset_index(drop=True),
        resolved,
        selected_layer,
    )
