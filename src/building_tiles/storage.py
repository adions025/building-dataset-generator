from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from rasterio.io import MemoryFile

from .geometry import geometry_hash_id
from .models import ImageArray


def save_png(path: Path, array: ImageArray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "PNG",
        "width": array.shape[2],
        "height": array.shape[1],
        "count": array.shape[0],
        "dtype": "uint8",
    }
    with MemoryFile() as memory_file:
        with memory_file.open(**profile) as dataset:
            dataset.write(array)
        path.write_bytes(memory_file.read())


def write_geometry_index(buildings: gpd.GeoDataFrame, output_directory: Path) -> None:
    indexed = buildings.copy()
    indexed["id"] = [geometry_hash_id(geometry) for geometry in indexed.geometry]
    _write_index(indexed, output_directory)


def write_named_index(buildings: gpd.GeoDataFrame, output_directory: Path) -> None:
    indexed = buildings.copy()
    indexed["id"] = indexed["output_base_id"].astype(str)
    _write_index(indexed, output_directory)


def _write_index(buildings: gpd.GeoDataFrame, output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for _, row in buildings.iterrows():
        centroid = row.geometry.centroid
        rows.append(
            {
                "id": str(row["id"]),
                "area_m2": float(row.geometry.area),
                "centroid_e": float(centroid.x),
                "centroid_n": float(centroid.y),
            }
        )

    pd.DataFrame(rows).drop_duplicates("id").to_csv(
        output_directory / "building_index.csv",
        index=False,
    )
    buildings[["id", "geometry"]].to_file(
        output_directory / "building_index.gpkg",
        layer="buildings",
        driver="GPKG",
    )
