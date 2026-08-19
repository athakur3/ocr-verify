"""A third engine on the same ladder: does every engine have a fabrication onset?

The two-onsets result rests on two engines, and two engines cannot separate "engines
fabricate under bleed-through" from "these two engines do". Both are also generative:
Marker and MinerU decode text with a language model, so every fabrication measured so far
was produced by something capable of inventing fluent words. Docling is the cheapest
available way to break that tie — a layout model plus a plain OCR reader, with no
generative decoding anywhere in the path.

This scores Docling on exactly the ladder the other two were scored on: the same three
sweep corpora, all seven capture sets (three coarse plus four bisects), the same
`bag_delta` measurement, and the same layer classification `fabricated_words.py` applies
to the other two. The bisects are not optional — Marker's and MinerU's published brackets
are 0.025 wide because they were bisected, and a coarse-only 0.1-wide bracket compared
against them would read as agreement wherever it is only imprecise. Nothing about the
existing captures or their committed results JSONs is touched: the third engine is a new
column, computed from new captures, written to its own file.

The capture command, recorded because this study has already lost a run to an unrecorded
engine invocation (`study/README.md`, the `--paginate_output` note) — run once per corpus
over `sweep{,2,3}.pdf`, `bisect.pdf`, `sweep2_bisect.pdf`, `sweep3_bisect.pdf` and
`sweep3_lowbisect.pdf`:

    docling convert --ocr-engine ocrmac --to json --image-export-mode placeholder \
        --device cpu <corpus>.pdf --output study/sweep/docling_<corpus>/

Docling 2.120.3 / docling-ibm-models 3.14.0, OCR backend `ocrmac` 1.0.1 (Apple Vision).
Two choices in that line are load-bearing:

* **`--ocr-engine ocrmac`, not `tesseract`.** Docling can drive Tesseract, which is also
  ocr-verify's witness. Sharing a reader with the witness would make any agreement
  circular. Apple Vision is an independent reader, so a Docling fabrication is not
  something the witness is guaranteed to also see.
* **`--to json`, not `--to md`.** Docling's markdown carries no page markers at all — the
  same shape as `marker_single` without `--paginate_output`, and with no flag to fix it.
  The JSON export's `prov[*].page_no` is the only per-page source; `pagesplit.docling_pages`
  raises rather than silently scoring a marker-less export as total content loss.

`--image-export-mode placeholder` only drops the base64 page rasters Docling would
otherwise embed (377 KB per page, of a PDF already committed beside it). Verified not to
change a single text item: the run was done both ways and the documents compare equal
apart from those rasters, and a repeat run is byte-identical.

What this refuses to do:

* **No new ladder.** If Docling's strengths did not match the ones the other two engines
  were measured at, the comparison would be between different experiments. The merged
  strengths are asserted equal to the ladder `onset_summary.json` publishes for each seed,
  so a missing bisect capture raises instead of quietly widening the bracket.
* **No ordering claimed from overlapping brackets.** `ordering()` reuses the published
  verdict's own `_provably_before`, so two engines the ladder cannot separate come back
  `undetermined` rather than being ranked by bracket midpoint.
* **No lexicality verdict.** Same as `fabricated_words.py`: buckets say which layer of the
  page could have produced a word, not whether it is a real word. The reading of "glyph
  noise vs fluent invention" stays in prose, over published token lists.
* **No onset invented from a clean curve.** An engine clean at every strength tested has
  no onset — reported as `crossed: false`, never as an onset above the top of the ladder.

Run: uv run python study/sweep/score_docling.py
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

from ocr_verify.normalize import near_miss  # noqa: E402

from fabricated_words import BUCKETS, classify, fabricated_tokens, toks  # noqa: E402
from pagesplit import docling_pages  # noqa: E402
from score import bag_delta  # noqa: E402
from summarize_onsets import SEEDS, _provably_before, onset  # noqa: E402

ENGINE = {
    "name": "docling",
    "version": "2.120.3",
    "ibm_models_version": "3.14.0",
    "ocr_backend": "ocrmac 1.0.1 (Apple Vision)",
    "generative": False,
    "command": (
        "docling convert --ocr-engine ocrmac --to json "
        "--image-export-mode placeholder --device cpu"
    ),
}

# Captures per seed, keyed to `summarize_onsets.SEEDS` by id, in the same coarse-then-bisect
# order the published curves merge them in. `real`/`ghost` are not repeated here on purpose:
# they are read from SEEDS, so this file cannot drift from the registry the published onsets
# were computed with. Only the capture paths are new.
CAPTURES = {
    "seed1": [
        {"kind": "coarse", "truth": "ground_truth.json", "doc": "docling_out/sweep.json"},
        {"kind": "bisect", "truth": "bisect_ground_truth.json", "doc": "docling_bisect/bisect.json"},
    ],
    "seed2": [
        {"kind": "coarse", "truth": "ground_truth2.json", "doc": "docling_out2/sweep2.json"},
        {
            "kind": "bisect",
            "truth": "sweep2_bisect_ground_truth.json",
            "doc": "docling_sweep2_bisect/sweep2_bisect.json",
        },
    ],
    "seed3": [
        {"kind": "coarse", "truth": "ground_truth3.json", "doc": "docling_out3/sweep3.json"},
        {
            "kind": "bisect",
            "truth": "sweep3_bisect_ground_truth.json",
            "doc": "docling_sweep3_bisect/sweep3_bisect.json",
        },
        {
            "kind": "lowbisect",
            "truth": "sweep3_lowbisect_ground_truth.json",
            "doc": "docling_sweep3_lowbisect/sweep3_lowbisect.json",
        },
    ],
}

PUBLISHED = json.loads((ROOT / "onset_summary.json").read_text("utf-8"))


class DoclingScoreError(RuntimeError):
    """Raised when the third engine cannot be scored on the same ladder as the other two."""


def _seed(seed_id: str) -> dict:
    for seed in SEEDS:
        if seed["id"] == seed_id:
            return seed
    raise DoclingScoreError(
        f"{seed_id} is not in summarize_onsets.SEEDS, so its real/ghost passages and its "
        f"published Marker/MinerU curve cannot be looked up"
    )


def _published_seed(seed_id: str) -> dict:
    for seed in PUBLISHED["seeds"]:
        if seed["id"] == seed_id:
            return seed
    raise DoclingScoreError(f"{seed_id} has no curve in onset_summary.json to match against")


def measure_capture(seed: dict, capture: dict) -> list[dict]:
    """One capture's per-strength fabricated/omitted counts and classified tokens."""
    truth = json.loads((ROOT / capture["truth"]).read_text("utf-8"))

    passage = PASSAGES[seed["real"]].strip()
    for page in truth["pages"]:
        if page["text"].strip() != passage:
            raise DoclingScoreError(
                f"{capture['truth']} page {page['page']} is not PASSAGES[{seed['real']!r}] — "
                f"the seed registry does not describe this corpus, so the ghost vocabulary "
                f"would be the wrong one to classify against"
            )

    truth_toks = {p["page"] - 1: toks(p["text"]) for p in truth["pages"]}
    strengths = {p["page"] - 1: round(float(p["ghost_strength"]), 4) for p in truth["pages"]}
    page_vocab = set(toks(PASSAGES[seed["real"]]))
    ghost_vocab = set(toks(PASSAGES[seed["ghost"]]))
    pages = docling_pages(ROOT / capture["doc"], len(truth_toks))

    rows = []
    for idx in sorted(truth_toks):
        emitted = toks(pages.get(idx, ""), markup=True)
        fab, omit = bag_delta(emitted, truth_toks[idx])
        tokens = fabricated_tokens(emitted, truth_toks[idx])
        if len(tokens) != fab:
            raise DoclingScoreError(
                f"{seed['id']} at {strengths[idx]}: bag_delta counted {fab} fabricated words "
                f"but {len(tokens)} tokens were extracted. The token list has to explain "
                f"the count it is a decomposition of."
            )
        counts = Counter(classify(t, page_vocab, ghost_vocab) for t in tokens)
        rows.append(
            {
                "strength": strengths[idx],
                "kind": capture["kind"],
                "docling_fabricated": fab,
                "docling_omitted": omit,
                "words_on_page": len(truth_toks[idx]),
                "tokens": tokens,
                "buckets": {b: counts.get(b, 0) for b in BUCKETS},
            }
        )
    return rows


