"""ocr-verify — trust but verify for AI OCR.

Runs deterministic Tesseract as a witness against a vision-language OCR engine's
output and surfaces only the places the two disagree, each backed by a crop of
the original scan.
"""

__version__ = "0.1.0"

from .align import Settings, compare_page
from .model import Finding, PageResult, Report

__all__ = ["Settings", "compare_page", "Finding", "PageResult", "Report", "__version__"]
