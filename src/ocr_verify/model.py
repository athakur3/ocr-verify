"""Core data model.

Deliberately plain dataclasses: every number in the HTML report must be traceable
back to one of these fields, and every finding must carry the evidence (image
region + both readings) needed for a human to overrule it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

BBox = tuple[int, int, int, int]  # x0, y0, x1, y1 in witness-image pixels


@dataclass
class Word:
    """One word as read by the witness engine."""

    text: str  # verbatim, as shown to the user
    norm: str  # normalized, used for matching
    conf: float  # 0-100 from Tesseract
    bbox: BBox
    line_key: tuple[int, int, int]  # (block, paragraph, line) from Tesseract TSV


@dataclass
class WitnessPage:
    index: int  # 0-based page index
    width: int
    height: int
    words: list[Word]
    ink_ratio: float  # fraction of non-white pixels; drives blank-page detection
    image: Path  # rendered page PNG on disk
    # Noise-robust ink fraction; computed lazily, only for pages where the
    # blind-witness hedge needs grading. None = not yet measured.
    ink_robust: float | None = None

    def confident_words(self, min_conf: float) -> list[Word]:
        return [w for w in self.words if w.conf >= min_conf]


@dataclass
class VlmPage:
    index: int
    text: str
    source: str  # where this page's text came from, for the report's provenance line


# Finding kinds. The first four are verdicts, ordered by how strongly they
# indicate fabrication. The last two are confessions: places where the witness
# cannot support a verdict either way, reported as prompts to look rather than
# as accusations — because an accusation the evidence cannot carry is precisely
# the false positive that gets a verification tool uninstalled.
BLANK_PAGE_FABRICATION = "blank_page_fabrication"
UNSUPPORTED_TEXT = "unsupported_text"
DROPPED_TEXT = "dropped_text"
SUBSTITUTION = "substitution"
WHOLESALE_DISAGREEMENT = "wholesale_disagreement"
UNVERIFIABLE_PAGE = "unverifiable_page"

# Kinds that assert the AI engine emitted text the page cannot support.
ACCUSATORY_KINDS = frozenset({BLANK_PAGE_FABRICATION, UNSUPPORTED_TEXT})

KIND_LABELS = {
    BLANK_PAGE_FABRICATION: "Blank-page fabrication",
    UNSUPPORTED_TEXT: "Unsupported text",
    DROPPED_TEXT: "Dropped text",
    SUBSTITUTION: "Disagreement",
    WHOLESALE_DISAGREEMENT: "Wholesale disagreement",
    UNVERIFIABLE_PAGE: "Unverifiable page",
}

KIND_BLURBS = {
    BLANK_PAGE_FABRICATION: (
        "The witness engine found effectively no ink on this page, yet the AI engine "
        "emitted running text. This is the classic silent-fabrication signature."
    ),
    UNSUPPORTED_TEXT: (
        "The AI engine emitted words that appear nowhere in the witness reading of this "
        "page — not merely in a different order, but absent entirely."
    ),
    DROPPED_TEXT: (
        "The witness engine read words that appear nowhere in the AI engine's output. "
        "Usually a skipped line, column, or caption."
    ),
    SUBSTITUTION: (
        "Both engines read text here but disagree on the words. Often ordinary OCR "
        "noise on hard glyphs; occasionally a rewritten passage."
    ),
    WHOLESALE_DISAGREEMENT: (
        "The two readings diverge heavily in both directions at once. That pattern "
        "usually means the witness could not handle the page (severe skew, noise, or "
        "degradation) — but it is also what a wholesale rewrite would look like, so "
        "the page deserves a human glance. No itemized accusations are made."
    ),
    UNVERIFIABLE_PAGE: (
        "There is ink on this page but the witness engine could not read it, so the AI "
        "engine's output here can be neither supported nor disputed. Not an accusation — "
        "a gap in coverage."
    ),
}


@dataclass
class Finding:
    page: int
    kind: str
    severity: float  # 0-1, drives ordering in the report
    vlm_text: str  # what the AI engine said
    witness_text: str  # what the witness read in the same region
    bbox: BBox | None  # region to crop; None means the whole page
    note: str = ""  # honest caveat, e.g. low witness confidence
    n_tokens: int = 0  # size of the divergent run
    context_before: str = ""  # surrounding AI-engine text, so the run reads in situ
    context_after: str = ""

    @property
    def label(self) -> str:
        return KIND_LABELS[self.kind]


@dataclass
class PageResult:
    index: int
    divergence: float  # 0-1; share of AI-engine words the witness cannot support
    witness_words: int
    vlm_words: int
    matched: int
    vlm_only: int  # AI words with no witness support anywhere on the page
    witness_only: int  # witness words absent from the AI output
    ink_ratio: float
    witness_quality: str  # "ok" | "low" | "blind" — how far to trust the witness here
    # False when the witness could not cover this page well enough for its numbers
    # to serve as fabrication evidence (blind or wholesale-disagreement pages).
    # Such pages are excluded from the overall divergence used by --fail-on.
    verified: bool = True
    findings: list[Finding] = field(default_factory=list)
    image: Path | None = None
    width: int = 0
    height: int = 0

    @property
    def flagged(self) -> bool:
        return bool(self.findings)


@dataclass
class Report:
    pdf: Path
    vlm_source: Path
    pages: list[PageResult]
    dpi: int
    min_conf: float
    engine_label: str = "AI engine"
    generated: str = ""
    version: str = "0.1.0"

    @property
    def flagged_pages(self) -> list[PageResult]:
        return [p for p in self.pages if p.flagged]

    @property
    def findings(self) -> list[Finding]:
        return [f for p in self.pages for f in p.findings]
