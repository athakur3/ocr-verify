"""What *kind* of word does each engine fabricate — invented, or ink from the wrong layer?

Every sweep result so far is a count. `sweep_results.json` says Marker fabricated 75 words
at ghost strength 0.30 and MinerU 13, and read as counts that says Marker is roughly six
times worse. The counts cannot say what those words *were*, and the two engines turn out
not to be doing the same thing at all.

The bleed-through corpus makes the question answerable without a dictionary or a judgement
call, because we wrote both layers. Every page is a known real passage with a known ghost
passage bled through it, so for any fabricated token there is an exact, checkable question:
does this word appear on the page — in either layer — at all? A word from the ghost passage
is a transcription error (real ink, wrong layer). A word in neither passage was invented:
nothing on that page could have produced it.

This script recomputes the fabricated tokens themselves from the seven committed capture
sets and classifies each one that way. Deliberate choices, each refusing a more flattering
or more arbitrary shape:

* **The token lists must explain the committed counts.** Every page's extracted list is
  checked against the `*_fabricated` number in the results JSON already committed beside
  it, and a mismatch raises rather than being written out. The extraction mirrors
  `study/score.py`'s `bag_delta` exactly — same near-miss tolerance, same order — so this
  is a decomposition of the published numbers, not a second opinion about them.
* **The ghost key is verified, not trusted.** Each ground-truth page's text is compared
  against `PASSAGES[real]` before the run's ghost vocabulary is used, because the ghost
  passage exists only in the generator, not in the ground truth JSON. A registry that had
  drifted would silently classify against the wrong ghost.
* **A word in both passages is attributed to neither.** Function words (`the`, `of`, `in`)
  are in every passage here, so crediting them to the ghost would inflate the benign
  bucket and crediting them to invention would inflate the damning one. They get their own
  bucket and are counted out of both claims.
* **No lexicality classifier.** An earlier version of this script tried to separate
  glyph-level noise (`zanmislaj`, `2115m12n1`) from fluent invention (`operations`,
  `programming`) with an orthographic proxy built from the corpus's own character bigrams.
  It misread about a quarter of the tokens in each direction — `topic` and `know` came out
  anomalous, `summity` and `anotherreado` came out clean — so it is not in here. That axis
  stays a reading of the published token lists rather than a computed verdict; see
  `study/README.md`.

Run: uv run python study/sweep/fabricated_words.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent.parent / "src"))
sys.path.insert(0, str(ROOT.parent))

from make_corpus import PASSAGES  # noqa: E402

from ocr_verify.normalize import near_miss, tokenize  # noqa: E402

from pagesplit import marker_pages, mineru_pages  # noqa: E402

ENGINES = ("marker", "mineru")

# The near-miss floor `bag_delta` uses: a candidate shorter than this is not allowed to
# absorb a token, because short words collide too easily to call it a misread.
NEAR_MISS_MIN_LEN = 4

# Buckets, from most attributable to least. `unattributable` is the one the claims rest on.
BUCKETS = ("ghost_only", "page_only", "both", "near_miss", "unattributable")

# One entry per capture set. `results` is the committed JSON whose counts this run must
# reproduce; `real`/`ghost` are `make_corpus.PASSAGES` keys, matching the generator that
# built the corpus (`make_sweep*.py`). Seed ids and passage keys are asserted against
# `summarize_onsets.SEEDS` by tests/test_fabricated_words.py so the two registries cannot
# drift apart.
RUNS = [
    {
        "seed": "seed1", "kind": "coarse", "real": "conclusions", "ghost": "survey",
        "truth": "ground_truth.json", "results": "sweep_results.json",
        "marker": "marker_out/sweep/sweep.md",
        "mineru": "mineru_out/sweep/hybrid_auto/sweep_content_list.json",
    },
    {
        "seed": "seed1", "kind": "bisect", "real": "conclusions", "ghost": "survey",
        "truth": "bisect_ground_truth.json", "results": "bisect_results.json",
        "marker": "marker_bisect/bisect/bisect.md",
        "mineru": "mineru_bisect/bisect/hybrid_auto/bisect_content_list.json",
    },
    {
        "seed": "seed2", "kind": "coarse", "real": "tides", "ghost": "instruments",
        "truth": "ground_truth2.json", "results": "sweep2_results.json",
        "marker": "marker_out2/sweep2/sweep2.md",
        "mineru": "mineru_out2/sweep2/hybrid_auto/sweep2_content_list.json",
    },
    {
        "seed": "seed2", "kind": "bisect", "real": "tides", "ghost": "instruments",
        "truth": "sweep2_bisect_ground_truth.json", "results": "sweep2_bisect_results.json",
        "marker": "marker_out2_bisect/sweep2_bisect/sweep2_bisect.md",
        "mineru": "mineru_out2_bisect/sweep2_bisect/hybrid_auto/sweep2_bisect_content_list.json",
    },
    {
        "seed": "seed3", "kind": "coarse", "real": "survey", "ghost": "tides",
        "truth": "ground_truth3.json", "results": "sweep3_results.json",
        "marker": "marker_out3/sweep3/sweep3.md",
        "mineru": "mineru_out3/sweep3/hybrid_auto/sweep3_content_list.json",
    },
    {
        "seed": "seed3", "kind": "bisect", "real": "survey", "ghost": "tides",
        "truth": "sweep3_bisect_ground_truth.json", "results": "sweep3_bisect_results.json",
        "marker": "marker_out3_bisect/sweep3_bisect/sweep3_bisect.md",
        "mineru": "mineru_out3_bisect/sweep3_bisect/hybrid_auto/sweep3_bisect_content_list.json",
    },
    {
        "seed": "seed3", "kind": "lowbisect", "real": "survey", "ghost": "tides",
        "truth": "sweep3_lowbisect_ground_truth.json", "results": "sweep3_lowbisect_results.json",
        "marker": "marker_out3_lowbisect/sweep3_lowbisect/sweep3_lowbisect.md",
        "mineru": "mineru_out3_lowbisect/sweep3_lowbisect/hybrid_auto/sweep3_lowbisect_content_list.json",
    },
]


class FabricationKindError(RuntimeError):
    """Raised when the extracted tokens cannot be reconciled with the committed captures."""


def toks(text: str, markup: bool = False) -> list[str]:
    return [n for _, n in tokenize(text, markup=markup)]


def fabricated_tokens(emitted: list[str], truth: list[str]) -> list[str]:
    """The tokens `study/score.py`'s `bag_delta` counts as fabricated, in emission order.

    Identical algorithm to `bag_delta`, returning the tokens instead of their number, so
    the list is a decomposition of the published count rather than a re-measurement of it.
    `reconcile()` asserts that equivalence against every committed results JSON.
    """
    remaining = Counter(truth)
    out = []
    for tok in emitted:
        if remaining.get(tok, 0) > 0:
            remaining[tok] -= 1
            continue
        hit = next(
            (
                c
                for c in remaining
                if remaining[c] > 0 and len(c) >= NEAR_MISS_MIN_LEN and near_miss(tok, c)
            ),
            None,
        )
        if hit is not None:
            remaining[hit] -= 1
        else:
            out.append(tok)
    return out


def classify(tok: str, page_vocab: set[str], ghost_vocab: set[str]) -> str:
    """Which layer of the page, if any, could have produced this word.

    Exact membership first, because it needs no tolerance to argue with. A token in both
    vocabularies is `both` — genuinely ambiguous, and left out of both claims rather than
    assigned to whichever is convenient. Only tokens matching nothing exactly are given
    the near-miss benefit of the doubt, and only against the same >=4-character floor the
    scorer uses.
    """
    on_page, in_ghost = tok in page_vocab, tok in ghost_vocab
    if on_page and in_ghost:
        return "both"
    if in_ghost:
        return "ghost_only"
    if on_page:
        return "page_only"
    if any(len(w) >= NEAR_MISS_MIN_LEN and near_miss(tok, w) for w in page_vocab | ghost_vocab):
        return "near_miss"
    return "unattributable"


def _committed_counts(path: Path) -> dict[float, dict[str, int]]:
    data = json.loads(path.read_text("utf-8"))
    return {
        round(float(r["ghost_strength"]), 4): {e: int(r[f"{e}_fabricated"]) for e in ENGINES}
        for r in data["rows"]
    }


def measure_run(run: dict) -> list[dict]:
    """One capture set's per-strength, per-engine fabricated tokens, classified."""
    truth = json.loads((ROOT / run["truth"]).read_text("utf-8"))
    passage = PASSAGES[run["real"]].strip()
    for page in truth["pages"]:
        if page["text"].strip() != passage:
            raise FabricationKindError(
                f"{run['truth']} page {page['page']} is not PASSAGES[{run['real']!r}] — the "
                f"registry's real/ghost keys do not describe this corpus, so the ghost "
                f"vocabulary would be the wrong one to classify against"
            )

    page_vocab = set(toks(PASSAGES[run["real"]]))
    ghost_vocab = set(toks(PASSAGES[run["ghost"]]))
    truth_toks = {p["page"] - 1: toks(p["text"]) for p in truth["pages"]}
    strengths = {p["page"] - 1: round(float(p["ghost_strength"]), 4) for p in truth["pages"]}

    pages = {
        "marker": marker_pages(ROOT / run["marker"], len(truth_toks)),
        "mineru": mineru_pages(ROOT / run["mineru"], len(truth_toks)),
    }

    rows = []
    for idx in sorted(truth_toks):
        row = {"seed": run["seed"], "kind": run["kind"], "strength": strengths[idx], "engines": {}}
        for engine in ENGINES:
            tokens = fabricated_tokens(
                toks(pages[engine].get(idx, ""), markup=True), truth_toks[idx]
            )
            kinds = [classify(t, page_vocab, ghost_vocab) for t in tokens]
            counts = Counter(kinds)
            row["engines"][engine] = {
                "fabricated": len(tokens),
                "tokens": tokens,
                "kinds": kinds,
                "buckets": {b: counts.get(b, 0) for b in BUCKETS},
            }
        rows.append(row)
    return rows


