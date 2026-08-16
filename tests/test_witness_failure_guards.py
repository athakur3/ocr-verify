"""Unit tests for the witness-failure guards, plus regression tests for the
red-team attacks that shaped them (2026-08-16).

Two rounds of history are pinned here:

1. The first real-engine study produced three false positives, all pages the
   witness could not read. Guards were added: the BLIND hedge and the
   WHOLESALE fold.
2. A red team then broke the first version of those guards: the wholesale fold
   hid full-page rewrites, and a fragment-merge repair pass could delete
   accusations outright. The fold gained a shred-evidence requirement, and the
   merge was removed entirely (ablation showed it changed zero study verdicts).

The attack-regression tests at the bottom are the contract: each one is a
minimized version of a demonstrated evasion, and must stay red-team-proof.

Like tests/test_align.py, these build synthetic witness pages rather than
running Tesseract, so they are fast and deterministic.
"""

from __future__ import annotations

from pathlib import Path

from ocr_verify.align import compare_page
from ocr_verify.model import (
    ACCUSATORY_KINDS,
    BLANK_PAGE_FABRICATION,
    UNSUPPORTED_TEXT,
    UNVERIFIABLE_PAGE,
    WHOLESALE_DISAGREEMENT,
    VlmPage,
    WitnessPage,
    Word,
)
from ocr_verify.normalize import normalize_token


def witness(
    text: str,
    *,
    conf: float = 92.0,
    ink: float = 0.02,
    ink_robust: float | None = None,
    index: int = 0,
) -> WitnessPage:
    """Build a witness page laying words out on synthetic lines of eight."""
    words: list[Word] = []
    for i, raw in enumerate(text.split()):
        norm = normalize_token(raw)
        if not norm:
            continue
        line = i // 8
        col = i % 8
        words.append(
            Word(
                text=raw,
                norm=norm,
                conf=conf,
                bbox=(50 + col * 90, 50 + line * 40, 130 + col * 90, 85 + line * 40),
                line_key=(1, 1, line),
            )
        )
    return WitnessPage(
        index=index,
        width=1000,
        height=1400,
        words=words,
        ink_ratio=ink,
        image=Path("/nonexistent"),
        ink_robust=ink_robust,
    )


def vlm(text: str, index: int = 0) -> VlmPage:
    return VlmPage(index=index, text=text, source="test")


PROSE = (
    "The commission dispatched three parties to survey the northern coastal stations "
    "during the summer season and each party carried a theodolite two chronometers "
    "and a barometer of the aneroid pattern"
)


def kinds(result) -> set[str]:
    return {f.kind for f in result.findings}


# ---------------------------------------------------------------------------
# Guard 1: BLIND (ink on page, witness reads ~nothing, engine reads plenty)
# ---------------------------------------------------------------------------


def test_blind_page_is_hedged_not_accused():
    """Inked page the witness cannot read at all: one hedge, no accusations."""
    result = compare_page(witness("", ink=0.06), vlm(PROSE))
    assert kinds(result) == {UNVERIFIABLE_PAGE}
    assert len(result.findings) == 1
    assert result.verified is False
    assert result.witness_quality == "blind"
    assert not kinds(result) & ACCUSATORY_KINDS
    # A page nobody could verify contributes nothing to the divergence metric.
    assert result.divergence == 0.0


def test_blind_ratio_arm_scales_with_engine_word_count():
    """On a dense page, a handful of witness words is still blind: the
    threshold is max(3, 0.05 * vlm_words), so 4 usable words against 100
    engine words (threshold 5) triggers the hedge even though 4 >= 3."""
    engine_text = " ".join(f"token{i:03d}" for i in range(100))
    result = compare_page(witness("token000 token001 token002 token003", ink=0.05), vlm(engine_text))
    assert kinds(result) == {UNVERIFIABLE_PAGE}
    assert result.verified is False
    assert result.witness_quality == "blind"


