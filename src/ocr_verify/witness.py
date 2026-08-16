"""The witness engine.

Tesseract is used not because it is accurate but because it is *boring*: it is
deterministic, it emits per-word confidences and bounding boxes, and it does not
invent text. When it and a generative engine disagree, the disagreement is
evidence; the crop shipped alongside it is what lets a human settle the matter.
"""

from __future__ import annotations

import csv
import io
import shutil
import subprocess
from pathlib import Path

from .model import WitnessPage, Word
from .normalize import normalize_token
from .render import ink_ratio


class TesseractMissing(RuntimeError):
    pass


def find_tesseract() -> str:
    exe = shutil.which("tesseract")
    if not exe:
        raise TesseractMissing(
            "tesseract not found on PATH.\n"
            "  macOS:  brew install tesseract\n"
            "  Debian: apt-get install tesseract-ocr"
        )
    return exe


def tesseract_version() -> str:
    try:
        out = subprocess.run(
            [find_tesseract(), "--version"], capture_output=True, text=True, check=False
        )
        return (out.stdout or out.stderr).splitlines()[0].strip()
    except (TesseractMissing, IndexError):
        return "unknown"


def run_witness(
    image: Path,
    page_index: int,
    *,
    lang: str = "eng",
    psm: int = 3,
    timeout: int = 300,
) -> WitnessPage:
    """OCR one rendered page and return its words with boxes and confidences."""
    exe = find_tesseract()
    cmd = [exe, str(image), "stdout", "-l", lang, "--psm", str(psm), "tsv"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"tesseract failed on {image.name} (exit {proc.returncode}): {proc.stderr.strip()[:400]}"
        )

    words = _parse_tsv(proc.stdout)
    width, height = _image_size(image)
    return WitnessPage(
        index=page_index,
        width=width,
        height=height,
        words=words,
        ink_ratio=ink_ratio(image),
        image=image,
    )


def _image_size(image: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(image) as im:
        return im.size


def _parse_tsv(tsv: str) -> list[Word]:
    words: list[Word] = []
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        if row.get("level") != "5":  # level 5 == word
            continue
        text = (row.get("text") or "").strip()
        if not text:
            continue
        norm = normalize_token(text)
        if not norm:
            continue
        try:
            conf = float(row["conf"])
            left, top = int(row["left"]), int(row["top"])
            w, h = int(row["width"]), int(row["height"])
            line_key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        except (KeyError, TypeError, ValueError):
            continue
        if conf < 0:  # Tesseract's sentinel for "no confidence available"
            continue
        words.append(
            Word(
                text=text,
                norm=norm,
                conf=conf,
                bbox=(left, top, left + w, top + h),
                line_key=line_key,
            )
        )
    return words


def line_bbox(words: list[Word], line_key: tuple[int, int, int]) -> tuple[int, int, int, int] | None:
    """Union bbox of every word on a given text line."""
    boxes = [w.bbox for w in words if w.line_key == line_key]
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )
