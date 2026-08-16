"""Self-contained HTML report.

The report is the product. A verdict nobody can check is worth nothing, so every
finding ships with the crop of the scan it came from and both engines' readings
of that same region — enough for a reader to overrule the tool in one glance.
"""

from __future__ import annotations

import base64
import html
import io
from pathlib import Path

from .model import (
    BLANK_PAGE_FABRICATION,
    DROPPED_TEXT,
    KIND_BLURBS,
    KIND_LABELS,
    SUBSTITUTION,
    UNSUPPORTED_TEXT,
    Finding,
    PageResult,
    Report,
)

MAX_CROP_WIDTH = 1100
MAX_PAGE_HEIGHT = 620

KIND_ORDER = [BLANK_PAGE_FABRICATION, UNSUPPORTED_TEXT, DROPPED_TEXT, SUBSTITUTION]


def write_report(report: Report, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_render(report), encoding="utf-8")
    return out


def _crop_data_uri(page: PageResult, finding: Finding) -> str | None:
    if page.image is None or not Path(page.image).exists():
        return None
    from PIL import Image

    try:
        with Image.open(page.image) as im:
            im = im.convert("L")
            if finding.bbox is None:
                crop = im.copy()
                if crop.height > MAX_PAGE_HEIGHT:
                    scale = MAX_PAGE_HEIGHT / crop.height
                    crop = crop.resize(
                        (max(1, int(crop.width * scale)), MAX_PAGE_HEIGHT), Image.LANCZOS
                    )
            else:
                crop = im.crop(finding.bbox)
                if crop.width > MAX_CROP_WIDTH:
                    scale = MAX_CROP_WIDTH / crop.width
                    crop = crop.resize(
                        (MAX_CROP_WIDTH, max(1, int(crop.height * scale))), Image.LANCZOS
                    )
            buf = io.BytesIO()
            crop.save(buf, format="PNG", optimize=True)
    except OSError:
        return None
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _e(text: str) -> str:
    return html.escape(text or "")


def _render(report: Report) -> str:
    pages = report.pages
    flagged = sorted(
        report.flagged_pages,
        key=lambda p: (-max((f.severity for f in p.findings), default=0), p.index),
    )
    findings = report.findings
    counts = {k: sum(1 for f in findings if f.kind == k) for k in KIND_ORDER}
    total_vlm_words = sum(p.vlm_words for p in pages)
    total_unsupported = sum(p.vlm_only for p in pages)
    overall = (total_unsupported / total_vlm_words) if total_vlm_words else 0.0

    parts: list[str] = [
        _HEAD.format(title=_e(report.pdf.name)),
        _header(report),
        _summary(report, flagged, counts, overall, total_unsupported, total_vlm_words),
        _method(report),
    ]

    if flagged:
        parts.append('<section class="findings"><h2>Flagged pages</h2>')
        for page in flagged:
            parts.append(_page_block(page, report))
        parts.append("</section>")
    else:
        parts.append(
            '<section class="clean-note"><h2>No divergences above threshold</h2>'
            "<p>The witness engine supports every word the AI engine emitted, on every page "
            "checked. That is evidence of agreement, not proof of correctness: two engines can "
            "be wrong together, and the witness is weak on handwriting and heavy layout.</p>"
            "</section>"
        )

    parts.append(_page_table(pages))
    parts.append(_FOOT.format(version=_e(report.version), generated=_e(report.generated)))
    return "\n".join(parts)


def _header(report: Report) -> str:
    return f"""
<header>
  <div class="brand">ocr-verify</div>
  <h1>{_e(report.pdf.name)}</h1>
  <p class="sub">
    Witness reading (Tesseract) vs <strong>{_e(report.engine_label)}</strong>
    &middot; {len(report.pages)} page{"s" if len(report.pages) != 1 else ""} checked
    &middot; rendered at {report.dpi} DPI
  </p>
  <p class="paths">
    <span>PDF <code>{_e(str(report.pdf))}</code></span>
    <span>AI output <code>{_e(str(report.vlm_source))}</code></span>
  </p>
</header>"""


