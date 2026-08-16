"""Loading the AI engine's output.

Every VLM-OCR tool writes something slightly different — Marker and MinerU emit a
markdown file per document, olmOCR emits JSONL, plenty of in-house pipelines emit
a directory of per-page text. All of them are accepted here, but page alignment is
never guessed: if page boundaries cannot be established unambiguously, this module
raises and tells the caller how to fix it. A silently misaligned page index would
turn the entire report into confident nonsense.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .model import VlmPage
from .normalize import split_pages

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".text"}
_TRAILING_INT = re.compile(r"(\d+)(?!.*\d)")


class IngestError(RuntimeError):
    pass


def load_vlm_output(path: Path, expected_pages: int) -> list[VlmPage]:
    """Load AI-engine output as one text blob per page index (0-based)."""
    if not path.exists():
        raise IngestError(f"AI-engine output not found: {path}")
    if path.is_dir():
        return _load_dir(path, expected_pages)
    if path.suffix.lower() == ".jsonl":
        return _load_jsonl(path, expected_pages)
    if path.suffix.lower() == ".json":
        return _load_json(path, expected_pages)
    return _load_single_text(path, expected_pages)


def _load_dir(path: Path, expected_pages: int) -> list[VlmPage]:
    per_page = _numbered_text_files(path)
    if per_page:
        return _from_numbered_files(per_page, expected_pages)

    candidates = sorted(
        [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES],
        key=lambda p: (len(p.parts), p.name),
    )
    jsonl = sorted(p for p in path.rglob("*.jsonl") if p.is_file())
    if jsonl:
        return _load_jsonl(jsonl[0], expected_pages)
    if not candidates:
        raise IngestError(
            f"no .md/.txt/.jsonl files under {path}\n"
            "Point --engine-output at the file or directory your OCR engine wrote."
        )
    if len(candidates) == 1:
        return _load_single_text(candidates[0], expected_pages)

    # Several text files but no usable page numbering.
    names = ", ".join(p.name for p in candidates[:5])
    raise IngestError(
        f"found {len(candidates)} text files under {path} ({names}...) but could not "
        "read page numbers from their names.\n"
        "Rename them so each ends in its page number (page_001.md, 12.txt), or pass a "
        "single file containing page-break markers."
    )


def _numbered_text_files(path: Path) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for p in sorted(path.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        m = _TRAILING_INT.search(p.stem)
        if not m:
            return []
        found.append((int(m.group(1)), p))
    if len(found) < 2:
        return []
    numbers = [n for n, _ in found]
    if len(set(numbers)) != len(numbers):
        return []
    return sorted(found)


def _from_numbered_files(found: list[tuple[int, Path]], expected_pages: int) -> list[VlmPage]:
    numbers = [n for n, _ in found]
    base = min(numbers)
    if base not in (0, 1):
        raise IngestError(
            f"page numbers in filenames start at {base}; expected 0 or 1. "
            "Rename the files so numbering starts at page 1."
        )
    pages: list[VlmPage] = []
    for number, file in found:
        idx = number - base
        pages.append(VlmPage(index=idx, text=file.read_text(encoding="utf-8", errors="replace"),
                             source=file.name))
    _check_count(pages, expected_pages, f"{len(found)} per-page files")
    return pages


def _load_single_text(path: Path, expected_pages: int) -> list[VlmPage]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if expected_pages == 1:
        return [VlmPage(index=0, text=text, source=path.name)]

    chunks = split_pages(text)
    if chunks is None:
        raise IngestError(
            f"{path.name} is a single document but the PDF has {expected_pages} pages, and it "
            "contains no page-break marker this tool recognises.\n"
            "Either re-run your OCR engine with per-page output (a directory of page_001.md "
            "files), or verify one page at a time with --pages N."
        )
    pages = [VlmPage(index=i, text=t, source=path.name) for i, t in enumerate(chunks)]
    _check_count(pages, expected_pages, f"{len(chunks)} chunks split on page markers")
    return pages


def _load_jsonl(path: Path, expected_pages: int) -> list[VlmPage]:
    records = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise IngestError(f"{path.name}:{lineno} is not valid JSON: {exc}") from exc
    pages = _pages_from_records(records, path.name)
    _check_count(pages, expected_pages, f"{len(pages)} JSONL records")
    return pages


def _load_json(path: Path, expected_pages: int) -> list[VlmPage]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(data, dict):
        for key in ("pages", "results", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            raise IngestError(
                f"{path.name} is a JSON object with no 'pages'/'results'/'data' list."
            )
    if not isinstance(data, list):
        raise IngestError(f"{path.name} must contain a list of page records.")
    pages = _pages_from_records(data, path.name)
    _check_count(pages, expected_pages, f"{len(pages)} JSON records")
    return pages


_TEXT_KEYS = ("natural_text", "text", "markdown", "md", "content", "page_text")
_PAGE_KEYS = ("page", "page_num", "page_number", "page_idx", "index", "id")


def _pages_from_records(records: list, source: str) -> list[VlmPage]:
    pages: list[VlmPage] = []
    explicit: list[int] = []
    for i, rec in enumerate(records):
        if isinstance(rec, str):
            pages.append(VlmPage(index=i, text=rec, source=source))
            continue
        if not isinstance(rec, dict):
            raise IngestError(f"{source}: record {i} is neither a string nor an object.")
        text = next((rec[k] for k in _TEXT_KEYS if isinstance(rec.get(k), str)), None)
        if text is None:
            raise IngestError(
                f"{source}: record {i} has no text field "
                f"(looked for {', '.join(_TEXT_KEYS)})."
            )
        num = next((rec[k] for k in _PAGE_KEYS if isinstance(rec.get(k), int)), None)
        if num is not None:
            explicit.append(num)
        pages.append(VlmPage(index=i, text=text, source=source))

    if explicit and len(explicit) == len(pages):
        base = min(explicit)
        if base in (0, 1):
            for page, num in zip(pages, explicit):
                page.index = num - base
            pages.sort(key=lambda p: p.index)
    return pages


def _check_count(pages: list[VlmPage], expected: int, described: str) -> None:
    highest = max((p.index for p in pages), default=-1) + 1
    if highest != expected:
        raise IngestError(
            f"page-count mismatch: the PDF has {expected} pages but the AI-engine output gave "
            f"{described} (highest page index {highest}).\n"
            "Verifying misaligned pages produces meaningless findings, so this is fatal. "
            "Use --pages to verify a subset, or fix the output so pages correspond 1:1."
        )
