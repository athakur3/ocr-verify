"""Ingest tests.

Most of these assert on *refusals*. Page indices are how every finding is
addressed, so an ingest that quietly misaligns pages produces a report that is
confidently wrong on every row — far worse than one that stops and explains.
"""

from __future__ import annotations

import json

import pytest

from ocr_verify.cli import parse_pages
from ocr_verify.ingest import IngestError, load_vlm_output


def write(dir_path, name, text):
    path = dir_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestPerPageFiles:
    def test_numbered_files_load_in_order(self, tmp_path):
        for i in (1, 2, 3):
            write(tmp_path, f"page_{i:03d}.md", f"page {i} body")
        pages = load_vlm_output(tmp_path, 3)
        assert [p.index for p in pages] == [0, 1, 2]
        assert "page 2 body" in pages[1].text

    def test_zero_based_numbering_accepted(self, tmp_path):
        for i in (0, 1):
            write(tmp_path, f"{i}.txt", f"body {i}")
        pages = load_vlm_output(tmp_path, 2)
        assert [p.index for p in pages] == [0, 1]

    def test_unpadded_numbers_sort_numerically_not_lexically(self, tmp_path):
        for i in (1, 2, 10):
            write(tmp_path, f"page{i}.md", f"body {i}")
        pages = load_vlm_output(tmp_path, 10)
        assert pages[-1].index == 9
        assert "body 10" in pages[-1].text

    def test_page_count_mismatch_is_fatal(self, tmp_path):
        for i in (1, 2):
            write(tmp_path, f"page_{i}.md", "body")
        with pytest.raises(IngestError, match="page-count mismatch"):
            load_vlm_output(tmp_path, 5)

    def test_unnumbered_multiple_files_refuses_to_guess(self, tmp_path):
        write(tmp_path, "intro.md", "a")
        write(tmp_path, "body.md", "b")
        write(tmp_path, "outro.md", "c")
        with pytest.raises(IngestError, match="could not read page numbers"):
            load_vlm_output(tmp_path, 3)


class TestSingleFile:
    def test_single_page_document(self, tmp_path):
        path = write(tmp_path, "doc.md", "the whole document")
        pages = load_vlm_output(path, 1)
        assert len(pages) == 1 and pages[0].index == 0

    def test_multipage_without_markers_refuses(self, tmp_path):
        path = write(tmp_path, "doc.md", "no markers here")
        with pytest.raises(IngestError, match="no page-break marker"):
            load_vlm_output(path, 3)

    def test_multipage_with_markers_splits(self, tmp_path):
        path = write(tmp_path, "doc.md", "one\x0ctwo\x0cthree")
        pages = load_vlm_output(path, 3)
        assert len(pages) == 3 and "two" in pages[1].text

    def test_marker_directory_with_one_markdown_file(self, tmp_path):
        write(tmp_path, "book/book.md", "single page body")
        write(tmp_path, "book/book_meta.json", "{}")
        pages = load_vlm_output(tmp_path, 1)
        assert len(pages) == 1


class TestJsonl:
    def test_natural_text_field(self, tmp_path):
        lines = [
            json.dumps({"page": 1, "natural_text": "first"}),
            json.dumps({"page": 2, "natural_text": "second"}),
        ]
        path = write(tmp_path, "out.jsonl", "\n".join(lines))
        pages = load_vlm_output(path, 2)
        assert [p.index for p in pages] == [0, 1]
        assert pages[1].text == "second"

    def test_out_of_order_records_sorted_by_page(self, tmp_path):
        lines = [
            json.dumps({"page": 2, "text": "second"}),
            json.dumps({"page": 1, "text": "first"}),
        ]
        path = write(tmp_path, "out.jsonl", "\n".join(lines))
        pages = load_vlm_output(path, 2)
        assert pages[0].text == "first"

    def test_missing_text_field_is_an_error(self, tmp_path):
        path = write(tmp_path, "out.jsonl", json.dumps({"page": 1, "blob": "x"}))
        with pytest.raises(IngestError, match="no text field"):
            load_vlm_output(path, 1)

    def test_malformed_json_names_the_line(self, tmp_path):
        path = write(tmp_path, "out.jsonl", '{"text": "ok"}\nnot json\n')
        with pytest.raises(IngestError, match=":2"):
            load_vlm_output(path, 2)


class TestJson:
    def test_pages_key(self, tmp_path):
        path = write(tmp_path, "out.json", json.dumps({"pages": [{"text": "a"}, {"text": "b"}]}))
        pages = load_vlm_output(path, 2)
        assert len(pages) == 2

    def test_bare_list_of_strings(self, tmp_path):
        path = write(tmp_path, "out.json", json.dumps(["a", "b", "c"]))
        assert len(load_vlm_output(path, 3)) == 3


class TestMissing:
    def test_missing_path(self, tmp_path):
        with pytest.raises(IngestError, match="not found"):
            load_vlm_output(tmp_path / "nope", 1)

    def test_empty_directory(self, tmp_path):
        with pytest.raises(IngestError, match="no .md"):
            load_vlm_output(tmp_path, 1)


class TestParsePages:
    def test_single_and_list(self):
        assert parse_pages("1", 10) == [0]
        assert parse_pages("1,3,5", 10) == [0, 2, 4]

    def test_range(self):
        assert parse_pages("2-4", 10) == [1, 2, 3]

    def test_mixed_deduplicated_and_sorted(self):
        assert parse_pages("5,1-3,2", 10) == [0, 1, 2, 4]

    def test_none_means_all(self):
        assert parse_pages(None, 10) is None

    def test_out_of_range_rejected(self):
        with pytest.raises(ValueError, match="out of range"):
            parse_pages("11", 10)

    def test_backwards_range_rejected(self):
        with pytest.raises(ValueError, match="backwards"):
            parse_pages("5-2", 10)

    def test_garbage_rejected(self):
        with pytest.raises(ValueError, match="bad page"):
            parse_pages("abc", 10)
