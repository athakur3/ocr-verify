"""Mechanically gate the project's headline claim: on the synthetic corpus,
ocr-verify holds precision=1.00 and recall=1.00 against every captured engine
output. Until now this number was asserted only in prose (README, study
writeups) and re-verified by hand each block via `study/score.py`'s printed
output — a real regression here would only be caught if someone happened to
read the number. This test makes it fail the build instead.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

STUDY = Path(__file__).parent.parent / "study"
if str(STUDY) not in sys.path:
    sys.path.insert(0, str(STUDY))

import score  # noqa: E402  (needs STUDY on sys.path first)

pytestmark = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")

ENGINE_OUTPUTS = [
    pytest.param(STUDY / "marker_out" / "corpus", id="marker"),
    pytest.param(STUDY / "mineru_out" / "pages", id="mineru"),
]


@pytest.mark.parametrize("engine_output", ENGINE_OUTPUTS)
def test_synthetic_corpus_precision_recall_is_1(engine_output):
    summary = score.score(engine_output)["summary"]
    assert summary["precision"] == 1.0, f"precision regressed to {summary['precision']}"
    assert summary["recall"] == 1.0, f"recall regressed to {summary['recall']}"