def test_blind_does_not_fire_on_truly_blank_page():
    """No ink at all + fabricating engine is still the flagship accusation."""
    result = compare_page(witness("", ink=0.0), vlm(PROSE))
    assert kinds(result) == {BLANK_PAGE_FABRICATION}
    assert result.verified is True  # accusations must stay in the --fail-on gate
    assert result.divergence == 1.0


def test_blind_does_not_fire_when_witness_reads_the_page():
    result = compare_page(witness(PROSE, ink=0.02), vlm(PROSE))
    assert result.findings == []
    assert result.verified is True
    assert result.witness_quality == "ok"
    assert UNVERIFIABLE_PAGE not in kinds(result)


def test_blind_hedge_grades_up_when_ink_is_structureless():
    """A blind page whose ink has no text-scale structure is likely a dirty
    blank: the hedge severity rises and the note says so — but it stays a
    hedge, never an accusation, because very faint real text measures the
    same (the study's fade_heavy page scores 0.000 on the robust measure)."""
    dirty_blank = compare_page(witness("", ink=0.06, ink_robust=0.0001), vlm(PROSE))
    structured = compare_page(witness("", ink=0.06, ink_robust=0.02), vlm(PROSE))
    unmeasured = compare_page(witness("", ink=0.06), vlm(PROSE))  # image unreadable

    assert kinds(dirty_blank) == {UNVERIFIABLE_PAGE}
    assert dirty_blank.findings[0].severity > structured.findings[0].severity
    assert "structure" in dirty_blank.findings[0].note
    assert not kinds(dirty_blank) & ACCUSATORY_KINDS

    assert structured.findings[0].severity <= 0.2
    assert unmeasured.findings[0].severity <= 0.2  # can't grade what wasn't measured


# ---------------------------------------------------------------------------
# Small shreds (the removed fragment-merge's territory)
# ---------------------------------------------------------------------------


def test_small_shreds_stay_below_finding_thresholds():
    """Tesseract shreds one word ('winter' -> 'wi' + 'nter') on an otherwise
    clean page. There is no merge pass anymore; the run thresholds are what
    keeps this quiet: one unsupported engine word and two dropped fragments
    are both below min_run, so no finding fires. The counts stay honest."""
    result = compare_page(
        witness("the party passed the wi nter at camp"),
        vlm("the party passed the winter at camp"),
    )
    assert result.findings == []
    assert result.vlm_only == 1  # 'winter' genuinely lacks whole-token support
    assert result.witness_only == 2


def test_shreds_across_lines_behave_the_same():
    filler = "alpha bravo charlie delta echo foxtrot golf"  # indices 0-6, line 0
    result = compare_page(
        witness(filler + " wi nter"),  # 'wi' -> line 0, 'nter' -> line 1
        vlm(filler + " winter"),
    )
    assert result.vlm_only == 1
    assert result.witness_only == 2
    assert result.findings == []


# ---------------------------------------------------------------------------
# Guard 2: WHOLESALE FOLD (heavy two-way disagreement + shred evidence)
# ---------------------------------------------------------------------------

COMMON = (
    "the commission dispatched three parties to survey the northern "
    "coastal stations during summer"
)
# A shredded witness residue — what a real Tesseract failure leaves behind
# (study measurement: frag share 0.44-0.55 on genuine witness failures).
WITNESS_SHREDS = "gr an ite ou tc ro ps bo un de d ev ery wes te rn"
ENGINE_EXTRA = "velvet curtains framed dusty parlor windows nightly"


def test_wholesale_disagreement_folds_to_single_hedge():
    result = compare_page(
        witness(COMMON + " " + WITNESS_SHREDS), vlm(COMMON + " " + ENGINE_EXTRA)
    )
    assert kinds(result) == {WHOLESALE_DISAGREEMENT}
    assert len(result.findings) == 1
    assert result.verified is False
    assert not kinds(result) & ACCUSATORY_KINDS
    finding = result.findings[0]
    assert finding.note  # the report must explain why no itemized accusations
    assert finding.bbox is None  # the whole page is the evidence


