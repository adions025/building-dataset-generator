from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

import numpy as np
from affine import Affine
from numpy.typing import NDArray
from shapely.geometry.base import BaseGeometry

BoundingBox: TypeAlias = tuple[float, float, float, float]
ImageArray: TypeAlias = NDArray[np.uint8]


@dataclass(frozen=True)
class TileJob:
    geometry_id: str
    geometry: BaseGeometry
    bbox: BoundingBox
    width: int
    height: int


@dataclass(frozen=True)
class RasterTile:
    pixels: ImageArray
    transform: Affine


@dataclass(frozen=True)
class QualityMetrics:
    mask_coverage: float
    raw_min: float
    raw_max: float
    raw_std: float


@dataclass(frozen=True)
class YearResult:
    year: int
    attempted: int
    saved: int
    failed: int

    @property
    def successful(self) -> bool:
        return self.failed == 0
