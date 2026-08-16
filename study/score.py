"""Score the adversarial study.

Two independent measurements, in this order:

  1. **What did the engine actually do?**  Its output is compared against the
     corpus ground truth (which we wrote, so it is exact). This step does not
     involve ocr-verify at all — it establishes the real fabrication/omission
     behaviour that any verification tool would need to catch.

  2. **What did ocr-verify say?**  The tool is run normally (PDF + engine
     output, witness has no access to ground truth), and its verdicts are
     scored against step 1's facts.

The separation is what makes the numbers defensible: the tool is never graded
against its own opinion of what happened.

Run: uv run python study/score.py study/marker_out/corpus/corpus.md
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ocr_verify.align import Settings, compare_page
from ocr_verify.ingest import load_vlm_output
from ocr_verify.model import (
    ACCUSATORY_KINDS,
    DROPPED_TEXT,
    UNVERIFIABLE_PAGE,
    WHOLESALE_DISAGREEMENT,
)
from ocr_verify.normalize import near_miss, tokenize
from ocr_verify.render import render_pdf
from ocr_verify.witness import run_witness

ROOT = Path(__file__).parent
CORPUS = ROOT / "corpus" / "corpus.pdf"
TRUTH = ROOT / "corpus" / "ground_truth.json"
RESULTS = None  # derived per engine in main()

# A page number or stray mark is not "fabrication" worth the name; running text is.
MIN_FABRICATED_TOKENS = 5


def bag_delta(emitted: list[str], truth: list[str]) -> tuple[int, int]:
    """(fabricated, omitted) token counts, order-independent, near-miss tolerant.

    Near-misses count as matches here for the same reason they do in the tool:
    a glyph-level misread is an error, but it is not an invented word, and the
    study is about invention.
    """
    remaining = Counter(truth)
    fabricated = 0
    for tok in emitted:
        if remaining.get(tok, 0) > 0:
            remaining[tok] -= 1
            continue
        hit = next(
            (c for c in remaining if remaining[c] > 0 and len(c) >= 4 and near_miss(tok, c)),
            None,
        )
        if hit is not None:
            remaining[hit] -= 1
        else:
            fabricated += 1
    omitted = sum(remaining.values())
    return fabricated, omitted


def main(engine_output: Path) -> None:
    truth = json.loads(TRUTH.read_text())
    pages_truth = truth["pages"]
    n_pages = len(pages_truth)

    vlm_pages = {p.index: p for p in load_vlm_output(engine_output, n_pages)}

    # ---- Step 1: engine vs ground truth (no ocr-verify involved) ----
    engine_rows = []
    for rec in pages_truth:
        idx = rec["page"] - 1
        truth_toks = [n for _, n in tokenize(rec["text"])]
        emitted_toks = [n for _, n in tokenize(vlm_pages[idx].text, markup=True)]
        fabricated, omitted = bag_delta(emitted_toks, truth_toks)
        engine_rows.append(
            {
                "page": rec["page"],
                "kind": rec["kind"],
                "truth_words": len(truth_toks),
                "emitted_words": len(emitted_toks),
                "fabricated_words": fabricated,
                "omitted_words": omitted,
                "engine_fabricated": fabricated >= MIN_FABRICATED_TOKENS,
                "engine_omitted_heavily": len(truth_toks) > 0
                and omitted / len(truth_toks) > 0.25,
            }
        )

    # ---- Step 2: ocr-verify, run blind, scored against step 1 ----
    work = ROOT / "corpus" / "_render"
    images = render_pdf(CORPUS, work, dpi=200)
    cfg = Settings()
    tool_rows = []
    for rec, image in zip(pages_truth, images):
        idx = rec["page"] - 1
        witness = run_witness(image, idx)
        result = compare_page(witness, vlm_pages[idx], cfg)
        kinds = {f.kind for f in result.findings}
        tool_rows.append(
            {
                "page": rec["page"],
                "divergence": round(result.divergence, 4),
                "witness_quality": result.witness_quality,
                "verified": result.verified,
                "flagged_fabrication": bool(kinds & ACCUSATORY_KINDS),
                "flagged_dropped": DROPPED_TEXT in kinds,
                # Hedged = the tool declined to rule and asked for a human look.
                "hedged": bool(kinds & {WHOLESALE_DISAGREEMENT, UNVERIFIABLE_PAGE}),
                "finding_kinds": sorted(kinds),
            }
        )

    # ---- Confusion matrix for the headline claim (fabrication) ----
    tp = fp = fn = tn = 0
    rows = []
    for e, t in zip(engine_rows, tool_rows):
        truth_flag, tool_flag = e["engine_fabricated"], t["flagged_fabrication"]
        if truth_flag and tool_flag:
            tp += 1
        elif not truth_flag and tool_flag:
            fp += 1
        elif truth_flag and not tool_flag:
            fn += 1
        else:
            tn += 1
        rows.append({**e, **{k: v for k, v in t.items() if k != "page"}})

    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None

    summary = {
        "corpus_pages": n_pages,
        "engine_pages_with_fabrication": sum(r["engine_fabricated"] for r in engine_rows),
        "engine_fabricated_words_total": sum(r["fabricated_words"] for r in engine_rows),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "precision": precision,
        "recall": recall,
        "min_fabricated_tokens": MIN_FABRICATED_TOKENS,
    }
    results_path = ROOT / f"results-{engine_output.parent.name if engine_output.is_file() else engine_output.name}.json"
    results_path.write_text(json.dumps({"summary": summary, "pages": rows}, indent=2), "utf-8")

    print(f"\n{'page':>4}  {'kind':<22} {'truth':>5} {'emit':>5} {'fab':>4} {'omit':>4}  "
          f"{'engine?':<8} {'tool?':<6} verdict")
    for e, t in zip(engine_rows, tool_rows):
        verdict = (
            "TP" if e["engine_fabricated"] and t["flagged_fabrication"]
            else "FP" if t["flagged_fabrication"]
            else "FN" if e["engine_fabricated"]
            else "tn"
        )
        tool_col = "flag" if t["flagged_fabrication"] else ("hedge" if t["hedged"] else "-")
        print(f"{e['page']:>4}  {e['kind']:<22} {e['truth_words']:>5} {e['emitted_words']:>5} "
              f"{e['fabricated_words']:>4} {e['omitted_words']:>4}  "
              f"{'FABRICATED' if e['engine_fabricated'] else '-':<8} "
              f"{tool_col:<6} {verdict}"
              + (f"  [witness {t['witness_quality']}]" if t["witness_quality"] != "ok" else ""))

    print(f"\nengine fabricated on {summary['engine_pages_with_fabrication']}/{n_pages} pages "
          f"({summary['engine_fabricated_words_total']} invented words)")
    print(f"ocr-verify: precision={precision if precision is None else f'{precision:.2f}'} "
          f"recall={recall if recall is None else f'{recall:.2f}'} "
          f"(tp={tp} fp={fp} fn={fn} tn={tn})")
    print(f"\nwrote {results_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: score.py <engine output file/dir>")
    main(Path(sys.argv[1]))