def _summary(
    report: Report,
    flagged: list[PageResult],
    counts: dict[str, int],
    overall: float,
    unsupported: int,
    total_words: int,
) -> str:
    tiles = [
        ("Pages flagged", f"{len(flagged)}", f"of {len(report.pages)}"),
        ("Unsupported words", f"{unsupported:,}", f"of {total_words:,} emitted"),
        ("Divergence", f"{overall * 100:.2f}%", "AI words the witness cannot place"),
    ]
    tile_html = "".join(
        f'<div class="tile"><div class="tile-v">{_e(v)}</div>'
        f'<div class="tile-k">{_e(k)}</div><div class="tile-n">{_e(n)}</div></div>'
        for k, v, n in tiles
    )
    chips = "".join(
        f'<span class="chip chip-{_e(kind)}">{_e(KIND_LABELS[kind])}<b>{counts[kind]}</b></span>'
        for kind in KIND_ORDER
        if counts.get(kind)
    )
    chip_block = f'<div class="chips">{chips}</div>' if chips else ""
    return f'<section class="summary"><div class="tiles">{tile_html}</div>{chip_block}</section>'


def _method(report: Report) -> str:
    return f"""
<section class="method">
  <h2>How to read this</h2>
  <p>
    Tesseract read every page independently as a <em>witness</em>. It is not the ground
    truth &mdash; it is worse than the AI engine at almost everything. It has one property the
    AI engine lacks: it does not invent words. Each finding below is a place the two readings
    diverge, shown with the crop of the scan it came from.
  </p>
  <ul>
    <li><b>{KIND_LABELS[BLANK_PAGE_FABRICATION]}</b> &mdash; {KIND_BLURBS[BLANK_PAGE_FABRICATION]}</li>
    <li><b>{KIND_LABELS[UNSUPPORTED_TEXT]}</b> &mdash; {KIND_BLURBS[UNSUPPORTED_TEXT]}</li>
    <li><b>{KIND_LABELS[DROPPED_TEXT]}</b> &mdash; {KIND_BLURBS[DROPPED_TEXT]}</li>
    <li><b>{KIND_LABELS[SUBSTITUTION]}</b> &mdash; {KIND_BLURBS[SUBSTITUTION]}</li>
  </ul>
  <p class="caveat">
    Text merely <em>moved</em> on the page &mdash; reordered columns, floated captions, table
    cells read in a different sequence &mdash; is not reported: a word counts as unsupported
    only when it is absent from the witness reading of the whole page. Words below
    {report.min_conf:.0f}% witness confidence are excluded from the comparison entirely.
    Pages where the witness itself struggled are labelled, and their findings are hedged.
  </p>
</section>"""


def _page_block(page: PageResult, report: Report) -> str:
    quality = (
        '<span class="badge badge-low">witness quality: low</span>'
        if page.witness_quality == "low"
        else ""
    )
    head = f"""
  <div class="page-head">
    <h3>Page {page.index + 1}</h3>
    <div class="page-meta">
      <span class="badge">divergence {page.divergence * 100:.1f}%</span>
      <span class="badge">{page.vlm_words:,} AI words</span>
      <span class="badge">{page.witness_words:,} witness words</span>
      <span class="badge">ink {page.ink_ratio * 100:.2f}%</span>
      {quality}
    </div>
  </div>"""
    blocks = "".join(_finding_block(page, f) for f in page.findings)
    return f'<article class="page" id="page-{page.index + 1}">{head}{blocks}</article>'


