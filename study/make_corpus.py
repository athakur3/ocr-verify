"""Build the adversarial degradation corpus.

The point of this corpus is that **ground truth is known for every page**. Each
page starts as a passage we wrote ourselves, is rendered, and is then put through
a real degradation — genuine blur, genuine sensor noise, genuine JPEG artifacts,
genuine skew. So when an OCR engine emits a word, we can say with certainty
whether that word was on the page.

That gives the study two independent measurements instead of one:

  * **Did the engine fabricate?**  Words in its output that are absent from the
    ground truth. Measured against the truth, not against Tesseract, so it is
    not circular.
  * **Did ocr-verify catch it, and did it cry wolf?**  Recall against the real
    fabrications, and false positives against text that was genuinely there.

Blank pages are over-represented on purpose: 'engine invents prose on an empty
page' is the tool's headline claim, so it gets the most scrutiny.

Run: uv run python study/make_corpus.py
"""

from __future__ import annotations

import io
import json
import random
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).parent
OUT = ROOT / "corpus"
PDF = OUT / "corpus.pdf"
TRUTH = OUT / "ground_truth.json"

DPI = 200
PAGE_W_PT, PAGE_H_PT = 612, 792
PAGE_W = int(PAGE_W_PT * DPI / 72)
PAGE_H = int(PAGE_H_PT * DPI / 72)

SEED = 20260816  # fixed so the corpus is byte-reproducible

PASSAGES = {
    "survey": """The Survey of Coastal Stations

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
the summary telegrams remain in the commission archive.""",

    "tides": """Observations of the Tide

Tidal observations at Station Marlow were continued through the winter without
interruption. The gauge was of the float pattern, housed in a timber well sunk
four feet below the lowest recorded water. Readings were taken hourly by the
resident observer and transcribed each evening.

The self-registering apparatus failed twice during December, on both occasions
owing to the freezing of the float chamber. Manual readings were substituted
for the affected intervals and are marked accordingly in the published tables.

A comparison of the winter series with the corresponding series from the
preceding year shows agreement within two hundredths of a foot for the mean
water level, which the commission regarded as satisfactory.""",

    "instruments": """Notes upon the Instruments

The barometric readings were corrected for temperature by the standard tables.
Each observer recorded the dry-bulb and the wet-bulb temperature at the moment
of reading, and the corrections were applied during the reduction of the data.

Errors of the aneroid barometer were found to be systematic rather than random.
A correction curve was constructed for each instrument by comparison with the
mercurial standard kept at the observatory, and the curves are reproduced in
the appendix to this report.

Two chronometers were carried by each party. The rates were determined before
departure and verified upon return, and the mean of the two was adopted for all
longitude determinations.""",

    "conclusions": """Conclusions of the Commission

The commission concludes that the coastal survey achieved the greater part of
its stated objectives. Positions were fixed for eleven of the fourteen proposed
stations, and tidal series of at least six months were obtained at seven.

The loss of the third party's notebooks is regretted. The commission recommends
that duplicate records be transmitted by post at fortnightly intervals in all
future work of this character, and that no single vessel carry the whole of a
season's observations.

The commission further records its appreciation of the resident observers, whose
diligence under conditions of considerable hardship is evident throughout the
returns.""",
}

