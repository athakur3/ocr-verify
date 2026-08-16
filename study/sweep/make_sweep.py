"""Ghost-contrast sweep corpus.

Both engines fabricated on the study's bleed-through page (ghost strength 0.55).
One data point per engine says "it happens"; a sweep says *when* it happens.
Six pages, identical real text (the conclusions passage), mirrored ghost of the
survey passage underneath at increasing strength. Ground truth is identical for
every page, so any emitted word outside it is fabricated — and the fabrication
count as a function of ghost strength is each engine's failure curve.

Run: uv run python study/sweep/make_sweep.py
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent.parent))
from make_corpus import PAGE_H_PT, PAGE_W_PT, PASSAGES, bleed_through, render  # noqa: E402

ROOT = Path(__file__).parent
PDF = ROOT / "sweep.pdf"
TRUTH = ROOT / "ground_truth.json"

STRENGTHS = [0.0, 0.10, 0.20, 0.30, 0.40, 0.55]


def build() -> None:
    real = render(PASSAGES["conclusions"])
    ghost_source = render(PASSAGES["survey"])

    doc = pymupdf.open()
    truth = []
    for number, strength in enumerate(STRENGTHS, start=1):
        img = real if strength == 0.0 else bleed_through(real, ghost_source, strength)
        buf = io.BytesIO()
        img.convert("L").save(buf, format="PNG")
        page = doc.new_page(width=PAGE_W_PT, height=PAGE_H_PT)
        page.insert_image(pymupdf.Rect(0, 0, PAGE_W_PT, PAGE_H_PT), stream=buf.getvalue())
        truth.append(
            {
                "page": number,
                "ghost_strength": strength,
                "text": PASSAGES["conclusions"].strip(),
            }
        )

    doc.save(PDF, deflate=True)
    doc.close()
    TRUTH.write_text(json.dumps({"strengths": STRENGTHS, "pages": truth}, indent=2), "utf-8")
    print(f"wrote {PDF} ({len(STRENGTHS)} pages, strengths {STRENGTHS})")


if __name__ == "__main__":
    build()
