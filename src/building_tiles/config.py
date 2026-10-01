from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_SOURCES_DIR = PROJECT_ROOT / "data_sources"
BOUNDARIES_DIR = DATA_SOURCES_DIR / "boundaries"
GROUND_TRUTH_DIR = DATA_SOURCES_DIR / "ground_truth"
DEFAULT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"
TARGET_CRS = "EPSG:25831"

DEFAULT_MARGIN_METERS = 0.5
DEFAULT_METERS_PER_PIXEL = 0.25
MAX_IMAGE_SIDE = 2048


@dataclass(frozen=True)
class SubmunicipalArea:
    cadastre_city: str
    boundary_file: Path


SUBMUNICIPAL_AREAS = {
    "valldoreix": SubmunicipalArea(
        cadastre_city="Sant Cugat del Vallès",
        boundary_file=BOUNDARIES_DIR / "valldoreix_boundary.geojson",
    ),
}


def normalized_city_key(city: str) -> str:
    return re.sub(r"\s+", " ", city.strip().replace("_", " ")).casefold()


def city_directory_name(city: str) -> str:
    name = re.sub(r"[^\w-]+", "_", city.strip(), flags=re.UNICODE).strip("_")
    if not name or name in {".", ".."}:
        raise ValueError("City must contain at least one letter or number.")
    return name


@dataclass(frozen=True)
class GenerationConfig:
    city: str
    year_start: int
    year_end: int
    province: str | None = None
    max_workers: int = 4
    margin_meters: float = DEFAULT_MARGIN_METERS
    meters_per_pixel: float = DEFAULT_METERS_PER_PIXEL
    output_root: Path = DEFAULT_OUTPUTS_DIR
    cadastre_source: str = "atom"
    cadastre_file: Path | None = None
    cadastre_city: str | None = None
    atom_cache: Path | None = None
    ground_truth_file: Path | None = None
    ground_truth_layer: str | None = None
    ground_truth_filter: str = "all"
    output_prefix: str = "build"
    include_year_in_name: bool = True
    ids_from_directories: tuple[Path, ...] = ()
    keep_multipart_buildings: bool = False
    debug_first: int = 0
    limit: int = 0
    start_date_field: str = "FECHAALTA"
    end_date_field: str = "FECHABAJA"
    aoi_mode: str = "muni"
    aoi_file: Path | None = None
    aoi_bbox: tuple[float, float, float, float] | None = None
    aoi_crs: str = TARGET_CRS

    @property
    def city_directory(self) -> str:
        return city_directory_name(self.city)

    @property
    def city_output_directory(self) -> Path:
        return self.output_root / self.city_directory

    @property
    def effective_cadastre_city(self) -> str:
        return self.cadastre_city or self.city

    @property
    def years(self) -> range:
        return range(self.year_start, self.year_end + 1)

    @property
    def uses_ground_truth(self) -> bool:
        return self.ground_truth_file is not None

    def with_submunicipal_defaults(self) -> GenerationConfig:
        area = SUBMUNICIPAL_AREAS.get(normalized_city_key(self.city))
        if area is None:
            return self

        changes: dict[str, object] = {}
        if not self.cadastre_city:
            changes["cadastre_city"] = area.cadastre_city
        if self.aoi_mode == "muni" and self.aoi_file is None:
            changes["aoi_mode"] = "file"
            changes["aoi_file"] = area.boundary_file
        return replace(self, **changes)

    def validate(self) -> None:
        if not self.city.strip():
            raise ValueError("--city cannot be empty.")
        city_directory_name(self.city)
        if self.year_start > self.year_end:
            raise ValueError("--year-ini must be less than or equal to --year-end.")
        if self.margin_meters < 0:
            raise ValueError("--margin must be zero or greater.")
        if self.meters_per_pixel <= 0:
            raise ValueError("--mpp must be greater than zero.")
        if self.max_workers < 1:
            raise ValueError("--max-workers must be at least 1.")
        if self.debug_first < 0 or self.limit < 0:
            raise ValueError("--debug-first and --limit cannot be negative.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.output_prefix):
            raise ValueError(
                "--output-prefix may contain only letters, numbers, underscores, and hyphens."
            )
        if self.cadastre_source not in {"file", "atom"}:
            raise ValueError(f"Unsupported cadastre source: {self.cadastre_source}")
        if self.aoi_mode not in {"muni", "from-cadastre", "bbox", "file"}:
            raise ValueError(f"Unsupported AOI mode: {self.aoi_mode}")
        if self.ground_truth_filter not in {"all", "positive"}:
            raise ValueError(
                f"Unsupported ground-truth filter: {self.ground_truth_filter}"
            )
        if (
            self.cadastre_source == "file"
            and self.cadastre_file is None
            and not self.uses_ground_truth
        ):
            raise ValueError("--cadastre is required when --cadastre-source=file.")
        if self.aoi_mode == "file" and self.aoi_file is None:
            raise ValueError("--aoi-file is required when --aoi-mode=file.")
        if self.aoi_mode == "bbox" and self.aoi_bbox is None:
            raise ValueError("--aoi-bbox is required when --aoi-mode=bbox.")
