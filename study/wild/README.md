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

## Next steps (not done this block)

- More wild documents, especially ones with confirmed bleed-through (the original target
  of this hunt) and ones with cleaner typefaces to isolate whether the false-positive
  driver here is specifically stylized/hand-lettered text, ink degradation, or both.
- If the pattern holds across more documents, the witness-quality heuristic (why did it
  call these pages "ok"?) is worth a dedicated look — out of scope for this block, which
  is document-gathering, not scorer surgery.
