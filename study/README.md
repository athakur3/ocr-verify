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

Both numbers are gated mechanically, not just claimed in prose:
`tests/test_study_gate.py` calls `study/score.py`'s scoring function directly
against both captured engine outputs and fails the build if either regresses
below 1.00.

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

### Second-seed check: does the onset survive a different passage pair? (run 2026-08-17)

The sweep above uses one passage pair (real "conclusions" text, ghost "survey" text). A
second corpus ([sweep/make_sweep2.py](sweep/make_sweep2.py)) repeats the same six-level
construction with a different pair — real "tides" text, ghost "instruments" text — same
strengths, same scoring ([sweep/score_sweep2.py](sweep/score_sweep2.py)), to check whether
the fabrication onset is a property of the mechanism or an artifact of that specific
wording. Marker ran in default (fast) mode here, not the explicit balanced mode used for
the main study's single fabrication case; the first sweep's run command was not recorded
precisely enough to confirm which mode it used, so mode is a confound between the two
sweeps and not just passage content — noted, not glossed over. Full numbers:
[sweep/sweep2_results.json](sweep/sweep2_results.json).

| Ghost strength | Marker fabricated | Marker omitted | MinerU fabricated | MinerU omitted |
| --- | --- | --- | --- | --- |
| 0.00 | 0 | 37 | 0 | 0 |
| 0.10 | 0 | 37 | 0 | 0 |
| 0.20 | 2 | 36 | 4 | 0 |
| 0.30 | 2 | 36 | 4 | 0 |
| 0.40 | 2 | 36 | 4 | 0 |
| 0.55 | 19 | 41 | 4 | 0 |

What replicates and what doesn't:

- **The core claim survives**: both engines are clean at 0.10 and both fabricate by 0.20
  — same coarse onset window as the first pair. Fabrication-under-bleed-through is not
  an artifact of the specific "conclusions"/"survey" wording.
- **The sharp two-onset story does not clearly replicate at this granularity.** In the
  first pair Marker was high-threshold-then-catastrophic and MinerU was hair-trigger-but-
  small; here both engines cross into fabrication in the *same* coarse bin (0.10–0.20),
  and Marker's fabrication stays small (2–19 words) rather than exploding — the opposite
  of its behaviour on the first pair. No bisect was run on this corpus (0.10–0.20 is
  unresolved into finer strengths), so a real onset-order difference could still be
  hiding inside that bin; this run cannot distinguish "the order flipped" from "the order
  is noise at coarse resolution." Given the mode confound above, this pair alone cannot
  settle it either way.
- **Marker's content-loss generalizes, but its shape changes.** Here it drops the title
  *and* the entire third paragraph (~37 of 115 words) at every strength including 0.0 —
  worse than the first pair's 4-word title-only loss, and ghost-independent in the same
  way. Content loss unrelated to the ghost looks like a real, passage-sensitive Marker
  behaviour, not a fluke of one passage.

Net effect on the multi-seed caveat below: the headline claim (fabrication has a
strength-dependent onset, and it's low) holds up under a second passage. The specific
per-engine onset *ordering* claimed from the first pair is now open again — it was
either passage-sensitive or is a coarse-resolution artifact, and this study can't tell
which without a matched-mode, bisected third run.

### Third-seed check: does matching mode resolve the onset-order question? (run 2026-08-18)

The construction here has no randomness — `bleed_through()` is a deterministic image
operation, and the main study already confirmed byte-identical output across repeat
engine runs at fixed input. So a "seed" in this study means a different passage pair, not
a different RNG draw; multi-seed and multi-passage are the same thing here. This third
corpus ([sweep/make_sweep3.py](sweep/make_sweep3.py)) swaps roles instead of introducing
new text: "survey" (ghost in the first pair) is real here, "tides" (real in the second
pair) is the ghost. Every passage used so far now appears in the opposite role at least
once, so no single passage's content can be the whole explanation for an onset that shows
up across all three runs. This run also closes the mode confound the second pair left
open: `marker_single --mode fast` was used explicitly and verified first — `--mode
balanced` was re-tested directly before this run and still fails with the same "Failed to
initialize samplers: failed to parse grammar" error on every page (confirmed broken in
this venv as of today), so fast mode is not just a match to the second pair, it is
currently the only mode that works at all. Same strengths, same scoring
([sweep/score_sweep3.py](sweep/score_sweep3.py)). Full numbers:
[sweep/sweep3_results.json](sweep/sweep3_results.json).