def reconcile(run: dict, rows: list[dict]) -> None:
    """Fail unless every extracted list is exactly as long as the committed count beside it."""
    committed = _committed_counts(ROOT / run["results"])
    for row in rows:
        expected = committed.get(row["strength"])
        if expected is None:
            raise FabricationKindError(
                f"{run['results']} has no row at strength {row['strength']} — the corpus and "
                f"its results JSON disagree about which strengths were measured"
            )
        for engine in ENGINES:
            got = row["engines"][engine]["fabricated"]
            if got != expected[engine]:
                raise FabricationKindError(
                    f"{run['seed']}/{run['kind']} {engine} at {row['strength']}: extracted "
                    f"{got} fabricated tokens but {run['results']} says {expected[engine]}. "
                    f"The token list does not explain the published count."
                )


def per_row_spread(rows: list[dict]) -> dict:
    """Per engine, how the invented fraction behaves row by row rather than in aggregate.

    A single pooled percentage can be carried by one huge row, so the floor across every
    fabricating strength is reported too: that is the number that says "this is not a
    high-strength artifact" without appealing to the total.
    """
    out = {}
    for engine in ENGINES:
        fractions = [
            (r["seed"], r["strength"], r["engines"][engine]["buckets"]["unattributable"]
             / r["engines"][engine]["fabricated"])
            for r in rows
            if r["engines"][engine]["fabricated"]
        ]
        if not fractions:
            out[engine] = {"fabricating_rows": 0}
            continue
        values = [f for _, _, f in fractions]
        out[engine] = {
            "fabricating_rows": len(values),
            "min_unattributable_pct": round(100 * min(values), 1),
            "max_unattributable_pct": round(100 * max(values), 1),
            "rows_majority_unattributable": sum(1 for v in values if v > 0.5),
            "rows_with_no_unattributable": sum(1 for v in values if v == 0),
        }
    return out


