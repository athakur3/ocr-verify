"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .align import Settings, compare_page
from .ingest import IngestError, load_vlm_output
from .model import ACCUSATORY_KINDS, KIND_BLURBS, KIND_LABELS, PageResult, Report, VlmPage
from .render import page_count, render_pdf
from .report import write_report
from .witness import TesseractMissing, run_witness, tesseract_version

EXIT_OK = 0
EXIT_FLAGGED = 1  # findings above --fail-on; the CI gate
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ocr-verify",
        description=(
            "Verify a vision-language OCR engine's output against a deterministic "
            "Tesseract witness, and report where they disagree."
        ),
        epilog=(
            "exit codes: 0 clean, 1 findings above --fail-on, 2 error.\n"
            "example: ocr-verify book.pdf marker_output/ -o report.html --fail-on 0.02"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("pdf", type=Path, help="source PDF the AI engine was run on")
    p.add_argument(
        "engine_output",
        type=Path,
        help="the AI engine's output: a directory of per-page .md/.txt, a single "
        "markdown file with page markers, or .jsonl/.json",
    )
    p.add_argument("-o", "--out", type=Path, default=Path("ocr-verify-report.html"),
                   help="HTML report path (default: ocr-verify-report.html)")
    p.add_argument("--json", type=Path, default=None, help="also write machine-readable findings here")
    p.add_argument("--sarif", type=Path, default=None,
                   help="also write findings as SARIF 2.1.0, for GitHub code scanning / CI dashboards")
    p.add_argument("--engine-label", default="AI engine", help="name of the engine under test, for the report")
    p.add_argument("--dpi", type=int, default=200, help="rasterization DPI (default: 200)")
    p.add_argument("--lang", default="eng", help="Tesseract language (default: eng)")
    p.add_argument("--psm", type=int, default=3, help="Tesseract page segmentation mode (default: 3)")
    p.add_argument("--min-conf", type=float, default=40.0,
                   help="ignore witness words below this confidence (default: 40)")
    p.add_argument("--min-run", type=int, default=3,
                   help="divergent tokens required to raise a finding (default: 3)")
    p.add_argument("--pages", default=None, help="subset to check, e.g. 1,4,7-9")
    p.add_argument("--fail-on", type=float, default=None, metavar="RATIO",
                   help="exit 1 if overall divergence exceeds this (e.g. 0.02)")
    p.add_argument("--max-unverified", type=float, default=0.25, metavar="RATIO",
                   help="with --fail-on: also exit 1 if more than this share of AI words "
                   "sits on pages the witness could not verify (default: 0.25). Hedged "
                   "pages must never be a free pass.")
    p.add_argument("--workers", type=int, default=4, help="parallel Tesseract workers (default: 4)")
    p.add_argument("--keep-images", type=Path, default=None, help="save rendered page PNGs here")
    p.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")
    p.add_argument("--version", action="version", version=f"ocr-verify {__version__}")
    return p


def parse_pages(spec: str | None, total: int) -> list[int] | None:
    """Parse a 1-based page spec into 0-based indices."""
    if not spec:
        return None
    out: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            a, _, b = chunk.partition("-")
            try:
                start, end = int(a), int(b)
            except ValueError:
                raise ValueError(f"bad page range {chunk!r}") from None
            if start > end:
                raise ValueError(f"page range {chunk!r} runs backwards")
            out.extend(range(start - 1, end))
        else:
            try:
                out.append(int(chunk) - 1)
            except ValueError:
                raise ValueError(f"bad page number {chunk!r}") from None
    bad = [i + 1 for i in out if i < 0 or i >= total]
    if bad:
        raise ValueError(f"page(s) {bad} out of range; document has {total} pages")
    return sorted(set(out))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda *a: None) if args.quiet else (lambda *a: print(*a, file=sys.stderr))

    try:
        if not args.pdf.exists():
            raise FileNotFoundError(f"PDF not found: {args.pdf}")
        total = page_count(args.pdf)
        wanted = parse_pages(args.pages, total)

        # Page indices are how findings are addressed; a subset must still line up
        # with the engine's own numbering, so we load the full output either way.
        vlm_pages = load_vlm_output(args.engine_output, total)
        by_index: dict[int, VlmPage] = {p.index: p for p in vlm_pages}

        targets = wanted if wanted is not None else list(range(total))
        log(f"ocr-verify {__version__} — {tesseract_version()}")
        log(f"checking {len(targets)} of {total} page(s) at {args.dpi} DPI")

        cfg = Settings(min_conf=args.min_conf, min_run=args.min_run)

        with tempfile.TemporaryDirectory(prefix="ocr-verify-") as tmp:
            work = Path(tmp)
            images = render_pdf(args.pdf, work, dpi=args.dpi, pages=targets)

            def check(pair: tuple[int, Path]) -> PageResult:
                index, image = pair
                witness = run_witness(image, index, lang=args.lang, psm=args.psm)
                vlm = by_index.get(index) or VlmPage(index=index, text="", source="(missing)")
                return compare_page(witness, vlm, cfg)

            workers = max(1, args.workers)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(check, zip(targets, images)))
            results.sort(key=lambda r: r.index)

            for r in results:
                if r.findings:
                    kinds = ", ".join(
                        sorted({KIND_LABELS[f.kind].lower() for f in r.findings})
                    )
                    log(f"  page {r.index + 1}: {r.divergence * 100:5.1f}% divergence — {kinds}")

            if args.keep_images:
                args.keep_images.mkdir(parents=True, exist_ok=True)
                for r in results:
                    if r.image:
                        dest = args.keep_images / Path(r.image).name
                        shutil.copy2(r.image, dest)
                        r.image = dest

            report = Report(
                pdf=args.pdf,
                vlm_source=args.engine_output,
                pages=results,
                dpi=args.dpi,
                min_conf=args.min_conf,
                engine_label=args.engine_label,
                generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                version=__version__,
            )
            # Crops are read from the rendered PNGs, so the report must be written
            # before the temporary directory goes away.
            write_report(report, args.out)

        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(_as_dict(report), indent=2), encoding="utf-8")

        if args.sarif:
            args.sarif.parent.mkdir(parents=True, exist_ok=True)
            args.sarif.write_text(json.dumps(_as_sarif(report), indent=2), encoding="utf-8")

        # Only pages the witness could actually cover count toward the gate:
        # failing a build because the witness went blind on a noisy page would
        # punish the AI engine for Tesseract's weakness.
        verified = [p for p in results if p.verified]
        unverified = [p for p in results if not p.verified]
        total_words = sum(p.vlm_words for p in verified)
        unsupported = sum(p.vlm_only for p in verified)
        overall = unsupported / total_words if total_words else 0.0
        flagged = [p for p in results if p.findings]

        log("")
        log(f"{len(flagged)} of {len(results)} page(s) flagged; "
            f"{unsupported:,} of {total_words:,} AI words unsupported ({overall * 100:.2f}%) "
            f"across {len(verified)} verified page(s)")
        if unverified:
            log(f"{len(unverified)} page(s) could not be verified (witness failed) — "
                f"excluded from the gate, listed in the report")
        log(f"report: {args.out}")
        if args.json:
            log(f"json:   {args.json}")
        if args.sarif:
            log(f"sarif:  {args.sarif}")

        if args.fail_on is not None:
            if overall > args.fail_on:
                log(f"FAIL: divergence {overall * 100:.2f}% exceeds --fail-on "
                    f"{args.fail_on * 100:.2f}%")
                return EXIT_FLAGGED
            # Unverified pages are excluded from the divergence metric, so they
            # need their own budget — otherwise an engine could pass the gate by
            # being unverifiable, which is exactly backwards.
            all_words = total_words + sum(p.vlm_words for p in unverified)
            unverified_words = sum(p.vlm_words for p in unverified)
            unverified_share = unverified_words / all_words if all_words else 0.0
            if unverified_share > args.max_unverified:
                log(f"FAIL: {unverified_share * 100:.1f}% of AI words sit on unverifiable "
                    f"pages (limit {args.max_unverified * 100:.0f}%, --max-unverified)")
                return EXIT_FLAGGED
        return EXIT_OK

    except (TesseractMissing, IngestError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_ERROR


def _as_dict(report: Report) -> dict:
    return {
        "tool": "ocr-verify",
        "version": report.version,
        "generated": report.generated,
        "pdf": str(report.pdf),
        "engine_output": str(report.vlm_source),
        "engine_label": report.engine_label,
        "dpi": report.dpi,
        "min_conf": report.min_conf,
        "pages": [
            {
                "page": p.index + 1,
                "divergence": round(p.divergence, 6),
                "vlm_words": p.vlm_words,
                "witness_words": p.witness_words,
                "unsupported_words": p.vlm_only,
                "dropped_words": p.witness_only,
                "ink_ratio": round(p.ink_ratio, 6),
                "witness_quality": p.witness_quality,
                "verified": p.verified,
                "findings": [
                    {
                        "kind": f.kind,
                        "severity": round(f.severity, 4),
                        "tokens": f.n_tokens,
                        "bbox": list(f.bbox) if f.bbox else None,
                        "vlm_text": f.vlm_text,
                        "witness_text": f.witness_text,
                        "note": f.note,
                    }
                    for f in p.findings
                ],
            }
            for p in report.pages
        ],
    }


def _sarif_level(kind: str, hedged: bool) -> str:
    """Map a finding to a SARIF result level.

    Mirrors the model's own distinction (see model.py's ACCUSATORY_KINDS comment):
    an accusation the witness cannot fully back is a warning, not an error, and a
    coverage gap (unverifiable_page) is a note, never an accusation at all.
    """
    if kind == "unverifiable_page":
        return "note"
    if kind in ACCUSATORY_KINDS:
        return "warning" if hedged else "error"
    return "warning"


def _as_sarif(report: Report) -> dict:
    """SARIF 2.1.0, for GitHub code scanning uploads and other CI dashboards.

    Locations point at the source PDF; there is no line number for a scanned
    page, so the page number fills `region.startLine` (SARIF requires the field
    if a region is present at all) and is repeated in `properties` for tools
    that read structured data instead.
    """
    pdf_uri = Path(report.pdf).as_posix()
    rules = [
        {
            "id": kind,
            "name": label.replace(" ", "").replace("-", ""),
            "shortDescription": {"text": label},
            "fullDescription": {"text": KIND_BLURBS[kind]},
            "defaultConfiguration": {"level": _sarif_level(kind, hedged=False)},
        }
        for kind, label in KIND_LABELS.items()
    ]
    results = [
        {
            "ruleId": f.kind,
            "level": _sarif_level(f.kind, hedged=bool(f.note)),
            "message": {"text": f.note or f"{KIND_LABELS[f.kind]}: {f.vlm_text!r}"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": pdf_uri},
                        "region": {"startLine": p.index + 1},
                    }
                }
            ],
            "properties": {
                "page": p.index + 1,
                "severity": round(f.severity, 4),
                "tokens": f.n_tokens,
                "vlm_text": f.vlm_text,
                "witness_text": f.witness_text,
            },
        }
        for p in report.pages
        for f in p.findings
    ]
    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ocr-verify",
                        "version": report.version,
                        "informationUri": "https://github.com/athakur3/ocr-verify",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
