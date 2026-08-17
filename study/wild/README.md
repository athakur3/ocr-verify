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
- The witness-quality fix design sketched above (per-finding-local confidence, not
  page-mean) is ready to be picked up as its own backlog item with its own ablation
  against the synthetic corpus's precision=1.00.
