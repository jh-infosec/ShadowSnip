"""The text of the clip confirmation.

Only `summarise` is tested. Everything else in toast.py is a widget, and what
matters about the widget -- that it does not take focus and does not swallow a
click -- is a property of two Qt attributes rather than of any code that could
be asserted on here.
"""

from __future__ import annotations

import pytest

from toast import SNIPPET_CHARS, summarise


def test_a_word_clip_names_itself():
    assert summarise("nmap", "word").startswith("word copied - 4 characters")


def test_a_line_clip_names_itself():
    assert summarise("a line", "line").startswith("line copied - 6 characters")


@pytest.mark.parametrize("kind", ["selection", "", "something-else", None])
def test_an_unknown_kind_falls_back_to_selection(kind):
    assert summarise("abc", kind).startswith("selection copied")


def test_one_character_is_singular():
    assert summarise("x", "word").startswith("word copied - 1 character\n")


def test_the_clip_itself_is_the_second_line():
    assert summarise("hashcat", "word").splitlines()[1] == "hashcat"


def test_newlines_and_runs_of_space_are_flattened():
    """A multi-line clip has to fit on one line of a small label."""
    assert summarise("one\n  two\tthree", "line").splitlines()[1] == "one two three"


def test_a_long_clip_is_truncated_to_the_snippet_width():
    snippet = summarise("x" * 500, "line").splitlines()[1]
    assert len(snippet) == SNIPPET_CHARS
    assert snippet.endswith("...")


def test_the_full_length_is_reported_even_when_truncated():
    assert summarise("x" * 500, "line").startswith("line copied - 500 characters")


def test_whitespace_only_clip_leaves_just_the_header():
    """The count still tells you something was copied, even with nothing to show."""
    assert summarise("   \n  ", "selection") == "selection copied - 6 characters"