| Ghost strength | Marker fabricated | Marker omitted | MinerU fabricated | MinerU omitted |
| --- | --- | --- | --- | --- |
| 0.00 | 0 | 39 | 0 | 0 |
| 0.10 | 0 | 39 | 0 | 0 |
| 0.20 | 0 | 39 | 4 | 0 |
| 0.30 | 14 | 3 | 4 | 0 |
| 0.40 | 1 | 39 | 4 | 0 |
| 0.55 | 0 | 39 | 4 | 0 |

**Cross-seed spread at each strength** (three passage pairs, same six strengths — this is
between-passage spread, not repeated-trial variance at fixed input, since nothing about
this pipeline is stochastic):

| Ghost strength | Marker (3 seeds) | Marker range | MinerU (3 seeds) | MinerU range |
| --- | --- | --- | --- | --- |
| 0.00 | 0, 0, 0 | 0 | 0, 0, 0 | 0 |
| 0.10 | 0, 0, 0 | 0 | 0, 0, 0 | 0 |
| 0.20 | 20, 2, 0 | 20 | 15, 4, 4 | 11 |
| 0.30 | 75, 2, 14 | 73 | 13, 4, 4 | 9 |
| 0.40 | 20, 2, 1 | 19 | 5, 4, 4 | 1 |
| 0.55 | 55, 19, 0 | 55 | 5, 4, 4 | 1 |

What this settles and what it doesn't:

- **MinerU's onset location replicates cleanly, 3 for 3**: clean at 0.00 and 0.10,
  fabricating by 0.20, every time. Magnitude is low and tightens with more seeds (range
  shrinks from 11 words at 0.20 to 1 word by 0.40–0.55) — this is the closest thing in
  the whole study to a *characterization* rather than an observation: MinerU has a real,
  narrow onset band on this mechanism, and its fabrication stays small regardless of
  passage.
- **Matching mode did not make Marker's curve well-behaved — it did the opposite.**
  Sweep 2 and sweep 3 both ran explicit `--mode fast`, removing the mode confound between
  those two runs specifically, yet they diverge sharply: sweep 2 fabricates a small,
  fairly steady amount from 0.20 (2, 2, 2, then 19 at 0.55); sweep 3 stays clean through
  0.20, spikes to 14 at 0.30, then reverts to 1 and 0. Same engine, same mode, same
  strength ladder, different passage — different shape entirely. That rules out "mode was
  the hidden variable" as the explanation for Marker's non-monotonicity; passage content
  is doing real work here, not just wording-level noise. The onset-order question from
  the first two pairs (does Marker or MinerU cross into fabrication first) is not
  resolvable at this coarse a strength resolution — a bisected run around 0.20–0.30 is
  still the way to settle it, now that mode is a controlled variable.
- **Marker's content-loss is the most stable signal across all three seeds at the
  strengths sampled so far**: every passage loses its title (and, for the second and
  third pairs, additional paragraphs) at every strength tested in the six-point sweep,
  ghost-independent every time. The bisect below complicates "ghost-independent," though
  — see next section.

### Bisecting sweep 3's 0.20-0.30 gap (run 2026-08-18)

