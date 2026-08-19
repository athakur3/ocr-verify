"""Bisect the third-seed sweep's coarse 0.10-0.20 gap (survey/tides pair).

`summarize_onsets.py` (block 22) computed what the three seeds can and cannot
support, and named this run as the gap. MinerU's onset bracket on seed 3 is the
wide `(0.10, 0.20]` only because this seed's existing bisect
(`make_sweep3_bisect.py`) was placed at 0.225/0.25/0.275 to chase *Marker's*
crossing. So MinerU's three per-seed brackets currently overlap, and the study
can only say no seed refutes a single common MinerU onset — which is not the
same as demonstrating one.

Seeds 1 and 2 both bracket MinerU at `(0.10, 0.125]`. This corpus samples the
same 0.125/0.15/0.175 strengths on the survey/tides pair, so seed 3's bracket
is measured at the resolution the other two already have. A fabrication at
0.125 tightens seed 3 to the same bracket and makes the common-onset reading a
positive result rather than an unrefuted one; a clean 0.125 splits it and
refutes the common onset outright. Either answer is worth more than the gap.

Marker is scored on the same pages as a by-product: its seed-3 onset is already
bracketed at `(0.275, 0.30]` by the other bisect, so these three strengths are
expected clean, and a fabrication here would contradict that bracket.

Run: uv run python study/sweep/make_sweep3_lowbisect.py
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
PDF = ROOT / "sweep3_lowbisect.pdf"
TRUTH = ROOT / "sweep3_lowbisect_ground_truth.json"

STRENGTHS = [0.125, 0.15, 0.175]
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
