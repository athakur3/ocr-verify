"""Small corpus exercising the two degradation modes the real-archival wild
hunt exposed (study/wild/README.md): hand-lettered display type (the "FAR EAST
SPOTLIGHT" cover) and uneven mimeograph ink. The main 24-page study corpus
(study/make_corpus.py) does not cover either, so witness fix (a) — the tight
local-confidence window landed in commit 018ea33 — was validated only against
one real downloaded document. This corpus makes that check reproducible and
puts it in front of the test suite (tests/test_degradation_modes.py) instead
of a one-off probe script.

Every page's ground truth is text this script wrote, so precision on these
pages has an unambiguous answer: with a "perfect" engine transcript (== ground
truth, standing in for an engine that made no error at all), any finding
ocr-verify raises here is caused purely by the witness struggling with the
degraded image, not by any real engine error.

Page 1 (hand_lettered_cover) mirrors the real page 1 failure exactly: a large
warped masthead title sits above a normal clean paragraph. The clean body
supplies enough well-read neighbours that the *page*-level confidence average
stays healthy, while the title words themselves read low locally — the split
that specifically exercises fix (a)'s local-vs-page-mean distinction (see
tests/test_degradation_modes.py for the numbers).

Page 2 (mimeograph_body) is uneven ink density across an ordinary paragraph.
At the severity used here it degrades enough of the page that the *existing*
wholesale-disagreement fold (not fix (a)) is what keeps ocr-verify from
raising an itemized accusation — also a real guard worth pinning against a
mode the corpus never previously covered.

Run: uv run python study/degradation_modes/make_modes_corpus.py
"""

from __future__ import annotations

import io
import json
import random
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).parent.parent))
from make_corpus import (  # noqa: E402
    PAGE_H_PT,
    PAGE_W_PT,
    PASSAGES,
    hand_lettered,
    mimeograph,
    render,
)

ROOT = Path(__file__).parent
PDF = ROOT / "modes.pdf"
TRUTH = ROOT / "ground_truth.json"

SEED = 20260817
DPI = 200

TITLE = "THE FRONTIER GAZETTE\nSpecial Report from the Northern Stations"
# Title-band bounds in 200-DPI pixels, matching the textbox below (60-230pt).
TITLE_Y0, TITLE_Y1 = 160, 650

# Parameters found by grid search against this exact seed (study/degradation_modes/
# make_modes_corpus.py, block 10): the smallest, most typical setting in a wide
# plateau of hits where fix (a)'s tight window (context=1) hedges the title
# finding and the pre-fix wide window (context=8) does not.
HAND_LETTER_AMPLITUDE = 6.2
HAND_LETTER_PERIOD = 18.0
HAND_LETTER_BLUR = 0.65

MIMEOGRAPH_STRENGTH = 0.6


def _render_cover(title: str, body: str) -> Image.Image:
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W_PT, height=PAGE_H_PT)
    page.insert_textbox(
        pymupdf.Rect(54, 60, PAGE_W_PT - 54, 230),
        title, fontsize=30, fontname="times-bold", align=1,
    )
    page.insert_textbox(
        pymupdf.Rect(72, 260, PAGE_W_PT - 72, PAGE_H_PT - 72),
        body, fontsize=12, fontname="times-roman",
    )
    pix = page.get_pixmap(matrix=pymupdf.Matrix(DPI / 72, DPI / 72), colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    doc.close()
    return img


def build() -> None:
    rng = random.Random(SEED)

    body_for_cover = PASSAGES["conclusions"]
    cover = _render_cover(TITLE, body_for_cover)
    # Warp the whole page (so the sine offset is computed in the same
    # page-absolute row coordinates the calibration search used), then keep
    # only the title band from the result -- the body stays untouched.
    warped_whole = hand_lettered(
        cover, rng, amplitude=HAND_LETTER_AMPLITUDE, period=HAND_LETTER_PERIOD
    )
    hand_lettered_img = cover.copy()
    hand_lettered_img.paste(
        warped_whole.crop((0, TITLE_Y0, cover.width, TITLE_Y1)), (0, TITLE_Y0)
    )
    hand_lettered_img = hand_lettered_img.filter(ImageFilter.GaussianBlur(HAND_LETTER_BLUR))
    hand_lettered_truth = TITLE.replace("\n", " ") + " " + body_for_cover

    body_img = render(PASSAGES["instruments"])
    mimeograph_img = mimeograph(body_img, MIMEOGRAPH_STRENGTH, rng)

    pages = [
        ("hand_lettered_cover", hand_lettered_truth, hand_lettered_img),
        ("mimeograph_body", PASSAGES["instruments"], mimeograph_img),
    ]

    doc = pymupdf.open()
    truth = []
    for number, (kind, text, img) in enumerate(pages, start=1):
        buf = io.BytesIO()
        img.convert("L").save(buf, format="PNG")
        page = doc.new_page(width=PAGE_W_PT, height=PAGE_H_PT)
        page.insert_image(pymupdf.Rect(0, 0, PAGE_W_PT, PAGE_H_PT), stream=buf.getvalue())
        truth.append({"page": number, "kind": kind, "text": text.strip()})

    doc.save(PDF, deflate=True)
    doc.close()
    TRUTH.write_text(json.dumps({"seed": SEED, "pages": truth}, indent=2), "utf-8")
    print(f"wrote {PDF} ({len(pages)} pages)")
    print(f"wrote {TRUTH}")


if __name__ == "__main__":
    build()