def measure_seed(seed_id: str) -> dict:
    """One seed's whole ladder — coarse plus every bisect — merged and bracketed.

    The merge is what makes this a third column rather than a third experiment: Marker's
    and MinerU's published brackets are 0.025 wide because they were bisected, and a
    0.1-wide bracket compared against them would look like agreement wherever it is only
    coarse. The merged strengths are asserted equal to the ladder `onset_summary.json`
    publishes for this seed, so a missing bisect capture fails instead of quietly widening
    the answer.
    """
    seed = _seed(seed_id)
    rows: list[dict] = []
    for capture in CAPTURES[seed_id]:
        rows.extend(measure_capture(seed, capture))

    seen = [r["strength"] for r in rows]
    if len(set(seen)) != len(seen):
        duplicated = sorted({s for s in seen if seen.count(s) > 1})
        raise DoclingScoreError(
            f"{seed_id}: strength(s) {duplicated} appear in more than one capture, so the "
            f"merged ladder would score the same point twice"
        )
    rows.sort(key=lambda r: r["strength"])

    published = _published_seed(seed_id)
    ladder = [round(float(s), 4) for s in published["strengths"]]
    measured = [r["strength"] for r in rows]
    if measured != ladder:
        raise DoclingScoreError(
            f"{seed_id}: Docling was scored at {measured} but Marker and MinerU are "
            f"published at {ladder} (onset_summary.json). A third engine on a different "
            f"ladder is a different experiment, not a third column."
        )

    words_per_page = {r["words_on_page"] for r in rows}
    if len(words_per_page) != 1:
        raise DoclingScoreError(
            f"{seed_id}: the captures disagree about the page length ({sorted(words_per_page)}), "
            f"so per-page omission shares would not be comparable across the ladder"
        )

    return {
        "id": seed_id,
        "real": seed["real"],
        "ghost": seed["ghost"],
        "truth_words_per_page": words_per_page.pop(),
        "captures": [c["doc"] for c in CAPTURES[seed_id]],
        "rows": rows,
        "onset": onset(rows, "docling"),
    }


