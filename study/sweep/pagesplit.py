"""Per-page text recovery for the sweep scorers, with a loud failure on empty output.

Every `score_sweep*.py` recovers per-page text the same two ways: splitting Marker's
markdown on its `{N}-----` page markers, and grouping MinerU's `content_list.json` items
by `page_idx`. Both used to be copy-pasted into each scorer, and both returned an empty
dict when the engine output could not be split — after which `pages.get(idx, "")` scored
every page as 100% omitted and 0 fabricated.

That failure mode reads as a *result*, not as an error: a plausible table of numbers, with
total content loss at every ghost strength. It has already cost two blocks, both times
because `marker_single` ran without `--paginate_output`, which produces perfectly valid
markdown with no page markers in it. The helpers here raise `SweepOutputError` instead, so
the mistake fails the run rather than being written into a results JSON.

Missing *some* pages is a different case and is only warned about: an engine that emits
nothing for one heavily-degraded page is a legitimate (if notable) measurement, so the
scorers keep scoring it as omission.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PAGE_MARKER = re.compile(r"^\{(\d+)\}-+$", re.M)


class SweepOutputError(RuntimeError):
    """Engine output that cannot be split into pages at all — an infrastructure fault."""


def _warn_missing(pages: dict[int, str], expected_pages: int | None, source: Path) -> None:
    if not expected_pages:
        return
    missing = sorted(set(range(expected_pages)) - set(pages))
    if missing:
        print(
            f"warning: {source} has no text for page index(es) {missing} of "
            f"{expected_pages} — scoring them as fully omitted",
            file=sys.stderr,
        )


def marker_pages(md_path: Path, expected_pages: int | None = None) -> dict[int, str]:
    """Split Marker's markdown into {page_index: text} on its `{N}-----` markers."""
    parts = PAGE_MARKER.split(md_path.read_text("utf-8"))
    pages = {int(parts[i]): parts[i + 1] for i in range(1, len(parts), 2)}
    if not pages:
        raise SweepOutputError(
            f"{md_path} contains no {{N}}----- page markers, so it cannot be scored "
            f"per page. marker_single was almost certainly run without "
            f"--paginate_output; re-run it with that flag and score again."
        )
    _warn_missing(pages, expected_pages, md_path)
    return pages


def mineru_pages(content_list: Path, expected_pages: int | None = None) -> dict[int, str]:
    """Group MinerU's content_list.json text items into {page_index: text}."""
    items = json.loads(content_list.read_text("utf-8"))
    chunks: dict[int, list[str]] = {}
    for it in items:
        t = (it.get("text") or "").strip()
        if t:
            chunks.setdefault(it["page_idx"], []).append(t)
    pages = {idx: "\n\n".join(texts) for idx, texts in chunks.items()}
    if not pages:
        raise SweepOutputError(
            f"{content_list} yielded no text on any page, so there is nothing to score. "
            f"Check that the MinerU run completed and that this is the right "
            f"*_content_list.json for the corpus being scored."
        )
    _warn_missing(pages, expected_pages, content_list)
    return pages


def docling_pages(doc_json: Path, expected_pages: int | None = None) -> dict[int, str]:
    """Group Docling's `DoclingDocument` JSON text items into {page_index: text}.

    Docling's markdown export carries no page markers at all — the same shape as a
    `marker_single` run without `--paginate_output`, and unfixable by a flag — so the
    JSON export is the only per-page source. Its `texts[*].prov[*].page_no` is 1-based;
    the indices returned here are 0-based, matching `marker_pages`/`mineru_pages`.

    `texts` is the only text-bearing collection in the sweep captures (no tables, no
    picture captions). That is asserted rather than assumed: a capture whose `tables` or
    `pictures` are non-empty would be silently under-read here, so it raises instead.
    """
    doc = json.loads(doc_json.read_text("utf-8"))
    for collection in ("tables", "pictures"):
        if doc.get(collection):
            raise SweepOutputError(
                f"{doc_json} has {len(doc[collection])} item(s) in '{collection}', which "
                f"this splitter does not read. The sweep corpora contain neither, so this "
                f"is a different document than expected — extend docling_pages() to walk "
                f"{collection} before scoring it, or the text in them counts as omitted."
            )
    chunks: dict[int, list[str]] = {}
    for item in doc.get("texts") or []:
        text = (item.get("text") or "").strip()
        prov = item.get("prov") or []
        if not text or not prov:
            continue
        chunks.setdefault(prov[0]["page_no"] - 1, []).append(text)
    pages = {idx: "\n\n".join(texts) for idx, texts in chunks.items()}
    if not pages:
        raise SweepOutputError(
            f"{doc_json} yielded no text on any page, so there is nothing to score. "
            f"Check that the docling run completed and that this is the JSON export "
            f"(`--to json`) rather than the markdown one, which has no page numbers."
        )
    _warn_missing(pages, expected_pages, doc_json)
    return pages
