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
    UNVERIFIABLE_PAGE,
    WHOLESALE_DISAGREEMENT,
    BBox,
    Finding,
    PageResult,
    VlmPage,
    WitnessPage,
    Word,
)
from .normalize import SHORT_TOKEN_FLOOR, near_miss, short_misread, tokenize

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
    # Witness-failure guards, added after the first real-engine study (2026-08-16),
    # where all three false positives were pages the witness could not read.
    blind_ratio: float = 0.05  # usable witness words below max(3, ratio*vlm) = blind
    wholesale_each: float = 0.15  # both-direction divergence above this = wholesale
    # The wholesale fold additionally demands positive evidence that the witness
    # failed: the share of unmatched witness tokens that are short shreds
    # (<=3 chars). Red-team measurement on the study corpus: genuine witness
    # failures shred (0.44 / 0.55); fabrications leave clean words (0.07 / 0.26).
    fold_frag_share: float = 0.38
    # Partial-blindness signal (added after the MinerU run, 2026-08-17): a
    # witness that is misreading a page leaves a measurable trace — a large
    # share of its own words match the engine only as near-misses, AND its mean
    # confidence is low. Both halves are image-derived, which is what makes the
    # signal safe: an engine can inflate the near-miss share by emitting
    # misspellings, but it cannot lower Tesseract's confidence in a page it
    # never touches, so the pair cannot be manufactured from the text side.
    misread_rate_low: float = 0.20
    misread_conf_ceiling: float = 80.0
    # Per-finding local-confidence hedge (added after the Tibet-pamphlet wild-hunt
    # false positive, 2026-08-17): the page-mean confidence checks above are blind
    # to a single confident-but-wrong word ('SPOTLIGHT' misread as 'DOTLOIGHT' at
    # 62.2%) once diluted by the rest of a mostly-correct page. A page-uniform
    # window doesn't fix it either — even a per-finding window at the report's
    # context=8 still averages in enough clean neighbors to clear the ceiling
    # (measured: ~88%). Only a tight window (empirically 1-2 words either side of
    # the finding's own witness span) stays close enough to the misread word to
    # trip the same misread_conf_ceiling. This hedges the individual finding
    # (note + severity), not the page's witness_quality — it does not change
    # whether a page is flagged, only whether that specific finding reads as a
    # confident accusation or a prompt to look.
    local_context: int = 1


LOW_QUALITY_NOTE = (
    "Witness confidence is low on this page, so this is a prompt to look, not a verdict."
)


