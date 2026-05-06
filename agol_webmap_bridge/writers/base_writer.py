"""Abstract base writer for map output formats."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseWriter(ABC):
    """Base class for map format writers.

    Sub-class this to add support for a new output format (e.g. QGIS project,
    Mapbox GL JSON, etc.).  Implement :meth:`write` to serialise *map_config*
    to the desired format and write it to *path*.
    """

    @abstractmethod
    def write(self, map_config: dict, path: Path) -> None:
        """Serialise *map_config* and write it to *path*.

        Args:
            map_config: Intermediate map configuration produced by the converter.
            path: Destination file path.
        """
