"""Test whether a tighter local-confidence window (backlog item 1, fix (a)) would
have caught the "FAR EAST SPOTLIGHT" false positive (study/wild/README.md).

Read-only measurement: reproduces compare_page's finding construction for page 0
of the Tibet pamphlet and reports, for several candidate window sizes, the mean
witness confidence around each finding's witness span. Does not modify align.py.

Run: uv run python3 study/wild/local_window_probe.py
"""

from __future__ import annotations

import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from ocr_verify.align import Settings, _classify, _runs, _witness_span, _UNSUPPORTED
from ocr_verify.ingest import load_vlm_output
from ocr_verify.normalize import tokenize
from ocr_verify.render import render_pdf
from ocr_verify.witness import run_witness

HERE = Path(__file__).parent
PDF = HERE / "downloads" / "what-about-tibet.pdf"
MARKER_MD = HERE / "marker_out" / "what-about-tibet" / "what-about-tibet.md"


def main() -> None:
    cfg = Settings()
    vlm_pages = load_vlm_output(MARKER_MD, 4)

    # DPI 200 matches the CLI default used to generate the committed report
    # (what-about-tibet-findings.json) -- the downloads/preview/ PNGs are a
    # separate, lower-resolution render made only for visual inspection, and
    # give a different (and misleading) Tesseract read.
    with tempfile.TemporaryDirectory(dir=HERE) as tmp:
        images = render_pdf(PDF, Path(tmp), dpi=200, pages=[0])
        wp = run_witness(images[0], 0)
    usable = wp.confident_words(cfg.min_conf)
    w_norms = [w.norm for w in usable]
    v_pairs = tokenize(vlm_pages[0].text, markup=True)
    v_norms = [n for _, n in v_pairs]
    v_raw = [r for r, _ in v_pairs]

    matcher = SequenceMatcher(None, w_norms, v_norms, autojunk=False)
    opcodes = matcher.get_opcodes()
    w_class, v_class, pairs = _classify(w_norms, v_norms, opcodes, usable, cfg)

    for start, end, count in _runs(v_class, _UNSUPPORTED, cfg.min_run, cfg.gap):
        lo, hi = _witness_span(start, end, pairs)
        print(f"finding: vlm_text={' '.join(v_raw[start:end])!r}")
        if lo is None or hi is None:
            print("  no witness span")
            continue
        print(f"  witness span [{lo}:{hi}] = {[w.text for w in usable[lo:hi]]!r}")
        for context in (0, 1, 2, 3, 4, 8):
            window = usable[max(0, lo - context) : hi + context]
            if not window:
                continue
            mean_conf = sum(w.conf for w in window) / len(window)
            trips = mean_conf < cfg.misread_conf_ceiling
            print(
                f"  context={context:>2}  n={len(window):>2}  mean_conf={mean_conf:6.1f}  "
                f"hedge={'YES' if trips else 'no '}  words={[w.text for w in window]!r}"
            )
        print()


if __name__ == "__main__":
    main()
