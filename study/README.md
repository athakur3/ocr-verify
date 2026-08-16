# Adversarial study: does a real VLM-OCR engine fabricate, and do we catch it?

*Run date: 2026-08-16. Engine: Marker (marker-pdf, balanced mode — VLM layout +
full-page OCR — forced OCR, MPS on Apple Silicon). Results: [results.json](results.json).*

## Why this exists

The sample report in `docs/` demonstrates the mechanism on a *simulated* hallucinating
engine. That is honest for explaining the tool but worthless as evidence for the thesis. This
study replaces it: a real engine, run once, no retries, over a corpus built so that ground
truth is exact — every page began as text we wrote ourselves before degradation.

It also doubles as the tool's first exposure to non-pristine input. The false-positive rate
on degraded pages is the number that decides whether anyone keeps this installed, and until
this run it was unknown.

## Corpus

24 pages, fixed seed, byte-reproducible (`make_corpus.py`):

| Group | Pages | Purpose |
| --- | --- | --- |
| Clean controls | 2 (incl. two-column) | Engine should be perfect; we must stay silent |
| Blank variants | 6 — white, speckle, noise, shadow, JPEG-artifact, scanner-line | The headline claim, stress-tested |
| Progressive fade | 3 | Where does degradation turn into invention? |
| Blur / noise / JPEG / skew / low-DPI | 9 | The ordinary ways scans go bad |
| Bleed-through | 1 | Ghost text from the reverse side |
| Compound failures | 3 | Bad photocopies of bad photocopies |

Every degradation is a real image operation (real Gaussian blur, real JPEG encode at Q5,
real rotation), not an instruction to a model to "pretend this is degraded."

## Method

Two measurements, strictly separated:

1. **Engine vs ground truth.** Bag-of-words comparison of the engine's output against the
   known text of each page, near-miss tolerant (a glyph misread is an error, not an invented
   word). A page counts as fabricated-on if ≥5 emitted tokens exist nowhere in its ground
   truth. ocr-verify plays no part in this step.
2. **ocr-verify vs step 1.** The tool runs exactly as a user would run it — PDF plus engine
   output, witness blind to ground truth — and its fabrication flags are scored against
   step 1's facts as a confusion matrix.

The tool is never graded against its own opinion of what happened.

## Results

### What Marker actually did (measured against ground truth, tool not involved)

