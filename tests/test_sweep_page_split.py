"""Guard the sweep scorers against silently unscorable engine output.

`study/sweep/pagesplit.py` exists because the previous copy-pasted splitters returned an
empty dict when they could not split the engine output, and the scorers then reported
every page as 100% omitted and 0 fabricated — a wrong answer shaped exactly like a real
finding. It happened twice, both times because `marker_single` ran without
`--paginate_output`. These tests fail the build on that shape instead.

The last test also checks the committed sweep artifacts themselves, so a Marker capture
made without page markers cannot be committed and scored as total content loss.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SWEEP = Path(__file__).parent.parent / "study" / "sweep"
if str(SWEEP) not in sys.path:
    sys.path.insert(0, str(SWEEP))

from pagesplit import SweepOutputError, marker_pages, mineru_pages  # noqa: E402

PAGINATED_MD = "Page one text.\n\n{0}------------------------------------------------\nPage two text.\n\n{1}------------------------------------------------\n"
UNPAGINATED_MD = "Page one text.\n\nPage two text, with no page markers anywhere.\n"


def test_marker_pages_splits_on_page_markers(tmp_path):
    md = tmp_path / "sweep.md"
    md.write_text(PAGINATED_MD, "utf-8")

    pages = marker_pages(md, expected_pages=2)

    assert sorted(pages) == [0, 1]
    assert "Page two text." in pages[0]


def test_marker_pages_raises_when_output_has_no_page_markers(tmp_path):
    md = tmp_path / "sweep.md"
    md.write_text(UNPAGINATED_MD, "utf-8")

    with pytest.raises(SweepOutputError) as excinfo:
        marker_pages(md, expected_pages=2)

    # The message has to name the actual cause: this is the mistake it exists to catch.
    assert "--paginate_output" in str(excinfo.value)


def test_marker_pages_warns_but_scores_when_only_some_pages_are_missing(tmp_path, capsys):
    md = tmp_path / "sweep.md"
    md.write_text(PAGINATED_MD, "utf-8")

    pages = marker_pages(md, expected_pages=4)

    assert sorted(pages) == [0, 1]          # an engine losing whole pages is a real result
    assert "[2, 3]" in capsys.readouterr().err


def test_mineru_pages_groups_text_by_page_index(tmp_path):
    cl = tmp_path / "x_content_list.json"
    cl.write_text(json.dumps([
        {"page_idx": 0, "text": "first"},
        {"page_idx": 0, "text": "second"},
        {"page_idx": 1, "text": "third"},
        {"page_idx": 1, "text": "   "},
        {"page_idx": 1, "type": "image"},
    ]), "utf-8")

    pages = mineru_pages(cl, expected_pages=2)

    assert pages == {0: "first\n\nsecond", 1: "third"}


@pytest.mark.parametrize("items", [[], [{"page_idx": 0, "type": "image"}]], ids=["empty", "no-text"])
def test_mineru_pages_raises_when_no_page_has_text(tmp_path, items):
    cl = tmp_path / "x_content_list.json"
    cl.write_text(json.dumps(items), "utf-8")

    with pytest.raises(SweepOutputError):
        mineru_pages(cl, expected_pages=2)


SWEEP_CAPTURES = [
    pytest.param("marker_out/sweep/sweep.md", "ground_truth.json", id="sweep"),
    pytest.param("marker_out2/sweep2/sweep2.md", "ground_truth2.json", id="sweep2"),
    pytest.param("marker_out3/sweep3/sweep3.md", "ground_truth3.json", id="sweep3"),
    pytest.param("marker_out2_bisect/sweep2_bisect/sweep2_bisect.md",
                 "sweep2_bisect_ground_truth.json", id="sweep2-bisect"),
    pytest.param("marker_out3_bisect/sweep3_bisect/sweep3_bisect.md",
                 "sweep3_bisect_ground_truth.json", id="sweep3-bisect"),
]


@pytest.mark.parametrize("md_rel,truth_rel", SWEEP_CAPTURES)
def test_committed_marker_captures_are_paginated(md_rel, truth_rel):
    """Every committed Marker capture must still split into the pages it was scored on."""
    md, truth_path = SWEEP / md_rel, SWEEP / truth_rel
    if not md.exists():                      # heavy captures are gitignored in some clones
        pytest.skip(f"{md_rel} not present")

    expected = len(json.loads(truth_path.read_text("utf-8"))["pages"])

    assert sorted(marker_pages(md, expected_pages=expected)) == list(range(expected))
