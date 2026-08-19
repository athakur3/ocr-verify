"""Pin the cross-seed sweep characterization to the committed measurements.

`study/sweep/summarize_onsets.py` turns six results JSONs into the claims the study makes
about fabrication onsets: which engine crosses first, and whether one onset strength fits
every passage. Those claims used to live only in prose typed by hand from the JSONs, where
a transcription slip is invisible.

The first test is the regression check — recompute the summary from the committed captures
and compare it to the committed `onset_summary.json`. The rest pin the reasoning itself:
brackets, not points; unknown omissions, not zeros; and an ordering verdict that says
"unresolved" when the intervals overlap instead of picking a winner.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SWEEP = Path(__file__).parent.parent / "study" / "sweep"
if str(SWEEP) not in sys.path:
    sys.path.insert(0, str(SWEEP))

from summarize_onsets import (  # noqa: E402
    SEEDS,
    SweepSummaryError,
    build_summary,
    load_curve,
    onset,
    onset_consistency,
    onset_ordering,
)


def rows(*triples: tuple[float, int, int]) -> list[dict]:
    """(strength, marker fabricated, mineru fabricated) → curve rows, omissions recorded."""
    return [
        {
            "strength": s,
            "source": "coarse",
            "marker_fabricated": m,
            "marker_omitted": 0,
            "mineru_fabricated": u,
            "mineru_omitted": 0,
        }
        for s, m, u in triples
    ]


def test_committed_summary_reproduces_from_the_committed_captures():
    committed = json.loads((SWEEP / "onset_summary.json").read_text("utf-8"))
    assert build_summary([load_curve(seed) for seed in SEEDS]) == committed


def test_onset_is_a_bracket_not_a_point():
    o = onset(rows((0.1, 0, 0), (0.2, 0, 0), (0.3, 5, 0)), "marker")
    assert o["crossed"] is True
    assert (o["last_clean"], o["first_fabricating"]) == (0.2, 0.3)
    assert o["bracket_width"] == pytest.approx(0.1)


def test_fabricating_at_the_lowest_strength_leaves_the_lower_bound_unknown():
    # Not 0.0: nothing below 0.1 was tested, so the onset could be anywhere beneath it.
    o = onset(rows((0.1, 3, 0), (0.2, 3, 0)), "marker")
    assert o["last_clean"] is None
    assert o["bracket_width"] is None


def test_never_crossing_is_reported_as_such_not_as_a_high_onset():
    o = onset(rows((0.1, 0, 0), (0.55, 0, 0)), "marker")
    assert o["crossed"] is False
    assert o["first_fabricating"] is None
    assert o["last_clean"] == 0.55


def test_onset_is_the_first_crossing_even_when_the_curve_comes_back_clean():
    # Marker's real curves are not monotonic — seed 3 is clean again at 0.55 after
    # fabricating at 0.30 — so a later clean level must not move the onset.
    o = onset(rows((0.1, 0, 0), (0.3, 14, 0), (0.55, 0, 0)), "marker")
    assert o["first_fabricating"] == 0.3


def test_touching_brackets_count_as_disjoint_and_overlapping_ones_do_not():
    # mineru crosses in (0.1, 0.2], marker in (0.2, 0.3] — they touch at 0.2, which
    # belongs to mineru's interval only, so the ordering is decided.
    decided = onset_ordering([{"id": "a", "rows": rows((0.1, 0, 0), (0.2, 0, 4), (0.3, 9, 4))}])
    assert decided["per_seed"]["a"] == "mineru_first"

    # Both cross in the same interval: no ordering is available at this resolution.
    tied = onset_ordering([{"id": "a", "rows": rows((0.1, 0, 0), (0.2, 7, 4))}])
    assert tied["per_seed"]["a"] == "unresolved_at_this_resolution"
    assert tied["unanimous"] is False


def test_disjoint_seed_brackets_are_only_passage_evidence_when_the_mode_matches():
    curves = [
        {"id": "s1", "marker_mode": None, "rows": rows((0.1, 0, 0), (0.2, 5, 0))},
        {"id": "s2", "marker_mode": "fast", "rows": rows((0.1, 0, 0), (0.2, 0, 0), (0.3, 5, 0))},
    ]
    marker = onset_consistency(curves)["marker"]
    assert marker["consistent_with_one_onset"] is False
    # The pair is provably different, but seed 1's Marker mode is unrecorded, so it
    # cannot be counted as evidence that the *passage* moved the onset.
    assert marker["provably_different_seed_pairs"] == [
        {"seeds": ["s1", "s2"], "marker_mode_matched": False}
    ]
    assert marker["provably_different_with_mode_matched"] == []


def test_unrecorded_omission_stays_unknown_rather_than_zero():
    summary = json.loads((SWEEP / "onset_summary.json").read_text("utf-8"))
    seed1 = next(s for s in summary["seeds"] if s["id"] == "seed1")
    # bisect_results.json records fabrication only; those three strengths must be null.
    assert seed1["omission_unrecorded_at"]["marker"] == [0.125, 0.15, 0.175]
    unknown = [r for r in seed1["rows"] if r["strength"] in (0.125, 0.15, 0.175)]
    assert unknown and all(r["marker_omitted"] is None for r in unknown)
    other = [s for s in summary["seeds"] if s["id"] != "seed1"]
    assert all(s["omission_unrecorded_at"]["marker"] == [] for s in other)


def test_spread_is_normalized_by_each_seeds_own_page_length():
    summary = json.loads((SWEEP / "onset_summary.json").read_text("utf-8"))
    lengths = [s["truth_words_per_page"] for s in summary["seeds"]]
    assert len(set(lengths)) > 1, "if every page were the same length, raw counts would do"
    at_030 = summary["cross_seed_spread"]["0.3"]["marker"]
    expected = [round(100.0 * w / n, 1) for w, n in zip(at_030["words"], lengths)]
    assert at_030["percent_of_page"] == expected


def test_a_bisect_from_a_different_passage_cannot_be_merged_into_a_curve(tmp_path):
    (tmp_path / "coarse.json").write_text(
        json.dumps({"truth_words_per_page": 104, "rows": [
            {"ghost_strength": 0.1, "marker_fabricated": 0, "mineru_fabricated": 0}]}))
    (tmp_path / "bisect.json").write_text(
        json.dumps({"truth_words_per_page": 124, "rows": [
            {"ghost_strength": 0.15, "marker_fabricated": 0, "mineru_fabricated": 0}]}))
    import summarize_onsets

    original, summarize_onsets.ROOT = summarize_onsets.ROOT, tmp_path
    try:
        with pytest.raises(SweepSummaryError, match="not the same passage"):
            load_curve({"id": "x", "real": "a", "ghost": "b", "marker_mode": "fast",
                        "coarse": "coarse.json", "bisect": "bisect.json"})
    finally:
        summarize_onsets.ROOT = original


def readme_table(heading: str) -> dict[str, list[str]]:
    """The rows of the markdown table that follows `heading` in study/README.md."""
    text = (Path(__file__).parent.parent / "study" / "README.md").read_text("utf-8")
    after = text.split(heading, 1)[1]
    out = {}
    for line in after.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5 or not cells[0].replace(".", "").isdigit():
            if out:
                break
            continue
        out[f"{float(cells[0]):g}"] = cells[1:]
    return out


def test_the_readme_normalized_table_matches_the_computed_spread():
    # The section this guards exists because hand-typed tables drift silently.
    summary = json.loads((SWEEP / "onset_summary.json").read_text("utf-8"))
    table = readme_table("**Cross-seed spread, normalized**")
    assert set(table) == {f"{s:g}" for s in summary["shared_strengths"]}
    for strength, (m_pct, m_range, u_pct, u_range) in table.items():
        spread = summary["cross_seed_spread"][strength]
        assert m_pct == ", ".join(f"{v}" for v in spread["marker"]["percent_of_page"])
        assert float(m_range) == spread["marker"]["percent_range"]
        assert u_pct == ", ".join(f"{v}" for v in spread["mineru"]["percent_of_page"])
        assert float(u_range) == spread["mineru"]["percent_range"]
