"""Pin the fabrication-kind characterization to the committed captures.

`study/sweep/fabricated_words.py` decomposes each sweep's fabricated-word *count* into the
words themselves, and asks of each one whether the page could have produced it at all. The
study's claims from that — Marker mostly transcribes the ghost layer, MinerU mostly invents
— are only worth stating if the token lists provably explain the counts already published
beside them, and if the classification cannot quietly drift.

So the tests come in three groups: the regression check against the committed JSON; the
reconciliation and registry guards, which are what stop a wrong ghost passage or a stale
capture from producing a confident wrong answer; and the claims themselves, re-derived.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

SWEEP = Path(__file__).parent.parent / "study" / "sweep"
if str(SWEEP) not in sys.path:
    sys.path.insert(0, str(SWEEP))

from fabricated_words import (  # noqa: E402
    BUCKETS,
    ENGINES,
    RUNS,
    FabricationKindError,
    build_summary,
    classify,
    fabricated_tokens,
    measure_run,
    reconcile,
)

COMMITTED = json.loads((SWEEP / "fabricated_words.json").read_text("utf-8"))


def _rows(engine: str):
    return [r for r in COMMITTED["rows"] if r["engines"][engine]["fabricated"]]


def _onset_row(seed: str, engine: str):
    """The lowest-strength row on a seed where this engine fabricates anything."""
    return next(r for r in COMMITTED["rows"] if r["seed"] == seed and r["engines"][engine]["fabricated"])


def _invented(row: dict, engine: str) -> list[str]:
    e = row["engines"][engine]
    return [t for t, k in zip(e["tokens"], e["kinds"]) if k == "unattributable"]


# --- regression -------------------------------------------------------------------


def test_committed_summary_reproduces_from_the_committed_captures():
    assert build_summary() == COMMITTED


# --- the guards that make a wrong answer loud -------------------------------------


def test_every_token_list_explains_its_committed_fabrication_count():
    # The load-bearing check: this file is a decomposition of numbers the study already
    # published, so any run whose tokens do not add up to those numbers is an error rather
    # than a new measurement. build_summary() calls this too; asserting it per run here
    # means a failure names the run.
    for run in RUNS:
        reconcile(run, measure_run(run))


def test_a_results_json_that_disagrees_with_the_tokens_is_an_error(tmp_path):
    run = dict(RUNS[0])
    doctored = json.loads((SWEEP / run["results"]).read_text("utf-8"))
    doctored["rows"][2]["marker_fabricated"] += 1
    path = tmp_path / "doctored.json"
    path.write_text(json.dumps(doctored), "utf-8")

    rows = measure_run(run)
    run["results"] = str(path)
    with pytest.raises(FabricationKindError, match="does not explain the published count"):
        reconcile(run, rows)


def test_a_registry_naming_the_wrong_real_passage_is_an_error_not_a_misclassification():
    # The ghost passage exists only in the generator, never in the ground truth JSON, so a
    # drifted `real`/`ghost` pair would classify every token against the wrong vocabulary
    # and still produce a plausible table. The ground-truth text is checked against
    # PASSAGES[real] first precisely so that fails instead.
    run = dict(RUNS[0], real="tides")
    with pytest.raises(FabricationKindError, match="not PASSAGES"):
        measure_run(run)


def test_the_run_registry_agrees_with_the_onset_summarys_seeds():
    from summarize_onsets import SEEDS  # noqa: PLC0415

    for seed in SEEDS:
        runs = [r for r in RUNS if r["seed"] == seed["id"]]
        assert runs, f"{seed['id']} has captures in summarize_onsets but none here"
        assert {r["real"] for r in runs} == {seed["real"]}
        assert {r["ghost"] for r in runs} == {seed["ghost"]}
        # Same results JSONs on both sides: the coarse ladder plus every bisect.
        assert {r["results"] for r in runs} == {seed["coarse"], *seed["bisects"]}


def test_the_onsets_here_match_the_brackets_the_onset_summary_computed():
    # Two scripts, two registries, one answer: the lowest strength at which a seed's engine
    # fabricates must be the `first_fabricating` end of that seed's bracket. This is what
    # catches a capture path pointing at the wrong run.
    summary = json.loads((SWEEP / "onset_summary.json").read_text("utf-8"))
    for seed in summary["seeds"]:
        for engine in ENGINES:
            expected = seed["onsets"][engine]["first_fabricating"]
            if expected is None:
                assert not [
                    r for r in _rows(engine) if r["seed"] == seed["id"]
                ], f"{seed['id']}/{engine} never crossed but has fabricated tokens here"
                continue
            assert _onset_row(seed["id"], engine)["strength"] == expected


def test_every_token_lands_in_exactly_one_bucket():
    for row in COMMITTED["rows"]:
        for engine in ENGINES:
            e = row["engines"][engine]
            assert len(e["tokens"]) == len(e["kinds"]) == e["fabricated"]
            assert set(e["buckets"]) == set(BUCKETS)
            assert sum(e["buckets"].values()) == e["fabricated"]


# --- the classification's own reasoning -------------------------------------------


def test_a_word_in_both_passages_is_attributed_to_neither():
    # Function words are in every passage in this corpus. Crediting them to the ghost would
    # inflate the benign bucket; crediting them to invention would inflate the damning one.
    assert classify("the", {"the", "tide"}, {"the", "survey"}) == "both"
    assert classify("survey", {"the", "tide"}, {"the", "survey"}) == "ghost_only"
    assert classify("tide", {"the", "tide"}, {"the", "survey"}) == "page_only"
    assert classify("zanmislaj", {"the", "tide"}, {"the", "survey"}) == "unattributable"


def test_a_glyph_level_misread_of_real_ink_is_not_counted_as_invention():
    # `survcy` is not on the page as written, but the ink that produced it is. Only tokens
    # matching nothing exactly get this benefit of the doubt, at the same >=4-character
    # floor the scorer uses — so a short collision cannot buy it.
    assert classify("survcy", set(), {"survey"}) == "near_miss"
    assert classify("sur", set(), {"survey"}) == "unattributable"


def test_fabricated_tokens_are_the_tokens_bag_delta_counts():
    sys.path.insert(0, str(SWEEP.parent))
    from score import bag_delta  # noqa: PLC0415

    emitted = ["the", "tide", "tide", "zanmislaj", "gauge", "gaugc"]
    truth = ["the", "tide", "gauge"]
    fabricated, _ = bag_delta(emitted, truth)
    assert len(fabricated_tokens(emitted, truth)) == fabricated
    # `gaugc` is absorbed as a near-miss of the remaining `gauge`, `tide` as a surplus.
    assert fabricated_tokens(emitted, truth) == ["tide", "zanmislaj", "gaugc"]


# --- the claims the study makes ---------------------------------------------------


def test_marker_mostly_transcribes_the_page_and_mineru_mostly_invents():
    marker, mineru = COMMITTED["totals"]["marker"], COMMITTED["totals"]["mineru"]
    assert marker["fabricated"] > mineru["fabricated"], "Marker fabricates the larger count"
    # ...and yet inverts on kind, which is the whole point of the section.
    assert marker["unattributable_pct"] < 25.0
    assert mineru["unattributable_pct"] > 65.0
    # Ghost attribution compared as a *rate*: the two totals differ (238 vs 130), so the
    # raw ghost_only counts happen to be close while the rates are 5x apart.
    ghost_rate = {e: t["buckets"]["ghost_only"] / t["fabricated"] for e, t in (("marker", marker), ("mineru", mineru))}
    assert ghost_rate["marker"] > 4 * ghost_rate["mineru"]


def test_both_engines_invent_at_every_strength_where_they_fabricate_at_all():
    # The difference between them is proportion, not kind. Stating it the other way round
    # would be the flattering-for-Marker version of this result.
    for engine in ENGINES:
        spread = COMMITTED["per_row_spread"][engine]
        assert spread["rows_with_no_unattributable"] == 0
        assert spread["min_unattributable_pct"] > 0
    assert (
        COMMITTED["per_row_spread"]["mineru"]["min_unattributable_pct"]
        > COMMITTED["per_row_spread"]["marker"]["min_unattributable_pct"]
    )


def test_seed_2_is_markers_smallest_count_and_its_worst_kind():
    # Two words, both invented, unchanged at three strengths — a count-based reading calls
    # this Marker's best seed.
    for strength in (0.2, 0.3, 0.4):
        row = next(r for r in COMMITTED["rows"] if r["seed"] == "seed2" and r["strength"] == strength)
        assert row["engines"]["marker"]["fabricated"] == 2
        assert _invented(row, "marker") == ["conception", "can"]


def test_the_noise_before_invention_reading_does_not_generalize_past_seed_3():
    # All three seeds cross at the same strength, so the tokens are directly comparable.
    # Seed 2 replicates seed 3 (digit-bearing non-words); seed 1 refutes the general form,
    # and refuting it needs no lexicality classifier — an alphabetic word is checkable.
    onsets = {seed: _onset_row(seed, "mineru") for seed in ("seed1", "seed2", "seed3")}
    assert {r["strength"] for r in onsets.values()} == {0.125}

    seed1 = _invented(onsets["seed1"], "mineru")
    seed2 = _invented(onsets["seed2"], "mineru")
    assert seed1 == ["true", "version", "create", "results"]
    assert seed2 == ["2115m12n1", "3d1", "noq1", "29104"]
    assert all(t.isalpha() for t in seed1), "seed 1 invents words, not glyph noise"
    assert all(any(c.isdigit() for c in t) for t in seed2), "seed 2 invents non-words"


def test_the_readme_totals_table_matches_the_computed_totals():
    readme = (SWEEP.parent / "README.md").read_text("utf-8")
    for engine, label in (("marker", "Marker"), ("mineru", "MinerU")):
        t = COMMITTED["totals"][engine]
        b = t["buckets"]
        row = (
            rf"\|\s*{label}\s*\|\s*{t['fabricated']}\s*\|\s*{b['unattributable']}\s*"
            rf"\({re.escape(str(t['unattributable_pct']))}%\)\s*\|\s*{b['ghost_only']}\s*"
            rf"\|\s*{b['both']}\s*\|\s*{b['page_only']}\s*\|\s*{b['near_miss']}\s*\|"
        )
        assert re.search(row, readme), f"README's {label} row does not match the computed totals"


def test_the_readme_onset_table_matches_the_computed_invented_words():
    readme = (SWEEP.parent / "README.md").read_text("utf-8")
    for number, seed in enumerate(("seed1", "seed2", "seed3"), start=1):
        words = ", ".join(f"`{t}`" for t in _invented(_onset_row(seed, "mineru"), "mineru"))
        assert f"| {number} | {words} |" in readme, f"README's {seed} onset row is stale"
