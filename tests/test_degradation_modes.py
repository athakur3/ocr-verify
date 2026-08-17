"""Golden regression test for the two real degradation modes the archival wild
hunt exposed (study/wild/README.md): hand-lettered display type and uneven
mimeograph ink. Witness fix (a) (commit 018ea33, the tight local-confidence
window in align.py) was validated only against one downloaded document; this
corpus (study/degradation_modes/make_modes_corpus.py) makes that check
reproducible and puts it in the suite instead of a one-off probe script.

Each page's "engine transcript" is set to the exact ground truth the page was
rendered from — standing in for an engine that made no error at all. Any
finding ocr-verify raises here is caused purely by the witness (Tesseract)
struggling with the degraded image, not by any real engine error. Note: the
hedge fix (a) adds does not remove a finding or its kind (both stay in
ACCUSATORY_KINDS by design — see study/wild/README.md's "Follow-up" section);
it lowers severity and attaches a note. So the regression pin is the note and
severity delta between the tight window (fix (a), the default) and the old
wide window, not the absence of a finding.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ocr_verify.align import Settings, compare_page
from ocr_verify.model import UNSUPPORTED_TEXT, VlmPage, WHOLESALE_DISAGREEMENT
from ocr_verify.render import render_pdf
from ocr_verify.witness import run_witness

ROOT = Path(__file__).parent.parent / "study" / "degradation_modes"
PDF = ROOT / "modes.pdf"
TRUTH = ROOT / "ground_truth.json"

pytestmark = [
    pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed"),
    pytest.mark.skipif(not PDF.exists(), reason="run study/degradation_modes/make_modes_corpus.py first"),
]


@pytest.fixture(scope="module")
def witnesses(tmp_path_factory):
    work = tmp_path_factory.mktemp("modes_render")
    images = render_pdf(PDF, work, dpi=200)
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))["pages"]
    out = {}
    for entry, image in zip(truth, images):
        index = entry["page"] - 1
        out[entry["kind"]] = (run_witness(image, index), entry["text"])
    return out


def test_hand_lettered_title_is_hedged_by_the_tight_window_not_the_wide_one(witnesses):
    """The FAR EAST SPOTLIGHT failure mode, reproduced synthetically: a warped
    masthead title above a clean paragraph. The clean body keeps the *page*
    mean confidence healthy, so only a genuinely local window catches the
    title's own low confidence — exactly the distinction fix (a) (context=1)
    was built for and the old width (context=8) missed on the real document.
    """
    witness, text = witnesses["hand_lettered_cover"]
    vlm = VlmPage(index=0, text=text, source="ground-truth")

    tight = compare_page(witness, vlm, Settings())  # fix (a): local_context=1
    wide = compare_page(witness, vlm, Settings(local_context=8))  # pre-fix width

    tight_finding = next(f for f in tight.findings if f.kind == UNSUPPORTED_TEXT)
    wide_finding = next(f for f in wide.findings if f.kind == UNSUPPORTED_TEXT)

    assert tight_finding.note, "the tight window must hedge the title finding"
    assert not wide_finding.note, "the wide window must NOT hedge it (that is the bug fix (a) closed)"
    assert tight_finding.severity < wide_finding.severity


def test_mimeograph_body_folds_to_a_hedge_not_an_itemized_accusation(witnesses):
    """Blotchy uneven ink density degrades enough of the page that the
    existing wholesale-disagreement fold — a different, already-shipped guard
    — is what keeps this from becoming an itemized fabrication accusation.
    Pins that guard against a mode the corpus never previously covered."""
    witness, text = witnesses["mimeograph_body"]
    vlm = VlmPage(index=0, text=text, source="ground-truth")

    result = compare_page(witness, vlm, Settings())
    kinds = {f.kind for f in result.findings}

    assert kinds == {WHOLESALE_DISAGREEMENT}
    assert result.verified is False
