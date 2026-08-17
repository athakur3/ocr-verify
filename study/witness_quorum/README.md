# Witness-quorum spike (branch `witness-quorum`, not merged)

Backlog question: can a second witness engine shrink the set of pages Tesseract hedges
on (blind / wholesale-disagreement), without breaking the property the whole tool leans
on — a witness that does not invent text?

## Setup

PaddleOCR 3.7 installed in an isolated venv ([`.venv`](.venv), gitignored, never a
dependency of the shipped package) so this spike cannot affect `pyproject.toml` or the
CI install. [`spike.py`](spike.py) runs PaddleOCR against five pages of the existing
study corpus and scores its output the same way `study/score.py` scores an AI engine —
against ground truth, not against Tesseract — because the question here is "can this
engine be trusted as a witness," which is a fabrication question, not an agreement
question.

Five pages: one clean page and one blank page as a sanity check, plus the three pages
the study runs hedged on ([`study/results-marker.json`](../results-marker.json),
[`study/results-mineru.json`](../results-mineru.json)) — page 15 (`noise_heavy`,
Tesseract went blind), page 19 (`skew_6deg`, wholesale disagreement, both engines), page
23 (`combo_severe`, wholesale disagreement, Marker run only).

## Results

| Page | Kind | Truth words | PaddleOCR words | Mean conf | Fabricated | Omitted |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | clean | 124 | 124 | 0.999 | 0 | 0 |
| 5 | blank_noise | 0 | 0 | 0.000 | 0 | 0 |
| 15 | noise_heavy | 104 | 104 | 0.997 | 0 | 0 |
| 19 | skew_6deg | 115 | 78 | 0.998 | 0 | 37 |
| 23 | combo_severe | 115 | 115 | 0.916 | **13** | 13 |

Full detail: [spike_results.json](spike_results.json).

## Reading it

- **The blind case (15) is a clean win.** Tesseract read almost nothing on this page and
  the tool correctly hedged rather than guessing. PaddleOCR reads it perfectly — 104/104,
  zero fabrication. A quorum that falls back to PaddleOCR only when Tesseract is blind
  would convert this specific hedge into a fully verified clean page. This is the good
  case the backlog item hoped for.
- **The skew case (19) is a partial win.** PaddleOCR recovers most of the page (78/115)
  with no fabrication, but still misses 37 words outright — it does not fully resolve
  the hedge, it would just shrink it. A quorum here still needs a coverage threshold, not
  a blind "PaddleOCR read something, trust it" rule.
- **The severe-combo case (23) is the finding that matters most: PaddleOCR fabricates
  13 words here.** This is the page with the heaviest degradation in the corpus, and it
  is exactly where a second witness would be most tempting to lean on — and exactly
  where it stops being boring. Tesseract's whole design principle
  ([`witness.py`](../../src/ocr_verify/witness.py) docstring) is that the witness is
  chosen for being unable to invent text, not for being accurate. PaddleOCR, a
  transformer-ish recognition model rather than a classical pipeline, does not have that
  guarantee — and this one page is enough to demonstrate it fails on the corpus's own
  hardest case.

## Answer to the backlog question

**Partially, and not for free.** A quorum shrinks the unverifiable set on genuine
blindness (page 15's kind) essentially without cost. It does not cleanly shrink the
wholesale-disagreement set (pages 19/23's kind) — on the harder of the two, the second
witness itself hallucinates, which is disqualifying for a component whose only claimed
property is that it doesn't. Naively adding PaddleOCR as an OR-fallback witness would
risk turning "unverifiable page" hedges into false-negative silent passes on exactly the
pages most likely to also fool the AI engine under test — the worst place to lose a
hedge.

**Not merging this spike.** Any real integration needs PaddleOCR to earn trust
per-page rather than being trusted whenever Tesseract fails — e.g. only accepted where
its own confidence is high AND its reading agrees with whatever fragments Tesseract
*did* read on that page (page 23's 0.916 mean confidence is suspiciously close to its
clean-page 0.997-0.999 range, so confidence alone would not have caught this case here).
That is real design work, not a config flag, so per the backlog item ("ablate before
merging") this stays a branch-only spike.

## Follow-up: does the agreement-gated rule actually work? ([agreement_gate.py](agreement_gate.py))

The obvious next question, and the one this spike's first pass left open: gate trust on
whether PaddleOCR's reading *agrees* with whatever Tesseract itself managed to read on
the same page, rather than trusting PaddleOCR outright. Tested directly — run Tesseract
(the existing witness) on the same 5 pages, and measure what share of Tesseract's own
words also show up in PaddleOCR's reading (exact or near-miss match, no ground truth
involved in this signal; ground truth is used only afterward, to grade the resulting
decision).

| Page | Kind | Tesseract usable words | Tesseract mean conf | Agreement (Tesseract⊆Paddle) | PaddleOCR fabricated |
| --- | --- | --- | --- | --- | --- |
| 1 | clean | 124 | 96.4 | 1.000 | 0 |
| 5 | blank_noise | 0 | 0.0 | 0.000 | 0 |
| 15 | noise_heavy | 0 | 0.0 | 0.000 | 0 |
| 19 | skew_6deg | 88 | 92.2 | 0.670 | 0 |
| 23 | combo_severe | 77 | 73.1 | **0.818** | **13** |

Full detail: [agreement_gate_results.json](agreement_gate_results.json).

**The rule as sketched does not work, on both halves.**

1. The "never trust when Tesseract read nothing" half directly disqualifies page 15 —
   Tesseract reads 0 usable words there, that being exactly *why* it's the blind case.
   Applied literally, the rule that was supposed to capture this spike's one clean win
   would refuse to trust PaddleOCR on the one page where trusting it pays off.
2. The "agreement" half is inverted from what's needed. Page 23 — the page where
   PaddleOCR fabricates — has *higher* agreement with Tesseract (0.818) than page 19,
   the clean partial-recovery case (0.670). The mechanism is legible in hindsight: under
   heavy combined degradation, both engines are looking at the same damaged pixels and
   converge on the same *wrong* reading, so agreement-with-Tesseract tracks shared
   exposure to bad image quality, not correctness. Two witnesses agreeing is not evidence
   they're right when the thing making one of them wrong (the image) is visible to both.

So this specific two-part rule is dead on a 5-page sample, not just unmerged. It isn't
a config-tuning problem (no threshold on this "agreement" signal separates page 23 from
page 19 in the needed direction — 23's value is simply higher). A workable quorum, if
one exists, needs a signal that isn't "do the two witnesses agree with each other,"
since the failure mode here is exactly correlated failure between them. Candidates for
a future pass, untested: whether PaddleOCR's own confidence separates cleanly on a
larger sample than n=5 (this sample's 0.916 vs 0.997-0.999 gap looked real but was
flagged too thin to trust after the first pass, and this second pass didn't add
confidence-signal evidence either way); or abandoning the "trust one witness over the
other" framing entirely in favor of surfacing disagreement itself as the finding
(closer to how the tool already treats Tesseract-vs-AI disagreement) rather than trying
to pick a winner. Not attempted here — this pass answers "does the sketched rule work,"
not "what rule would."
