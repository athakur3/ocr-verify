"""The comparison engine.

Two levels, and the order matters:

1. **Bag level (order-independent).** A token the AI engine emitted counts as
   unsupported only if it is absent from the witness reading of the whole page —
   not merely somewhere else on it. Without this, every multi-column page,
   sidebar, and reordered table would light up red, and the tool would be a
   false-positive machine that nobody trusts twice.

2. **Sequence level (positional).** Only once a token is known to be genuinely
   unsupported do we use the alignment to say *where* it sits, so the report can
   crop the corresponding strip of the scan.

Near-miss tokens ('rn' vs 'm', '0' vs 'O') are separated out as OCR noise. They
are real disagreements, but they are not fabrications, and letting them into the
headline count would bury the findings that matter.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from .model import (
    BLANK_PAGE_FABRICATION,
    DROPPED_TEXT,
    SUBSTITUTION,
    UNSUPPORTED_TEXT,
    BBox,
    Finding,
    PageResult,
    VlmPage,
    WitnessPage,
    Word,
)
from .normalize import near_miss, tokenize

# Token classifications produced by the bag level.
_SUPPORTED = "supported"  # matched in place
_DISPLACED = "displaced"  # present on the page, different position — not a finding
_NOISE = "noise"  # near-miss, i.e. glyph-level OCR disagreement
_UNSUPPORTED = "unsupported"  # absent from the other engine entirely


@dataclass
class Settings:
    min_conf: float = 40.0  # witness words below this are too unreliable to argue with
    blank_ink: float = 0.005  # page ink fraction under which a page counts as blank
    blank_min_vlm_words: int = 8  # AI words needed on a blank page to call fabrication
    min_run: int = 3  # divergent tokens needed to raise a finding
    subst_min_run: int = 5  # substitutions are noisy; demand a longer run
    gap: int = 2  # supported tokens tolerated inside one divergent run
    context: int = 8  # context tokens shown either side of a run
    low_conf_mean: float = 65.0  # mean witness confidence under which findings are hedged
    pad: int = 8  # pixels of padding around a crop


LOW_QUALITY_NOTE = (
    "Witness confidence is low on this page, so this is a prompt to look, not a verdict."
)


def compare_page(witness: WitnessPage, vlm: VlmPage, cfg: Settings | None = None) -> PageResult:
    cfg = cfg or Settings()

    usable = witness.confident_words(cfg.min_conf)
    w_norms = [w.norm for w in usable]
    v_pairs = tokenize(vlm.text, markup=True)
    v_norms = [n for _, n in v_pairs]
    v_raw = [r for r, _ in v_pairs]

    quality = _witness_quality(witness, usable, cfg)
    note = LOW_QUALITY_NOTE if quality == "low" else ""

    base = PageResult(
        index=witness.index,
        divergence=0.0,
        witness_words=len(usable),
        vlm_words=len(v_norms),
        matched=0,
        vlm_only=0,
        witness_only=0,
        ink_ratio=witness.ink_ratio,
        witness_quality=quality,
        image=witness.image,
        width=witness.width,
        height=witness.height,
    )

    # The flagship case: nothing on the page, fluent prose out of the engine.
    if (
        witness.ink_ratio < cfg.blank_ink
        and len(usable) < 3
        and len(v_norms) >= cfg.blank_min_vlm_words
    ):
        base.divergence = 1.0
        base.vlm_only = len(v_norms)
        base.findings.append(
            Finding(
                page=witness.index,
                kind=BLANK_PAGE_FABRICATION,
                severity=1.0,
                vlm_text=" ".join(v_raw),
                witness_text="",
                bbox=None,
                note=(
                    f"Page ink coverage is {witness.ink_ratio * 100:.2f}% and the witness read "
                    f"{len(usable)} words, yet the AI engine emitted {len(v_norms)}."
                ),
                n_tokens=len(v_norms),
            )
        )
        return base

    if not v_norms and not w_norms:
        return base  # genuinely blank on both sides

    matcher = SequenceMatcher(None, w_norms, v_norms, autojunk=False)
    opcodes = matcher.get_opcodes()

    w_class, v_class, pairs = _classify(w_norms, v_norms, opcodes)

    base.matched = sum(1 for c in v_class if c == _SUPPORTED)
    base.vlm_only = sum(1 for c in v_class if c == _UNSUPPORTED)
    base.witness_only = sum(1 for c in w_class if c == _UNSUPPORTED)
    base.divergence = base.vlm_only / len(v_norms) if v_norms else 0.0

    findings: list[Finding] = []
    for start, end, count in _runs(v_class, _UNSUPPORTED, cfg.min_run, cfg.gap):
        findings.append(
            _unsupported_finding(start, end, count, v_raw, pairs, usable, witness, cfg, note)
        )
    for start, end, count in _runs(w_class, _UNSUPPORTED, cfg.min_run, cfg.gap):
        findings.append(_dropped_finding(start, end, count, usable, witness, cfg, note))
    for start, end, count in _runs(v_class, _NOISE, cfg.subst_min_run, cfg.gap):
        findings.append(
            _substitution_finding(start, end, count, v_raw, pairs, usable, witness, cfg, note)
        )

    findings.sort(key=lambda f: (-f.severity, f.kind))
    base.findings = findings
    return base


def _witness_quality(witness: WitnessPage, usable: list[Word], cfg: Settings) -> str:
    if witness.ink_ratio >= cfg.blank_ink and not usable:
        return "low"  # there is ink here and the witness read none of it
    if not usable:
        return "ok"
    mean_conf = sum(w.conf for w in usable) / len(usable)
    if mean_conf < cfg.low_conf_mean:
        return "low"
    if witness.words and len(usable) / len(witness.words) < 0.5:
        return "low"
    return "ok"


def _classify(
    w_norms: list[str], v_norms: list[str], opcodes
) -> tuple[list[str], list[str], list[tuple[int, int]]]:
    """Label every token on both sides and collect the matched index pairs."""
    w_class = [""] * len(w_norms)
    v_class = [""] * len(v_norms)
    pairs: list[tuple[int, int]] = []

    residual_w: Counter[str] = Counter()
    residual_v: Counter[str] = Counter()

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for k in range(i2 - i1):
                w_class[i1 + k] = _SUPPORTED
                v_class[j1 + k] = _SUPPORTED
                pairs.append((i1 + k, j1 + k))
            continue
        for i in range(i1, i2):
            residual_w[w_norms[i]] += 1
        for j in range(j1, j2):
            residual_v[v_norms[j]] += 1

    # Each side's leftovers are matched against the other side's leftovers,
    # ignoring position entirely — this is the reordering-tolerant step.
    avail_w = Counter(residual_w)
    avail_v = Counter(residual_v)
    w_buckets = _length_buckets(avail_w)
    v_buckets = _length_buckets(avail_v)

    for j, tok in enumerate(v_norms):
        if v_class[j]:
            continue
        v_class[j] = _consume(tok, avail_w, w_buckets)
    for i, tok in enumerate(w_norms):
        if w_class[i]:
            continue
        w_class[i] = _consume(tok, avail_v, v_buckets)

    return w_class, v_class, pairs


def _length_buckets(counter: Counter[str]) -> dict[int, set[str]]:
    buckets: dict[int, set[str]] = defaultdict(set)
    for tok in counter:
        buckets[len(tok)].add(tok)
    return buckets


def _consume(tok: str, avail: Counter[str], buckets: dict[int, set[str]]) -> str:
    """Spend one occurrence of `tok` (or a near-miss of it) from the other side."""
    if avail.get(tok, 0) > 0:
        _spend(tok, avail, buckets)
        return _DISPLACED
    if len(tok) >= 4:
        # ±2 because a single m/rn fold shifts length by one, and a word can
        # carry two of them ('instrurnents', 'circurnstances').
        for length in range(len(tok) - 2, len(tok) + 3):
            for cand in tuple(buckets.get(length, ())):
                if avail.get(cand, 0) > 0 and near_miss(tok, cand):
                    _spend(cand, avail, buckets)
                    return _NOISE
    return _UNSUPPORTED


def _spend(tok: str, avail: Counter[str], buckets: dict[int, set[str]]) -> None:
    avail[tok] -= 1
    if avail[tok] <= 0:
        del avail[tok]
        buckets.get(len(tok), set()).discard(tok)


def _runs(classes: list[str], target: str, min_run: int, gap: int) -> list[tuple[int, int, int]]:
    """Group nearby tokens of one class into runs of (start, end, count).

    A fabricated sentence is never made purely of unsupported words — its 'the's
    and 'of's exist elsewhere on the page — so short gaps are absorbed rather
    than splitting one fabrication into five findings.
    """
    runs: list[tuple[int, int, int]] = []
    start: int | None = None
    last_hit = -1
    count = 0
    for idx, cls in enumerate(classes):
        if cls == target:
            if start is None:
                start = idx
                count = 0
            elif idx - last_hit - 1 > gap:
                if count >= min_run:
                    runs.append((start, last_hit + 1, count))
                start = idx
                count = 0
            last_hit = idx
            count += 1
    if start is not None and count >= min_run:
        runs.append((start, last_hit + 1, count))
    return runs


def _unsupported_finding(
    start: int,
    end: int,
    count: int,
    v_raw: list[str],
    pairs: list[tuple[int, int]],
    usable: list[Word],
    witness: WitnessPage,
    cfg: Settings,
    note: str,
) -> Finding:
    lo, hi = _witness_span(start, end, pairs)
    bbox = _region(usable, witness, lo, hi, cfg)
    witness_text = " ".join(w.text for w in usable[lo:hi]) if lo is not None and hi is not None else ""
    severity = min(1.0, 0.25 + 0.05 * count)
    if note:
        severity *= 0.6
    return Finding(
        page=witness.index,
        kind=UNSUPPORTED_TEXT,
        severity=severity,
        vlm_text=" ".join(v_raw[start:end]),
        witness_text=witness_text,
        bbox=bbox,
        note=note,
        n_tokens=count,
        context_before=" ".join(v_raw[max(0, start - cfg.context) : start]),
        context_after=" ".join(v_raw[end : end + cfg.context]),
    )


def _dropped_finding(
    start: int,
    end: int,
    count: int,
    usable: list[Word],
    witness: WitnessPage,
    cfg: Settings,
    note: str,
) -> Finding:
    bbox = _region(usable, witness, start, end, cfg)
    severity = min(0.9, 0.2 + 0.04 * count)
    if note:
        severity *= 0.6
    return Finding(
        page=witness.index,
        kind=DROPPED_TEXT,
        severity=severity,
        vlm_text="",
        witness_text=" ".join(w.text for w in usable[start:end]),
        bbox=bbox,
        note=note,
        n_tokens=count,
    )


def _substitution_finding(
    start: int,
    end: int,
    count: int,
    v_raw: list[str],
    pairs: list[tuple[int, int]],
    usable: list[Word],
    witness: WitnessPage,
    cfg: Settings,
    note: str,
) -> Finding:
    lo, hi = _witness_span(start, end, pairs)
    bbox = _region(usable, witness, lo, hi, cfg)
    witness_text = " ".join(w.text for w in usable[lo:hi]) if lo is not None and hi is not None else ""
    return Finding(
        page=witness.index,
        kind=SUBSTITUTION,
        severity=min(0.35, 0.1 + 0.02 * count),
        vlm_text=" ".join(v_raw[start:end]),
        witness_text=witness_text,
        bbox=bbox,
        note=note,
        n_tokens=count,
        context_before=" ".join(v_raw[max(0, start - cfg.context) : start]),
        context_after=" ".join(v_raw[end : end + cfg.context]),
    )


def _witness_span(
    v_start: int, v_end: int, pairs: list[tuple[int, int]]
) -> tuple[int | None, int | None]:
    """Locate an AI-side run on the witness side using the nearest matched anchors.

    Unsupported text has no witness words of its own by definition, so its
    position is inferred from the agreed-upon text surrounding it.
    """
    before = [i for i, j in pairs if j < v_start]
    after = [i for i, j in pairs if j >= v_end]
    lo = max(before) + 1 if before else None
    hi = min(after) if after else None
    if lo is None and hi is None:
        return None, None
    if lo is None:
        lo = max(0, hi - 1) if hi is not None else None
    if hi is None:
        hi = lo + 1 if lo is not None else None
    if lo is not None and hi is not None and hi < lo:
        lo, hi = hi, lo
    return lo, hi


def _region(
    usable: list[Word], witness: WitnessPage, lo: int | None, hi: int | None, cfg: Settings
) -> BBox | None:
    """Crop region for a span, widened to whole text lines so it reads naturally."""
    if lo is None or hi is None:
        return None
    span = usable[lo:hi] or usable[max(0, lo - 1) : lo + 1]
    if not span:
        return None
    line_keys = {w.line_key for w in span}
    boxes = [w.bbox for w in witness.words if w.line_key in line_keys] or [w.bbox for w in span]
    x0 = max(0, min(b[0] for b in boxes) - cfg.pad)
    y0 = max(0, min(b[1] for b in boxes) - cfg.pad)
    x1 = min(witness.width, max(b[2] for b in boxes) + cfg.pad)
    y1 = min(witness.height, max(b[3] for b in boxes) + cfg.pad)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)