def totals(rows: list[dict]) -> dict:
    """Per-engine bucket totals over every strength on every seed."""
    out = {}
    for engine in ENGINES:
        counts = Counter()
        fabricated = 0
        for row in rows:
            fabricated += row["engines"][engine]["fabricated"]
            counts.update(row["engines"][engine]["buckets"])
        out[engine] = {
            "fabricated": fabricated,
            "buckets": {b: counts.get(b, 0) for b in BUCKETS},
            "unattributable_pct": (
                None if not fabricated else round(100.0 * counts["unattributable"] / fabricated, 1)
            ),
        }
    return out


def build_summary() -> dict:
    """The committed `fabricated_words.json`, as data — so a test can recompute and compare."""
    rows = []
    for run in RUNS:
        run_rows = measure_run(run)
        reconcile(run, run_rows)
        rows += run_rows
    # Strength order within each seed, not capture order: a seed's bisect runs at lower
    # strengths than its coarse ladder, so "the first row that fabricates" is only the
    # onset once the ladder and its bisects are interleaved.
    rows.sort(key=lambda r: (r["seed"], r["strength"]))
    fabricating = [r for r in rows if any(r["engines"][e]["fabricated"] for e in ENGINES)]
    return {
        "buckets": list(BUCKETS),
        "runs": [{k: run[k] for k in ("seed", "kind", "real", "ghost", "results")} for run in RUNS],
        "rows": rows,
        "totals": totals(rows),
        "per_row_spread": per_row_spread(rows),
        "strengths_with_any_fabrication": sorted({r["strength"] for r in fabricating}),
    }


