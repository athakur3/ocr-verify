"""Score the third-seed ghost-contrast sweep (survey/tides pair).

Same bag-delta measurement as score_sweep.py/score_sweep2.py, pointed at the
sweep3 corpus and sweep3 engine outputs.

Run: uv run python study/sweep/score_sweep3.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent.parent / "src"))
sys.path.insert(0, str(ROOT.parent))

from pagesplit import marker_pages, mineru_pages  # noqa: E402
from score import bag_delta  # noqa: E402
from ocr_verify.normalize import tokenize  # noqa: E402


def toks(text: str, markup: bool = False) -> list[str]:
    return [n for _, n in tokenize(text, markup=markup)]


def main() -> None:
    truth = json.loads((ROOT / "ground_truth3.json").read_text())
    truth_toks = {p["page"] - 1: toks(p["text"]) for p in truth["pages"]}
    strengths = {p["page"] - 1: p["ghost_strength"] for p in truth["pages"]}

    engines = {
        "marker": marker_pages(
            ROOT / "marker_out3" / "sweep3" / "sweep3.md", len(truth_toks)
        ),
        "mineru": mineru_pages(
            ROOT / "mineru_out3" / "sweep3" / "hybrid_auto" / "sweep3_content_list.json",
            len(truth_toks),
        ),
    }

    rows = []
    print(f"{'ghost':>6}  {'marker fab':>10} {'marker omit':>11}  {'mineru fab':>10} {'mineru omit':>11}")
    for idx in sorted(truth_toks):
        row = {"ghost_strength": strengths[idx]}
        for name, pages in engines.items():
            fab, omit = bag_delta(toks(pages.get(idx, ""), markup=True), truth_toks[idx])
            row[f"{name}_fabricated"] = fab
            row[f"{name}_omitted"] = omit
        rows.append(row)
        print(f"{row['ghost_strength']:>6}  {row['marker_fabricated']:>10} {row['marker_omitted']:>11}  "
              f"{row['mineru_fabricated']:>10} {row['mineru_omitted']:>11}")

    out = ROOT / "sweep3_results.json"
    out.write_text(json.dumps({"truth_words_per_page": len(truth_toks[0]), "rows": rows}, indent=2), "utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
