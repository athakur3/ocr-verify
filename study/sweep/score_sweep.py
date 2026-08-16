"""Score the ghost-contrast sweep: fabricated words per engine per ghost strength.

Same bag-delta measurement as the main study (order-independent, near-miss
tolerant, engine vs exact ground truth — ocr-verify plays no part), applied
across the strength ladder. The output is each engine's fabrication-onset curve.

Run: uv run python study/sweep/score_sweep.py
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
    truth = json.loads((ROOT / "ground_truth.json").read_text())
    truth_toks = {p["page"] - 1: toks(p["text"]) for p in truth["pages"]}
    strengths = {p["page"] - 1: p["ghost_strength"] for p in truth["pages"]}

    engines = {
        "marker": marker_pages(ROOT / "marker_out" / "sweep" / "sweep.md"),
        "mineru": mineru_pages(
            ROOT / "mineru_out" / "sweep" / "hybrid_auto" / "sweep_content_list.json"
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

    out = ROOT / "sweep_results.json"
    out.write_text(json.dumps({"truth_words_per_page": len(truth_toks[0]), "rows": rows}, indent=2), "utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
