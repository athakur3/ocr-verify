# ocr-verify

**Trust but verify for AI OCR.** Vision-language OCR engines — DeepSeek-OCR, Marker, MinerU,
olmOCR — share a failure mode that ordinary OCR does not have: on blank, degraded, or unusual
pages they can silently emit fluent, plausible text that is not on the page. The output looks
perfect. Nothing downstream can tell.

`ocr-verify` runs boring, deterministic Tesseract as a **witness**, aligns its reading against
the AI engine's output, and reports only the places the two disagree — each one backed by the
crop of the scan it came from.

```bash
ocr-verify book.pdf marker_output/ -o report.html
```

→ [**See a sample report**](docs/demo-report.html) (self-contained HTML, no server needed).

---

## Why a witness instead of a confidence score

VLM-OCR engines emit no reliable per-word coordinates and no calibrated confidence. There is
nothing inside their output to check. Tesseract is worse than they are at almost everything —
layout, handwriting, low contrast — but it has the one property they lack: **it does not invent
words.** It also emits a bounding box and a confidence for every word it reads.

So we do not try to judge the AI engine's output on its own terms. We diff it against a witness
and show you the disagreements. The tool is a smoke alarm, not a judge.

## Install

Tesseract is the only system dependency:

```bash
brew install tesseract          # macOS
apt-get install tesseract-ocr   # Debian/Ubuntu
```

Then:

```bash
pip install ocr-verify
```

## Usage

```bash
# directory of per-page files (page_001.md, page_002.md, ...)
ocr-verify book.pdf marker_output/ -o report.html

# single markdown file containing page-break markers
ocr-verify book.pdf book.md -o report.html

# olmOCR-style JSONL
ocr-verify book.pdf out.jsonl -o report.html

# one page, while you are iterating
ocr-verify book.pdf out/ --pages 47

# machine-readable findings alongside the report
ocr-verify book.pdf out/ -o report.html --json findings.json

# SARIF, for GitHub code scanning or another CI dashboard
ocr-verify book.pdf out/ -o report.html --sarif findings.sarif

# a whole corpus at once, from a JSON manifest — see "Checking a corpus at once" below
ocr-verify --batch manifest.json --fail-on 0.02
```

### In CI

`--fail-on` turns the tool into a quality gate. Exit codes: `0` clean, `1` over threshold,
`2` error.

```bash
ocr-verify book.pdf out/ -o report.html --fail-on 0.02   # fail above 2% divergence
```

Two gate semantics worth knowing:

- The divergence ratio counts only pages the witness could verify. Pages where the witness
  failed (severe noise, skew, degradation) are hedged and excluded — Tesseract's weakness
  must not fail your build.
- Exclusion is not a free pass: if more than `--max-unverified` (default 25%) of the AI
  engine's words sit on unverifiable pages, the gate fails anyway. An engine cannot pass
  by being unverifiable.
- Going silent is not a free pass either: if the witness verifies pages but the AI engine
  produced zero words on all of them (wrong output path, an ingest bug, a crashed run),
  the divergence ratio has nothing to divide by and the gate fails rather than reading
  that as 0% divergence.

### Checking a corpus at once

`--batch` runs a whole manifest of documents through the same gate in one invocation —
useful for a nightly regression run over a fixed corpus, rather than one shell loop per repo.

```bash
ocr-verify --batch manifest.json --fail-on 0.02 --json summary.json
```

```json
[
  {"pdf": "corpus/doc1.pdf", "engine_output": "marker_out/doc1/"},
  {"pdf": "corpus/doc2.pdf", "engine_output": "marker_out/doc2/", "out": "reports/doc2.html"}
]
```

Every global flag (`--dpi`, `--fail-on`, `--max-unverified`, ...) applies to each entry; an
entry can override `out`/`json`/`sarif`/`engine_label` individually. The exit code is the
worst across all entries (`2` if any document errored, else `1` if any failed `--fail-on`,
else `0`), and `--json` writes one aggregate summary instead of a single document's findings.
`--pages` is not supported in batch mode.

```yaml
- name: Verify OCR output
  run: ocr-verify corpus/doc.pdf ocr-out/ -o report.html --fail-on 0.02 --sarif findings.sarif
- uses: actions/upload-artifact@v4
  if: always()
  with: { name: ocr-verify-report, path: report.html }
- uses: github/codeql-action/upload-sarif@v3
  if: always()
  with: { sarif_file: findings.sarif }
```

## What it reports

Four **accusations** — claims the evidence can carry:

