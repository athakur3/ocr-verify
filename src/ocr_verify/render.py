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


def robust_ink_ratio(
    image_path: Path,
    work: int = 1000,
    delta: int = 50,
    min_component: int = 12,
) -> float:
    """Ink fraction that survives noise, speckle, shadow gradients and scan streaks.

    Pipeline (red-team prototype, 2026-08-16): estimate the local background with
    a max filter, threshold the difference (kills sensor noise and illumination
    gradients), then keep only connected components of text scale — dropping
    dust (< min_component px) and full-width sliver streaks (scan-head lines).

    Used to GRADE unverifiable-page hedges, never to accuse: faint real text
    also measures ~0 here (the study's fade_heavy page scores 0.000), so a low
    value means "dirty blank OR very faint text", which is exactly the wording
    the report uses. Cost is a pure-Python flood fill on a thumbnail, so it is
    only computed for pages that need it.
    """
    from collections import deque

    from PIL import Image, ImageChops, ImageFilter

    with Image.open(image_path) as im:
        im = im.convert("L")
        im.thumbnail((work, work))
        background = im.filter(ImageFilter.MaxFilter(31))
        mask = ImageChops.subtract(background, im).point(lambda v: 255 if v >= delta else 0)

    w, h = mask.size
    px = mask.load()
    seen = bytearray(w * h)
    kept = 0
    for x0 in range(w):
        for y0 in range(h):
            if seen[x0 * h + y0] or px[x0, y0] == 0:
                continue
            queue = deque([(x0, y0)])
            seen[x0 * h + y0] = 1
            size = 0
            minx = maxx = x0
            miny = maxy = y0
            while queue:
                x, y = queue.popleft()
                size += 1
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[nx * h + ny] and px[nx, ny]:
                        seen[nx * h + ny] = 1
                        queue.append((nx, ny))
            if size < min_component:
                continue
            if (maxx - minx + 1) > 0.6 * w and (maxy - miny + 1) <= 6:
                continue  # scan-head streak: page-wide but a few pixels tall
            kept += size
    return kept / (w * h) if w and h else 0.0


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