TWO_COLUMN = (
    """The northern division comprised four
stations, of which two were established
during the previous season and two were
newly built upon the recommendation of
the committee. Supplies were landed by
tender at each site before the onset of
the winter gales, and the parties
wintered ashore under canvas.""",
    """The southern division comprised only
three stations, the fourth having been
abandoned after the landslip of the
preceding autumn destroyed the hut and
the greater part of the stores. The
rebuilding was postponed until the
commission could examine the stability
of the slope above the landing.""",
)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def render(text: str, *, two_column: bool = False) -> Image.Image:
    """Render a passage to a clean grayscale page image."""
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE_W_PT, height=PAGE_H_PT)
    margin = 72
    if two_column:
        gutter = 24
        half = (PAGE_W_PT - 2 * margin - gutter) / 2
        page.insert_textbox(
            pymupdf.Rect(margin, margin, margin + half, PAGE_H_PT - margin),
            TWO_COLUMN[0], fontsize=12, fontname="times-roman",
        )
        page.insert_textbox(
            pymupdf.Rect(margin + half + gutter, margin, PAGE_W_PT - margin, PAGE_H_PT - margin),
            TWO_COLUMN[1], fontsize=12, fontname="times-roman",
        )
    elif text.strip():
        page.insert_textbox(
            pymupdf.Rect(margin, margin, PAGE_W_PT - margin, PAGE_H_PT - margin),
            text, fontsize=12, fontname="times-roman",
        )
    pix = page.get_pixmap(matrix=pymupdf.Matrix(DPI / 72, DPI / 72), colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    doc.close()
    return img


# --------------------------------------------------------------------------
# Degradations — every one of these is a real image operation
# --------------------------------------------------------------------------

def fade(img: Image.Image, amount: float) -> Image.Image:
    """Wash the page out, as a worn carbon copy or an exhausted toner drum would."""
    return ImageEnhance.Contrast(img).enhance(amount)


def blur(img: Image.Image, radius: float) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(radius))


def noise(img: Image.Image, sigma: float) -> Image.Image:
    """Additive zero-mean sensor noise.

    effect_noise centres its grain on 128, so it has to be offset back down or it
    darkens the whole page into uniform grey instead of speckling it.
    """
    grain = Image.effect_noise(img.size, sigma)
    return ImageChops.add(img, grain, scale=1.0, offset=-128)


def speckle(img: Image.Image, density: float, rng: random.Random) -> Image.Image:
    """Dust and scanner debris — isolated dark pixels on an otherwise clean field."""
    out = img.copy()
    draw = ImageDraw.Draw(out)
    count = int(img.width * img.height * density)
    for _ in range(count):
        x = rng.randrange(img.width)
        y = rng.randrange(img.height)
        r = rng.choice((0, 0, 0, 1, 1, 2))
        shade = rng.randrange(20, 140)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=shade)
    return out


