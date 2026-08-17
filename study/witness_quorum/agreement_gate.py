"""Agreement-gated trust rule experiment (branch `witness-quorum`, not merged).

The spike (spike.py) found PaddleOCR is a clean win on the blind page (15) but
fabricates 13 words on the corpus's hardest page (23) — disqualifying a naive
OR-fallback quorum. The spike's README sketched a fix: trust PaddleOCR only
where its reading agrees with fragments Tesseract also read, never on a page
Tesseract read nothing on. This script tests whether that signal actually
exists and actually separates the good case from the bad one, using only
information a production run would have (Tesseract's own output, PaddleOCR's
own output) — never ground truth, which is used here only to grade the
resulting decision after the fact.

Run: study/witness_quorum/.venv/bin/python study/witness_quorum/agreement_gate.py
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

from ocr_verify.align import Settings  # noqa: E402
from ocr_verify.normalize import near_miss, tokenize  # noqa: E402
from ocr_verify.witness import run_witness  # noqa: E402

TARGET_PAGES = [1, 5, 15, 19, 23]


def bag_delta(emitted: list[str], truth: list[str]) -> tuple[int, int]:
    remaining: dict[str, int] = {}
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


def bag_overlap_fraction(a: list[str], b: list[str]) -> float:
    """Share of `a`'s tokens that also appear (exact or near-miss) in `b`. 0.0 if `a` empty."""
    if not a:
        return 0.0
    remaining: dict[str, int] = {}
    for t in b:
        remaining[t] = remaining.get(t, 0) + 1
    hits = 0
    for tok in a:
        if remaining.get(tok, 0) > 0:
            remaining[tok] -= 1
            hits += 1
            continue
        cand = next(
            (c for c, n in remaining.items() if n > 0 and len(c) >= 4 and near_miss(tok, c)),
            None,
        )
        if cand is not None:
            remaining[cand] -= 1
            hits += 1
    return hits / len(a)


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
    cfg = Settings()

    rows = []
    for page in TARGET_PAGES:
        rec = pages_truth[page]
        truth_toks = [n for _, n in tokenize(rec["text"])]

        image = RENDER_DIR / f"page-{page:04d}.png"
        wp = run_witness(image, page)
        usable = wp.confident_words(cfg.min_conf)
        w_norms = [w.norm for w in usable]
        w_mean_conf = sum(w.conf for w in usable) / len(usable) if usable else 0.0

        words, confs = run_paddle(image)
        p_norms = [n for _, n in tokenize(" ".join(words))]
        p_mean_conf = sum(confs) / len(confs) if confs else 0.0

        # The candidate signal: of what Tesseract itself managed to read, how
        # much does PaddleOCR's reading corroborate? This is available with no
        # ground truth — it only compares the two witnesses to each other.
        agreement = bag_overlap_fraction(w_norms, p_norms)

        # Graded after the fact, ground truth only used here to check the rule:
        fabricated, omitted = bag_delta(p_norms, truth_toks)

        rows.append(
            {
                "page": page,
                "kind": rec["kind"],
                "tesseract_usable": len(w_norms),
                "tesseract_mean_conf": round(w_mean_conf, 1),
                "paddle_words": len(p_norms),
                "paddle_mean_conf": round(p_mean_conf, 3),
                "agreement_tesseract_in_paddle": round(agreement, 3),
                "paddle_fabricated_vs_truth": fabricated,
                "paddle_omitted_vs_truth": omitted,
            }
        )
        print(
            f"page {page:>3} {rec['kind']:<18} tess_usable={len(w_norms):>3} "
            f"tess_conf={w_mean_conf:>5.1f} agreement={agreement:.3f} "
            f"paddle_fab={fabricated} paddle_omit={omitted}"
        )

    out = ROOT / "witness_quorum" / "agreement_gate_results.json"
    out.write_text(json.dumps({"pages": rows}, indent=2), "utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
