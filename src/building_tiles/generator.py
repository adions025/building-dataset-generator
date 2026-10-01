from __future__ import annotations

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .catastro import download_municipality_buildings
from .config import GenerationConfig, normalized_city_key
from .geometry import (
    cadastre_feature_id,
    clean_cadastre_records,
    clip_buildings,
    create_tile_jobs,
    ensure_target_crs,
    explode_building_parts,
    filter_cadastre_by_year,
)
from .icgc import download_orthophoto, get_municipality_boundary
from .imaging import calculate_quality_metrics, white_outside_geometry
from .local_data import load_boundary_file, load_buildings_file, load_ground_truth
from .models import RasterTile, YearResult
from .storage import save_png, write_geometry_index, write_named_index

LOGGER = logging.getLogger(__name__)
OrthophotoLoader = Callable[
    [tuple[float, float, float, float], int, int, int], RasterTile
]


class ThumbnailGenerator:
    def __init__(
        self,
        config: GenerationConfig,
        orthophoto_loader: OrthophotoLoader = download_orthophoto,
    ) -> None:
        self.config = config.with_submunicipal_defaults()
        self.config.validate()
        self.orthophoto_loader = orthophoto_loader

    def run(self) -> list[YearResult]:
        buildings = self._load_buildings()
        if not self.config.uses_ground_truth:
            buildings = clean_cadastre_records(
                buildings,
                self.config.start_date_field,
                self.config.end_date_field,
            )

        area, area_label = self._resolve_area(buildings)
        area_km2 = area.area / 1_000_000
        LOGGER.info(
            "AOI %s: %.3f km2; bounds=%s",
            area_label,
            area_km2,
            tuple(round(value, 1) for value in area.bounds),
        )

        selected = clip_buildings(buildings, area)
        LOGGER.info(
            "Selected %d of %d buildings inside the AOI", len(selected), len(buildings)
        )
        if selected.empty:
            raise ValueError("No buildings intersect the selected area.")

        if (
            not self.config.uses_ground_truth
            and not self.config.keep_multipart_buildings
        ):
            before = len(selected)
            clip_geometry = (
                area if normalized_city_key(self.config.city) == "valldoreix" else None
            )
            selected = explode_building_parts(selected, clip_geometry)
            LOGGER.info(
                "Exploded building parts: %d features -> %d tiles",
                before,
                len(selected),
            )

        selected = self._filter_requested_ids(selected)
        if self.config.limit and len(selected) > self.config.limit:
            selected = selected.head(self.config.limit).copy()
            LOGGER.info("Limited processing to %d buildings", self.config.limit)

        if self.config.uses_ground_truth:
            write_named_index(selected, self.config.city_output_directory)
        else:
            write_geometry_index(selected, self.config.city_output_directory)

        years = list(self.config.years)
        worker_count = min(self.config.max_workers, len(years))
        LOGGER.info("Processing %d years with max_workers=%d", len(years), worker_count)

        results: list[YearResult] = []
        unexpected_failures: list[tuple[int, Exception]] = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(self._process_year, year, selected): year
                for year in years
            }
            for future in as_completed(futures):
                year = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # preserve other years, then fail the run
                    LOGGER.exception("Year %d failed", year)
                    unexpected_failures.append((year, exc))

        unsuccessful = [result for result in results if not result.successful]
        if unexpected_failures or unsuccessful:
            failed_years = sorted(
                [year for year, _ in unexpected_failures]
                + [result.year for result in unsuccessful]
            )
            raise RuntimeError(f"Generation failed for years: {failed_years}")

        results.sort(key=lambda result: result.year)
        LOGGER.info("Generation completed for %s", self.config.city)
        return results

    def _load_buildings(self) -> gpd.GeoDataFrame:
        if self.config.ground_truth_file is not None:
            buildings, path, layer = load_ground_truth(
                self.config.ground_truth_file,
                self.config.ground_truth_layer,
            )
            LOGGER.info(
                "Loaded %d ground-truth buildings from %s [%s]",
                len(buildings),
                path,
                layer,
            )
            return buildings

        if self.config.cadastre_source == "file":
            assert self.config.cadastre_file is not None
            buildings = load_buildings_file(self.config.cadastre_file)
            LOGGER.info(
                "Loaded %d cadastral buildings from %s",
                len(buildings),
                self.config.cadastre_file,
            )
            return buildings

        cache = self.config.atom_cache
        if cache is not None and cache.expanduser().is_file():
            buildings = load_buildings_file(cache)
            LOGGER.info(
                "Loaded %d cadastral buildings from cache %s", len(buildings), cache
            )
            return buildings

        LOGGER.info(
            "Downloading Catastro buildings for %s (%s)",
            self.config.effective_cadastre_city,
            self.config.province or "all provinces",
        )
        buildings = ensure_target_crs(
            download_municipality_buildings(
                self.config.effective_cadastre_city,
                self.config.province,
            )
        )
        LOGGER.info("Downloaded %d cadastral buildings", len(buildings))

        if cache is not None:
            cache = cache.expanduser().resolve()
            cache.parent.mkdir(parents=True, exist_ok=True)
            buildings.to_file(cache, layer="buildings", driver="GPKG")
            LOGGER.info("Wrote Catastro cache to %s", cache)
        return buildings

    def _resolve_area(self, buildings: gpd.GeoDataFrame) -> tuple[BaseGeometry, str]:
        if self.config.aoi_mode == "muni":
            municipality = ensure_target_crs(
                get_municipality_boundary(self.config.city)
            )
            return municipality.geometry.iloc[0], self.config.city
        if self.config.aoi_mode == "from-cadastre":
            union = unary_union(buildings.geometry)
            return union.buffer(0).envelope, "cadastre-union"
        if self.config.aoi_mode == "bbox":
            assert self.config.aoi_bbox is not None
            bbox = gpd.GeoDataFrame(
                geometry=[box(*self.config.aoi_bbox)], crs=self.config.aoi_crs
            )
            return ensure_target_crs(bbox).geometry.iloc[0], "custom-bbox"
        if self.config.aoi_mode == "file":
            assert self.config.aoi_file is not None
            return load_boundary_file(self.config.aoi_file)
        raise ValueError(f"Unsupported AOI mode: {self.config.aoi_mode}")

    def _filter_requested_ids(self, buildings: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        if not self.config.ids_from_directories:
            return buildings

        allowed_ids: set[str] = set()
        pattern = re.compile(
            r"^(?:build|raster)_(?P<id>.+?)(?:_\d{4})?\.png$", re.IGNORECASE
        )
        for directory in self.config.ids_from_directories:
            resolved = directory.expanduser().resolve()
            if not resolved.is_dir():
                raise FileNotFoundError(f"ID source directory not found: {directory}")
            for image in resolved.iterdir():
                match = pattern.match(image.name)
                if match:
                    allowed_ids.add(match.group("id").split("_", 1)[0])

        def row_id(row: pd.Series) -> str:
            return str(
                row.get("source_feature_id")
                or row.get("output_base_id")
                or row.get("id")
            ).split("_", 1)[0]

        selected = buildings.loc[
            buildings.apply(lambda row: row_id(row) in allowed_ids, axis=1)
        ].copy()
        LOGGER.info(
            "Selected %d of %d buildings using %d requested IDs",
            len(selected),
            len(buildings),
            len(allowed_ids),
        )
        if selected.empty:
            raise ValueError("No geometries match IDs found in --ids-from-dir.")
        return selected

    def _process_year(self, year: int, buildings: gpd.GeoDataFrame) -> YearResult:
        year_buildings = self._buildings_for_year(buildings, year).reset_index(
            drop=True
        )
        if year_buildings.empty:
            LOGGER.info("Year %d: no active buildings; skipped", year)
            return YearResult(year, attempted=0, saved=0, failed=0)

        jobs = create_tile_jobs(
            year_buildings,
            self.config.meters_per_pixel,
            self.config.margin_meters,
            include_context=self.config.include_context,
        )
        output_directory = self.config.city_output_directory / str(year)
        debug_directory = (
            self.config.output_root
            / "_debug"
            / self.config.city_directory
            / str(year)
            / "_raw"
        )
        saved = 0
        failed = 0

        LOGGER.info("Year %d: processing %d buildings", year, len(jobs))
        for position, (job, (_, row)) in enumerate(
            zip(jobs, year_buildings.iterrows(), strict=True),
            start=1,
        ):
            output_id = self._output_id(row, job.geometry_id, position, year)
            try:
                raster = self.orthophoto_loader(job.bbox, job.width, job.height, year)
                metrics = calculate_quality_metrics(
                    raster.pixels, job.geometry, raster.transform
                )
                output_pixels = (
                    raster.pixels
                    if self.config.include_context
                    else white_outside_geometry(
                        raster.pixels, job.geometry, raster.transform
                    )
                )

                if saved < self.config.debug_first:
                    save_png(debug_directory / f"{output_id}_raw.png", raster.pixels)
                save_png(output_directory / f"{output_id}.png", output_pixels)
                saved += 1
                LOGGER.debug(
                    "Year %d tile %s: coverage=%.4f raw_min=%.1f raw_max=%.1f raw_std=%.2f",
                    year,
                    output_id,
                    metrics.mask_coverage,
                    metrics.raw_min,
                    metrics.raw_max,
                    metrics.raw_std,
                )
            except Exception:
                failed += 1
                LOGGER.exception("Year %d: failed building %s", year, output_id)

        LOGGER.info("Year %d completed: saved=%d failed=%d", year, saved, failed)
        return YearResult(year, attempted=len(jobs), saved=saved, failed=failed)

    def _buildings_for_year(
        self, buildings: gpd.GeoDataFrame, year: int
    ) -> gpd.GeoDataFrame:
        if not self.config.uses_ground_truth:
            return filter_cadastre_by_year(
                buildings,
                year,
                self.config.start_date_field,
                self.config.end_date_field,
            )
        if self.config.ground_truth_filter == "all":
            return buildings.copy()

        year_column = f"GT_{year}"
        if year_column not in buildings.columns:
            raise ValueError(f"Ground-truth data has no '{year_column}' column.")
        return buildings.loc[buildings[year_column].fillna(0) != 0].copy()

    def _output_id(
        self, row: pd.Series, geometry_id: str, position: int, year: int
    ) -> str:
        if not self.config.uses_ground_truth:
            return geometry_id
        feature_id = row.get("output_base_id") or cadastre_feature_id(row) or position
        base_name = f"{self.config.output_prefix}_{feature_id}"
        return f"{base_name}_{year}" if self.config.include_year_in_name else base_name