def reversed_vocab_matches(seeds: list[dict]) -> int:
    """How many fabricated tokens match a character-reversed page word. A failed test.

    The corpus bleeds its ghost passage through *mirrored*, and Docling's fabricated
    tokens read by eye as mirrored ink transcribed literally — `anoitsviezdo` next to
    "Observations", `odt`/`edi`/`adi` next to "the". If that reading were mechanically
    checkable, `unattributable` would be the wrong bucket for most of them.

    It is not. Reversing each page and ghost word and matching with the same >=4-character
    near-miss tolerance the scorer uses catches 3 of the 64 tokens: mirroring flips each
    glyph's *shape*, which the reader then misidentifies (b/d, r/i), so the string is not a
    reversal of anything. The number is computed and published rather than dropped, because
    the alternative is a claim about mirrored ink resting on nothing but how it looks.
    """
    hits = 0
    for seed in seeds:
        reversed_words = {
            w[::-1] for key in ("real", "ghost") for w in toks(PASSAGES[seed[key]])
        }
        for row in seed["rows"]:
            for tok in row["tokens"]:
                if tok in reversed_words or any(
                    len(w) >= 4 and near_miss(tok, w) for w in reversed_words
                ):
                    hits += 1
    return hits


def totals(seeds: list[dict]) -> dict:
    """Pooled fabrication and its attribution, with the invention claim held as a bound.

    `unattributable` is a word neither layer's *stored* vocabulary could have produced. For
    Marker and MinerU that reads as invention. It cannot be read that way here: Docling
    transcribes mirrored ghost glyphs literally, and the ghost passage is stored un-mirrored,
    so a faithful transcription of ghost ink lands in `unattributable` too. The share is
    therefore reported as an upper bound on invention and named as one.

    `max_omitted_share` is the *worst* omission row across every seed and strength, reported
    because a pooled average would hide a single catastrophic page.
    """
    rows = [r for s in seeds for r in s["rows"]]
    fabricating = [r for r in rows if r["docling_fabricated"] > 0]
    fab_total = sum(r["docling_fabricated"] for r in rows)
    unattributable = sum(r["buckets"]["unattributable"] for r in rows)
    ghost = sum(r["buckets"]["ghost_only"] for r in rows)
    omitted_shares = [round(r["docling_omitted"] / r["words_on_page"], 4) for r in rows]
    return {
        "rows_measured": len(rows),
        "rows_fabricating": len(fabricating),
        "fabricated_words": fab_total,
        "unattributable_words": unattributable,
        "ghost_layer_words": ghost,
        "invented_share_upper_bound": (
            None if not fab_total else round(unattributable / fab_total, 4)
        ),
        "reversed_vocab_matches": reversed_vocab_matches(seeds),
        "caveat": (
            "unattributable is an upper bound on invention for this engine, not a "
            "measurement of it: the ghost layer is mirrored on the page and stored "
            "un-mirrored, so literally transcribed ghost ink cannot match it"
        ),
        "seeds_crossing": sorted(s["id"] for s in seeds if s["onset"]["crossed"]),
        "seeds_clean": sorted(s["id"] for s in seeds if not s["onset"]["crossed"]),
        "max_omitted_share": max(omitted_shares),
        "min_omitted_share": min(omitted_shares),
    }


