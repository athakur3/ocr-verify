"""End-to-end golden tests over the fixture corpus.

These run the real pipeline — rasterize, Tesseract, align, report — and pin the
documented behaviour of each fixture page. If a change to the matching rules
makes the tool cry wolf on the reordered-columns page, or go quiet on the blank
page, these fail.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ocr_verify.align import Settings, compare_page
from ocr_verify.cli import main
from ocr_verify.ingest import load_vlm_output
from ocr_verify.model import (
    BLANK_PAGE_FABRICATION,
    DROPPED_TEXT,
    KIND_LABELS,
    UNSUPPORTED_TEXT,
    PageResult,
)
from ocr_verify.render import render_pdf
from ocr_verify.witness import run_witness

FIXTURES = Path(__file__).parent.parent / "fixtures"
PDF = FIXTURES / "sample.pdf"
ENGINE = FIXTURES / "engine_output"

pytestmark = [
    pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed"),
    pytest.mark.skipif(not PDF.exists(), reason="run fixtures/make_fixtures.py first"),
]


@pytest.fixture(scope="module")
def results(tmp_path_factory) -> dict[int, PageResult]:
    work = tmp_path_factory.mktemp("render")
    images = render_pdf(PDF, work, dpi=200)
    vlm_pages = {p.index: p for p in load_vlm_output(ENGINE, len(images))}
    cfg = Settings()
    out: dict[int, PageResult] = {}
    for index, image in enumerate(images):
        witness = run_witness(image, index)
        out[index + 1] = compare_page(witness, vlm_pages[index], cfg)
    return out


def kinds(result: PageResult) -> set[str]:
    return {f.kind for f in result.findings}


def test_page_1_clean_agreement_is_silent(results):
    page = results[1]
    assert page.findings == []
    assert page.divergence == 0.0
    assert page.witness_words > 90  # the witness actually read the page


def test_page_2_blank_page_fabrication(results):
    page = results[2]
    assert kinds(page) == {BLANK_PAGE_FABRICATION}
    assert page.ink_ratio < 0.001
    assert page.witness_words == 0
    assert page.vlm_words > 50
    assert page.divergence == 1.0
    finding = page.findings[0]
    assert finding.severity == 1.0
    assert finding.bbox is None  # the whole page is the evidence
    assert "barometric" in finding.vlm_text.lower()


def test_page_3_dropped_paragraph(results):
    page = results[3]
    assert DROPPED_TEXT in kinds(page)
    assert page.vlm_only == 0  # nothing was invented, only omitted
    finding = next(f for f in page.findings if f.kind == DROPPED_TEXT)
    assert "self-registering" in finding.witness_text.lower()
    assert finding.bbox is not None
    x0, y0, x1, y1 = finding.bbox
    assert x1 > x0 and y1 > y0


def test_page_4_reordered_columns_stay_silent(results):
    """The load-bearing non-detection.

    Page 4's two columns are emitted right-to-left by the engine. Every word is
    correct; only the order differs. A tool that flags this is a tool nobody
    keeps installed.
    """
    page = results[4]
    assert page.findings == []
    assert page.vlm_only == 0
    assert page.divergence == 0.0


def test_page_5_inserted_sentence_is_unsupported(results):
    page = results[5]
    assert UNSUPPORTED_TEXT in kinds(page)
    finding = next(f for f in page.findings if f.kind == UNSUPPORTED_TEXT)
    assert "magnetic observatory" in finding.vlm_text.lower()
    assert finding.bbox is not None  # anchored to the surrounding agreed text
    assert finding.context_before or finding.context_after


def test_only_the_three_intended_pages_are_flagged(results):
    flagged = {n for n, page in results.items() if page.findings}
    assert flagged == {2, 3, 5}


class TestCli:
    def test_writes_report_and_json(self, tmp_path):
        html = tmp_path / "report.html"
        js = tmp_path / "report.json"
        code = main([str(PDF), str(ENGINE), "-o", str(html), "--json", str(js), "-q"])
        assert code == 0
        body = html.read_text(encoding="utf-8")
        assert body.startswith("<!doctype html>")
        assert "data:image/png;base64," in body  # evidence crops are embedded
        assert "Blank-page fabrication" in body
        assert js.exists()

    def test_writes_sarif(self, tmp_path, results):
        html = tmp_path / "report.html"
        sarif_path = tmp_path / "report.sarif"
        code = main([str(PDF), str(ENGINE), "-o", str(html), "--sarif", str(sarif_path), "-q"])
        assert code == 0

        data = json.loads(sarif_path.read_text(encoding="utf-8"))
        assert data["version"] == "2.1.0"
        run = data["runs"][0]
        assert run["tool"]["driver"]["name"] == "ocr-verify"
        rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
        assert rule_ids == set(KIND_LABELS)

        sarif_results = run["results"]
        total_findings = sum(len(page.findings) for page in results.values())
        assert len(sarif_results) == total_findings
        assert {r["ruleId"] for r in sarif_results} <= rule_ids
        assert {r["level"] for r in sarif_results} <= {"error", "warning", "note"}

        blank_finding = next(f for f in results[2].findings if f.kind == BLANK_PAGE_FABRICATION)
        page_2_blank = next(
            r for r in sarif_results
            if r["ruleId"] == BLANK_PAGE_FABRICATION and r["properties"]["page"] == 2
        )
        # An accusatory finding is only downgraded to "warning" when hedged (has a
        # note) — same distinction the report itself draws (report.py's note paragraph).
        assert page_2_blank["level"] == ("warning" if blank_finding.note else "error")
        assert page_2_blank["locations"][0]["physicalLocation"]["region"]["startLine"] == 2

    def test_report_is_self_contained(self, tmp_path):
        html = tmp_path / "report.html"
        main([str(PDF), str(ENGINE), "-o", str(html), "-q"])
        body = html.read_text(encoding="utf-8")
        for remote in ("http://", "https://", "<script"):
            assert remote not in body

    def test_fail_on_gates_for_ci(self, tmp_path):
        html = tmp_path / "report.html"
        args = [str(PDF), str(ENGINE), "-o", str(html), "-q"]
        assert main(args + ["--fail-on", "0.5"]) == 0
        assert main(args + ["--fail-on", "0.01"]) == 1

    def test_page_subset(self, tmp_path):
        html = tmp_path / "report.html"
        js = tmp_path / "report.json"
        code = main([str(PDF), str(ENGINE), "--pages", "2", "-o", str(html), "--json", str(js), "-q"])
        assert code == 0
        import json

        data = json.loads(js.read_text())
        assert [p["page"] for p in data["pages"]] == [2]
        assert data["pages"][0]["findings"][0]["kind"] == BLANK_PAGE_FABRICATION

    def test_missing_pdf_exits_2(self, tmp_path):
        assert main([str(tmp_path / "nope.pdf"), str(ENGINE), "-q"]) == 2

    def test_bad_page_spec_exits_2(self, tmp_path):
        assert main([str(PDF), str(ENGINE), "--pages", "99", "-q"]) == 2

    def test_missing_pdf_and_engine_output_exits_2(self):
        assert main(["-q"]) == 2


class TestBatch:
    def _manifest(self, tmp_path, n, break_second=False):
        entries = []
        for i in range(n):
            entries.append({
                # entry 1 of a break_second manifest points at a PDF that doesn't
                # exist, forcing that entry's own main() call to EXIT_ERROR — proof
                # the aggregate reflects the worst per-entry outcome, not just the
                # first or last.
                "pdf": str(PDF) if not (break_second and i == 1) else str(tmp_path / "nope.pdf"),
                "engine_output": str(ENGINE),
                "out": str(tmp_path / f"{i}-report.html"),
                "json": str(tmp_path / f"{i}-report.json"),
            })
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps(entries), encoding="utf-8")
        return manifest

    def test_batch_runs_every_entry_and_writes_summary(self, tmp_path):
        manifest = self._manifest(tmp_path, 2)
        summary = tmp_path / "summary.json"
        code = main(["--batch", str(manifest), "--json", str(summary), "-q"])
        assert code == 0
        for i in range(2):
            assert (tmp_path / f"{i}-report.html").exists()
            assert (tmp_path / f"{i}-report.json").exists()

        data = json.loads(summary.read_text(encoding="utf-8"))
        rows = data["batch"]
        assert len(rows) == 2
        assert all(r["exit_code"] == 0 for r in rows)
        assert all(r["pages_total"] == 5 for r in rows)
        assert all(r["pages_flagged"] == 3 for r in rows)  # matches pages 2, 3, 5 above

    def test_batch_worst_exit_code_wins(self, tmp_path):
        manifest = self._manifest(tmp_path, 2, break_second=True)
        summary = tmp_path / "summary.json"
        code = main(["--batch", str(manifest), "--json", str(summary), "-q"])
        assert code == 2  # EXIT_ERROR, even though entry 0 alone succeeds

        rows = json.loads(summary.read_text(encoding="utf-8"))["batch"]
        assert [r["exit_code"] for r in rows] == [0, 2]

    def test_batch_rejects_pages_flag(self, tmp_path):
        manifest = self._manifest(tmp_path, 1)
        assert main(["--batch", str(manifest), "--pages", "2", "-q"]) == 2

    def test_batch_missing_manifest_exits_2(self, tmp_path):
        assert main(["--batch", str(tmp_path / "nope.json"), "-q"]) == 2

    def test_batch_entry_missing_engine_output_exits_2(self, tmp_path):
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps([{"pdf": str(PDF)}]), encoding="utf-8")
        assert main(["--batch", str(manifest), "-q"]) == 2