- **Fabricated on 1 of 24 pages.** On the bleed-through page it wove the mirrored ghost
  text into fluent prose ("achieved the greater part of the summer of the summer of the
  coastal stations") and then fell into a degeneration loop — *"the subply vessel tourists
  off the shorts in each season and only was"* repeated three times — 58 invented words on
  one page. Deterministic: byte-identical across two independent runs.
- **Silently dropped the title and entire final paragraph** from 7 readable pages —
  including the *clean, undegraded control page* (39 of 124 words gone). A control run
  with `--keep_pageheader_in_output --keep_pagefooter_in_output` produced identical output,
  so this is not marginalia-stripping configuration; it is real content loss.
- **Emitted nothing at all** on the extreme-fade page — while the Tesseract witness could
  still read it. Degradation causes silent total omission as well as fabrication.
- **Refused to invent on all six blank pages** (white, speckle, noise, shadow, JPEG
  artifacts, scanner streak): zero words emitted on each. On this corpus, Marker's
  blank-page behaviour is clean — the fabrication risk concentrated in bleed-through
  and, per its own output, repetition loops on ghosted text.

### What ocr-verify said (run blind, scored against the above)

| | |
| --- | --- |
| Fabrication precision | **1.00** (0 false accusations on 23 clean pages) |
| Fabrication recall | **1.00** (the bleed-through fabrication was flagged) |
| Dropped-text detection | 11/11 pages with heavy omission flagged |
| Hedged pages | 3 (heavy noise, 6° skew, compound degradation) — all genuine witness failures, correctly reported as "cannot verify" rather than accused |

The first version of this scorer measured precision 0.25: three false accusations, every
one a page where *Tesseract* failed and the tool blamed the engine. Those became the
witness-failure guards (blind hedge, wholesale fold), which is why the hedge row exists.

### The red team round

The guards were then attacked by independent adversarial reviewers, who broke the first
version three ways: the wholesale fold hid a full-page rewrite from the CI gate (a 10-page
doc with one entirely fabricated page gated at 0.00%); a fragment-merge repair pass could
silently delete an accusation; and the blank/blind boundary sat on a knife edge that two
scanner streaks could cross. The surviving design responds to each:

- The wholesale fold demands **shred evidence** — real witness failures leave short
  fragments (measured 0.44–0.55 share on this corpus), fabrications leave clean words
  (0.07–0.26). A confident witness contradicted wholesale is treated as what it looks
  like: a rewrite, accused and gated.
- The fragment merge was **removed**, not repaired: ablation showed it changed zero
  verdicts on this corpus, against two demonstrated accusation-deletion attacks.
- Blind hedges are **graded by a noise-robust ink measure**: structureless ink reads as
  "likely a dirty blank, treat the output with real suspicion" at raised severity. It
  never escalates to accusation, because faint real text measures identically (this
  corpus's fade_heavy page scores 0.000 on the robust measure).
- Unverifiable pages are **budgeted in CI** (`--max-unverified`, default 25% of AI words):
  an engine cannot pass the gate by being unverifiable.

Every attack is pinned as a regression test in `tests/test_witness_failure_guards.py`.

## Second engine: MinerU 3.4.5 (run 2026-08-17)

Same corpus, same blind protocol, second engine (`mineru -p corpus.pdf`, hybrid-auto
pipeline, local). Per-page mapping from `content_list.json` (`page_idx`); captured output in
`mineru_out/`. Results: [results-pages.json](results-pages.json) (Marker's are
[results-corpus.json](results-corpus.json)).

| | Marker 2.0 | MinerU 3.4.5 |
| --- | --- | --- |
| Clean pages | dropped title + final paragraph (39 words) | perfect |
| Fades | dropped paragraph; emitted nothing on extreme fade | perfect, including extreme fade |
| Blanks (all 6) | clean — emitted nothing | clean — emitted nothing |
| Skew 6° | (witness failed; hedged) | title duplicated (4 words, below threshold) |
| **Bleed-through** | **58 fabricated words, degeneration loop** | **5 fabricated words ("lye source of catalyst solutions")** |
| ocr-verify score | precision 1.00, recall 1.00 | precision 1.00, recall 1.00 |

The cross-engine headline: **two engines, different quality tiers, same fabrication
trigger.** MinerU is dramatically more faithful than Marker on this corpus — no dropped
content anywhere — yet bleed-through still induced invented text on both. Ghosted
reverse-side text appears to be a reliable fabrication trigger for generative OCR, which
is exactly the kind of page real archival scans are full of.

The MinerU run also caught a tool bug: its fuller output shifted the divergence ratios on
the compound-degraded page and produced a false accusation the Marker run's numbers had
masked (witness half-read the page at mean confidence 73; the engine's correct text in
witness-silent regions read as "unsupported"). The wholesale fold's witness-side arm now
relaxes on **image-side evidence only** — low witness confidence — which an engine's text
cannot manufacture; the misspelling-evasion this could otherwise invite is a pinned
regression test. Both engines' scorecards hold at 1.00/1.00 under the fixed engine, and
all red-team attack scripts remain dead.

## Ghost-contrast sweep: where fabrication begins (runs 2026-08-17)

Both engines fabricated on the study's single bleed-through page, which carries its ghost
at strength 0.55. One point per engine says *it happens*; a sweep asks *when*. The sweep
corpus ([sweep/make_sweep.py](sweep/make_sweep.py)) is six pages with identical real text
(the conclusions passage, 104 words) over a mirrored ghost of the survey passage at
strengths 0.0 / 0.10 / 0.20 / 0.30 / 0.40 / 0.55 — ground truth is identical on every
page, so any emitted word outside it is fabricated, and the count as a function of ghost
strength is each engine's failure curve. Scoring is the same bag-delta measurement as the
main study ([sweep/score_sweep.py](sweep/score_sweep.py)); the first pass placed both
onsets in the same coarse bin (0.10–0.20), so a follow-up bisect added pages at
0.125 / 0.15 / 0.175. Full numbers: [sweep/sweep_results.json](sweep/sweep_results.json),
[sweep/bisect_results.json](sweep/bisect_results.json); captured engine outputs alongside.

| Ghost strength | Marker fabricated | Marker omitted | MinerU fabricated | MinerU omitted |
| --- | --- | --- | --- | --- |
| 0.00 | 0 | 4 | 0 | 0 |
| 0.10 | 0 | 4 | 0 | 0 |
| 0.125 † | 0 | — | **5** | — |
| 0.15 † | 0 | — | 5 | — |
| 0.175 † | **24** | — | 15 | — |
| 0.20 | 20 | 12 | 15 | 0 |
| 0.30 | 75 | 23 | 13 | 0 |
| 0.40 | 20 | 13 | 5 | 0 |
| 0.55 | 55 | 10 | 5 | 0 |

*† bisect pages (same construction, separate build; omissions not recorded in the bisect
scorer). Bold marks each engine's onset.*

What the curves show — on this corpus, with one seed and one run per level, so these are
observations about these runs, not laws:

- **The onsets are distinct, and the failure styles are opposite.** MinerU is
  hair-trigger, low-amplitude: it starts inventing between 0.10 and 0.125 — a ghost
  barely visible on screen — but the damage stays small (5–15 words) at every strength
  tested. Marker is high-threshold, catastrophic: clean through 0.15, then 24 fabricated
  words at 0.175 and a peak of 75 at 0.30.
- **MinerU improves as the ghost gets stronger** (15 → 13 → 5 → 5 across 0.20 → 0.55). A
  plausible reading is that it suppresses interference it can recognize as such, and is
  fooled mainly by *faint* ghosts — which is the regime real bleed-through occupies. Its
  worst case here is a barely-there ghost, not a flagrant one.
- **Neither curve is monotonic above onset** (Marker: 20 → 75 → 20 → 55). Run-to-run
  variance at a fixed strength is unmeasured; the main study saw Marker reproduce its
  bleed-through fabrication byte-identically across two runs, so determinism is
  plausible, but a multi-seed pass is the obvious next step before reading shape into
  these curves.
- **Marker's title omission is ghost-independent** — the 4-word title is dropped even at
  strength 0.0, consistent with the content-loss behaviour in the main study — and its
  omissions grow once the ghost passes its onset.

The practical consequence for verification: a detector tuned to one engine's failure
regime misses the other's. MinerU's 5-word inventions sit below any alarm threshold sized
for Marker's 75-word collapses, and Marker is perfectly clean at strengths where MinerU
is already fabricating. There is no universal "safe" ghost level to test at — which is an
argument for witnessing every page rather than spot-checking known-bad conditions.

## Honest limits of this study

- One engine, one run, one synthetic-then-degraded corpus. This measures existence
  ("a current, widely used engine does/does not fabricate under these conditions"), not
  prevalence in the wild.
- The passages are 19th-century-survey pastiche written for this study. Real archival scans
  have layouts and typefaces this corpus does not attempt.
- Degradations are real image operations, but the *pages* are born digital. A physically
  scanned test target would be stronger and is future work.
- The sweep and bisect run one seed and one engine pass per strength level, on a single
  passage pair. The onset locations and curve shapes are observations about these runs;
  a multi-seed, multi-passage robustness pass is future work before treating either
  number as a property of the engine.
