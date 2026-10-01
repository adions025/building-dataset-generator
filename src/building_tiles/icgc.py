from __future__ import annotations

import unicodedata

import geopandas as gpd
import requests
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

from .config import BOUNDARIES_DIR, TARGET_CRS
from .models import BoundingBox, RasterTile

TERRITORIAL_WMS_URL = (
    "https://geoserveis.icgc.cat/servei/catalunya/orto-territorial/wms"
)
TERRITORIAL_LAYER = "ortofoto_color_serie_anual"
MUNICIPALITIES_QUERY_URL = "https://geoserveis.icgc.cat/vector01/rest/services/divisions_administratives_wfs/MapServer/2/query"
MUNICIPALITIES_ZIP = BOUNDARIES_DIR / "divisions-administratives-v2r1-20250730.zip"
MUNICIPALITIES_SHAPEFILE = "divisions-administratives-v2r1-municipis-5000-20250730.shp"


def _normalized_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return (
        "".join(
            character
            for character in decomposed
            if not unicodedata.combining(character)
        )
        .lower()
        .strip()
    )


def _select_municipality(
    municipalities: gpd.GeoDataFrame,
    city: str,
    source: str,
) -> gpd.GeoDataFrame:
    if municipalities.empty or "NOMMUNI" not in municipalities.columns:
        raise ValueError(f"{source} returned no municipality matches for '{city}'.")

    wanted = _normalized_name(city)

    def score(name: str) -> int:
        normalized = _normalized_name(name)
        if normalized == wanted:
            return 100
        if normalized.startswith(wanted):
            return 80
        if wanted in normalized:
            return 60
        return 0

    candidates = municipalities.copy()
    candidates["__score"] = candidates["NOMMUNI"].astype(str).map(score)
    candidates["__area"] = candidates.geometry.area
    candidates = candidates.sort_values(["__score", "__area"], ascending=[False, False])
    if candidates["__score"].iloc[0] == 0:
        suggestions = ", ".join(candidates["NOMMUNI"].head(5).astype(str))
        raise ValueError(
            f"Municipality '{city}' was not found in {source}. Suggestions: {suggestions}"
        )
    return candidates.head(1).drop(columns=["__score", "__area"]).reset_index(drop=True)


def _load_local_municipality(city: str) -> gpd.GeoDataFrame:
    if not MUNICIPALITIES_ZIP.is_file():
        raise FileNotFoundError(
            f"Local municipality archive not found: {MUNICIPALITIES_ZIP}"
        )

    errors = []
    paths = (
        f"zip+file://{MUNICIPALITIES_ZIP}!{MUNICIPALITIES_SHAPEFILE}",
        f"zip://{MUNICIPALITIES_ZIP}!{MUNICIPALITIES_SHAPEFILE}",
    )
    for path in paths:
        try:
            municipalities = gpd.read_file(path)
            if (
                municipalities.crs
                and municipalities.crs.to_string().upper() != TARGET_CRS
            ):
                municipalities = municipalities.to_crs(TARGET_CRS)
            return _select_municipality(
                municipalities, city, "local municipality archive"
            )
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    raise RuntimeError(
        "Unable to read the local municipality archive. " + " | ".join(errors)
    )


def _load_remote_municipality(city: str) -> gpd.GeoDataFrame:
    escaped_city = city.strip().replace("'", "''")

    def search(where: str) -> gpd.GeoDataFrame:
        response = requests.get(
            MUNICIPALITIES_QUERY_URL,
            params={
                "where": where,
                "outFields": "NOMMUNI,NOMCOMAR",
                "returnGeometry": "true",
                "outSR": "25831",
                "f": "geojson",
            },
            timeout=30,
        )
        response.raise_for_status()
        features = response.json().get("features", [])
        if features:
            return gpd.GeoDataFrame.from_features(features, crs=TARGET_CRS)
        return gpd.GeoDataFrame(geometry=[], crs=TARGET_CRS)

    municipalities = search(f"UPPER(NOMMUNI) = '{escaped_city.upper()}'")
    if municipalities.empty:
        municipalities = search(f"NOMMUNI LIKE '%{escaped_city.upper()}%'")
    return _select_municipality(municipalities, city, "ICGC service")


def get_municipality_boundary(city: str) -> gpd.GeoDataFrame:
    try:
        return _load_local_municipality(city)
    except (FileNotFoundError, OSError, RuntimeError, ValueError):
        return _load_remote_municipality(city)


def download_orthophoto(
    bbox: BoundingBox,
    width: int,
    height: int,
    year: int,
) -> RasterTile:
    min_x, min_y, max_x, max_y = bbox
    response = requests.get(
        TERRITORIAL_WMS_URL,
        params={
            "SERVICE": "WMS",
            "VERSION": "1.1.1",
            "REQUEST": "GetMap",
            "LAYERS": TERRITORIAL_LAYER,
            "STYLES": "",
            "SRS": TARGET_CRS,
            "BBOX": f"{min_x:.3f},{min_y:.3f},{max_x:.3f},{max_y:.3f}",
            "WIDTH": str(width),
            "HEIGHT": str(height),
            "FORMAT": "image/png",
            "TRANSPARENT": "FALSE",
            "TIME": str(year),
            "EXCEPTIONS": "application/vnd.ogc.se_xml",
        },
        timeout=90,
    )
    response.raise_for_status()
    content_start = response.content.lstrip()[:200].lower()
    if content_start.startswith(b"<?xml") and b"exception" in content_start:
        raise RuntimeError(f"ICGC WMS rejected year {year}: {response.text[:300]}")

    with MemoryFile(response.content) as memory_file, memory_file.open() as dataset:
        pixels = dataset.read()
    transform = from_bounds(min_x, min_y, max_x, max_y, width, height)
    return RasterTile(pixels=pixels, transform=transform)
