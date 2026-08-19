"""Pin the third engine's curve to its committed captures.

`study/sweep/score_docling.py` adds Docling — a layout model plus Apple Vision OCR, with no
generative decoding — to the ladder Marker and MinerU were measured on, bisects included, so
its onset bracket is 0.025 wide like theirs. The results the study takes from it (a
non-generative pipeline crosses into fabrication too, in the same 0.10-0.15 region; it omits
nothing at any strength; the published `mineru_first` verdict survives a third engine) are
only worth stating if the comparison is provably against the same ladder at the same
resolution, and if the numbers cannot drift.

Three groups, same shape as `test_fabricated_words.py`: the regression check against the
committed JSON; the guards that make a wrong corpus, a wrong ladder or an unsplittable
capture fail loudly instead of scoring as a result; and the claims themselves, re-derived.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SWEEP = Path(__file__).parent.parent / "study" / "sweep"
if str(SWEEP) not in sys.path:
    sys.path.insert(0, str(SWEEP))

from pagesplit import SweepOutputError, docling_pages  # noqa: E402
from score_docling import (  # noqa: E402
    CAPTURES,
    ENGINE,
    DoclingScoreError,
    build_summary,
    measure_seed,
)
from summarize_onsets import SEEDS  # noqa: E402

COMMITTED = json.loads((SWEEP / "docling_results.json").read_text("utf-8"))
ONSETS = json.loads((SWEEP / "onset_summary.json").read_text("utf-8"))


def _seed(seed_id: str) -> dict:
    return next(s for s in COMMITTED["seeds"] if s["id"] == seed_id)


def _published(seed_id: str) -> dict:
    return next(s for s in ONSETS["seeds"] if s["id"] == seed_id)["onsets"]


def _rows():
    return [(s["id"], r) for s in COMMITTED["seeds"] for r in s["rows"]]


# --- regression -------------------------------------------------------------------


def test_committed_results_reproduce_from_the_committed_captures():
    assert build_summary() == COMMITTED


def test_every_token_list_is_exactly_as_long_as_the_count_beside_it():
    for seed_id, row in _rows():
        assert len(row["tokens"]) == row["docling_fabricated"], (
            f"{seed_id} at {row['strength']} publishes {row['docling_fabricated']} "
            f"fabricated words and {len(row['tokens'])} tokens"
        )


def test_every_token_lands_in_exactly_one_bucket():
    for seed_id, row in _rows():
        assert sum(row["buckets"].values()) == row["docling_fabricated"], seed_id


def test_a_doctored_results_json_fails_the_regression_check():
    """The committed JSON is evidence only because editing it is caught."""
    doctored = json.loads(json.dumps(COMMITTED))
    doctored["seeds"][0]["rows"][3]["docling_fabricated"] = 0
    assert doctored != build_summary()


# --- guards -----------------------------------------------------------------------


def test_the_capture_registry_covers_exactly_the_onset_summarys_seeds():
    assert set(CAPTURES) == {s["id"] for s in SEEDS}


def test_the_real_and_ghost_passages_come_from_the_onset_summarys_registry():
    """Not re-declared in the capture registry: a second copy is a second thing to go stale."""
    for seed in COMMITTED["seeds"]:
        registry = next(s for s in SEEDS if s["id"] == seed["id"])
        assert (seed["real"], seed["ghost"]) == (registry["real"], registry["ghost"])


def test_every_seed_is_measured_on_the_published_ladder_bisects_included():
    for seed in COMMITTED["seeds"]:
        ladder = [round(float(s), 4) for s in next(
            s for s in ONSETS["seeds"] if s["id"] == seed["id"]
        )["strengths"]]
        assert [r["strength"] for r in seed["rows"]] == ladder


def test_scoring_a_corpus_the_registry_does_not_describe_is_an_error(monkeypatch):
    """A ground truth that is not the registry's `real` passage must raise, not misclassify."""
    import score_docling

    monkeypatch.setitem(score_docling.CAPTURES["seed1"][0], "truth", "ground_truth3.json")
    with pytest.raises(DoclingScoreError, match="PASSAGES"):
        measure_seed("seed1")