def _finding_block(page: PageResult, finding: Finding) -> str:
    uri = _crop_data_uri(page, finding)
    if uri:
        caption = (
            "full page" if finding.bbox is None else f"crop at {finding.bbox[0]},{finding.bbox[1]}"
        )
        image = (
            f'<figure class="crop"><img src="{uri}" alt="Scan region for this finding">'
            f"<figcaption>Scan &mdash; {_e(caption)}</figcaption></figure>"
        )
    else:
        image = '<div class="crop missing">Scan region unavailable</div>'

    vlm_body = _e(finding.vlm_text) or '<span class="empty">(nothing)</span>'
    if finding.context_before or finding.context_after:
        vlm_body = (
            f'<span class="ctx">{_e(finding.context_before)}</span> '
            f'<mark>{vlm_body}</mark> '
            f'<span class="ctx">{_e(finding.context_after)}</span>'
        )
    witness_body = _e(finding.witness_text) or (
        '<span class="empty">(the witness read nothing here)</span>'
    )
    note = f'<p class="note">{_e(finding.note)}</p>' if finding.note else ""

    return f"""
  <div class="finding f-{_e(finding.kind)}">
    <div class="f-head">
      <span class="kind">{_e(finding.label)}</span>
      <span class="sev" title="severity">{finding.severity:.2f}</span>
      <span class="ntok">{finding.n_tokens} token{"s" if finding.n_tokens != 1 else ""}</span>
    </div>
    {image}
    <div class="readings">
      <div class="reading vlm"><h4>AI engine read</h4><p>{vlm_body}</p></div>
      <div class="reading wit"><h4>Witness read</h4><p>{witness_body}</p></div>
    </div>
    {note}
  </div>"""


def _page_table(pages: list[PageResult]) -> str:
    rows = []
    for p in pages:
        cls = "row-flag" if p.flagged else ""
        link = f'<a href="#page-{p.index + 1}">{p.index + 1}</a>' if p.flagged else str(p.index + 1)
        rows.append(
            f'<tr class="{cls}"><td>{link}</td>'
            f"<td>{p.divergence * 100:.1f}%</td>"
            f"<td>{p.vlm_words:,}</td><td>{p.witness_words:,}</td>"
            f"<td>{p.vlm_only:,}</td><td>{p.witness_only:,}</td>"
            f"<td>{p.ink_ratio * 100:.2f}%</td>"
            f"<td>{_e(p.witness_quality)}</td>"
            f"<td>{len(p.findings)}</td></tr>"
        )
    return f"""
<section class="all-pages">
  <h2>Every page</h2>
  <div class="table-wrap">
  <table>
    <thead><tr>
      <th>Page</th><th>Divergence</th><th>AI words</th><th>Witness words</th>
      <th>Unsupported</th><th>Dropped</th><th>Ink</th><th>Witness</th><th>Findings</th>
    </tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
  </div>
</section>"""