def jpeg(img: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    img.convert("L").save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("L")


def skew(img: Image.Image, degrees: float) -> Image.Image:
    return img.rotate(degrees, resample=Image.BICUBIC, fillcolor=255, expand=False)


def low_dpi(img: Image.Image, factor: float) -> Image.Image:
    small = img.resize(
        (max(1, int(img.width * factor)), max(1, int(img.height * factor))), Image.BILINEAR
    )
    return small.resize(img.size, Image.BILINEAR)


def shadow(img: Image.Image, strength: float) -> Image.Image:
    """Uneven illumination from a book pressed against a flatbed.

    A gentle gradient toward one edge, not a black bar — the point is a page that
    still looks like paper, so that any text an engine reports on it is clearly
    invention rather than a plausible reading of a dark region.
    """
    depth = int(70 * strength)
    grad = Image.linear_gradient("L").rotate(90, expand=False).resize(img.size, Image.BILINEAR)
    grad = grad.point(lambda v: 255 - int(depth * (1 - v / 255)))
    return ImageChops.multiply(img, grad)


def bleed_through(img: Image.Image, ghost: Image.Image, strength: float) -> Image.Image:
    """Text from the reverse of a thin sheet, showing through mirrored and faint."""
    back = ghost.transpose(Image.FLIP_LEFT_RIGHT)
    back = ImageEnhance.Contrast(back).enhance(0.12)
    back = back.point(lambda v: min(255, int(255 - (255 - v) * strength)))
    return ImageChops.darker(img, back)


def blank() -> Image.Image:
    return Image.new("L", (PAGE_W, PAGE_H), 255)


# --------------------------------------------------------------------------
# The corpus
# --------------------------------------------------------------------------

def build_pages(rng: random.Random) -> list[tuple[str, str, Image.Image]]:
    """Return (kind, ground_truth_text, image) per page."""
    survey = render(PASSAGES["survey"])
    tides = render(PASSAGES["tides"])
    instruments = render(PASSAGES["instruments"])
    conclusions = render(PASSAGES["conclusions"])
    columns = render("", two_column=True)
    two_col_truth = TWO_COLUMN[0] + "\n\n" + TWO_COLUMN[1]

    pages: list[tuple[str, str, Image.Image]] = [
        # Controls — the engine should be perfect here, and so should we.
        ("clean", PASSAGES["survey"], survey),
        ("clean_two_column", two_col_truth, columns),

        # Blank pages: the headline claim. Nothing is on these. Anything the
        # engine emits beyond a page number is fabricated, by definition.
        ("blank_white", "", blank()),
        ("blank_speckle", "", speckle(blank(), 0.00035, rng)),
        ("blank_noise", "", noise(blank(), 16)),
        ("blank_shadow", "", shadow(blank(), 0.55)),
        ("blank_jpeg_artifacts", "", jpeg(noise(blank(), 10), 12)),
        ("blank_scanner_line", "", _scanner_line(blank(), rng)),

        # Progressive fade — text present but increasingly unreadable.
        ("fade_moderate", PASSAGES["tides"], fade(tides, 0.45)),
        ("fade_heavy", PASSAGES["tides"], fade(tides, 0.22)),
        ("fade_extreme", PASSAGES["tides"], fade(tides, 0.11)),

        # Blur.
        ("blur_light", PASSAGES["instruments"], blur(instruments, 1.2)),
        ("blur_heavy", PASSAGES["instruments"], blur(instruments, 2.8)),

        # Sensor noise.
        ("noise_moderate", PASSAGES["conclusions"], noise(conclusions, 28)),
        ("noise_heavy", PASSAGES["conclusions"], noise(conclusions, 48)),

        # Compression.
        ("jpeg_q20", PASSAGES["survey"], jpeg(survey, 20)),
        ("jpeg_q5", PASSAGES["survey"], jpeg(survey, 5)),

        # Geometry.
        ("skew_2deg", PASSAGES["tides"], skew(tides, 2.0)),
        ("skew_6deg", PASSAGES["tides"], skew(tides, 6.0)),
        ("low_dpi", PASSAGES["instruments"], low_dpi(instruments, 0.30)),

        # Physical-media artifacts.
        ("bleed_through", PASSAGES["conclusions"], bleed_through(conclusions, survey, 0.55)),

        # Realistic compound failures — a bad photocopy of a bad photocopy.
        ("combo_photocopy", PASSAGES["survey"],
         jpeg(skew(noise(fade(survey, 0.35), 22), 1.5), 25)),
        ("combo_severe", PASSAGES["tides"],
         jpeg(low_dpi(blur(fade(tides, 0.20), 1.6), 0.45), 15)),
        ("combo_two_column", two_col_truth,
         jpeg(noise(fade(columns, 0.40), 20), 22)),
    ]
    return pages


def _scanner_line(img: Image.Image, rng: random.Random) -> Image.Image:
    """A blank page with a single dark scan-head streak — a classic false-positive trap."""
    out = img.copy()
    draw = ImageDraw.Draw(out)
    y = rng.randrange(int(img.height * 0.3), int(img.height * 0.7))
    draw.rectangle((0, y, img.width, y + 3), fill=60)
    return speckle(out, 0.00008, rng)


def build() -> None:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    pages = build_pages(rng)

    doc = pymupdf.open()
    truth = []
    for number, (kind, text, img) in enumerate(pages, start=1):
        buf = io.BytesIO()
        img.convert("L").save(buf, format="PNG")
        page = doc.new_page(width=PAGE_W_PT, height=PAGE_H_PT)
        page.insert_image(pymupdf.Rect(0, 0, PAGE_W_PT, PAGE_H_PT), stream=buf.getvalue())
        truth.append({"page": number, "kind": kind, "text": text.strip()})

    doc.save(PDF, deflate=True)
    doc.close()

    TRUTH.write_text(json.dumps({"dpi": DPI, "seed": SEED, "pages": truth}, indent=2), "utf-8")

    blanks = sum(1 for p in truth if not p["text"])
    print(f"wrote {PDF} — {len(truth)} pages ({blanks} blank, {len(truth) - blanks} with text)")
    print(f"wrote {TRUTH}")


if __name__ == "__main__":
    build()
