from __future__ import annotations

from ocr_verify.normalize import (
    near_miss,
    short_misread,
    normalize_token,
    ocr_skeleton,
    split_pages,
    strip_markup,
    tokenize,
)


def norms(text: str, markup: bool = False) -> list[str]:
    return [n for _, n in tokenize(text, markup=markup)]


class TestNormalizeToken:
    def test_case_and_punctuation_folded(self):
        assert normalize_token("Commission,") == "commission"
        assert normalize_token("(1897)") == "1897"

    def test_curly_quotes_match_straight(self):
        assert normalize_token("party’s") == normalize_token("party's")

    def test_dash_variants_collapse(self):
        assert normalize_token("well—known") == normalize_token("well-known")

    def test_ligatures_expand(self):
        assert normalize_token("ﬁeld") == "field"

    def test_pure_punctuation_drops(self):
        assert normalize_token("---") == ""
        assert normalize_token("•") == ""
        assert normalize_token("|") == ""


class TestStripMarkup:
    def test_headings_and_emphasis_removed(self):
        assert norms("## **Station** _Marlow_", markup=True) == ["station", "marlow"]

    def test_table_content_survives_but_pipes_do_not(self):
        table = "| Station | Depth |\n|---|---|\n| Marlow | four |"
        assert norms(table, markup=True) == ["station", "depth", "marlow", "four"]

    def test_image_placeholder_dropped_entirely(self):
        assert norms("![alt text](_page_3_Figure_1.jpeg) caption", markup=True) == ["caption"]

    def test_link_text_kept_url_dropped(self):
        assert norms("see [the report](https://example.com/x.pdf)", markup=True) == [
            "see", "the", "report",
        ]

    def test_html_tags_removed(self):
        assert norms("<b>bold</b> text", markup=True) == ["bold", "text"]

    def test_markup_left_alone_when_not_requested(self):
        assert strip_markup("## Heading").strip() == "Heading"


class TestNearMiss:
    def test_identical(self):
        assert near_miss("barometer", "barometer")

    def test_m_rn_confusion(self):
        assert near_miss("barometer", "barorneter")
        assert near_miss("instruments", "instrurnents")

    def test_single_substitution_on_long_token(self):
        assert near_miss("observatory", "observalory")

    def test_digit_letter_confusion(self):
        assert near_miss("1897", "l897")

    def test_short_tokens_are_never_near_misses(self):
        assert not near_miss("the", "she")

    def test_genuinely_different_words_are_not_near_misses(self):
        assert not near_miss("magnetic", "commission")
        assert not near_miss("observatory", "laboratory")

    def test_skeleton_is_symmetric_and_stable(self):
        assert ocr_skeleton("barorneter") == ocr_skeleton("barometer")
        assert ocr_skeleton("plain") == ocr_skeleton("plain")


class TestShortMisread:
    """The under-the-floor rule. Safe only because `align._classify` calls it
    with a position constraint; everything here is about how narrow it is."""

    def test_the_wild_corpus_cases(self):
        # study/wild/: Tesseract read "as" as "ae" at 95.6% confidence, and
        # "the" as "ths", on the mimeographed body pages.
        assert short_misread("as", "ae")
        assert short_misread("the", "ths")

    def test_only_curated_glyph_pairs_count(self):
        # One edit apart, but s/t and n/s are not confusable pairs — folding
        # these would make every short function word interchangeable.
        assert not short_misread("as", "at")
        assert not short_misread("an", "as")
        assert not short_misread("to", "do")
        assert not short_misread("cat", "car")

    def test_two_differences_never_count(self):
        assert not short_misread("as", "ee")

    def test_single_characters_are_refused(self):
        # 'a' vs 'e' is one edit in a one-character word: nothing is left to
        # constrain the match, so the rule declines.
        assert not short_misread("a", "e")
        assert not short_misread("i", "l")

    def test_length_must_match(self):
        assert not short_misread("as", "a")
        assert not short_misread("the", "th")

    def test_floor_is_an_upper_bound_here(self):
        # Four characters and up is `near_miss`'s territory, not this rule's.
        assert not short_misread("hats", "hate")
        assert near_miss("affairs", "affaire")

    def test_skeleton_folds_still_apply(self):
        assert short_misread("0n", "on")
        assert short_misread("1s", "is")

    def test_identical_tokens_are_not_a_misread(self):
        assert not short_misread("as", "as")


class TestSplitPages:
    def test_form_feed(self):
        assert len(split_pages("one\x0ctwo\x0cthree") or []) == 3

    def test_brace_marker(self):
        text = "{1}------\nfirst\n{2}------\nsecond"
        pages = split_pages(text)
        assert pages is not None and len(pages) == 2
        assert "first" in pages[0] and "second" in pages[1]

    def test_html_comment_marker(self):
        pages = split_pages("first\n<!-- page-break -->\nsecond")
        assert pages is not None and len(pages) == 2

    def test_no_marker_returns_none(self):
        assert split_pages("just a document with no page markers at all") is None
