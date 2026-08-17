"""Witness-quorum spike (branch `witness-quorum`, not merged to main).

Question: on the pages where Tesseract hedges (blind / wholesale-disagreement),
would a second witness engine (PaddleOCR) actually read the page well enough to
shrink the unverifiable set? This script does not touch align.py or the CI gate
at all — it is a standalone read-only measurement against the existing study
corpus, run with a separate venv (study/witness_quorum/.venv) so PaddleOCR is
never a dependency of the shipped package.

Run: study/witness_quorum/.venv/bin/python study/witness_quorum/spike.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent  # study/
CORPUS_DIR = ROOT / "corpus"
RENDER_DIR = CORPUS_DIR / "_render"
TRUTH = CORPUS_DIR / "ground_truth.json"

sys.path.insert(0, str(ROOT.parent / "src"))

from ocr_verify.normalize import near_miss, tokenize  # noqa: E402

# The three pages both engines' study runs hedged on (see study/results-*.json):
# 15 noise_heavy (blind), 19 skew_6deg (wholesale), 23 combo_severe (marker only).
# Plus two clean pages as a sanity check that PaddleOCR is actually working.
TARGET_PAGES = [1, 5, 15, 19, 23]


def bag_delta(emitted: list[str], truth: list[str]) -> tuple[int, int]:
    remaining = {}
    for t in truth:
        remaining[t] = remaining.get(t, 0) + 1
    fabricated = 0
    for tok in emitted:
        if remaining.get(tok, 0) > 0:
            remaining[tok] -= 1
            continue
        hit = next(
            (c for c, n in remaining.items() if n > 0 and len(c) >= 4 and near_miss(tok, c)),
            None,
        )
        if hit is not None:
            remaining[hit] -= 1
        else:
            fabricated += 1
    omitted = sum(v for v in remaining.values() if v > 0)
    return fabricated, omitted


_OCR = None


def run_paddle(image_path: Path):
    global _OCR
    from paddleocr import PaddleOCR

    if _OCR is None:
        _OCR = PaddleOCR(lang="en")
    result = _OCR.predict(str(image_path))
    words = []
    confs = []
    for page in result:
        texts = page.get("rec_texts", []) or []
        scores = page.get("rec_scores", []) or []
        for text, score in zip(texts, scores):
            for w in text.split():
                words.append(w)
                confs.append(score)
    return words, confs


def main() -> None:
    truth = json.loads(TRUTH.read_text())
    pages_truth = {rec["page"]: rec for rec in truth["pages"]}

    rows = []
    for page in TARGET_PAGES:
        rec = pages_truth[page]
        truth_toks = [n for _, n in tokenize(rec["text"])]
        image = RENDER_DIR / f"page-{page:04d}.png"
        words, confs = run_paddle(image)
        norm_words = [n for _, n in tokenize(" ".join(words))]
        fabricated, omitted = bag_delta(norm_words, truth_toks)
        mean_conf = sum(confs) / len(confs) if confs else 0.0
        rows.append(
            {
                "page": page,
                "kind": rec["kind"],
                "truth_words": len(truth_toks),
                "paddle_words": len(norm_words),
                "paddle_mean_conf": round(mean_conf, 3),
                "paddle_fabricated": fabricated,
                "paddle_omitted": omitted,
            }
        )
        print(
            f"page {page:>3} {rec['kind']:<18} truth={len(truth_toks):>4} "
            f"paddle_words={len(norm_words):>4} mean_conf={mean_conf:.3f} "
            f"fab={fabricated} omit={omitted}"
        )

    out = ROOT / "witness_quorum" / "spike_results.json"
    out.write_text(json.dumps({"pages": rows}, indent=2), "utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
