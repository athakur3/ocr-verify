"""Score the third-seed sweep's 0.20-0.30 bisect (survey/tides pair).

Same bag-delta measurement as score_sweep3.py, pointed at the finer
0.225/0.25/0.275 corpus built by make_sweep3_bisect.py.

Run: uv run python study/sweep/score_sweep3_bisect.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent.parent / "src"))
sys.path.insert(0, str(ROOT.parent))

from score import bag_delta  # noqa: E402
from ocr_verify.normalize import tokenize  # noqa: E402


def toks(text: str, markup: bool = False) -> list[str]:
    return [n for _, n in tokenize(text, markup=markup)]


def marker_pages(md_path: Path) -> dict[int, str]:
    parts = re.split(r"^\{(\d+)\}-+$", md_path.read_text("utf-8"), flags=re.M)
    return {int(parts[i]): parts[i + 1] for i in range(1, len(parts), 2)}


def mineru_pages(content_list: Path) -> dict[int, str]:
    items = json.loads(content_list.read_text("utf-8"))
    pages: dict[int, list[str]] = {}
    for it in items:
        t = (it.get("text") or "").strip()
        if t:
            pages.setdefault(it["page_idx"], []).append(t)
    return {idx: "\n\n".join(chunks) for idx, chunks in pages.items()}


def main() -> None:
    truth = json.loads((ROOT / "sweep3_bisect_ground_truth.json").read_text())
    truth_toks = {p["page"] - 1: toks(p["text"]) for p in truth["pages"]}
    strengths = {p["page"] - 1: p["ghost_strength"] for p in truth["pages"]}

    engines = {
        "marker": marker_pages(ROOT / "marker_out3_bisect" / "sweep3_bisect" / "sweep3_bisect.md"),
        "mineru": mineru_pages(
            ROOT / "mineru_out3_bisect" / "sweep3_bisect" / "hybrid_auto" / "sweep3_bisect_content_list.json"
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

    out = ROOT / "sweep3_bisect_results.json"
    out.write_text(json.dumps({"truth_words_per_page": len(truth_toks[0]), "rows": rows}, indent=2), "utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
