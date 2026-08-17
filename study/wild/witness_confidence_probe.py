"""Reproduce the witness-quality diagnosis on the Tibet pamphlet (study/wild/README.md).

Read-only measurement script: runs the real Tesseract witness and the real
`compare_page`/`_classify` code paths against data already committed in this
directory, and prints the numbers behind "why did witness-quality say ok here".
Does not modify align.py or witness.py.

Run: uv run python3 study/wild/witness_confidence_probe.py
"""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

from ocr_verify.align import Settings, _classify, _NOISE
from ocr_verify.ingest import load_vlm_output
from ocr_verify.normalize import tokenize
from ocr_verify.witness import run_witness

HERE = Path(__file__).parent
PREVIEW_DIR = HERE / "downloads" / "preview"
MARKER_MD = HERE / "marker_out" / "what-about-tibet" / "what-about-tibet.md"


def main() -> None:
    cfg = Settings()
    vlm_pages = load_vlm_output(MARKER_MD, 4)

    print(
        f"{'page':>4}  {'mean_conf':>9}  {'usable/total':>12}  {'noise_rate':>10}  "
        f"{'quality':>7}  low_conf<{cfg.low_conf_mean:.0f}?  "
        f"misread-fold(rate>={cfg.misread_rate_low:.2f} & conf<{cfg.misread_conf_ceiling:.0f})?"
    )
    for i in range(4):
        image = PREVIEW_DIR / f"page_0{i}.png"
        wp = run_witness(image, i)
        usable = wp.confident_words(cfg.min_conf)
        w_norms = [w.norm for w in usable]
        v_pairs = tokenize(vlm_pages[i].text, markup=True)
        v_norms = [n for _, n in v_pairs]

        matcher = SequenceMatcher(None, w_norms, v_norms, autojunk=False)
        w_class, _v_class, _pairs = _classify(w_norms, v_norms, matcher.get_opcodes(), usable, cfg)
        noise = sum(1 for c in w_class if c == _NOISE)

        mean_conf = sum(w.conf for w in usable) / len(usable) if usable else 0.0
        noise_rate = noise / len(usable) if usable else 0.0
        usable_ratio = len(usable) / len(wp.words) if wp.words else 0.0
        low_conf_trip = mean_conf < cfg.low_conf_mean or usable_ratio < 0.5
        misread_fold_trip = noise_rate >= cfg.misread_rate_low and mean_conf < cfg.misread_conf_ceiling

        print(
            f"{i:>4}  {mean_conf:>9.1f}  {usable_ratio:>12.3f}  {noise_rate:>10.3f}  "
            f"{'low' if low_conf_trip else 'ok':>7}  {low_conf_trip!s:>10}  {misread_fold_trip!s:>10}"
        )

    print()
    print("Concrete high-confidence misread: witness read 'as' as 'ae' on page 1")
    print("twice, at 95.6% and 86.2% Tesseract confidence -- both well above every")
    print("threshold in Settings. Aggregate/mean-confidence gates cannot see this:")
    print("a handful of glyph-plausible wrong words are diluted by hundreds of")
    print("correctly-read ones, so the page-level mean stays high regardless.")


if __name__ == "__main__":
    main()