def test_dropping_a_bisect_capture_is_an_error_not_a_wider_bracket(monkeypatch):
    """The coarse-only bracket is 0.1 wide and would read as agreement with everything."""
    import score_docling

    monkeypatch.setitem(
        score_docling.CAPTURES, "seed1", [score_docling.CAPTURES["seed1"][0]]
    )
    with pytest.raises(DoclingScoreError, match="different ladder"):
        measure_seed("seed1")


def test_scoring_the_same_strength_from_two_captures_is_an_error(monkeypatch):
    import score_docling

    coarse = score_docling.CAPTURES["seed1"][0]
    monkeypatch.setitem(score_docling.CAPTURES, "seed1", [coarse, dict(coarse)])
    with pytest.raises(DoclingScoreError, match="more than one capture"):
        measure_seed("seed1")


def test_a_capture_with_no_text_raises_rather_than_scoring_as_total_loss(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"texts": []}), "utf-8")
    with pytest.raises(SweepOutputError, match="no text on any page"):
        docling_pages(empty)


def test_a_capture_with_tables_raises_rather_than_reading_only_the_paragraphs(tmp_path):
    """Table text this splitter cannot see would be scored as the engine omitting it."""
    with_table = tmp_path / "table.json"
    with_table.write_text(
        json.dumps(
            {
                "texts": [{"text": "hello", "prov": [{"page_no": 1}]}],
                "tables": [{"self_ref": "#/tables/0"}],
            }
        ),
        "utf-8",
    )
    with pytest.raises(SweepOutputError, match="tables"):
        docling_pages(with_table)


def test_page_numbers_are_converted_from_doclings_one_based_provenance(tmp_path):
    doc = tmp_path / "doc.json"
    doc.write_text(
        json.dumps(
            {
                "texts": [
                    {"text": "first", "prov": [{"page_no": 1}]},
                    {"text": "third", "prov": [{"page_no": 3}]},
                ]
            }
        ),
        "utf-8",
    )
    assert docling_pages(doc) == {0: "first", 2: "third"}


# --- the claims -------------------------------------------------------------------


def test_a_non_generative_pipeline_crosses_into_fabrication_on_every_seed():
    """The point of adding this engine: fabrication is not exclusive to generative decoding."""
    assert ENGINE["generative"] is False
    assert COMMITTED["totals"]["seeds_crossing"] == ["seed1", "seed2", "seed3"]
    assert COMMITTED["totals"]["seeds_clean"] == []


def test_its_onset_lands_in_the_same_region_as_the_two_generative_engines():
    """Every bracket falls inside 0.10-0.15, where MinerU's and two of Marker's do."""
    for seed in COMMITTED["seeds"]:
        assert 0.10 <= seed["onset"]["last_clean"] < seed["onset"]["first_fabricating"] <= 0.15


def test_its_brackets_are_as_narrow_as_the_published_ones():
    """Matched resolution is what makes the ordering below a comparison rather than a guess."""
    for seed in COMMITTED["seeds"]:
        assert seed["onset"]["bracket_width"] == 0.025
        for other in ("marker", "mineru"):
            assert _published(seed["id"])[other]["bracket_width"] == 0.025


def test_it_omits_nothing_at_any_strength_on_any_seed():
    """The sharpest contrast with Marker, which drops most of a page at most strengths."""
    assert COMMITTED["totals"]["max_omitted_share"] == 0.0
    assert all(row["docling_omitted"] == 0 for _, row in _rows())


