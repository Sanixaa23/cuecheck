"""The parser must never lose a cue in silence.

Each test here is one malformation that reaches real files, and the claim is
the same every time: the cue is still returned, and the fault is reported
beside it. A parser that dropped the bad cue would let the rest of the
pipeline conclude the file was checked.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "src"))

from cuecheck import cues  # noqa: E402


def parse(body):
    return cues.parse(body, cues.SRT)


def kinds(parsed):
    return {d.kind for d in parsed.defects}


def test_a_plain_file_parses_with_no_defects():
    out = parse("1\n00:00:01,000 --> 00:00:03,000\nhello\n\n")
    assert len(out.cues) == 1
    assert out.cues[0].start == 1.0 and out.cues[0].end == 3.0
    assert out.cues[0].lines == ("hello",)
    assert out.defects == ()


def test_milliseconds_are_a_decimal_fraction_not_a_count():
    # ",5" is half a second. Reading it as 5ms would shift the cue by 495ms.
    out = parse("1\n00:00:01,5 --> 00:00:02,25\nx\n\n")
    assert out.cues[0].start == 1.5
    assert out.cues[0].end == 2.25


def test_a_reversed_cue_is_reported_and_still_returned():
    out = parse("1\n00:00:05,000 --> 00:00:02,000\nx\n\n")
    assert len(out.cues) == 1
    assert cues.REVERSED in kinds(out)


def test_zero_duration_is_reported():
    out = parse("1\n00:00:02,000 --> 00:00:02,000\nx\n\n")
    assert cues.EMPTY_DURATION in kinds(out)


def test_overlap_is_reported_but_not_corrected():
    body = ("1\n00:00:01,000 --> 00:00:04,000\na\n\n"
            "2\n00:00:03,000 --> 00:00:06,000\nb\n\n")
    out = parse(body)
    assert cues.OVERLAP in kinds(out)
    # Both cues survive with their own times; nothing was moved.
    assert out.cues[1].start == 3.0


def test_cues_out_of_order_are_reported():
    body = ("1\n00:00:10,000 --> 00:00:12,000\na\n\n"
            "2\n00:00:02,000 --> 00:00:04,000\nb\n\n")
    assert cues.OUT_OF_ORDER in kinds(parse(body))


def test_a_missing_blank_line_does_not_swallow_the_next_cue():
    # Two cues with no blank line between them: the text of the first must
    # not absorb the second's timestamp line.
    body = ("1\n00:00:01,000 --> 00:00:02,000\na\n"
            "2\n00:00:03,000 --> 00:00:04,000\nb\n")
    out = parse(body)
    assert len(out.cues) == 2
    assert out.cues[0].lines == ("a", "2")
    assert out.cues[1].start == 3.0


def test_both_decimal_separators_are_accepted_and_the_mixture_reported():
    body = ("1\n00:00:01.000 --> 00:00:02,000\na\n\n")
    out = parse(body)
    assert out.cues[0].start == 1.0
    assert cues.MIXED_DECIMAL in kinds(out)


def test_webvtt_without_hours_parses():
    out = cues.parse("WEBVTT\n\n01:02.500 --> 01:04.000\nx\n\n", cues.VTT)
    assert out.cues[0].start == 62.5


def test_a_file_with_no_cues_is_not_a_clean_file():
    out = parse("this is not a subtitle file\n")
    assert out.usable is False
    assert cues.NO_CUES in kinds(out)


def test_timestamps_round_trip():
    assert cues.format_timestamp(62.5) == "00:01:02,500"
    assert cues.format_timestamp(62.5, cues.VTT) == "00:01:02.500"
    # 999.9995s must not render as :60.000 or ,1000.
    assert cues.format_timestamp(59.9999) == "00:01:00,000"
