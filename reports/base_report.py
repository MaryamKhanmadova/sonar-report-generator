"""
Abstract base class for all report generators.

Defines the common interface and shared utilities so each concrete
generator (PDF, DOCX, Excel, HTML, JSON) only needs to implement
:meth:`generate`.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.project import ReportData

logger = logging.getLogger(__name__)


class BaseReport(ABC):
    """
    Abstract report generator.

    Parameters
    ----------
    output_dir:
        Directory where the output file will be written.
    """

    def __init__(self, output_dir: str = "output") -> None:
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def generate(self, data: "ReportData") -> str:
        """
        Generate the report and return the absolute path to the output file.

        Parameters
        ----------
        data:
            Fully populated :class:`ReportData` bundle.

        Returns
        -------
        str
            Absolute path to the generated file.
        """

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def output_path(self, filename: str) -> str:
        """Return the full output path for a given filename."""
        return os.path.join(self.output_dir, filename)

    @staticmethod
    def format_date(dt: datetime, fmt: str = "%B %d, %Y") -> str:
        """Format a datetime for display."""
        return dt.strftime(fmt)

    @staticmethod
    def format_datetime(dt: datetime) -> str:
        """Format a datetime with time component."""
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    @staticmethod
    def truncate(text: str, max_len: int = 80) -> str:
        """Truncate text and append ellipsis if needed."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "…"