| Finding | Meaning |
| --- | --- |
| **Blank-page fabrication** | Effectively no ink on the page, yet the engine emitted running text. The clearest signature there is. |
| **Unsupported text** | The engine emitted words absent from the witness reading of the whole page — not moved, absent. |
| **Dropped text** | The witness read words the engine never emitted. Usually a skipped line, column, or caption. |
| **Disagreement** | Both engines read text here and disagree on the words. Mostly OCR noise; occasionally a rewrite. |

And two **hedges** — confessions that the witness could not cover the page. Hedged pages are
marked `verified: false`, excluded from the gate divergence, and counted against a separate
CI budget (below):

| Finding | Meaning |
| --- | --- |
| **Unverifiable page** | Ink on the page but the witness read essentially none of it. When the ink also shows no text-scale structure (a robust measure that ignores noise, speckle, streaks, and shadow), the page is likely a dirty blank and the hedge says so at higher severity — but it never becomes an accusation, because very faint real text measures the same. |
| **Wholesale disagreement** | Both readings diverge heavily at once *and* the witness's unmatched words are dominated by short shreds — the signature of Tesseract losing the page. Without the shred evidence, the itemized accusations stand instead: a confident witness contradicted wholesale is exactly what a rewrite looks like. |

## How the comparison works

Two levels, in this order — the order is what keeps the false-positive rate survivable:

1. **Bag level (order-independent).** A word counts as unsupported only if it is missing from
   the witness reading of the *entire page*, not merely from the same position. Multi-column
   pages, floated captions and reordered tables therefore produce **no findings**. This is the
   difference between a tool people keep installed and one they uninstall on day two — the
   fixture suite has a dedicated two-column page whose columns the engine emits in reverse,
   and it must stay silent.

2. **Sequence level (positional).** Only once a word is known to be genuinely unsupported is
   the alignment used to locate it, so the report can crop the right strip of the scan.
   Fabricated text has no coordinates of its own, so it is anchored between the nearest
   agreed-upon words on either side.

Three more rules keep the signal clean:

- Witness words below `--min-conf` (default 40) are excluded from the comparison entirely —
  the tool never argues from evidence the witness itself does not believe.
- Glyph-level misreads are folded before comparison: `m`/`rn`, `vv`/`w`, `cl`/`d`, and the
  digit/letter confusions `0`/`o`, `1`/`l`/`i`, `5`/`s`, `8`/`b`. `barorneter` and
  `barometer` are one word seen by two recognizers, and counting that as a fabrication
  would bury the real findings.
- Pages the witness cannot testify about produce hedges, not accusations (see the table
  above). These guards were shaped by an adversarial study against a real engine and then
  red-teamed; the design notes live in [study/README.md](study/README.md). One deliberate
  absence: there is no "repair" pass that reassembles shredded witness words — a red team
  showed such a pass can silently delete an accusation, and ablation showed it changed zero
  verdicts on the study corpus.

## Limitations — read these before quoting a number

- **Agreement is not correctness.** Both engines can be wrong together, most easily on the
  degraded pages where the witness is also weak. A clean report is evidence, not proof.
- **The witness is weak on handwriting, dense layout, tables, and low-contrast scans.** Pages
  the witness cannot read at all are labelled `blind`, produce a single unverifiable-page
  hedge instead of accusations, and are excluded from the gate (but budgeted — see CI above).
  Readable-but-shaky pages are labelled `low` and their findings are damped. On a fully
  handwritten corpus this tool has little to say.
- **Non-Latin scripts** need the matching Tesseract language pack via `--lang`, and the
  glyph-confusion folding above is Latin-specific.
- **Findings are prompts to look, not verdicts.** That is why every one ships with a crop.
- **Page alignment is never guessed.** If page boundaries cannot be established from your
  engine's output, the tool stops and says so rather than producing a confidently misaligned
  report.

## Reproducing the sample report

```bash
uv run python fixtures/make_fixtures.py
uv run ocr-verify fixtures/sample.pdf fixtures/engine_output -o docs/demo-report.html
```

The fixture corpus is five pages, each isolating one behaviour: a clean page, a blank page the
engine fills with invented prose, a page with a dropped paragraph, a two-column page emitted in
reverse order, and a page with a fabricated sentence spliced into real text.

> **Note on the sample report:** the fixture corpus *simulates* engine output to demonstrate
> the mechanism. For a **real** captured fabrication — Marker inventing 58 words on a
> bleed-through page, caught by this tool — see the adversarial study in
> [study/README.md](study/README.md) and the [real-run demo report](docs/demo-report-marker.html).

## Development

```bash
uv sync
uv run pytest
```

The suite includes golden fixture tests that pin each documented behaviour, dispute-drill
tests for the non-detections — the cases where the tool must stay quiet — and regression
tests for every evasion a red team demonstrated against the witness-failure guards.

## License

MIT
