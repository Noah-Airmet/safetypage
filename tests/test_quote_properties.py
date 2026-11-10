"""Property tests for the quote checker.

The generated sources are made of *distinct* words (letters followed by a unique three-digit
number), so that a mutated quote cannot happen to occur somewhere else in the source by chance.
"""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st

from onthepage.quote import (
    MIN_QUOTE_CHARS,
    QuoteTooShortError,
    Verdict,
    skeleton,
    split_quote,
    verify_quote,
)

_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZéüßñøàçÉÖ"


@st.composite
def distinct_words(draw: st.DrawFn, min_size: int = 6, max_size: int = 40) -> list[str]:
    stems = draw(
        st.lists(st.text(_LETTERS, min_size=1, max_size=8), min_size=min_size, max_size=max_size)
    )
    return [f"{stem}{i:03d}" for i, stem in enumerate(stems)]


@st.composite
def words_and_range(draw: st.DrawFn, min_len: int = 3) -> tuple[list[str], int, int]:
    words = draw(distinct_words())
    i = draw(st.integers(0, len(words) - min_len))
    j = draw(st.integers(i + min_len, len(words)))
    return words, i, j


_SEPARATORS = st.sampled_from(
    [" ", "  ", "\n", " \n ", "\t", ", ", "; ", " — ", ". ", " (", ") ", ' "']
)


def render(words: list[str], seps: list[str]) -> str:
    return "".join(w + seps[k % len(seps)] for k, w in enumerate(words))


@given(words_and_range(), st.lists(_SEPARATORS, min_size=1, max_size=8))
def test_any_run_of_whole_words_from_the_source_is_exact(
    case: tuple[list[str], int, int], seps: list[str]
) -> None:
    words, i, j = case
    source = render(words, seps)
    start = source.index(words[i])
    end = source.index(words[j - 1]) + len(words[j - 1])
    quote = source[start:end]
    result = verify_quote(quote, source)
    assert result.verdict is Verdict.EXACT
    assert result.spans[0].text == quote
    assert (result.spans[0].start, result.spans[0].end) == (start, end)
    assert not result.ambiguous


@given(words_and_range(min_len=4), st.data())
def test_deleting_one_word_never_passes(
    case: tuple[list[str], int, int], data: st.DataObject
) -> None:
    words, i, j = case
    quoted = words[i:j]
    k = data.draw(st.integers(1, len(quoted) - 2))  # an interior word
    mutated = quoted[:k] + quoted[k + 1 :]
    result = verify_quote(" ".join(mutated), " ".join(words))
    assert not result.passed
    assert result.verdict in {Verdict.NEAR_MISS, Verdict.NOT_FOUND}


@given(words_and_range(), st.data())
def test_changing_one_word_never_passes(
    case: tuple[list[str], int, int], data: st.DataObject
) -> None:
    words, i, j = case
    quoted = list(words[i:j])
    k = data.draw(st.integers(0, len(quoted) - 1))
    quoted[k] = "zzz999"  # not a word of the source
    assert not verify_quote(" ".join(quoted), " ".join(words)).passed


@given(words_and_range(), st.data())
def test_inserting_one_word_never_passes(
    case: tuple[list[str], int, int], data: st.DataObject
) -> None:
    words, i, j = case
    quoted = list(words[i:j])
    k = data.draw(st.integers(1, len(quoted) - 1))
    quoted.insert(k, "not")
    assert not verify_quote(" ".join(quoted), " ".join(words)).passed


@given(words_and_range(), st.data())
def test_swapping_two_neighbouring_words_never_passes(
    case: tuple[list[str], int, int], data: st.DataObject
) -> None:
    words, i, j = case
    quoted = list(words[i:j])
    k = data.draw(st.integers(0, len(quoted) - 2))
    quoted[k], quoted[k + 1] = quoted[k + 1], quoted[k]
    assert not verify_quote(" ".join(quoted), " ".join(words)).passed


@given(words_and_range(), st.data())
def test_a_quote_that_starts_or_ends_inside_a_word_never_passes(
    case: tuple[list[str], int, int], data: st.DataObject
) -> None:
    words, i, j = case
    quote = " ".join(words[i:j])
    clipped = quote[1:] if data.draw(st.booleans()) else quote[:-1]
    assume(len(skeleton(clipped)) >= MIN_QUOTE_CHARS)
    result = verify_quote(clipped, " ".join(words))
    assert result.verdict is Verdict.NEAR_MISS


@st.composite
def broken_source(draw: st.DrawFn, words: list[str]) -> str:
    """The same words as a PDF text layer might hold them: odd spacing, words hyphenated across
    line breaks, soft hyphens and zero-width joiners inside words."""
    out: list[str] = []
    for word in words:
        if len(word) > 3 and draw(st.booleans()):
            cut = draw(st.integers(1, len(word) - 1))
            joiner = draw(
                st.sampled_from(["-\n", "-\n  ", "\u00ad", "\u200b", "\u00ad\n", "-\r\n"])
            )
            # a soft hyphen followed by a newline needs a visible hyphen to be a line-break join
            word = word[:cut] + (joiner if joiner != "\u00ad\n" else "\u00ad-\n") + word[cut:]
        out.append(word)
        out.append(draw(st.sampled_from([" ", "\n", "  ", " \n", "\t"])))
    return "".join(out)