def main() -> None:
    summary = build_summary()

    print("Fabricated words by attribution — can the page produce this word at all?\n")
    header = (
        f"{'seed':6} {'strength':>8} {'engine':7} {'fab':>4} {'unattr':>7} "
        f"{'ghost':>6} {'page':>5} {'both':>5} {'near':>5}"
    )
    print(header)
    for row in summary["rows"]:
        for engine in ENGINES:
            e = row["engines"][engine]
            if not e["fabricated"]:
                continue
            b = e["buckets"]
            print(
                f"{row['seed']:6} {row['strength']:>8g} {engine:7} {e['fabricated']:>4} "
                f"{b['unattributable']:>7} {b['ghost_only']:>6} {b['page_only']:>5} "
                f"{b['both']:>5} {b['near_miss']:>5}"
            )

    print("\nTotals over every strength on all three seeds\n")
    for engine, t in summary["totals"].items():
        b = t["buckets"]
        print(
            f"    {engine:7} {t['fabricated']:>4} fabricated   "
            f"{b['unattributable']:>3} invented ({t['unattributable_pct']}%)   "
            f"{b['ghost_only']:>3} ghost-only   {b['both']:>3} in both   "
            f"{b['page_only']:>2} page-only   {b['near_miss']:>2} near-miss"
        )

    print("\nInvented fraction row by row, not pooled\n")
    for engine, s in summary["per_row_spread"].items():
        print(
            f"    {engine:7} {s['fabricating_rows']:>2} fabricating rows   "
            f"invented fraction {s['min_unattributable_pct']}%-{s['max_unattributable_pct']}%   "
            f"majority-invented in {s['rows_majority_unattributable']}   "
            f"none invented in {s['rows_with_no_unattributable']}"
        )

    print("\nWords invented at each engine's own onset strength (nothing on the page produced them)")
    for engine in ENGINES:
        for seed in ("seed1", "seed2", "seed3"):
            first = next(
                (
                    r
                    for r in summary["rows"]
                    if r["seed"] == seed and r["engines"][engine]["fabricated"]
                ),
                None,
            )
            if first is None:
                print(f"    {engine:7} {seed}: never fabricated")
                continue
            e = first["engines"][engine]
            invented = [t for t, k in zip(e["tokens"], e["kinds"]) if k == "unattributable"]
            print(f"    {engine:7} {seed} at {first['strength']:g}: {invented or '(none)'}")

    out = ROOT / "fabricated_words.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
