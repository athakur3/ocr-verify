"""PDF rasterization.

PyMuPDF is used rather than poppler so a `pip install` is the whole setup on the
PDF side; Tesseract remains the only system dependency.
"""

from __future__ import annotations

from pathlib import Path


def _pymupdf():
    """Import PyMuPDF under whichever module name this install provides.

    The package renamed itself from `fitz` to `pymupdf` in 1.24.3 and now warns on
    the old name; both are still shipped, so accept either.
    """
    try:
        import pymupdf

        return pymupdf
    except ImportError:  # pragma: no cover - only on PyMuPDF < 1.24.3
        import fitz

        return fitz


def render_pdf(pdf: Path, out_dir: Path, dpi: int = 200, pages: list[int] | None = None) -> list[Path]:
    """Render pages to PNG. Returns paths indexed by page order.

    `pages` is a 0-based whitelist; None renders everything.
    """
    fitz = _pymupdf()

    out_dir.mkdir(parents=True, exist_ok=True)
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    written: list[Path] = []
    with fitz.open(pdf) as doc:
        wanted = range(doc.page_count) if pages is None else pages
        for i in wanted:
            if i < 0 or i >= doc.page_count:
                raise ValueError(f"page {i + 1} out of range (document has {doc.page_count} pages)")
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csGRAY)
            path = out_dir / f"page-{i + 1:04d}.png"
            pix.save(path)
            written.append(path)
    return written


def page_count(pdf: Path) -> int:
    fitz = _pymupdf()

    with fitz.open(pdf) as doc:
        return doc.page_count


def ink_ratio(image_path: Path, threshold: int = 200) -> float:
    """Fraction of pixels dark enough to be ink.

    Deliberately crude and deterministic: this is the blank-page detector, and a
    blank-page claim in the report must be defensible from the image alone.
    Downsampled so the cost is negligible on large scans.
    """
    from PIL import Image

    with Image.open(image_path) as im:
        im = im.convert("L")
        im.thumbnail((1000, 1000))
        hist = im.histogram()
    total = sum(hist)
    if not total:
        return 0.0
    dark = sum(hist[: threshold + 1])
    return dark / total