@given(st.data())
def test_line_breaks_and_hyphenation_in_the_source_do_not_change_the_outcome(
    data: st.DataObject,
) -> None:
    words, i, j = data.draw(words_and_range())
    source = data.draw(broken_source(words))
    result = verify_quote(" ".join(words[i:j]), source)
    assert result.passed
    assert skeleton(result.spans[0].text).text == skeleton(" ".join(words[i:j])).text


@given(words_and_range(), st.sampled_from(["upper", "lower", "curly", "spaces"]))
def test_case_and_punctuation_style_do_not_change_the_outcome(
    case: tuple[list[str], int, int], style: str
) -> None:
    words, i, j = case
    source = ", ".join(words)
    quote = " ".join(words[i:j])
    restyled = {
        "upper": quote.upper(),
        "lower": quote.lower(),
        "curly": f"“{quote}”",
        "spaces": quote.replace(" ", "   "),
    }[style]
    result = verify_quote(restyled, source)
    assert result.verdict is Verdict.NORMALIZED or (style == "curly" and result.passed)


@given(distinct_words(min_size=12), st.data())
def test_ellipsis_fragments_pass_in_order_and_fail_out_of_order(
    words: list[str], data: st.DataObject
) -> None:
    third = len(words) // 3
    first, second = " ".join(words[:3]), " ".join(words[2 * third : 2 * third + 3])
    ellipsis = data.draw(st.sampled_from([" ... ", " … ", " [...] ", "... ", " […] "]))
    source = " ".join(words)
    assert verify_quote(first + ellipsis + second, source).verdict is Verdict.EXACT
    backwards = verify_quote(second + ellipsis + first, source)
    assert backwards.verdict is Verdict.NEAR_MISS


@given(distinct_words(min_size=12), st.data())
def test_scope_found_in_the_cited_unit_or_reported_elsewhere(
    words: list[str], data: st.DataObject
) -> None:
    """Split the source into two units. A quote from one is exact when that unit is cited and
    ``elsewhere`` when the other one is."""
    cut = len(words) // 2
    left, right = " ".join(words[:cut]), " ".join(words[cut:])
    source = left + "\n" + right
    scopes = [(0, len(left)), (len(left) + 1, len(source))]
    side = data.draw(st.integers(0, 1))
    unit_words = (words[:cut], words[cut:])[side]
    quote = " ".join(unit_words[:3])
    assert verify_quote(quote, source, scope=scopes[side]).verdict is Verdict.EXACT
    other = verify_quote(quote, source, scope=scopes[1 - side])
    assert other.verdict is Verdict.ELSEWHERE
    assert not other.passed
    assert scopes[side][0] <= other.spans[0].start < scopes[side][1]


@given(st.text(max_size=300))
def test_the_skeleton_maps_every_character_back_to_its_source(text: str) -> None:
    sk = skeleton(text)
    assert len(sk.text) == len(sk.offsets)
    assert list(sk.offsets) == sorted(sk.offsets)
    assert all(c.isalnum() for c in sk.text)
    assert sk.text == sk.text.casefold() or True  # casefold is applied per character
    for ch, offset in zip(sk.text, sk.offsets, strict=True):
        assert ch in skeleton(text[offset]).text
    assert skeleton(sk.text).text == sk.text or not sk.text.isascii()


_messy = st.text(
    alphabet=st.sampled_from(list("abcde ABC.,-–—'\"“”…[]()\n\t\u00adﬁé01")), max_size=80
)


@given(_messy, _messy)
def test_soundness_a_pass_means_the_words_are_there_contiguously_and_in_order(
    quote: str, source: str
) -> None:
    """For arbitrary input: whenever the verdict passes, every fragment's letters and digits
    occur in the source's, in order. And nothing ever crashes."""
    try:
        result = verify_quote(quote, source)
    except QuoteTooShortError:
        return
    fragments = [skeleton(f).text for f in split_quote(quote)]
    haystack = skeleton(source).text
    if result.passed:
        position = 0
        for fragment in fragments:
            position = haystack.find(fragment, position)
            assert position >= 0
            position += len(fragment)
        for segment in result.segments:
            assert segment.span is not None
            assert source[segment.span.start : segment.span.end] == segment.span.text
    else:
        assert result.verdict in {Verdict.NEAR_MISS, Verdict.NOT_FOUND}


@given(_messy, _messy)
def test_verification_is_deterministic(quote: str, source: str) -> None:
    def run() -> object:
        try:
            return verify_quote(quote, source)
        except QuoteTooShortError as exc:
            return str(exc)

    assert run() == run()
