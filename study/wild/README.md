# Found in the wild: a real archival scan, not a synthetic one

*Run date: 2026-08-17. Engine: Marker (marker-pdf, default mode). Source: public-domain
scan from the Internet Archive, downloaded once, run once, no retries.*

## Why this exists

Every result elsewhere in `study/` is measured on a corpus this project built itself —
pages that started as text we wrote, then degraded with real image operations. That is
exact ground truth, but it is also a corpus whose failure modes we chose. This directory
is the first test against something nobody built for us: a scan someone else made,
decades ago, for a reason that had nothing to do with OCR.

## The document

[`downloads/what-about-tibet.pdf`](downloads/what-about-tibet.pdf) — *"What About
Tibet?"*, a 4-page pamphlet issued by the Committee For A Democratic Far Eastern Policy,
New York, 1950 ([archive.org/details/what-about-tibet](https://archive.org/details/what-about-tibet),
public domain). A cover with hand-lettered display type over a printed masthead, plus
three pages of single-spaced typewritten body text, mimeographed. Real 1950s degradation:
faded and uneven ink, small stains, a stray ghost-gray smudge in the left margin of page 2
that turned out on close inspection (300 DPI crop) to be a random stain, not mirrored
text from the reverse side — this candidate has no bleed-through.

Screened one other candidate this block and rejected it: a 12-page 1914 Atlanta
Constitution front section (dense multi-column newsprint, halftone photo) — visually
inspected all pages at 120 DPI, no bleed-through either. Not processed further (large,
and the specific artifact this hunt was seeking wasn't present). 2 of the 3
downloads-per-block budget used.

## What Marker actually did (checked by hand against the page images)

Zero fabrication across all 4 pages. Every one of Marker's near-miss errors is a glyph
substitution on real source text, not invented content: "Peopled" for "People's",
"Sun Tat-sen" for "Sun Yat-sen", "ths" for "the", "Ihasa" for "Lhasa", "affaire" for
"affairs". It dropped the page number ("-3-") and a catalog code ("GNYL-205") from the
last page's footer — consistent with the marginalia-dropping behavior already documented
in the main study, not fabrication.

Full output: [`marker_out/what-about-tibet/what-about-tibet.md`](marker_out/what-about-tibet/what-about-tibet.md).
Source page images for visual cross-check: [`downloads/preview/`](downloads/preview/).

## What ocr-verify said — and why this is the actual finding

Ran blind (PDF + Marker output, `ocr-verify` v0.1.0):
[`what-about-tibet-report.html`](what-about-tibet-report.html),
[`what-about-tibet-findings.json`](what-about-tibet-findings.json).

```
page 1:  38.6% divergence — dropped text, unsupported text
page 2:  13.4% divergence — unsupported text
page 3:  10.7% divergence — unsupported text
page 4:  10.4% divergence — unsupported text
4 of 4 page(s) flagged; 126 of 956 AI words unsupported (13.18%)
```

Every page flagged. But hand-checking each `unsupported_text` finding against the source
image confirms none of them is Marker fabrication — every flagged phrase is verbatim on
the page. What's actually happening: the Tesseract witness is failing on this document's
two real degradation modes that the synthetic corpus doesn't have — hand-lettered display
type on the cover (witness read "SPOTLIGHT" as `"DOTLOIGHT"`) and faded/uneven mimeograph
ink on the body pages (witness read "China just as much as" as `"China just a much ae"`).
The witness-quality heuristic still marked all four pages `"ok"` despite this. ocr-verify
correctly declined to *accuse* Marker in the report language, but "unsupported" pages at
13% of words is a real false-positive rate this document produces that the synthetic
corpus's 1.00 precision does not capture, because the synthetic corpus never included
stylized display type or period-authentic ink variability.

This is the honest headline result of this block's wild hunt: not a caught fabrication,
but confirmation that the study's clean precision=1.00 is a property of its own corpus,
not yet demonstrated on real archival material. The "Honest limits" section of
`study/README.md` already flagged this gap ("Real archival scans have layouts and
typefaces this corpus does not attempt"); this is the first direct data point on it.

## Follow-up: why witness-quality said "ok" (confirmed root cause, next block)

The previous block flagged this as worth a dedicated look but didn't dig in. Reproduced
directly against the real `compare_page`/`_classify` code path (read-only —
`witness_confidence_probe.py` in this directory, no `align.py`/`witness.py` changes):

```
page  mean_conf  usable/total  noise_rate  quality  low_conf<65?  misread-fold(rate>=0.20 & conf<80)?
   0       84.2         0.854       0.098       ok       False       False
   1       89.0         0.922       0.054       ok       False       False
   2       90.0         0.941       0.075       ok       False       False
   3       89.3         0.921       0.052       ok       False       False
```

(Divergence from these page images comes out slightly different from the committed
report — 40.4/13.7/9.9/14.0% vs. the report's 38.6/13.4/10.7/10.4% — because this probe
reruns Tesseract against the saved `downloads/preview/` PNGs rather than the original
higher-resolution PDF render the report used. Same order of magnitude, same verdict on
every page, not a discrepancy worth chasing further.)

Both of the heuristic's guards miss independently, for the same underlying reason:

1. **`low_conf_mean` (65) / usable-ratio (0.5) gate never trips.** Mean witness
   confidence is 84–90% and 85–94% of raw words clear the usable-confidence floor —
   this document is *mostly* read correctly, so the page-level average looks completely
   healthy.
2. **The `misread_rate_low` (0.20) × `misread_conf_ceiling` (80) fold never trips
   either.** The witness-side noise rate (near-miss words, glyph-level disagreement
   with the AI engine) is 5–10% on every page — real, but under the 20% trigger — and
   mean confidence sits above the 80 ceiling regardless.

The concrete failure: on page 1 Tesseract read "as" as **"ae" twice, at 95.6% and 86.2%
confidence** — both comfortably above every threshold in `Settings`. A design comment in
`align.py` (on `misread_conf_ceiling`) reasons that an engine "cannot lower Tesseract's
confidence in a page it never touches" — true, but the implicit assumption is that a
*misreading* witness also reports low confidence on its own misreads. That holds for
the synthetic corpus's degradation modes (blur, noise, warp — genuinely hard to read, so
Tesseract is genuinely unsure). It does not hold here: hand-lettered display type and
uneven mimeograph ink produce glyph shapes that are still clean enough for Tesseract's
character classifier to be confident about the *wrong* sequence. The errors are a small
enough minority (5–10% noise rate) that they never pull the page mean down, and
individually confident enough that no single-word threshold would catch them without
also catching plenty of correct words.

This means a real fix is not a threshold tweak (lowering `misread_conf_ceiling` or
`low_conf_mean` would just make the gate fire more often on the synthetic corpus too,
where high confidence currently *is* a reliable correctness signal — that would need its
own precision/recall ablation on `study/`'s corpus before touching anything). It would
need a signal that survives dilution — e.g. locally low confidence *within the specific
run of tokens a finding is built from*, rather than a whole-page mean — which is a
different kind of change to `_classify`/`compare_page`'s finding construction, not a
constant change. Left as a scoped design problem for a future block, per the standing
guidance not to rush this into `witness.py`/`align.py` without its own ablation.

## Follow-up: the per-finding-local-confidence sketch was tried and doesn't work either

Picked this up the block after it was scoped above. Implemented it exactly as sketched:
window the mean-confidence / misread-rate check to the witness words anchoring one
finding (`usable[lo-context : hi+context]`, same `context=8` already used for report
snippets) instead of the whole page, and hedge that finding alone if the *local* window
looks unreliable. Full precision/recall on both engines held at 1.00/1.00 (unsurprising —
the synthetic corpus's degradation is page-uniform, so a page-mean and a local-mean never
disagree there; `git status` after regenerating both `results-corpus.json` and
`results-pages.json` was clean, byte-identical). But re-run against the real
`what-about-tibet` findings, **it changed nothing** — none of the document's 12 findings
picked up the hedge. Instrumented the two concrete false-positive examples directly:

- **"China.Just as much as" (page 2, the "as"→"ae" case).** The witness word `"ae"`
  itself reads at 95.9% confidence — but the ±8-token window around the finding is 21
  words, and the other 20 are mostly clean 90%+ reads (`than`, `three`, `hundred`,
  `years`, `has`, `been`, `part`, `of`, `China`, `just`...). Window mean comes out ~89%,
  same as the page mean. **The dilution problem doesn't go away at window scale — it just
  shrinks from ~110 words to ~21 and stays above every threshold.** Below the confidence
  question entirely, there's a sharper root cause for this specific pair: `near_miss()`
  in `normalize.py` refuses to compare tokens at all when
  `max(len(a), len(b)) < 4` (a deliberate floor, to stop short words spuriously matching
  each other) — `"as"` and `"ae"` are both 2 characters, so they never reach the
  edit-distance check regardless of confidence. No confidence-based fix, local or global,
  touches this; the exclusion happens one step earlier, in the matching logic, not the
  quality gate.
- **"FAR EAST SPOTLIGHT..." (page 1, the hand-lettered cover).** Here the misread word
  itself *is* low confidence (`"DOTLOIGHT"` at 62.2%) — but it's one word in a 9-word
  window (`context=8` pulls in the next line), and the other 8 are 84–95%. Window mean
  ≈88%, again above the 80 ceiling. A tighter window (e.g. `context=2` instead of 8)
  would likely have caught this one specifically, but that's a different, untested
  change, and shrinking the window doesn't touch the "as"/"ae" case above at all — that
  one fails earlier, in `near_miss`, not in the confidence gate.

Net: the sketch as specified doesn't fire on either motivating example, so it was **not
committed** — shipping it would have added real complexity (a new helper, a changed
finding-builder signature) for zero behavior change on the cases it was meant to fix.
Reverted after instrumenting; `git diff` after the revert is empty. This is a more
precise diagnosis than the previous block reached, and changes what "the fix" looks like:

1. The window-vs-page framing was the wrong axis. Shrinking the averaging window helps
   only when the misread word itself is unconfident (the SPOTLIGHT case) — trying a much
   tighter window (`context=1` or 2, not the report's `context=8`) is the natural next
   experiment there, with its own precision/recall ablation since it changes what counts
   as "nearby" for every finding, not just these two.
2. The "as"/"ae" case is a *different bug* wearing the same symptom. It never reaches the
   confidence gate because `near_miss()`'s `< 4` character floor excludes it from
   comparison outright. Any fix here is a `normalize.py` change (relaxing or
   confidence-gating the short-token floor), not an `align.py` one — and it's the riskier
   of the two, since the floor exists specifically to stop short words from spuriously
   matching each other; loosening it needs its own red-team pass, not just the existing
   `tests/test_witness_failure_guards.py` suite.

## Next steps (not done this block)

- More wild documents, especially ones with confirmed bleed-through (the original target
  of this hunt, still unfound — this block screened several archive.org metadata leads
  with explicit "show-through"/"bleed through" language, including a 1696 English
  auction-catalogue microfilm scan literally titled "Faded, print show-through" — but at
  full resolution none showed unambiguous mirrored/reversed text, and the strongest
  metadata hit was Latin book-catalogue listings, off-domain for this study's English
  word-level scoring; no download spent, all screening was via archive.org's page-preview
  JPEGs) and ones with cleaner typefaces to isolate whether the false-positive driver here
  is specifically stylized/hand-lettered text, ink degradation, or both.
- Witness-quality fix, now split into two independent candidates per the diagnosis above:
  (a) a much tighter local-confidence window (`context=1`–2) for the single-unconfident-
  word case, ablated against the synthetic corpus; (b) a `near_miss()` short-token floor
  relaxation for the confident-short-misread case, which needs its own red-team pass
  since it touches the floor that guards against short words matching spuriously. Treat
  these as separate backlog items — a fix for one will not touch the other.
