from __future__ import annotations

import os
import sys
from pathlib import Path


def configure_geospatial_environment() -> None:
    """Expose Conda GDAL/PROJ resource directories when the IDE does not."""
    share_directory = Path(sys.prefix) / "Library" / "share"
    gdal_directory = share_directory / "gdal"
    proj_directory = share_directory / "proj"
    if "GDAL_DATA" not in os.environ and gdal_directory.is_dir():
        os.environ["GDAL_DATA"] = str(gdal_directory)
    if "PROJ_LIB" not in os.environ and proj_directory.is_dir():
        os.environ["PROJ_LIB"] = str(proj_directory)
