"""Reading-speed findings, and the citation that comes with each one.

The thresholds are not this project's opinion, so the tests check both the
finding and that the standard is named in it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "src"))

from cuecheck import reading  # noqa: E402
from cuecheck.cues import Cue  # noqa: E402


def cue(start, end, *lines):
    return Cue(index=1, start=start, end=end, lines=tuple(lines),
               line_number=1)


def kinds(report):
    return {f.kind for f in report.findings}


def test_a_comfortable_cue_produces_nothing():
    out = reading.check([cue(0.0, 3.0, "short enough to read")])
    assert out.findings == ()


def test_too_fast_is_measured_against_the_named_standard():
    # 60 characters in one second is 60 cps against a limit of 17.
    out = reading.check([cue(0.0, 1.0, "x" * 60)])
    fast = out.of_kind(reading.TOO_FAST)
    assert len(fast) == 1
    assert fast[0].limit == 17.0
    assert fast[0].standard == "Netflix (adult)"


def test_the_children_standard_is_stricter_on_the_same_cue():
    line = cue(0.0, 2.0, "x" * 30)          # 15 cps
    assert reading.check([line], reading.NETFLIX_ADULT).findings == ()
    strict = reading.check([line], reading.NETFLIX_CHILDREN)
    assert reading.TOO_FAST in kinds(strict)


def test_a_cue_shorter_than_the_minimum_is_reported():
    out = reading.check([cue(0.0, 0.4, "hi")])
    assert reading.TOO_SHORT in kinds(out)


def test_a_long_line_is_reported_per_line_not_per_cue():
    out = reading.check([cue(0.0, 10.0, "y" * 50, "y" * 50)])
    assert len(out.of_kind(reading.LINE_TOO_LONG)) == 2


def test_three_lines_at_once_is_reported():
    out = reading.check([cue(0.0, 10.0, "a", "b", "c")])
    assert reading.TOO_MANY_LINES in kinds(out)


def test_characters_per_second_excludes_the_line_break():
    # The same text on one line or two must read at the same speed.
    one = reading.characters_per_second(cue(0.0, 2.0, "abcd efgh"))
    two = reading.characters_per_second(cue(0.0, 2.0, "abcd", "efgh"))
    assert abs(one - two) < 1e-9


def test_a_zero_duration_cue_does_not_divide_by_zero():
    out = reading.check([cue(1.0, 1.0, "x")])
    assert out.rates == ()


def test_a_gap_too_small_to_see_is_reported():
    out = reading.check([cue(0.0, 2.0, "a"), cue(2.01, 4.0, "b")])
    assert reading.GAP_TOO_TIGHT in kinds(out)