The third-seed check narrowed Marker's onset to somewhere between 0.20 (clean) and 0.30
(14 fabricated words, omission drops from 39 to 3) but couldn't resolve it further, and
flagged this exact gap as the next step. A bisect corpus
([sweep/make_sweep3_bisect.py](sweep/make_sweep3_bisect.py)) adds three finer strengths —
0.225 / 0.25 / 0.275 — on the same survey/tides pair, same explicit `--mode fast`. Full
numbers: [sweep/sweep3_bisect_results.json](sweep/sweep3_bisect_results.json).

| Ghost strength | Marker fabricated | Marker omitted | MinerU fabricated | MinerU omitted |
| --- | --- | --- | --- | --- |
| 0.20 | 0 | 39 | 4 | 0 |
| 0.225 | 0 | 0 | 4 | 0 |
| 0.25 | 0 | 0 | 4 | 0 |
| 0.275 | 0 | 0 | 4 | 0 |
| 0.30 | 14 | 3 | 4 | 0 |

Two findings, one expected and one not:

- **Marker's cliff is sharper than the coarse sweep suggested, not fuzzier.** Zero
  fabrication and zero omission at 0.225, 0.25, and 0.275 — completely clean — then both
  fabrication (14 words) and near-complete omission-recovery (39 → 3) appear together at
  0.30. The transition is confined to a 0.025-wide band (0.275–0.30) rather than smeared
  across the whole 0.20–0.30 decade. This settles the onset-ordering question for this
  pair specifically: MinerU is already fabricating at 0.20 (steady 4 words, unchanged
  through the whole bisect and into 0.55), while Marker stays clean until 0.30 — MinerU
  crosses first, cleanly, matching the first pair's ordering rather than the second pair's
  same-coarse-bin result.
- **The "ghost-independent" title-omission claim doesn't hold at 0.225–0.275.** All three
  bisect pages render the title and every paragraph intact — 0 omitted words, not the 39
  seen at 0.0/0.10/0.20 and every other level in the coarse sweep. Content-loss and
  fabrication are moving together here, not independently: the same 0.275→0.30 boundary
  that turns on fabrication also turns off the title-dropping behavior. That reframes the
  coarse-sweep pattern — omission wasn't a strength-independent constant, it was constant
  *within the strengths actually sampled*, and the bisect happened to land in a gap where
  it isn't. Whether that gap is a narrow real feature of this passage or evidence the
  omission behavior has its own separate, unmeasured onset is unresolved by this run —
  worth a finer bisect specifically around content-loss if picked up again, independent of
  the fabrication question this run was built to answer.

### Bisecting sweep 2's 0.10-0.20 gap (run 2026-08-19)

The second-seed check left pair 2 (tides/instruments) as the one pair where both engines'
onset landed in the same coarse bin — Marker 0→2 fabricated and MinerU 0→4 fabricated,
both between 0.10 and 0.20 — an open tie the "Honest limits" section flagged as the one
pair not yet bisected. A bisect corpus
([sweep/make_sweep2_bisect.py](sweep/make_sweep2_bisect.py)) adds three finer strengths —
0.125 / 0.15 / 0.175 — on the same pair, same explicit `--mode fast`. Full numbers:
[sweep/sweep2_bisect_results.json](sweep/sweep2_bisect_results.json).

| Ghost strength | Marker fabricated | Marker omitted | MinerU fabricated | MinerU omitted |
| --- | --- | --- | --- | --- |
| 0.10 | 0 | 37 | 0 | 0 |
| 0.125 | 0 | 0 | 4 | 0 |
| 0.15 | 2 | 0 | 3 | 0 |
| 0.175 | 2 | 0 | 4 | 0 |
| 0.20 | 2 | 36 | 4 | 0 |