def test_wholesale_does_not_fire_on_asymmetric_divergence():
    """A genuine fabrication is one-directional: the witness supports the rest
    of the page, so the accusation must survive the fold."""
    fabrication = (
        "the commission further resolved that a permanent magnetic observatory "
        "be established at cape ellery next season"
    )
    result = compare_page(witness(PROSE), vlm(PROSE + " " + fabrication))
    assert UNSUPPORTED_TEXT in kinds(result)
    assert WHOLESALE_DISAGREEMENT not in kinds(result)
    assert result.verified is True
    assert result.witness_only == 0  # the divergence really is one-sided


def test_wholesale_does_not_fire_on_clean_agreement():
    result = compare_page(witness(PROSE), vlm(PROSE))
    assert result.findings == []
    assert result.verified is True


def test_wholesale_does_not_fire_on_pure_reorder():
    left = "The northern division comprised four stations of which two were established"
    right = "The southern division comprised only three stations the fourth having been abandoned"
    result = compare_page(witness(left + " " + right), vlm(right + " " + left))
    assert result.findings == []
    assert result.verified is True
    assert result.vlm_only == 0
    assert result.witness_only == 0


# ---------------------------------------------------------------------------
# Attack regressions — each is a minimized demonstrated evasion
# ---------------------------------------------------------------------------

TRUE_PAGE = (
    "The commission dispatched three survey parties to the northern coastal stations "
    "during the summer season and each party carried a theodolite two chronometers "
    "and an aneroid barometer for the elevation work The parties reported monthly by "
    "telegraph and their observations were reduced at the central office"
)
REWRITTEN_PAGE = (
    "Quarterly revenue increased eighteen percent driven by strong demand across our "
    "enterprise segment while operating margins expanded due to disciplined cost "
    "management The board approved a dividend of forty cents per share payable in "
    "October and management raised full year guidance citing a robust pipeline"
)


def test_full_page_rewrite_is_accused_not_hedged():
    """Red-team attack A: a confident witness contradicted wholesale is what a
    rewrite looks like. The unmatched witness words are CLEAN (no shreds), so
    the fold must decline and the itemized accusations must count in the gate."""
    result = compare_page(witness(TRUE_PAGE, conf=96.0), vlm(REWRITTEN_PAGE))
    assert kinds(result) & ACCUSATORY_KINDS
    assert WHOLESALE_DISAGREEMENT not in kinds(result)
    assert result.verified is True  # the CI gate must see this page
    assert result.divergence > 0.5


def test_fabrication_plus_independent_omission_is_still_accused():
    """Red-team attack B: the engine invents a block while separately skipping
    a sidebar only the witness read. Both directions diverge, but the witness
    residue is clean words (the sidebar), not shreds — accusation survives."""
    body = (
        "Rainfall records for the district were maintained continuously from the "
        "opening of the station and the gauges were inspected twice yearly by the "
        "divisional engineer who certified the readings against the standard measure"
    )
    sidebar = "Figure eleven comparative discharge hydrograph plotted from weekly gaugings"
    fabrication = (
        "Officials later conceded that several gauges had been vandalised and the "
        "affected records were quietly reconstructed from neighbouring stations"
    )
    result = compare_page(witness(body + " " + sidebar, conf=95.0), vlm(body + " " + fabrication))
    assert UNSUPPORTED_TEXT in kinds(result)
    assert result.verified is True


