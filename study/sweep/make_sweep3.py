"""Ghost-contrast sweep corpus, third seed.

Same construction as make_sweep.py/make_sweep2.py (six pages, one ghost
strength per page, identical ground truth per page) but a third passage
pair, chosen to swap roles relative to both prior sweeps rather than
introduce brand-new text: "survey" (ghost in sweep 1) is real text here,
"tides" (real in sweep 2) is the ghost. Every passage that has appeared in
either prior sweep now appears at least once in the opposite role, so no
single passage's content can explain an onset that shows up in all three
runs.

This run also fixes the mode confound the first two sweeps left open: run
explicitly with `marker_single --mode fast` (matching sweep 2 exactly;
sweep 1's mode was never recorded, and `--mode balanced` is confirmed
broken in this venv as of 2026-08-18 — "Failed to initialize samplers:
failed to parse grammar" on every page, reproduced directly before writing
this file).

Run: uv run python study/sweep/make_sweep3.py
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
PDF = ROOT / "sweep3.pdf"
TRUTH = ROOT / "ground_truth3.json"

STRENGTHS = [0.0, 0.10, 0.20, 0.30, 0.40, 0.55]
REAL_KEY = "survey"
GHOST_KEY = "tides"


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
