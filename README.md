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
```

### In CI

`--fail-on` turns the tool into a quality gate. Exit codes: `0` clean, `1` over threshold,
`2` error.

```bash
ocr-verify book.pdf out/ -o report.html --fail-on 0.02   # fail above 2% divergence
```

```yaml
- name: Verify OCR output
  run: ocr-verify corpus/doc.pdf ocr-out/ -o report.html --fail-on 0.02
- uses: actions/upload-artifact@v4
  if: always()
  with: { name: ocr-verify-report, path: report.html }
```

## What it reports

| Finding | Meaning |
| --- | --- |
| **Blank-page fabrication** | Effectively no ink on the page, yet the engine emitted running text. The clearest signature there is. |
| **Unsupported text** | The engine emitted words absent from the witness reading of the whole page — not moved, absent. |
| **Dropped text** | The witness read words the engine never emitted. Usually a skipped line, column, or caption. |
| **Disagreement** | Both engines read text here and disagree on the words. Mostly OCR noise; occasionally a rewrite. |

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

Two more rules keep the signal clean:

- Witness words below `--min-conf` (default 40) are excluded from the comparison entirely —
  the tool never argues from evidence the witness itself does not believe.
- Glyph-level misreads are folded before comparison: `m`/`rn`, `vv`/`w`, `cl`/`d`, `0`/`o`,
  `1`/`l`. `barorneter` and `barometer` are one word seen by two recognizers, and counting
  that as a fabrication would bury the real findings.

## Limitations — read these before quoting a number

- **Agreement is not correctness.** Both engines can be wrong together, most easily on the
  degraded pages where the witness is also weak. A clean report is evidence, not proof.
- **The witness is weak on handwriting, dense layout, tables, and low-contrast scans.** Pages
  where Tesseract struggled are labelled `witness quality: low` and their findings are hedged
  in the score. On a fully handwritten corpus this tool has little to say.
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

> **Note on the sample report:** the fixture corpus *simulates* engine output rather than being
> produced by a live run of DeepSeek-OCR or Marker. It demonstrates the mechanism honestly, but
> it is not a captured real-world fabrication. Replacing it with a real one is the next task —
> see [HANDOFF.md](HANDOFF.md).

## Development

```bash
uv sync
uv run pytest          # 74 tests
```

The suite includes golden fixture tests that pin each documented behaviour, and dispute-drill
tests for the non-detections — the cases where the tool must stay quiet.

## License

MIT