def test_rewriting_more_is_never_safer_than_rewriting_less():
    """Red-team attack C pinned the anti-monotonicity: above the two-way ratio
    threshold a bigger rewrite used to become a hedge. With the shred gate, a
    clean-worded rewrite of ANY size stays an accusation."""
    base_words = [f"word{i:03d}" for i in range(80)]
    for k in (10, 20, 40, 80):
        rewritten = ["fake%03d" % i for i in range(k)] + base_words[k:]
        result = compare_page(
            witness(" ".join(base_words), conf=95.0), vlm(" ".join(rewritten))
        )
        assert kinds(result) & ACCUSATORY_KINDS, f"rewrite of {k} words must accuse"
        assert result.verified is True, f"rewrite of {k} words must stay in the gate"


def test_shred_deletion_attack_is_dead_with_the_merge():
    """The removed merge's critical attack: witness legitimately reads 'in to'
    on one line; the engine drops the pair and fabricates 'leapt into darkness'.
    The merge used to support the fabricated 'into' and sink the run below
    min_run. With no merge, the three-token fabrication must be reported."""
    result = compare_page(
        witness("we walked in to the harbour house at dusk", conf=95.0),
        vlm("we walked the harbour house at dusk leapt into darkness"),
    )
    unsupported = [f for f in result.findings if f.kind == UNSUPPORTED_TEXT]
    assert unsupported, "the fabricated run must produce a finding"
    assert any(f.n_tokens >= 3 for f in unsupported)


def test_partial_blindness_is_hedged_not_accused():
    """MinerU-run regression (2026-08-17): the witness half-reads a degraded
    page — its matched words are heavily near-miss ('comission', 'partis'),
    its confidence is low, and it never read the page's tail at all. The
    engine's correct tail text must not be called fabrication."""
    head = (
        "the comission dispached three partis to survye the northem coastal "
        "stasions during the sumer season and each party carried a theodolite"
    )
    shreds = "ur an im"
    tail = (
        "two chronometers and a barometer of the aneroid pattern compared at "
        "the observatory before departure and again upon return"
    )
    truth_head = (
        "the commission dispatched three parties to survey the northern coastal "
        "stations during the summer season and each party carried a theodolite"
    )
    result = compare_page(witness(head + " " + shreds, conf=70.0), vlm(truth_head + " " + tail))
    assert result.witness_quality == "low"
    assert not kinds(result) & ACCUSATORY_KINDS
    assert kinds(result) == {WHOLESALE_DISAGREEMENT}
    assert result.verified is False


def test_misspelling_engine_cannot_buy_a_hedge():
    """The evasion the conf ceiling exists to block: an engine emits misspelled
    versions of real words (inflating the witness's apparent misread rate) plus
    a fabricated run. The witness read the page cleanly at high confidence, so
    the partial-blindness signal must NOT fire and the accusation must stand."""
    misspelled = (
        "the comission dispached three partis to survye the northem coastal "
        "stasions during the sumer season and each party carried a theodolite "
        "two chronometers and a barometer of the aneroid pattern"
    )
    fabrication = "officials quietly reconstructed the vandalised gauge records afterwards"
    result = compare_page(witness(PROSE, conf=93.0), vlm(misspelled + " " + fabrication))
    assert result.witness_quality == "ok"
    assert kinds(result) & ACCUSATORY_KINDS
    assert result.verified is True


# ---------------------------------------------------------------------------
# Hedge severity / note sanity
# ---------------------------------------------------------------------------


def test_hedge_findings_carry_notes_and_calibrated_severity():
    blind = compare_page(witness("", ink=0.06), vlm(PROSE))
    wholesale = compare_page(
        witness(COMMON + " " + WITNESS_SHREDS), vlm(COMMON + " " + ENGINE_EXTRA)
    )

    blind_finding = blind.findings[0]
    assert blind_finding.kind == UNVERIFIABLE_PAGE
    assert blind_finding.note
    assert blind_finding.severity <= 0.2  # ungraded coverage gap ranks below accusations

    wholesale_finding = wholesale.findings[0]
    assert wholesale_finding.kind == WHOLESALE_DISAGREEMENT
    assert wholesale_finding.note
    assert 0.0 < wholesale_finding.severity < 1.0  # a look-here prompt, not a verdict
