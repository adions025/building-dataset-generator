from __future__ import annotations

import logging

from affine import Affine
from rasterio import features
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from .models import ImageArray, QualityMetrics

LOGGER = logging.getLogger(__name__)


def calculate_quality_metrics(
    array: ImageArray, geometry: BaseGeometry, transform: Affine
) -> QualityMetrics:
    height, width = array.shape[1], array.shape[2]
    mask = features.rasterize(
        [(geometry, 1)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)
    coverage = float(mask.mean()) if mask.size else 0.0
    return QualityMetrics(
        coverage, float(array.min()), float(array.max()), float(array.std())
    )


def white_outside_geometry(
    array: ImageArray,
    geometry: BaseGeometry,
    transform: Affine,
) -> ImageArray:
    height, width = array.shape[1], array.shape[2]
    mask = features.rasterize(
        [(mapping(geometry), 1)],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)

    if not mask.any():
        LOGGER.warning("Building geometry covers no pixels in the generated tile")

    output = array.copy()
    for band_index in range(min(3, output.shape[0])):
        output[band_index][~mask] = 255
    if output.shape[0] >= 4:
        output[3][:] = 255
    return output