_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ocr-verify — {title}</title>
<style>
  :root {{
    --bg: #fbfaf8; --panel: #ffffff; --ink: #1b1a18; --muted: #6b6862;
    --line: #e3e0da; --accent: #7a2e2e; --warn: #8a5a12; --ok: #2f6b45;
    --mark: #fdeaea; --code: #f4f2ee;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #14140f; --panel: #1c1c19; --ink: #eceae4; --muted: #9d9a92;
      --line: #302f2a; --accent: #e0908c; --warn: #d9a95a; --ok: #7ec39a;
      --mark: #3a2020; --code: #232320;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font: 16px/1.6 ui-serif, Georgia, "Iowan Old Style", serif;
  }}
  .wrap, header, section {{ max-width: 1000px; margin: 0 auto; padding: 0 24px; }}
  header {{ padding-top: 48px; padding-bottom: 8px; }}
  .brand {{
    font: 600 12px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
    letter-spacing: .18em; text-transform: uppercase; color: var(--accent);
  }}
  h1 {{ font-size: 34px; line-height: 1.2; margin: 10px 0 6px; font-weight: 600; }}
  h2 {{ font-size: 20px; margin: 40px 0 12px; font-weight: 600; }}
  h3 {{ font-size: 19px; margin: 0; font-weight: 600; }}
  h4 {{
    font: 600 11px/1 ui-monospace, SFMono-Regular, Menlo, monospace;
    letter-spacing: .12em; text-transform: uppercase; color: var(--muted);
    margin: 0 0 8px;
  }}
  .sub {{ color: var(--muted); margin: 0 0 10px; }}
  .paths {{ margin: 0; display: flex; flex-wrap: wrap; gap: 8px 18px; font-size: 13px; }}
  .paths span {{ color: var(--muted); }}
  code {{
    font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
    background: var(--code); padding: 2px 6px; border-radius: 4px;
  }}
  .tiles {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 28px; }}
  .tile {{
    flex: 1 1 200px; background: var(--panel); border: 1px solid var(--line);
    border-radius: 10px; padding: 18px 20px;
  }}
  .tile-v {{ font-size: 30px; font-weight: 600; line-height: 1.1; }}
  .tile-k {{ font-size: 14px; margin-top: 4px; }}
  .tile-n {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }}
  .chip {{
    font-size: 13px; border: 1px solid var(--line); background: var(--panel);
    border-radius: 999px; padding: 5px 12px;
  }}
  .chip b {{ margin-left: 8px; }}
  .chip-blank_page_fabrication {{ border-color: var(--accent); color: var(--accent); }}
  .chip-unsupported_text {{ border-color: var(--accent); }}
  .chip-dropped_text {{ border-color: var(--warn); }}
  .method p, .method li {{ color: var(--ink); }}
  .method ul {{ padding-left: 20px; }}
  .method li {{ margin-bottom: 6px; }}
  .caveat {{ color: var(--muted); font-size: 14px; border-left: 3px solid var(--line); padding-left: 14px; }}
  .page {{
    background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
    padding: 22px; margin-bottom: 22px;
  }}
  .page-head {{
    display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between;
    gap: 10px; border-bottom: 1px solid var(--line); padding-bottom: 12px; margin-bottom: 4px;
  }}
  .page-meta {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .badge {{
    font: 11px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;
    background: var(--code); color: var(--muted); border-radius: 5px; padding: 2px 8px;
  }}
  .badge-low {{ color: var(--warn); }}
  .finding {{ border-top: 1px solid var(--line); padding-top: 18px; margin-top: 18px; }}
  .finding:first-of-type {{ border-top: none; }}
  .f-head {{ display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }}
  .kind {{ font-weight: 600; }}
  .f-blank_page_fabrication .kind, .f-unsupported_text .kind {{ color: var(--accent); }}
  .f-dropped_text .kind {{ color: var(--warn); }}
  .sev, .ntok {{
    font: 11px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--muted);
    background: var(--code); border-radius: 5px; padding: 2px 8px;
  }}
  .crop {{ margin: 0 0 14px; }}
  .crop img {{
    display: block; max-width: 100%; height: auto; border: 1px solid var(--line);
    border-radius: 6px; background: #fff;
  }}
  .crop figcaption {{
    font: 11px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;
    color: var(--muted); margin-top: 6px;
  }}
  .crop.missing {{ color: var(--muted); font-size: 13px; }}
  .readings {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
  @media (max-width: 720px) {{ .readings {{ grid-template-columns: 1fr; }} }}
  .reading {{ background: var(--code); border-radius: 8px; padding: 14px 16px; }}
  .reading p {{ margin: 0; }}
  .reading.vlm mark {{ background: var(--mark); color: var(--ink); padding: 1px 2px; }}
  .ctx {{ color: var(--muted); }}
  .empty {{ color: var(--muted); font-style: italic; }}
  .note {{
    font-size: 13px; color: var(--warn); margin: 12px 0 0;
    border-left: 3px solid var(--warn); padding-left: 12px;
  }}
  .table-wrap {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
  th, td {{ text-align: right; padding: 7px 10px; border-bottom: 1px solid var(--line); }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{
    font: 600 11px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;
    text-transform: uppercase; letter-spacing: .08em; color: var(--muted);
  }}
  .row-flag td {{ font-weight: 600; }}
  .row-flag a {{ color: var(--accent); }}
  footer {{
    max-width: 1000px; margin: 48px auto 60px; padding: 20px 24px 0;
    border-top: 1px solid var(--line); color: var(--muted); font-size: 13px;
  }}
</style>
</head>
<body>"""


_FOOT = """
<footer>
  <p>Generated by <strong>ocr-verify</strong> v{version} &middot; {generated}.
  The witness engine is a check, not an oracle: it is weak on handwriting, dense layout and
  low-contrast scans, and agreement between two engines is not proof of correctness.</p>
</footer>
</body>
</html>"""