- **The tie resolves: MinerU crosses first here too.** MinerU is already fabricating (3-4
  words) at 0.125, the first strength above 0.10, while Marker stays clean until 0.15. The
  coarse run's apparent tie was a resolution artifact, not a genuine simultaneous
  crossing. All three passage pairs now agree on ordering (MinerU's onset precedes
  Marker's), which is the strongest form of that claim this study can currently make —
  see "Honest limits" below for what "agree" does and doesn't establish.
- **The "ghost-independent" omission claim breaks down here too, replicating the sweep-3
  bisect finding on a second pair.** All three bisect strengths render the title and every
  paragraph intact — 0 omitted, not the 36-37 words dropped at every coarse strength
  (0.0 through 0.55, this same pair). Two of the three pairs checked at fine resolution now
  show the same pattern: the "always omits regardless of ghost strength" framing held only
  at the coarse strengths actually sampled, not in between. Verified by reading the raw
  Marker markdown directly (all three pages show the full title and all three paragraphs),
  not inferred from the scorer alone.
- **Infra note for future sweep runs**: the first attempt at this bisect (produced by an
  interrupted prior session, recovered and finished this block) omitted
  `--paginate_output` from the `marker_single` invocation, silently producing markdown
  with no `{N}---` page markers — `score_sweep2_bisect.py`'s page-splitting regex then
  found zero pages and scored every page as 100% omitted. This is the same failure mode
  already documented in this study's operational history.
- **Guard added (2026-08-19), so it cannot recur silently**: the five scorers' duplicated
  page-splitting helpers were replaced by one shared `study/sweep/pagesplit.py`, which
  raises `SweepOutputError` when Marker's markdown contains no `{N}---` markers (naming
  `--paginate_output` as the cause) or when MinerU's `content_list.json` yields no text on
  any page. Losing *some* pages still scores as omission — an engine emitting nothing for a
  heavily degraded page is a real measurement — but it now prints which page indices were
  missing. `tests/test_sweep_page_split.py` covers both failure shapes and additionally
  re-splits every committed Marker capture, so an un-paginated capture cannot be committed
  and scored as total content loss. All five scorers were re-run after the refactor and
  reproduce their committed results JSONs byte-for-byte.

### Bisecting sweep 3's 0.10-0.20 gap: MinerU's onset at matched resolution (run 2026-08-19)

The computed characterization below named its own weakest claim: MinerU's onset was only
*consistent with* one common strength, and seed 3's bracket was the wide (0.10, 0.20] not
because the measurement said so but because that seed's bisect had been placed at
0.225–0.275 to chase Marker's crossing. Seeds 1 and 2 were both bracketed at
(0.10, 0.125]; seed 3 had simply never been sampled there. That is a gap in the ladder,
not a result, so this run closes it — a second bisect corpus on the same survey/tides
pair, same explicit `--mode fast`, at the same 0.125 / 0.15 / 0.175 strengths the other
two seeds already have ([sweep/make_sweep3_lowbisect.py](sweep/make_sweep3_lowbisect.py),
numbers in [sweep/sweep3_lowbisect_results.json](sweep/sweep3_lowbisect_results.json)).

The run was designed to be able to fail: a clean 0.125 on this pair would have split
MinerU's brackets and refuted the common onset outright.

| Ghost strength | Marker fabricated | Marker omitted | MinerU fabricated | MinerU omitted |
| --- | --- | --- | --- | --- |
| 0.10 | 0 | 39 | 0 | 0 |
| 0.125 | 0 | 0 | 4 | 0 |
| 0.15 | 0 | 0 | 4 | 0 |
| 0.175 | 0 | 0 | 4 | 0 |
| 0.20 | 0 | 39 | 4 | 0 |

- **MinerU crosses at 0.125 here too, so all three seeds now carry the identical bracket
  (0.10, 0.125].** The common-onset reading stops being merely unrefuted and becomes a
  positive agreement of three independent passage pairs at 0.025 resolution — the finest
  any of them has been measured at. It is still three pairs and still a bracket, not a
  constant: what is now excluded is any onset outside (0.10, 0.125] on these pairs, not
  the possibility that a fourth passage lands elsewhere.