def test_a_third_engine_does_not_overturn_the_published_mineru_first_verdict():
    """On no seed does Docling provably cross before MinerU; on two, MinerU provably first."""
    assert ONSETS["onset_ordering"]["verdict"] == "mineru_first"
    assert COMMITTED["ordering"]["docling_provably_first_against"]["mineru"] == []
    assert COMMITTED["ordering"]["provably_first_against_docling"]["mineru"] == ["seed1", "seed2"]


def test_it_provably_crosses_before_marker_on_two_of_the_three_seeds():
    assert COMMITTED["ordering"]["docling_provably_first_against"]["marker"] == ["seed1", "seed3"]
    assert COMMITTED["ordering"]["provably_first_against_docling"]["marker"] == []


def test_overlapping_brackets_are_reported_undetermined_not_ranked():
    """seed2 shares Marker's bracket exactly and seed3 shares MinerU's — neither is a verdict."""
    undetermined = COMMITTED["ordering"]["undetermined_against"]
    assert undetermined == {"marker": ["seed2"], "mineru": ["seed3"]}
    assert _seed("seed2")["onset"]["first_fabricating"] == _published("seed2")["marker"][
        "first_fabricating"
    ]
    assert _seed("seed3")["onset"]["first_fabricating"] == _published("seed3")["mineru"][
        "first_fabricating"
    ]


def test_the_onset_is_not_the_same_bracket_on_every_seed():
    """Passage-dependent, like Marker's — so it is not a fixed property of the engine."""
    brackets = {
        (s["onset"]["last_clean"], s["onset"]["first_fabricating"]) for s in COMMITTED["seeds"]
    }
    assert len(brackets) > 1


def test_the_curve_is_not_monotonic():
    """seed2 is clean again at 0.2 after fabricating at 0.175, so 'onset' means first crossing."""
    rows = _seed("seed2")["rows"]
    crossed = False
    recovered = False
    for row in rows:
        if row["docling_fabricated"]:
            crossed = True
        elif crossed:
            recovered = True
    assert recovered


def test_the_invention_claim_is_published_as_a_bound_not_a_measurement():
    """The mirrored ghost layer makes `unattributable` unreadable as invention here."""
    t = COMMITTED["totals"]
    assert "invented_share_upper_bound" in t and "invented_share" not in t
    assert "upper bound" in t["caveat"]
    assert t["unattributable_words"] <= t["fabricated_words"]


def test_the_mirrored_ink_reading_is_recorded_as_mechanically_unconfirmed():
    """7 of 106 tokens match a reversed page word — published because it is the weak result."""
    t = COMMITTED["totals"]
    assert t["reversed_vocab_matches"] == 7
    assert t["reversed_vocab_matches"] < t["unattributable_words"] / 2


def test_seed_2_fabricates_by_duplicating_a_real_heading_at_the_upper_strengths():
    """A third failure mode, distinct from ghost transcription and from invention."""
    duplicating = [
        r
        for r in _seed("seed2")["rows"]
        if r["docling_fabricated"] and r["buckets"]["unattributable"] == 0
    ]
    assert duplicating, "seed2 no longer duplicates the heading at any strength"
    for row in duplicating:
        assert {"observations", "of", "the", "tide"} <= set(row["tokens"])


# --- the writeup ------------------------------------------------------------------


def test_the_readme_totals_match_the_computed_ones():
    readme = (SWEEP.parent / "README.md").read_text("utf-8")
    t = COMMITTED["totals"]
    for label, value in (
        ("fabricated words", t["fabricated_words"]),
        ("rows fabricating", t["rows_fabricating"]),
        ("reversed matches", t["reversed_vocab_matches"]),
    ):
        assert str(value) in readme, f"README no longer carries the computed {label}"


def test_the_readme_onset_row_matches_each_seeds_computed_bracket():
    readme = (SWEEP.parent / "README.md").read_text("utf-8")
    for seed in COMMITTED["seeds"]:
        o = seed["onset"]
        assert f"({o['last_clean']}, {o['first_fabricating']}]" in readme, (
            f"README's {seed['id']} Docling bracket is stale"
        )
