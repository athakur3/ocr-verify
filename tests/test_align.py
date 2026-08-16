"""Unit tests for the comparison engine.

These build synthetic witness pages rather than running Tesseract, so they are
fast and deterministic. The end-to-end behaviour on real rendered pages is
covered by test_fixtures.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ocr_verify.align import Settings, compare_page
from ocr_verify.model import (
    BLANK_PAGE_FABRICATION,
    DROPPED_TEXT,
    UNSUPPORTED_TEXT,
    VlmPage,
    WitnessPage,
    Word,
)
from ocr_verify.normalize import normalize_token


def witness(text: str, *, conf: float = 92.0, ink: float = 0.02, index: int = 0) -> WitnessPage:
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
        index=index, width=1000, height=1400, words=words, ink_ratio=ink, image=Path("/nonexistent")
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


def test_identical_text_is_clean():
    result = compare_page(witness(PROSE), vlm(PROSE))
    assert result.findings == []
    assert result.divergence == 0.0
    assert result.vlm_only == 0


def test_blank_page_fabrication_is_caught():
    result = compare_page(
        witness("", ink=0.0),
        vlm("The barometric readings were corrected for temperature using standard tables"),
    )
    assert kinds(result) == {BLANK_PAGE_FABRICATION}
    assert result.divergence == 1.0
    assert result.findings[0].severity == 1.0
    assert result.findings[0].bbox is None  # whole page is the evidence


def test_blank_page_with_little_engine_text_is_not_flagged():
    """A page number or stray header on a blank page is not a fabrication."""
    result = compare_page(witness("", ink=0.0), vlm("iv"))
    assert result.findings == []


def test_reordered_columns_are_not_flagged():
    """The single most important non-detection in the suite.

    Multi-column pages routinely come back from VLM engines in a different
    reading order than Tesseract uses. The content is identical; only the
    sequence differs. Flagging this would make the tool useless in practice.
    """
    left = "The northern division comprised four stations of which two were established"
    right = "The southern division comprised only three stations the fourth having been abandoned"
    result = compare_page(witness(left + " " + right), vlm(right + " " + left))
    assert result.findings == []
    assert result.vlm_only == 0
    assert result.divergence == 0.0


def test_inserted_sentence_is_unsupported():
    fabrication = (
        "The commission further resolved that a permanent magnetic observatory "
        "be established at Cape Ellery next season"
    )
    result = compare_page(witness(PROSE), vlm(PROSE + " " + fabrication))
    assert UNSUPPORTED_TEXT in kinds(result)
    finding = next(f for f in result.findings if f.kind == UNSUPPORTED_TEXT)
    assert "magnetic" in finding.vlm_text
    assert finding.n_tokens >= 8
    assert result.divergence > 0


def test_dropped_paragraph_is_caught():
    dropped = (
        "The self registering apparatus failed twice during December on both occasions "
        "owing to the freezing of the float chamber"
    )
    result = compare_page(witness(PROSE + " " + dropped), vlm(PROSE))
    assert DROPPED_TEXT in kinds(result)
    finding = next(f for f in result.findings if f.kind == DROPPED_TEXT)
    assert "registering" in finding.witness_text
    assert finding.bbox is not None  # dropped text has real coordinates


def test_ocr_noise_is_not_called_fabrication():
    """Glyph-level misreads are disagreements, not inventions."""
    original = "barometer theodolite chronometers observatory instruments"
    misread = "barorneter theodolile chronorneters observalory instrurnents"
    result = compare_page(witness(original), vlm(misread))
    assert UNSUPPORTED_TEXT not in kinds(result)
    assert result.vlm_only == 0


def test_single_word_difference_below_min_run_is_ignored():
    result = compare_page(witness(PROSE), vlm(PROSE + " zzzz"))
    assert result.findings == []


def test_min_run_is_configurable():
    extra = "alpha bravo charlie"
    default = compare_page(witness(PROSE), vlm(PROSE + " " + extra))
    strict = compare_page(witness(PROSE), vlm(PROSE + " " + extra), Settings(min_run=10))
    assert UNSUPPORTED_TEXT in kinds(default)
    assert strict.findings == []


def test_low_witness_confidence_hedges_findings():
    fabrication = "a permanent magnetic observatory established at Cape Ellery next season"
    strong = compare_page(witness(PROSE, conf=95), vlm(PROSE + " " + fabrication))
    weak = compare_page(witness(PROSE, conf=45), vlm(PROSE + " " + fabrication))
    assert weak.witness_quality == "low"
    assert strong.witness_quality == "ok"
    weak_finding = next(f for f in weak.findings if f.kind == UNSUPPORTED_TEXT)
    strong_finding = next(f for f in strong.findings if f.kind == UNSUPPORTED_TEXT)
    assert weak_finding.severity < strong_finding.severity
    assert weak_finding.note  # the report must say the witness was shaky


def test_words_below_min_conf_are_excluded_from_comparison():
    """Junk the witness itself does not believe must not generate dropped-text claims."""
    page = witness(PROSE)
    for word in page.words[:10]:
        word.conf = 12.0
    result = compare_page(page, vlm(PROSE))
    assert DROPPED_TEXT not in kinds(result)


def test_engine_emitting_nothing_reports_dropped_not_fabrication():
    result = compare_page(witness(PROSE), vlm(""))
    assert kinds(result) == {DROPPED_TEXT}
    assert result.divergence == 0.0  # no AI words at all, so nothing unsupported


def test_markdown_scaffolding_is_not_treated_as_text():
    page = witness("Station Marlow reported four readings")
    markdown = "## Station Marlow\n\n| Station | Marlow |\n|---|---|\n\n**reported** *four* readings"
    result = compare_page(page, vlm(markdown))
    assert result.findings == []


def test_image_placeholders_do_not_create_findings():
    page = witness("Figure two shows the tidal series")
    result = compare_page(page, vlm("![](_page_3_Figure_1.jpeg)\n\nFigure two shows the tidal series"))
    assert result.findings == []


def test_divergence_is_share_of_engine_words():
    result = compare_page(witness("alpha bravo charlie"), vlm("alpha bravo charlie delta echo foxtrot"))
    assert result.vlm_words == 6
    assert result.vlm_only == 3
    assert result.divergence == pytest.approx(0.5)


def test_findings_are_ordered_by_severity():
    fabrication = "a permanent magnetic observatory established at Cape Ellery next season indeed"
    dropped = "the field notebooks were lost when the supply vessel foundered off shoals"
    result = compare_page(witness(PROSE + " " + dropped), vlm(PROSE + " " + fabrication))
    severities = [f.severity for f in result.findings]
    assert severities == sorted(severities, reverse=True)