def ordering(seeds: list[dict]) -> dict:
    """Per seed, which engine provably crosses first — Docling, or each generative engine.

    Reuses `summarize_onsets._provably_before`, so "provably" means the same thing it means
    for the published Marker-vs-MinerU verdict: the two brackets are disjoint. Overlapping
    brackets return `undetermined`, which is the answer whenever the ladder cannot separate
    two engines — never the engine with the lower midpoint.
    """
    out = {}
    for seed in seeds:
        published = _published_seed(seed["id"])["onsets"]
        verdicts = {}
        for other in ("marker", "mineru"):
            mine, theirs = seed["onset"], published[other]
            if _provably_before(mine, theirs):
                verdicts[other] = "docling_first"
            elif _provably_before(theirs, mine):
                verdicts[other] = f"{other}_first"
            else:
                verdicts[other] = "undetermined"
        out[seed["id"]] = verdicts
    return {
        "per_seed": out,
        "docling_provably_first_against": {
            other: sorted(sid for sid, v in out.items() if v[other] == "docling_first")
            for other in ("marker", "mineru")
        },
        "provably_first_against_docling": {
            other: sorted(sid for sid, v in out.items() if v[other] == f"{other}_first")
            for other in ("marker", "mineru")
        },
        "undetermined_against": {
            other: sorted(sid for sid, v in out.items() if v[other] == "undetermined")
            for other in ("marker", "mineru")
        },
    }


def build_summary() -> dict:
    seeds = [measure_seed(sid) for sid in CAPTURES]
    return {
        "engine": ENGINE,
        "seeds": seeds,
        "ordering": ordering(seeds),
        "totals": totals(seeds),
    }


def main() -> None:
    summary = build_summary()
    seeds = summary["seeds"]

    print(f"{'seed':>6} {'ghost':>6} {'fabricated':>10} {'invented':>8} {'omitted':>7} {'of':>4}")
    for seed in seeds:
        for row in seed["rows"]:
            print(
                f"{seed['id']:>6} {row['strength']:>6} {row['docling_fabricated']:>10} "
                f"{row['buckets']['unattributable']:>8} {row['docling_omitted']:>7} "
                f"{seed['truth_words_per_page']:>4}"
            )
    for seed in seeds:
        o = seed["onset"]
        where = (
            f"({o['last_clean']}, {o['first_fabricating']}]"
            if o["crossed"]
            else f"none — clean through {o['last_clean']}"
        )
        print(f"{seed['id']} onset: {where}")

    out = ROOT / "docling_results.json"
    out.write_text(json.dumps(summary, indent=2), "utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
