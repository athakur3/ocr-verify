"""Generate the golden fixture corpus.

Five pages, each isolating one behaviour the tool must get right. Two of them are
detections; one of them — the reordered two-column page — is a *non*-detection,
and it is the most important test in the suite. A verification tool that cries
wolf on every multi-column scan is worse than no tool at all.

Run: uv run python fixtures/make_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).parent
PDF = ROOT / "sample.pdf"
ENGINE = ROOT / "engine_output"

PAGE_W, PAGE_H = 612, 792  # US Letter at 72dpi
MARGIN = 72
FONT = "times-roman"
SIZE = 12

# --- Page 1: clean. Both engines should agree. ------------------------------
P1 = """Chapter One: The Survey of Coastal Stations

In the summer of 1897 the commission dispatched three parties to survey the
northern coastal stations. Each party carried a theodolite, two chronometers,
and a barometer of the aneroid pattern. The instruments were compared at the
observatory before departure and again upon return.

The first party reached Station Marlow on the fourteenth of June. Weather
conditions were poor for eleven consecutive days, and the observations taken
during that interval were later discarded as unreliable. The second party,
working southward from Cape Ellery, fared considerably better.

Readings from the third party have not survived. The field notebooks were lost
when the supply vessel foundered off the shoals in early September, and only
the summary telegrams remain in the commission archive."""

# --- Page 2: BLANK. The engine invents a page of prose. ---------------------
P2 = ""

P2_FABRICATED = """Chapter Two: Instrumentation and Method

The barometric readings were corrected for temperature using the standard
tables published by the Bureau in 1889. Each observer recorded the dry-bulb
and wet-bulb temperatures at the moment of reading, and the corrections were
applied during the reduction of the data at headquarters.

Errors of the aneroid barometer were found to be systematic rather than random,
and a correction curve was constructed for each instrument."""

# --- Page 3: engine drops the middle paragraph. ----------------------------
P3_PARAS = [
    """Chapter Three: The Tidal Observations

Tidal observations at Station Marlow were continued through the winter of
1897 without interruption. The gauge was of the float pattern, housed in a
timber well sunk four feet below the lowest recorded water.""",
    """The self-registering apparatus failed twice during December, on both
occasions owing to the freezing of the float chamber. Manual readings were
substituted for the affected intervals and are marked accordingly in the
published tables of the commission.""",
    """A comparison of the winter series with the corresponding series from the
preceding year shows agreement within two hundredths of a foot for the mean
water level, which the commission regarded as satisfactory.""",
]

# --- Page 4: two columns. The engine reads them right-to-left. -------------
P4_LEFT = """The northern division comprised
four stations, of which two were
established during the previous
season and two were newly built
upon the recommendation of the
committee. Supplies were landed
by tender at each site before the
onset of the winter gales, and
the parties wintered ashore."""

P4_RIGHT = """The southern division comprised
only three stations, the fourth
having been abandoned after the
landslip of the preceding autumn
destroyed the observation hut and
the greater part of the stores.
Rebuilding was postponed until
the commission could examine the
stability of the slope above."""

# --- Page 5: engine inserts a plausible fabricated sentence. ---------------
P5_REAL = """Chapter Five: Conclusions of the Commission

The commission concludes that the coastal survey of 1897 achieved the greater
part of its stated objectives. Positions were fixed for eleven of the fourteen
proposed stations, and tidal series of at least six months were obtained at
seven of them.

The loss of the third party's notebooks is regretted. The commission recommends
that duplicate records be transmitted by post at fortnightly intervals in all
future work of this character, and that no single vessel carry the whole of a
season's observations."""

P5_FABRICATION = (
    "The commission further resolved that a permanent magnetic observatory be "
    "established at Cape Ellery in the following season, with an annual grant of "
    "four hundred pounds charged to the hydrographic vote."
)


def _text_page(doc: fitz.Document, body: str) -> None:
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    if body.strip():
        rect = fitz.Rect(MARGIN, MARGIN, PAGE_W - MARGIN, PAGE_H - MARGIN)
        page.insert_textbox(rect, body, fontsize=SIZE, fontname=FONT, align=0)


def _two_column_page(doc: fitz.Document, left: str, right: str) -> None:
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    gutter = 24
    half = (PAGE_W - 2 * MARGIN - gutter) / 2
    page.insert_textbox(
        fitz.Rect(MARGIN, MARGIN, MARGIN + half, PAGE_H - MARGIN),
        left, fontsize=SIZE, fontname=FONT,
    )
    page.insert_textbox(
        fitz.Rect(MARGIN + half + gutter, MARGIN, PAGE_W - MARGIN, PAGE_H - MARGIN),
        right, fontsize=SIZE, fontname=FONT,
    )


def build() -> None:
    doc = fitz.open()
    _text_page(doc, P1)
    _text_page(doc, P2)  # blank
    _text_page(doc, "\n\n".join(P3_PARAS))
    _two_column_page(doc, P4_LEFT, P4_RIGHT)

    p5 = P5_REAL.split("\n\n")
    _text_page(doc, "\n\n".join(p5))

    doc.save(PDF)
    doc.close()

    ENGINE.mkdir(parents=True, exist_ok=True)
    for old in ENGINE.glob("page_*.md"):
        old.unlink()

    # What a hallucinating engine would have produced for this PDF.
    pages = {
        1: P1,
        2: P2_FABRICATED,  # invented wholesale on a blank page
        3: "\n\n".join([P3_PARAS[0], P3_PARAS[2]]),  # middle paragraph dropped
        4: P4_RIGHT + "\n\n" + P4_LEFT,  # correct text, opposite column order
        5: _insert_fabrication(P5_REAL, P5_FABRICATION),
    }
    for number, text in pages.items():
        (ENGINE / f"page_{number:03d}.md").write_text(text.strip() + "\n", encoding="utf-8")

    print(f"wrote {PDF}")
    print(f"wrote {len(pages)} page files to {ENGINE}")


def _insert_fabrication(body: str, sentence: str) -> str:
    paras = body.split("\n\n")
    paras.insert(2, sentence)
    return "\n\n".join(paras)


if __name__ == "__main__":
    build()