- **The first-crossing amplitude is as stable as the threshold — but the *count* is the
  flattering half of that.** MinerU fabricates 5, 4 and 4 words at its first fabricating
  strength across the three seeds (4.8%, 3.5%, 3.2% of each page), against Marker's 24, 2
  and 14 on the same pairs. Reading the actual tokens on seed 3, though, the constant 4 is
  two different behaviours wearing one number: at 0.125 and 0.15 the invented words are
  glyph-level garbage (`anotherreado`, `ebit`, `edit`, `to`), while from 0.175 up through
  0.55 they settle into the same recurring fluent fragment (`of`, `operations`, `the`,
  `topic`, with `title`/`operation` substituted at two strengths). A count-only view of
  this curve looks flat across 0.125–0.55; the words say the engine crosses into noise
  first and into plausible-looking invention afterwards. `tests/test_onset_summary.py`
  re-derives both token sets from the committed captures so this stays a measurement.
- **Marker stays clean at all three strengths, which is the check this run had to pass.**
  Seed 3's Marker onset is bracketed at (0.275, 0.30] by the other bisect, so any
  fabrication at 0.125–0.175 would have contradicted it. None appeared. The two bisects
  on this seed are separate corpora built from the same passage pair, so this is a weak
  but real reproducibility check on the generator, not only on the engine.
- **The omission-vanishes-between-coarse-strengths pattern replicates a third time**, on
  the third pair: 39 words omitted at every coarse strength on this seed, 0 at all six
  bisected strengths across both of its bisects. All three pairs checked at fine
  resolution now show it. The pattern is consistent enough that "Marker drops content
  independently of ghost strength" should be read as an artifact of which strengths the
  coarse ladder happened to sample, not as a property of the engine.

### Cross-seed characterization: the onset claims, computed (2026-08-19)

The five sections above were written one run at a time, and their cross-seed table was
typed by hand out of the results JSONs. That is fine for narrative and weak for a claim:
a transcription slip is invisible, and raw word counts are not comparable across seeds in
the first place — the three passages are 104, 115 and 124 words, so "20 fabricated" means
19.2% of the page on seed 1 and 16.1% on seed 3. [sweep/summarize_onsets.py](sweep/summarize_onsets.py)
recomputes the consolidation from all seven committed results JSONs into
[sweep/onset_summary.json](sweep/onset_summary.json); `tests/test_onset_summary.py`
re-derives it and fails if it drifts from the captures. (Written when there were six; the
seventh is seed 3's low bisect above, and every number in this section was regenerated
from the script rather than edited by hand when it landed.)

Three deliberate choices in how it computes, each refusing a more flattering shape:

- **An onset is a bracket, not a point.** A sampled ladder can only say the crossing lies
  above the last clean strength and at or below the first fabricating one, so that is what
  is reported: `(last clean, first fabricating]`. Fabricating at the lowest strength tested
  leaves the lower bound *unknown*, not 0.0.
- **Unrecorded is unknown, not zero.** Seed 1's bisect scorer recorded fabrication only, so
  omission at 0.125/0.15/0.175 is `null` — a missing measurement rendered as 0 would read
  as "no content lost," the flattering direction.
- **Ordering is decided by disjoint intervals or not at all.** Overlapping brackets return
  `unresolved_at_this_resolution` rather than picking whichever engine's number came first.

| Seed | Passages (real / ghost) | Marker mode | Page words | Marker onset | MinerU onset |
| --- | --- | --- | --- | --- | --- |
| 1 | conclusions / survey | unrecorded (confound) | 104 | (0.15, 0.175] | (0.10, 0.125] |
| 2 | tides / instruments | fast | 115 | (0.125, 0.15] | (0.10, 0.125] |
| 3 | survey / tides | fast | 124 | (0.275, 0.30] | (0.10, 0.125] |

