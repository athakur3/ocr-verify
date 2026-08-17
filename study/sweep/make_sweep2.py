"""Ghost-contrast sweep corpus, second seed.

Same construction as make_sweep.py (six pages, one ghost strength per page,
identical ground truth per page) but a different passage pair — "tides" as
the real text, "instruments" as the mirrored ghost underneath it, instead of
"conclusions"/"survey". The point is to check whether the two fabrication
onsets found in the first pass (study/README.md) are a property of the
ghost-contrast mechanism or an artifact of that specific pair of passages.

Run: uv run python study/sweep/make_sweep2.py
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
PDF = ROOT / "sweep2.pdf"
TRUTH = ROOT / "ground_truth2.json"

STRENGTHS = [0.0, 0.10, 0.20, 0.30, 0.40, 0.55]
REAL_KEY = "tides"
GHOST_KEY = "instruments"


def build() -> None:
    real = render(PASSAGES[REAL_KEY])
    ghost_source = render(PASSAGES[GHOST_KEY])

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
                "text": PASSAGES[REAL_KEY].strip(),
            }
        )

    doc.save(PDF, deflate=True)
    doc.close()
    TRUTH.write_text(json.dumps({"strengths": STRENGTHS, "pages": truth}, indent=2), "utf-8")
    print(f"wrote {PDF} ({len(STRENGTHS)} pages, strengths {STRENGTHS})")


if __name__ == "__main__":
    build()
