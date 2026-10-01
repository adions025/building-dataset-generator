from __future__ import annotations

import argparse
import logging
import warnings
from logging.handlers import RotatingFileHandler
from pathlib import Path

from building_tiles.config import (
    DEFAULT_MARGIN_METERS,
    DEFAULT_METERS_PER_PIXEL,
    DEFAULT_OUTPUTS_DIR,
    GenerationConfig,
)
from building_tiles.runtime import configure_geospatial_environment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate per-building thumbnails from ICGC Territorial orthophotos."
    )
    parser.add_argument("--city", required=True, help="Municipality or area name.")
    parser.add_argument(
        "--year-ini", type=int, required=True, help="Initial year, inclusive."
    )
    parser.add_argument(
        "--year-end", type=int, required=True, help="Final year, inclusive."
    )
    parser.add_argument(
        "--province", help="Province used to narrow Catastro ATOM lookup."
    )
    parser.add_argument(
        "--max-workers", type=int, default=4, help="Maximum concurrent years."
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=DEFAULT_MARGIN_METERS,
        help="Margin around buildings in meters.",
    )
    parser.add_argument(
        "--mpp",
        type=float,
        default=DEFAULT_METERS_PER_PIXEL,
        help="Target meters per pixel.",
    )
    parser.add_argument(
        "--outroot",
        type=Path,
        default=DEFAULT_OUTPUTS_DIR,
        help="Output root directory.",
    )

    parser.add_argument("--cadastre-source", choices=("file", "atom"), default="atom")
    parser.add_argument("--cadastre", type=Path, help="Local cadastral building file.")
    parser.add_argument(
        "--cadastre-city", help="Official municipality used for Catastro lookup."
    )
    parser.add_argument(
        "--atom-cache", type=Path, help="Optional GeoPackage cache for Catastro ATOM."
    )

    parser.add_argument("--gt-polygons", type=Path, help="Ground-truth GeoPackage.")
    parser.add_argument(
        "--gt-layer", help="Ground-truth layer; defaults to the first layer."
    )
    parser.add_argument("--gt-filter", choices=("all", "positive"), default="all")
    parser.add_argument("--output-prefix", default="build")
    parser.add_argument("--omit-year-in-name", action="store_true")
    parser.add_argument("--ids-from-dir", type=Path, nargs="*", default=[])

    parser.add_argument("--keep-multipart-buildings", action="store_true")
    parser.add_argument(
        "--include-context",
        action="store_true",
        help="Keep the complete bounding-box image without masking its surroundings.",
    )
    parser.add_argument("--debug-first", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show debug logs and expected Rasterio georeferencing warnings.",
    )
    parser.add_argument("--alta-field", default="FECHAALTA")
    parser.add_argument("--baja-field", default="FECHABAJA")

    parser.add_argument(
        "--aoi-mode", choices=("muni", "from-cadastre", "bbox", "file"), default="muni"
    )
    parser.add_argument("--aoi-file", type=Path)
    parser.add_argument("--aoi-bbox", type=_parse_bbox)
    parser.add_argument("--aoi-crs", default="EPSG:25831")
    return parser


def config_from_args(args: argparse.Namespace) -> GenerationConfig:
    return GenerationConfig(
        city=args.city,
        year_start=args.year_ini,
        year_end=args.year_end,
        province=args.province,
        max_workers=args.max_workers,
        margin_meters=args.margin,
        meters_per_pixel=args.mpp,
        output_root=args.outroot.expanduser().resolve(),
        cadastre_source=args.cadastre_source,
        cadastre_file=args.cadastre,
        cadastre_city=args.cadastre_city,
        atom_cache=args.atom_cache,
        ground_truth_file=args.gt_polygons,
        ground_truth_layer=args.gt_layer,
        ground_truth_filter=args.gt_filter,
        output_prefix=args.output_prefix,
        include_year_in_name=not args.omit_year_in_name,
        ids_from_directories=tuple(args.ids_from_dir),
        keep_multipart_buildings=args.keep_multipart_buildings,
        include_context=args.include_context,
        debug_first=args.debug_first,
        limit=args.limit,
        start_date_field=args.alta_field,
        end_date_field=args.baja_field,
        aoi_mode=args.aoi_mode,
        aoi_file=args.aoi_file,
        aoi_bbox=args.aoi_bbox,
        aoi_crs=args.aoi_crs,
    ).with_submunicipal_defaults()


def configure_logging(config: GenerationConfig, verbose: bool = False) -> Path:
    config.city_output_directory.mkdir(parents=True, exist_ok=True)
    log_path = config.city_output_directory / "generation.log"
    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    return log_path


def log_run_configuration(
    logger: logging.Logger,
    config: GenerationConfig,
    verbose: bool,
) -> None:
    source = (
        "ground-truth"
        if config.uses_ground_truth
        else f"cadastre:{config.cadastre_source}"
    )
    image_mode = (
        "context (exact geometry bounds)"
        if config.include_context
        else f"masked (margin={config.margin_meters:g} m)"
    )
    if config.uses_ground_truth:
        multipart_mode = "as provided by ground truth"
    else:
        multipart_mode = (
            "keep together" if config.keep_multipart_buildings else "split components"
        )
    limit = str(config.limit) if config.limit else "all"
    logger.info(
        "Run options | source=%s | image=%s | multipart=%s | aoi=%s | "
        "resolution=%g m/px | years=%d-%d | workers=%d | limit=%s | verbose=%s",
        source,
        image_mode,
        multipart_mode,
        config.aoi_mode,
        config.meters_per_pixel,
        config.year_start,
        config.year_end,
        config.max_workers,
        limit,
        "yes" if verbose else "no",
    )


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        coordinates = tuple(float(item) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("BBox coordinates must be numbers.") from exc
    if len(coordinates) != 4:
        raise argparse.ArgumentTypeError("BBox must be 'minx,miny,maxx,maxy'.")
    return coordinates


def configure_warnings(verbose: bool) -> None:
    from rasterio.errors import NotGeoreferencedWarning

    action = "always" if verbose else "ignore"
    warnings.filterwarnings(action, category=NotGeoreferencedWarning)


def main(arguments: list[str] | None = None) -> int:
    configure_geospatial_environment()
    parser = build_parser()
    args = parser.parse_args(arguments)
    configure_warnings(args.verbose)

    from building_tiles.generator import ThumbnailGenerator

    try:
        config = config_from_args(args)
        config.validate()
    except ValueError as exc:
        parser.error(str(exc))

    log_path = configure_logging(config, verbose=args.verbose)
    logger = logging.getLogger(__name__)
    logger.info("Starting generation for %s; log=%s", config.city, log_path)
    log_run_configuration(logger, config, args.verbose)
    try:
        ThumbnailGenerator(config).run()
    except KeyboardInterrupt:
        logger.warning("Generation interrupted by the user")
        return 130
    except Exception:
        logger.exception("Generation failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