def _robust_ink(witness: WitnessPage) -> float | None:
    """Lazily measure noise-robust ink for a page, caching on the WitnessPage."""
    if witness.ink_robust is not None:
        return witness.ink_robust
    try:
        from .render import robust_ink_ratio

        witness.ink_robust = robust_ink_ratio(witness.image)
    except (OSError, ValueError):
        return None
    return witness.ink_robust


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

    # The inverse of the blank-page case: ink on the page, but the witness read
    # essentially none of it while the AI engine read plenty. The witness has no
    # standing to accuse here — the honest verdict is "cannot verify", not
    # "fabricated". (Study page noise_heavy, 2026-08-16: Tesseract read 0 of 104
    # words Marker got right; the old behaviour called all 104 fabricated.)
    if (
        witness.ink_ratio >= cfg.blank_ink
        and len(v_norms) >= cfg.blank_min_vlm_words
        and len(usable) < max(3, cfg.blind_ratio * len(v_norms))
    ):
        base.witness_quality = "blind"
        base.verified = False
        # Grade the hedge by whether the ink has text-scale structure. A robust
        # (noise/speckle/streak/shadow-insensitive) ink measure near zero means
        # the page is effectively a dirty blank — on those, engine output is far
        # more suspect than on a page with structured ink the witness merely
        # failed to read. We still do not *accuse*: faint real text also measures
        # near zero (fade_heavy in the study corpus scores 0.000), so a blind
        # accusation here would false-flag degraded-but-real pages. The severity
        # and note carry the distinction instead.
        robust = _robust_ink(witness)
        if robust is not None and robust < cfg.blank_ink:
            severity = 0.45
            structure = (
                f"The ink shows no text-scale structure (robust ink {robust * 100:.3f}% vs raw "
                f"{witness.ink_ratio * 100:.2f}%): this page is likely a dirty blank, and the "
                f"{len(v_norms)} words the AI engine emitted deserve real suspicion. It could "
                "also be very faint text, which measures the same — hence a strong prompt to "
                "look, not a verdict."
            )
        else:
            severity = 0.15
            structure = (
                f"The witness read only {len(usable)} usable words against the AI engine's "
                f"{len(v_norms)}. Nothing on this page was verified."
            )
        base.findings.append(
            Finding(
                page=witness.index,
                kind=UNVERIFIABLE_PAGE,
                severity=severity,
                vlm_text=" ".join(v_raw[:60]) + (" …" if len(v_raw) > 60 else ""),
                witness_text=" ".join(w.text for w in usable),
                bbox=None,
                note=f"Ink coverage is {witness.ink_ratio * 100:.2f}%. {structure}",
                n_tokens=len(v_norms),
            )
        )
        return base

    matcher = SequenceMatcher(None, w_norms, v_norms, autojunk=False)
    opcodes = matcher.get_opcodes()

    w_class, v_class, pairs = _classify(w_norms, v_norms, opcodes, usable, cfg)

    base.matched = sum(1 for c in v_class if c == _SUPPORTED)
    base.vlm_only = sum(1 for c in v_class if c == _UNSUPPORTED)
    base.witness_only = sum(1 for c in w_class if c == _UNSUPPORTED)
    base.divergence = base.vlm_only / len(v_norms) if v_norms else 0.0

    # Partial blindness: the witness read the page, but badly — a large share of
    # its own words only match the engine as near-misses, and its confidence is
    # low. Its silences on the rest of the page are then not evidence of absence,
    # so findings built on those silences get the low-quality hedge. The conf
    # ceiling is what keeps this un-gameable: an engine emitting misspellings can
    # inflate the near-miss share, but cannot lower Tesseract's confidence.
    if base.witness_quality == "ok" and usable:
        witness_noise = sum(1 for c in w_class if c == _NOISE)
        mean_conf = sum(w.conf for w in usable) / len(usable)
        if (
            witness_noise / len(usable) >= cfg.misread_rate_low
            and mean_conf < cfg.misread_conf_ceiling
        ):
            base.witness_quality = "low"
            note = LOW_QUALITY_NOTE

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

    # Wholesale disagreement: both directions diverge heavily at once, AND the
    # unmatched witness tokens are dominated by short shreds. The shred share is
    # the load-bearing condition, added after a red team showed the two-sided
    # ratio alone lets an engine hide a full-page rewrite: a rewrite pushes both
    # ratios up, but it leaves the witness's unmatched words *clean* (the witness
    # read the real text fine), while a genuine witness failure leaves fragments
    # ('th', 'nter', 'wi'). Without shred evidence the itemized accusations stand
    # and count toward the CI gate — a confident witness contradicted wholesale
    # is exactly what a rewrite looks like, and it must fail the build.
    unmatched_w_norms = [
        w.norm for w, cls in zip(usable, w_class) if cls == _UNSUPPORTED
    ]
    frag_share = (
        sum(1 for n in unmatched_w_norms if len(n) <= 3) / len(unmatched_w_norms)
        if unmatched_w_norms
        else 0.0
    )
    # The witness-side ratio arm demands substantial witness-side divergence
    # before a fold — it is what stops an engine from buying a hedge by omitting
    # a sprinkle of short real words (red-team case 2). But it also blocks the
    # honest partial-blindness case (MinerU run, combo_severe): a low-confidence
    # witness that half-read the page leaves few leftovers of its own while the
    # engine's correct text goes unsupported. The arm therefore relaxes only on
    # image-side evidence the engine cannot manufacture: low witness confidence,
    # or a quality flag that is itself image-derived.
    mean_conf = sum(w.conf for w in usable) / len(usable) if usable else 0.0
    witness_side_diverges = (
        base.witness_only / len(usable) >= cfg.wholesale_each if usable else False
    )
    if base.witness_only >= cfg.min_run and (
        mean_conf < cfg.misread_conf_ceiling or base.witness_quality != "ok"
    ):
        witness_side_diverges = True
    if (
        len(usable) >= 10
        and len(v_norms) >= 10
        and base.vlm_only >= cfg.min_run
        and base.witness_only >= cfg.min_run
        and base.vlm_only / len(v_norms) >= cfg.wholesale_each
        and witness_side_diverges
        and frag_share >= cfg.fold_frag_share
    ):
        base.verified = False
        unmatched_v = " ".join(
            raw for raw, cls in zip(v_raw, v_class) if cls == _UNSUPPORTED
        )
        unmatched_w = " ".join(
            w.text for w, cls in zip(usable, w_class) if cls == _UNSUPPORTED
        )
        base.findings = [
            Finding(
                page=witness.index,
                kind=WHOLESALE_DISAGREEMENT,
                severity=0.5,
                vlm_text=unmatched_v[:600],
                witness_text=unmatched_w[:600],
                bbox=None,
                note=(
                    f"{base.vlm_only} of {len(v_norms)} AI words lack witness support and "
                    f"{base.witness_only} of {len(usable)} witness words lack AI support, and "
                    f"{frag_share * 100:.0f}% of the unmatched witness words are short shreds — "
                    "the witness likely could not handle this page. Review the page image "
                    "rather than trusting either reading."
                ),
                n_tokens=base.vlm_only + base.witness_only,
            )
        ]
        return base

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
    w_norms: list[str],
    v_norms: list[str],
    opcodes,
    usable: list[Word],
    cfg: Settings,
) -> tuple[list[str], list[str], list[tuple[int, int]]]:
    """Label every token on both sides and collect the matched index pairs.

    Note there is deliberately NO fragment-repair pass here. An earlier version
    merged shredded witness words ('wi' + 'nter') back into the AI engine's
    tokens; a red team showed the merge could silently delete an accusation
    (legit 'in to' on one line supporting a fabricated 'into' elsewhere), and
    ablation showed it changed zero verdicts on the real study corpus. Shredded
    witnesses are instead handled at page level by the wholesale-disagreement
    fold, which uses the shreds as *evidence of witness failure* rather than
    trying to repair them. A repair pass that can delete accusations has to buy
    more than a rounding error.
    """
    w_class = [""] * len(w_norms)
    v_class = [""] * len(v_norms)
    pairs: list[tuple[int, int]] = []

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            for k in range(i2 - i1):
                w_class[i1 + k] = _SUPPORTED
                v_class[j1 + k] = _SUPPORTED
                pairs.append((i1 + k, j1 + k))

    # Short misreads, resolved *positionally* before the position-free pool
    # below ever sees them. The pool refuses to near-miss anything under
    # SHORT_TOKEN_FLOOR for a good reason — at two or three characters an
    # edit-distance match would let a short fabricated word be absorbed by any
    # unmatched short witness word anywhere on the page. Inside a 1:1 `replace`
    # region the position constraint does that job instead: the two tokens are
    # the same word slot in the same sentence, so a single confusable-glyph
    # substitution is one recognizer misreading one word, not invented content.
    # This is the fix for the confidently-wrong-witness case in study/wild/
    # ('as' read as 'ae' at 95.6% confidence — above every threshold in
    # Settings, and never even compared under the old floor).
    for tag, i1, i2, j1, j2 in opcodes:
        if tag != "replace" or (i2 - i1) != (j2 - j1):
            continue
        for k in range(i2 - i1):
            if short_misread(w_norms[i1 + k], v_norms[j1 + k]):
                w_class[i1 + k] = _NOISE
                v_class[j1 + k] = _NOISE

    # Each side's remaining leftovers are matched against the other side's,
    # ignoring position entirely — this is the reordering-tolerant step.
    residual_w = Counter(w_norms[i] for i in range(len(w_norms)) if not w_class[i])
    residual_v = Counter(v_norms[j] for j in range(len(v_norms)) if not v_class[j])
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
    if len(tok) >= SHORT_TOKEN_FLOOR:
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


def _local_hedge(usable: list[Word], lo: int | None, hi: int | None, cfg: Settings) -> str:
    """Hedge one finding if witness confidence right around its own span is low.

    Distinct from the page-level checks in compare_page(): those average over
    the whole page and miss a lone confident misread. This averages over a
    handful of words either side of the finding's own witness span instead.
    """
    if lo is None or hi is None:
        return ""
    window = usable[max(0, lo - cfg.local_context) : hi + cfg.local_context]
    if not window:
        return ""
    mean_conf = sum(w.conf for w in window) / len(window)
    return LOW_QUALITY_NOTE if mean_conf < cfg.misread_conf_ceiling else ""


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
    note = note or _local_hedge(usable, lo, hi, cfg)
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
    note = note or _local_hedge(usable, start, end, cfg)
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
    note = note or _local_hedge(usable, lo, hi, cfg)
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
