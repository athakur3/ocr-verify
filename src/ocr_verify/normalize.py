"""Token normalization.

Both engines are normalized into the same token space before any comparison. The
rule of thumb: fold away differences that are *typographic* (quote style, case,
ligatures, markdown syntax) and preserve everything that is *lexical*, because a
lexical difference is exactly the thing we are trying to surface.
"""

from __future__ import annotations

import re
import unicodedata

# Markdown / layout syntax that VLM engines emit and Tesseract never will.
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]{1,80}>")
_MD_FENCE = re.compile(r"^\s*```.*$", re.MULTILINE)
_MD_RULE = re.compile(r"^\s*([-*_]\s*){3,}$", re.MULTILINE)
_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]{4,}\|?\s*$", re.MULTILINE)
_MD_MARKS = re.compile(r"[*_`~#>|]+")
_PAGE_BREAK = re.compile(r"^\s*(-{3,}|\{\d+\}-{5,}|<!--\s*page[^>]*-->)\s*$", re.MULTILINE | re.IGNORECASE)

_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    "ﬅ": "st", "ﬆ": "st", "œ": "oe", "Œ": "oe", "æ": "ae", "Æ": "ae",
}

# Characters that differ only by typography.
_PUNCT_FOLD = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-", "­": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
    "…": "...",
}

_STRIP_EDGE = "\"'`.,;:!?()[]{}<>*_~|\\/•·-—"


def fold(text: str) -> str:
    """Typographic folding shared by both engines."""
    text = unicodedata.normalize("NFKC", text)
    out = []
    for ch in text:
        if ch in _LIGATURES:
            out.append(_LIGATURES[ch])
        elif ch in _PUNCT_FOLD:
            out.append(_PUNCT_FOLD[ch])
        else:
            out.append(ch)
    return "".join(out)


def strip_markup(text: str) -> str:
    """Remove markdown/HTML scaffolding from VLM output.

    Table *content* survives (cells become bare words); only the pipes, rules and
    emphasis markers go. Image placeholders are dropped entirely — they describe
    the page rather than transcribe it, so counting them as text would produce
    fake 'unsupported text' findings on every figure.
    """
    text = _MD_IMAGE.sub(" ", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_FENCE.sub(" ", text)
    text = _TABLE_SEP.sub(" ", text)
    text = _MD_RULE.sub(" ", text)
    text = _HTML_TAG.sub(" ", text)
    text = _MD_MARKS.sub(" ", text)
    return text


def normalize_token(raw: str) -> str:
    """Normalize one word for matching. Returns '' for tokens carrying no lexical content."""
    tok = fold(raw).lower().strip()
    tok = tok.strip(_STRIP_EDGE)
    # Collapse internal repeats of punctuation that OCR sprays around.
    tok = re.sub(r"[\s]+", "", tok)
    if not tok:
        return ""
    # A token of pure punctuation/symbols carries no lexical signal.
    if not any(ch.isalnum() for ch in tok):
        return ""
    return tok


def tokenize(text: str, *, markup: bool = False) -> list[tuple[str, str]]:
    """Split text into (verbatim, normalized) pairs, dropping empty normalizations."""
    if markup:
        text = strip_markup(text)
    out: list[tuple[str, str]] = []
    for raw in text.split():
        norm = normalize_token(raw)
        if norm:
            out.append((raw, norm))
    return out


# Glyph pairs that a shape-based recognizer genuinely confuses. Folded on both
# sides symmetrically, so the fold can only ever make two readings *agree* — it
# can never manufacture a disagreement that was not there.
_CONFUSABLE_PAIRS = (("rn", "m"), ("vv", "w"), ("cl", "d"))
_CONFUSABLE_CHARS = str.maketrans({"0": "o", "1": "i", "l": "i", "5": "s", "8": "b"})


def ocr_skeleton(tok: str) -> str:
    """Collapse a token onto a shape-canonical form.

    'barorneter' and 'barometer' are one word seen through two recognizers: m and
    rn are the same marks on the page. Comparing skeletons keeps that class of
    misread out of the fabrication count, where it would otherwise be the loudest
    and least useful category of finding.
    """
    for confusable, canonical in _CONFUSABLE_PAIRS:
        tok = tok.replace(confusable, canonical)
    return tok.translate(_CONFUSABLE_CHARS)


def near_miss(a: str, b: str) -> bool:
    """True if two normalized tokens differ only as OCR noise, not as content.

    Used to keep glyph-level misreads ('rn' vs 'm', '0' vs 'O') out of the
    fabrication count — they are real disagreements but they are not the thing
    this tool exists to catch, and reporting them drowns the signal.
    """
    if a == b:
        return True
    skel_a, skel_b = ocr_skeleton(a), ocr_skeleton(b)
    if skel_a == skel_b:
        return True
    if abs(len(skel_a) - len(skel_b)) > 1:
        return False
    if max(len(a), len(b)) < 4:
        return False
    return _edit_distance_within_1(skel_a, skel_b)


def _edit_distance_within_1(a: str, b: str) -> bool:
    if a == b:
        return True
    la, lb = len(a), len(b)
    if la > lb:
        a, b, la, lb = b, a, lb, la
    if lb - la > 1:
        return False
    i = j = 0
    seen_diff = False
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        if seen_diff:
            return False
        seen_diff = True
        if la == lb:
            i += 1
            j += 1
        else:
            j += 1
    return True


def split_pages(text: str) -> list[str] | None:
    """Split a single concatenated document into pages on an explicit page marker.

    Returns None when no unambiguous marker is present — we would rather ask the
    caller for per-page files than guess page boundaries and misalign the whole
    report.
    """
    for pattern in (
        re.compile(r"^\s*\{(\d+)\}-{5,}\s*$", re.MULTILINE),  # Marker/pdftotext style
        re.compile(r"^\s*<!--\s*page[ _-]?break[^>]*-->\s*$", re.MULTILINE | re.IGNORECASE),
        re.compile(r"^\s*\[?page\s+\d+\]?\s*$", re.MULTILINE | re.IGNORECASE),
        re.compile(r"\f"),
    ):
        parts = pattern.split(text)
        if pattern.groups:
            parts = parts[:: pattern.groups + 1]
        if len(parts) > 1:
            pages = [p for p in parts]
            # Leading empty chunk when the document opens with a marker.
            if pages and not pages[0].strip():
                pages = pages[1:]
            if len(pages) > 1:
                return pages
    return None