**Cross-seed spread, normalized** (seeds 1, 2, 3 at the nine strengths all three now
share; percentages are of each seed's own page). Seed 3's low bisect added the three
bisected strengths to this intersection — before it, only the six coarse strengths were
common to all three seeds:

| Ghost strength | Marker % of page | Marker range | MinerU % of page | MinerU range |
| --- | --- | --- | --- | --- |
| 0.00 | 0.0, 0.0, 0.0 | 0.0 | 0.0, 0.0, 0.0 | 0.0 |
| 0.10 | 0.0, 0.0, 0.0 | 0.0 | 0.0, 0.0, 0.0 | 0.0 |
| 0.125 | 0.0, 0.0, 0.0 | 0.0 | 4.8, 3.5, 3.2 | 1.6 |
| 0.15 | 0.0, 1.7, 0.0 | 1.7 | 4.8, 2.6, 3.2 | 2.2 |
| 0.175 | 23.1, 1.7, 0.0 | 23.1 | 14.4, 3.5, 3.2 | 11.2 |
| 0.20 | 19.2, 1.7, 0.0 | 19.2 | 14.4, 3.5, 3.2 | 11.2 |
| 0.30 | 72.1, 1.7, 11.3 | 70.4 | 12.5, 3.5, 3.2 | 9.3 |
| 0.40 | 19.2, 1.7, 0.8 | 18.4 | 4.8, 3.5, 3.2 | 1.6 |
| 0.55 | 52.9, 16.5, 0.0 | 52.9 | 4.8, 3.5, 3.2 | 1.6 |

What the computation says that the prose could not:

- **The ordering claim survives being made mechanical.** All three seeds return
  `mineru_first`, and each does so because the two brackets are disjoint — on seed 2 they
  merely touch (MinerU crosses at 0.125, Marker's last clean strength *is* 0.125), which
  is still decisive for half-open intervals but is the thinnest of the three margins. This
  is the same conclusion the per-seed sections argued, now derived from the numbers rather
  than read off them.
- **Marker's onset is provably passage-dependent, and not because of the mode confound.**
  All three pairs of Marker brackets are disjoint, so no single onset strength fits the
  three seeds — but seed 1's Marker mode was never recorded, so only the seed 2 / seed 3
  pair isolates passage from mode. That pair is disjoint on its own ((0.125, 0.15] vs
  (0.275, 0.30]), which is what makes "passage content moves Marker's onset" a measurement
  here rather than an inference about a confound.
- **MinerU's three brackets are now identical, not merely overlapping.** When this
  section was first written they overlapped — no seed refuted a common onset in
  (0.10, 0.125], but seed 3's bracket was the wide (0.10, 0.20] only because its bisect
  had been placed around 0.20–0.30 to chase Marker, so the agreement was partly an
  absence of measurement. The low bisect above supplied it: all three seeds bracket
  MinerU at (0.10, 0.125]. `consistent_with_one_onset` still reports what it reports —
  no seed refutes a common onset — but it is now backed by three seeds measured at that
  resolution rather than two measured and one unsampled.
- **Normalizing does not rescue Marker and does not change MinerU.** Marker's between-seed
  spread at 0.30 is 70.4 percentage points of the page, against 1.6 for MinerU at its own
  first crossing — the passage-sensitivity is not an
  artifact of comparing differently-sized pages. MinerU's spread still tightens with
  strength (11.2 → 1.6 points), the same shape the raw counts showed.
- The pre-existing hand-typed cross-seed table in "Third-seed check" was checked against
  the computed values and matches exactly. No drift had accumulated — the guard is against
  the next edit, not a repair of this one.

## Degradation-mode regression corpus (`study/degradation_modes/`, added 2026-08-17)

The real-archival wild hunt (`study/wild/`) found two failure modes the 24-page corpus
above never covered: hand-lettered display type and uneven mimeograph ink. Witness fix
(a) — the tight local-confidence window that closed the false positives those modes
caused on a real document — was validated only against that one download. This small,
synthetic, two-page corpus reproduces both modes with known ground truth so the check is
reproducible and runs in the test suite (`tests/test_degradation_modes.py`) instead of a
one-off probe script:

- **Hand-lettered cover**: a warped masthead title above a clean paragraph. The clean
  body keeps the page-mean confidence healthy while the title itself reads low locally —
  the split fix (a)'s local-vs-page-mean distinction was built for. Confirmed: the tight
  window (`context=1`) hedges the title finding; the old wide window (`context=8`) does
  not, matching the real document's before/after.
- **Mimeograph body**: blotchy ink-density variation across an ordinary paragraph. At the
  severity used here, the existing wholesale-disagreement fold — a different, already-
  shipped guard, not fix (a) — is what keeps this from becoming an itemized accusation.
  Pinned as a regression against a mode the corpus never previously exercised.

Both pages use a "perfect" engine transcript (the exact ground truth text) as the
comparison input, so any finding raised is attributable purely to the witness struggling
with the image, not to any simulated engine error. This corpus is separate from the
24-page corpus above and does not feed `study/score.py`'s precision/recall gate — its
role is validating the witness heuristics generalize to failure modes real archival
material exposed, not measuring engine fabrication.

## Honest limits of this study

- One engine, one run, one synthetic-then-degraded corpus. This measures existence
  ("a current, widely used engine does/does not fabricate under these conditions"), not
  prevalence in the wild.
- The passages are 19th-century-survey pastiche written for this study. Real archival scans
  have layouts and typefaces this corpus does not attempt.
- Degradations are real image operations, but the *pages* are born digital. A physically
  scanned test target would be stronger and is future work.
- The sweep and bisect run one seed and one engine pass per strength level, and the
  mechanism itself is fully deterministic (no randomness in the construction; the main
  study already confirmed byte-identical repeat runs), so "seed" here means passage pair,
  not RNG draw. Three passage pairs are all *consistent with* a single narrow MinerU
  fabrication onset, and as of the seed-3 low bisect all three carry the *identical*
  bracket (0.10, 0.125] rather than merely overlapping ones — none refutes a common
  onset, and all three have now been measured at the resolution where they could have.
  That is still weaker than the "passage-independent property" this section once claimed:
  three pairs agreeing is agreement, not independence. Marker's
  onset location and magnitude are not — a third pair with mode explicitly matched to the
  second still produced a materially different curve (see "Third-seed check" above),
  which rules out mode as the hidden variable but leaves passage-sensitivity unexplained.
  A bisect of the third pair's 0.20–0.30 gap (see "Bisecting sweep 3's 0.20-0.30 gap"
  above) pinned Marker's cliff on *that specific pair* to a narrow 0.275–0.30 band — clean
  before, fabricating and content-complete after — and confirmed MinerU crosses first on
  this pair, matching the first pair's ordering. A second bisect, of the second pair's
  0.10–0.20 gap (see "Bisecting sweep 2's 0.10-0.20 gap" above), resolved that pair's
  apparent tie the same way: MinerU fabricates by 0.125, Marker not until 0.15. All three
  passage pairs now agree once measured at matched fine resolution — MinerU's onset
  precedes Marker's in every case checked. That is still three pairs, not a general law;
  the honest claim is "ordering is resolvable and all three pairs tested agree," not
  "ordering always favors MinerU." The two bisects also share a second result: both found
  the coarse sweep's "ghost-independent" Marker content-loss (title and a paragraph
  dropped at every coarse strength) vanishes at the finer strengths in between —
  present at every strength actually sampled, but not a strength-independent constant.
  Both the ordering verdict and the per-engine "is one onset consistent with every seed"
  question are now computed from disjoint onset brackets rather than argued in prose —
  see "Cross-seed characterization" above, which also records that Marker's
  passage-sensitivity holds between the two seeds whose Marker mode matches, so it is not
  the mode confound wearing a different hat. The third pair's 0.10–0.20 gap has since been
  bisected as well, so no seed's onset bracket is now wider than 0.025 for either engine,
  and the omission-vanishes-between-sampled-strengths pattern has replicated on all three
  pairs — the "Marker drops content regardless of ghost strength" reading should be
  treated as a sampling artifact of the coarse ladder rather than an engine property.
