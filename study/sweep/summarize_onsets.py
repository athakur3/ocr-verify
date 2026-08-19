"""Consolidate the three ghost-contrast sweep seeds into one computed characterization.

The per-seed sections of `study/README.md` were written one run at a time, and their
cross-seed table was typed by hand from the results JSONs. That is fine for a narrative
and bad for a claim: a transcription slip is invisible, and the three seeds are not
directly comparable in raw word counts anyway — their passages are 104, 115 and 124 words
long, so "20 fabricated" on seed 1 and "20" on seed 3 are different fractions of the page.

This script recomputes the consolidation from the six committed results JSONs instead:

* merges each seed's coarse ladder with its bisect rows into one strength-ordered curve;
* brackets each engine's fabrication onset as an interval `(last clean, first
  fabricating]` rather than a point, which is all a sampled ladder can support;
* reports per-strength spread across seeds in both absolute words and percent of that
  seed's own page, at the six strengths every seed actually shares.

Omission is *unknown*, never zero, where a scorer did not record it: seed 1's bisect
(`bisect_results.json`) carries fabrication counts only. A missing measurement rendered as
0 would read as "no content lost", the flattering direction.

Run: uv run python study/sweep/summarize_onsets.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent

ENGINES = ("marker", "mineru")

# marker_mode is None where the run predates the study recording it — seed 1's mode is a
# known confound (study/README.md, second-seed check), not an omission to paper over.
SEEDS = [
    {
        "id": "seed1",
        "real": "conclusions",
        "ghost": "survey",
        "marker_mode": None,
        "coarse": "sweep_results.json",
        "bisect": "bisect_results.json",
    },
    {
        "id": "seed2",
        "real": "tides",
        "ghost": "instruments",
        "marker_mode": "fast",
        "coarse": "sweep2_results.json",
        "bisect": "sweep2_bisect_results.json",
    },
    {
        "id": "seed3",
        "real": "survey",
        "ghost": "tides",
        "marker_mode": "fast",
        "coarse": "sweep3_results.json",
        "bisect": "sweep3_bisect_results.json",
    },
]


class SweepSummaryError(RuntimeError):
    """Raised when the committed results JSONs cannot be consolidated as claimed."""


def _rows(path: Path, source: str) -> tuple[list[dict], int | None]:
    data = json.loads(path.read_text("utf-8"))
    out = []
    for row in data["rows"]:
        entry = {"strength": round(float(row["ghost_strength"]), 4), "source": source}
        for engine in ENGINES:
            fab = row.get(f"{engine}_fabricated")
            if fab is None:
                raise SweepSummaryError(f"{path.name}: no {engine}_fabricated in row {row}")
            entry[f"{engine}_fabricated"] = int(fab)
            # Absent omission is unknown, not zero. Only seed 1's bisect lacks it today.
            omit = row.get(f"{engine}_omitted")
            entry[f"{engine}_omitted"] = None if omit is None else int(omit)
        out.append(entry)
    return out, data.get("truth_words_per_page")


def load_curve(seed: dict) -> dict:
    coarse, coarse_truth = _rows(ROOT / seed["coarse"], "coarse")
    bisect, bisect_truth = _rows(ROOT / seed["bisect"], "bisect")

    if coarse_truth is None:
        raise SweepSummaryError(f"{seed['coarse']}: no truth_words_per_page to normalize by")
    truth_inherited = bisect_truth is None
    if not truth_inherited and bisect_truth != coarse_truth:
        raise SweepSummaryError(
            f"{seed['id']}: bisect page is {bisect_truth} words but the ladder is "
            f"{coarse_truth} — the two are not the same passage, so they cannot share a curve"
        )

    rows = coarse + bisect
    strengths = [r["strength"] for r in rows]
    if len(set(strengths)) != len(strengths):
        raise SweepSummaryError(f"{seed['id']}: a strength appears in both the ladder and the bisect")
    rows.sort(key=lambda r: r["strength"])

    return {
        "id": seed["id"],
        "real_passage": seed["real"],
        "ghost_passage": seed["ghost"],
        "marker_mode": seed["marker_mode"],
        "truth_words_per_page": coarse_truth,
        "truth_words_inherited_by_bisect": truth_inherited,
        "sources": [seed["coarse"], seed["bisect"]],
        "rows": rows,
    }


def onset(rows: list[dict], engine: str) -> dict:
    """Bracket the first crossing into fabrication as an interval, not a point.

    A sampled ladder can only say the onset lies above the last clean strength and at or
    below the first fabricating one. Curves here are not monotonic (Marker on seed 3 is
    clean again at 0.55 after fabricating at 0.30), so this is deliberately the *first*
    crossing and says so.
    """
    key = f"{engine}_fabricated"
    for idx, row in enumerate(rows):
        if row[key] > 0:
            below = rows[idx - 1]["strength"] if idx else None
            return {
                "crossed": True,
                "last_clean": below,
                "first_fabricating": row["strength"],
                "words_at_first_fabricating": row[key],
                # None below means the lowest strength tested already fabricates: the
                # lower bound is unknown, not 0.0.
                "bracket_width": None if below is None else round(row["strength"] - below, 4),
            }
    return {
        "crossed": False,
        "last_clean": rows[-1]["strength"],
        "first_fabricating": None,
        "words_at_first_fabricating": None,
        "bracket_width": None,
        "note": "clean at every strength tested",
    }


def _bounds(onset_: dict) -> tuple[float, float]:
    """The open-closed onset bracket as numbers, with unknown ends pushed outward.

    A missing lower bound means the lowest strength tested already fabricated, so the
    onset could be arbitrarily low; a missing upper bound means it never crossed at all.
    Both widen the interval, which is the direction that refuses conclusions rather than
    inventing them.
    """
    lo = float("-inf") if onset_["last_clean"] is None or not onset_["crossed"] else onset_["last_clean"]
    hi = float("inf") if onset_["first_fabricating"] is None else onset_["first_fabricating"]
    if not onset_["crossed"]:
        lo = onset_["last_clean"]
    return lo, hi


def _provably_before(a: dict, b: dict) -> bool:
    """True when a's whole onset bracket lies at or below b's — no overlap to argue with."""
    _, a_hi = _bounds(a)
    b_lo, _ = _bounds(b)
    return a_hi <= b_lo


def onset_ordering(curves: list[dict]) -> dict:
    """Which engine provably crosses first, per seed, from disjoint brackets alone.

    The README argues this in prose per seed. Computed from the brackets it is a yes/no:
    the claim holds only where the two intervals do not overlap, and a seed whose
    intervals overlap says "unresolved at this resolution" rather than picking a winner.
    """
    per_seed = {}
    for curve in curves:
        marker, mineru = onset(curve["rows"], "marker"), onset(curve["rows"], "mineru")
        if _provably_before(mineru, marker):
            verdict = "mineru_first"
        elif _provably_before(marker, mineru):
            verdict = "marker_first"
        else:
            verdict = "unresolved_at_this_resolution"
        per_seed[curve["id"]] = verdict
    verdicts = set(per_seed.values())
    return {
        "per_seed": per_seed,
        "unanimous": len(verdicts) == 1 and "unresolved_at_this_resolution" not in verdicts,
        "verdict": per_seed[curves[0]["id"]] if len(verdicts) == 1 else "mixed",
    }


def onset_consistency(curves: list[dict]) -> dict:
    """Per engine: is one common onset strength consistent with every seed's bracket?

    Two seeds whose brackets are disjoint prove the onset moved — but only a pair that
    ran the same Marker mode proves it moved with the *passage*. Seed 1's mode was never
    recorded, so every pair involving it is confounded and is flagged rather than counted.
    Seeds whose brackets all overlap are merely *consistent* with a single onset — that is
    not the same as showing there is one, and the key name says so.
    """
    modes = {c["id"]: c["marker_mode"] for c in curves}
    out = {}
    for engine in ENGINES:
        onsets = {c["id"]: onset(c["rows"], engine) for c in curves}
        disjoint = []
        ids = list(onsets)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if _provably_before(onsets[a], onsets[b]) or _provably_before(onsets[b], onsets[a]):
                    matched = modes[a] is not None and modes[a] == modes[b]
                    disjoint.append({"seeds": [a, b], "marker_mode_matched": matched})
        out[engine] = {
            "brackets": {
                sid: [o["last_clean"], o["first_fabricating"]] for sid, o in onsets.items()
            },
            "provably_different_seed_pairs": disjoint,
            "consistent_with_one_onset": not disjoint,
            # The only pairs that isolate passage from engine mode.
            "provably_different_with_mode_matched": [
                d["seeds"] for d in disjoint if d["marker_mode_matched"]
            ],
        }
    return out


def level_spread(curves: list[dict]) -> dict:
    shared = set.intersection(*({r["strength"] for r in c["rows"]} for c in curves))
    out = {}
    for strength in sorted(shared):
        entry = {}
        for engine in ENGINES:
            words, pct = [], []
            for curve in curves:
                row = next(r for r in curve["rows"] if r["strength"] == strength)
                fab = row[f"{engine}_fabricated"]
                words.append(fab)
                pct.append(round(100.0 * fab / curve["truth_words_per_page"], 1))
            entry[engine] = {
                "words": words,
                "words_range": max(words) - min(words),
                "percent_of_page": pct,
                "percent_range": round(max(pct) - min(pct), 1),
            }
        out[f"{strength:g}"] = entry
    return out


def _fmt(value) -> str:
    return "unknown" if value is None else f"{value:g}" if isinstance(value, float) else str(value)


def build_summary(curves: list[dict]) -> dict:
    """The committed `onset_summary.json`, as data — so a test can recompute and compare."""
    spread = level_spread(curves)
    return {
        "seeds": [
            {
                "id": c["id"],
                "real_passage": c["real_passage"],
                "ghost_passage": c["ghost_passage"],
                "marker_mode": c["marker_mode"],
                "truth_words_per_page": c["truth_words_per_page"],
                "truth_words_inherited_by_bisect": c["truth_words_inherited_by_bisect"],
                "sources": c["sources"],
                "strengths": [r["strength"] for r in c["rows"]],
                "omission_unrecorded_at": {
                    e: [r["strength"] for r in c["rows"] if r[f"{e}_omitted"] is None]
                    for e in ENGINES
                },
                "onsets": {e: onset(c["rows"], e) for e in ENGINES},
                "rows": c["rows"],
            }
            for c in curves
        ],
        "shared_strengths": [float(s) for s in spread],
        "cross_seed_spread": spread,
        "onset_ordering": onset_ordering(curves),
        "onset_consistency": onset_consistency(curves),
    }


def main() -> None:
    curves = [load_curve(seed) for seed in SEEDS]

    print("Per-seed curves (ladder + bisect merged; omission 'unknown' where unrecorded)\n")
    for curve in curves:
        mode = curve["marker_mode"] or "unrecorded (confound)"
        print(f"{curve['id']}: real={curve['real_passage']} ghost={curve['ghost_passage']} "
              f"page={curve['truth_words_per_page']} words, marker mode={mode}")
        for engine in ENGINES:
            o = onset(curve["rows"], engine)
            if o["crossed"]:
                lo = "below the ladder" if o["last_clean"] is None else f"{o['last_clean']:g}"
                print(f"    {engine:7s} onset in ({lo}, {o['first_fabricating']:g}]  "
                      f"first fabricating count {o['words_at_first_fabricating']}")
            else:
                print(f"    {engine:7s} never crossed at or below {o['last_clean']:g}")
        print()

    spread = level_spread(curves)
    ids = ", ".join(c["id"] for c in curves)
    print(f"Cross-seed spread at the strengths all three seeds share ({ids})\n")
    header = f"{'ghost':>6}  {'marker words':>22} {'range':>5}  {'marker % of page':>22} {'range':>6}"
    print(header)
    for strength, entry in spread.items():
        m = entry["marker"]
        print(f"{strength:>6}  {str(m['words']):>22} {m['words_range']:>5}  "
              f"{str(m['percent_of_page']):>22} {m['percent_range']:>6}")
    print()
    header = f"{'ghost':>6}  {'mineru words':>22} {'range':>5}  {'mineru % of page':>22} {'range':>6}"
    print(header)
    for strength, entry in spread.items():
        m = entry["mineru"]
        print(f"{strength:>6}  {str(m['words']):>22} {m['words_range']:>5}  "
              f"{str(m['percent_of_page']):>22} {m['percent_range']:>6}")

    ordering = onset_ordering(curves)
    consistency = onset_consistency(curves)
    print("\nOnset ordering per seed (from disjoint brackets, not from prose)")
    for sid, verdict in ordering["per_seed"].items():
        print(f"    {sid}: {verdict}")
    print(f"    unanimous: {ordering['unanimous']}")
    print("\nIs one common onset consistent with every seed's bracket?")
    for engine, info in consistency.items():
        print(f"    {engine:7s} {info['consistent_with_one_onset']}"
              f"{'' if info['consistent_with_one_onset'] else '  provably different (mode-matched pairs): ' + str(info['provably_different_with_mode_matched'])}")

    summary = build_summary(curves)
    out = ROOT / "onset_summary.json"
    out.write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
