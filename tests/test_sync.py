"""The per-cue timing claim, and the two ways it could be wrong.

Most of these run on a hand-built `Audio` so they need no ffmpeg and no media
file: the speech intervals are stated outright, which makes the expected
offset arithmetic rather than opinion.

The last two run against real audio. `tools/make_fixture.py` measures the
narration clips committed in `corpus/narration/`, derives a subtitle file from
them, and lays the same clips out as one audio track on the same grid -- so
the correct timings are known by construction rather than asserted. It then
writes a second copy with two cues moved by stated amounts. The checker must
name exactly those two: missing one is the obvious failure, and reporting a
third is the expensive one, because this tool's output tells someone to go and
retime their work.

Both the clips and the built track live in this repository, so these two do
not depend on a sibling checkout. They did once, and they skipped themselves
for anyone who cloned only this project, which is the same as not having
them.
"""
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from cuecheck import sync  # noqa: E402
from cuecheck.audio import Audio, Interval  # noqa: E402
from cuecheck.cues import Cue, parse  # noqa: E402

CLEAN = os.path.join(ROOT, "corpus", "legible-clean.srt")
SHIFTED = os.path.join(ROOT, "corpus", "legible-shifted.srt")
AUDIO = os.path.join(ROOT, "corpus", "legible-narration.m4a")
CLIPS = os.path.join(ROOT, "corpus", "narration")
FIXTURE = os.path.join(ROOT, "tools", "make_fixture.py")


def built_fixture():
    """Build the fixture if it is not there yet; skip if ffmpeg is not."""
    if os.path.exists(AUDIO) and os.path.exists(CLEAN)             and os.path.exists(SHIFTED):
        return
    if not os.path.isdir(CLIPS):
        pytest.skip("corpus/narration/ is missing")
    done = subprocess.run([sys.executable, FIXTURE], capture_output=True,
                          text=True)
    if done.returncode != 0 or not os.path.exists(AUDIO):
        pytest.skip("could not build the fixture: %s"
                    % (done.stderr or "").strip()[:200])


def audio(*spans, duration=60.0, continuous=False):
    """An Audio whose speech is exactly the spans given."""
    speech = tuple(Interval(a, b) for a, b in spans)
    silence = []
    cursor = 0.0
    for interval in speech:
        if interval.start > cursor:
            silence.append(Interval(cursor, interval.start))
        cursor = interval.end
    if duration > cursor:
        silence.append(Interval(cursor, duration))
    return Audio(path="<test>", duration=duration, speech=speech,
                 silence=tuple(silence), threshold_db=-40.0,
                 min_silence=0.25, continuous=continuous)


def cue(start, end, text="x"):
    return Cue(index=1, start=start, end=end, lines=(text,), line_number=1)


def one(cues, a, **kw):
    return sync.time_cues(cues, a, **kw).timings[0]


def test_a_cue_on_its_speech_is_on_time():
    t = one([cue(2.0, 4.0)], audio((2.0, 4.0)))
    assert t.state == sync.MEASURED
    assert t.verdict == sync.ON_TIME
    assert abs(t.offset) < 1e-9


def test_a_cue_after_its_speech_is_late():
    t = one([cue(3.0, 5.0)], audio((2.0, 5.0)))
    assert t.verdict == sync.LATE
    assert abs(t.offset - (-1.0)) < 1e-9


def test_a_cue_before_its_speech_is_early():
    t = one([cue(1.0, 4.0)], audio((2.0, 4.0)))
    assert t.verdict == sync.EARLY
    assert abs(t.offset - 1.0) < 1e-9


def test_two_possible_onsets_make_the_direction_undecidable():
    # A pause inside the line splits the speech, so the cue sits between two
    # onsets. The magnitude is reportable; the sign is not.
    a = audio((2.0, 2.6), (4.4, 6.0))
    t = one([cue(3.1, 6.0)], a)
    assert t.verdict == sync.MISTIMED
    assert len(t.candidates) == 2
    assert t.offset is not None


def test_a_line_over_silence_is_not_given_an_offset():
    t = one([cue(10.0, 12.0)], audio((2.0, 5.0)))
    assert t.state == sync.NO_SPEECH
    assert t.offset is None
    assert t.verdict is None


def test_a_cue_mid_sentence_has_no_anchor_and_is_not_a_finding():
    # Speech runs from 0 to 30; a cue at 20 has no onset within the window.
    # Calling that late would be a false positive on a correct file.
    report = sync.time_cues([cue(20.0, 22.0)], audio((0.0, 30.0)))
    assert report.timings[0].state == sync.UNMEASURABLE
    assert report.off == ()


def test_audio_with_no_silence_measures_nothing():
    report = sync.time_cues([cue(1.0, 3.0), cue(5.0, 7.0)],
                            audio((0.0, 60.0), continuous=True))
    assert report.counts() == (0, 0, 2)
    assert report.off == ()
    assert report.median_offset is None


def test_a_correct_file_produces_no_findings():
    cues = [cue(2.0, 4.0), cue(6.0, 8.0), cue(10.0, 12.0)]
    report = sync.time_cues(cues, audio((2.0, 4.0), (6.0, 8.0), (10.0, 12.0)))
    assert report.off == ()
    assert len(report.measured) == 3


def test_a_near_zero_median_hides_badly_timed_cues():
    """The claim the project exists for.

    Two cues are off by a second in opposite directions and the rest are
    perfect, so the median shift a whole-file synchroniser computes is zero.
    Shifting this file by that median repairs nothing and reports success.
    """
    cues = [cue(2.0, 3.0), cue(6.0, 7.0), cue(9.0, 11.0), cue(13.0, 15.0),
            cue(18.0, 19.0)]
    a = audio((2.0, 3.0), (6.0, 7.0), (10.0, 11.0), (12.0, 15.0),
              (18.0, 19.0))
    report = sync.time_cues(cues, a)
    assert abs(report.median_offset) < 0.001
    assert len(report.off) == 2
    assert report.worst_offset >= 1.0


def test_the_derived_fixture_is_reported_as_correct():
    built_fixture()
    from cuecheck.audio import analyse

    with open(CLEAN, encoding="utf-8") as handle:
        cues = parse(handle.read()).cues
    report = sync.time_cues(cues, analyse(AUDIO))
    assert len(report.measured) == len(cues)
    assert report.off == ()
    assert report.over_silence == ()


def test_exactly_the_two_shifted_cues_are_reported():
    built_fixture()
    from cuecheck.audio import analyse

    with open(SHIFTED, encoding="utf-8") as handle:
        cues = parse(handle.read()).cues
    report = sync.time_cues(cues, analyse(AUDIO))

    reported = sorted(t.cue.index for t in report.off)
    assert reported == [3, 7], "expected cues 3 and 7, got %s" % reported
    # The one with a clean anchor keeps its direction; the one with a pause
    # inside its own line is reported without a direction rather than with
    # the wrong one.
    by_index = {t.cue.index: t for t in report.off}
    assert by_index[7].verdict == sync.EARLY
    assert by_index[3].verdict == sync.MISTIMED
    assert abs(by_index[7].offset) > 1.0
    assert abs(by_index[3].offset) > 1.0
