"""Bisect the third-seed sweep's coarse 0.20-0.30 gap (survey/tides pair).

Sweep 3 (make_sweep3.py) closed the mode confound between sweep 2 and sweep 3
(both ran `marker_single --mode fast` explicitly) but still left the
per-engine onset *ordering* unsettled: Marker was clean at 0.20 and spiked to
14 fabricated words at 0.30, so the crossing point is hiding somewhere inside
that gap at this strength ladder's resolution. This mirrors the original
sweep's bisect (make_sweep.py's ad-hoc 0.125/0.15/0.175 pages, never
committed as its own generator script) but targets the 0.20-0.30 gap instead,
on the survey/tides pair, with the mode confound already closed.

Run: uv run python study/sweep/make_sweep3_bisect.py
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
PDF = ROOT / "sweep3_bisect.pdf"
TRUTH = ROOT / "sweep3_bisect_ground_truth.json"

STRENGTHS = [0.225, 0.25, 0.275]
REAL_KEY = "survey"
GHOST_KEY = "tides"


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
