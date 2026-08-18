"""Bisect the second-seed sweep's coarse 0.10-0.20 gap (tides/instruments pair).

Sweep 2 (make_sweep2.py) placed both engines' onset in the same coarse bin:
Marker went from 0 fabricated at 0.10 to 2 at 0.20, MinerU from 0 to 4 at the
same step — a tie at this resolution, unlike pair 1 and pair 3 where MinerU
crossed first. This bisect (0.125/0.15/0.175, matching the original sweep's
own bisect ladder) targets that exact gap to see whether the tie is real or
just coarse-resolution aliasing, and whether "MinerU first" generalizes to a
second pair.

Run: uv run python study/sweep/make_sweep2_bisect.py
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
PDF = ROOT / "sweep2_bisect.pdf"
TRUTH = ROOT / "sweep2_bisect_ground_truth.json"

STRENGTHS = [0.125, 0.15, 0.175]
REAL_KEY = "tides"
GHOST_KEY = "instruments"


def build() -> None:
    real = render(PASSAGES[REAL_KEY])
    ghost_source = render(PASSAGES[GHOST_KEY])

    doc = pymupdf.open()
    truth = []
    for number, strength in enumerate(STRENGTHS, start=1):
        img = bleed_through(real, ghost_source, strength)
        buf = io.BytesIO()
        img.convert("L").save(buf, format="PNG")
        page = doc.new_page(width=PAGE_W_PT, height=PAGE_H_PT)
        page.insert_image(pymupdf.Rect(0, 0, PAGE_W_PT, PAGE_H_PT), stream=buf.getvalue())
        truth.append(
            {
                "page": number,
                "ghost_strength": strength,
                "text": PASSAGES[REAL_KEY].strip(),
            }
        )

    doc.save(PDF, deflate=True)
    doc.close()
    TRUTH.write_text(json.dumps({"strengths": STRENGTHS, "pages": truth}, indent=2), "utf-8")
    print(f"wrote {PDF} ({len(STRENGTHS)} pages, strengths {STRENGTHS})")


if __name__ == "__main__":
    build()
