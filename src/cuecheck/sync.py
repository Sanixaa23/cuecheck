"""Which line is off, not how far the file is off.

Every subtitle synchroniser I can find answers one question: by how much is
this whole file shifted. They cross-correlate the speech against the cue
times, produce a single number, and move everything by it. That is the right
tool for a file that was muxed against the wrong frame rate, and it is blind
to the failure that actually reaches viewers -- a file whose median offset is
zero and whose five hardest lines are a second and a half late, because
someone retimed the middle by hand. Shifting that file by its median changes
nothing and reports success.

So this measures each cue separately, and it refuses to measure most of them.

A cue can only be timed against a moment the audio itself marks, and the only
such moment `silencedetect` gives is the end of a silence -- speech starting.
A cue that lands in the middle of a continuous sentence has no onset near it,
and that is entirely normal: dialogue does not pause between lines. Calling
such a cue wrong would be a false positive, and a false positive here tells
someone to retime a line that was correct. Hence three outcomes, not two:

    MEASURED       a silence ended near this cue, so the offset is a number
    NO_SPEECH      the cue's whole span is silent -- a line over nothing
    UNMEASURABLE   speech is already running; there is no anchor to use

Only MEASURED cues get a verdict. The count of each is part of the report,
because "48 of 120 cues measurable" is information the reader needs in order
to know what the verdict covers.

One number here is mine rather than a standard's. Reading speed has
published limits and sync tolerance does not: no body states how many
milliseconds a subtitle may lead its audio. `TOLERANCE` is 0.25s because
below that the measurement's own resolution dominates, and it is an argument
so anyone who disagrees can set their own and see the report change.
"""
from __future__ import annotations

from typing import List, NamedTuple, Optional, Sequence, Tuple

from .audio import Audio, Interval
from .cues import Cue

MEASURED = "measured"
NO_SPEECH = "no-speech"
UNMEASURABLE = "unmeasurable"

ON_TIME = "on-time"
EARLY = "early"
LATE = "late"
# Off, but the audio cannot say which way. See `_onsets_near`.
MISTIMED = "mistimed"

# How far from a cue's start a speech onset may sit and still be taken as
# that cue's onset.
DEFAULT_WINDOW = 2.0
# Chosen, not standardised. See the module docstring.
DEFAULT_TOLERANCE = 0.25


class Timing(NamedTuple):
    cue: Cue
    state: str                      # MEASURED / NO_SPEECH / UNMEASURABLE
    offset: Optional[float]         # onset - cue.start, seconds; None unless MEASURED
    onset: Optional[float]
    verdict: Optional[str]          # ON_TIME / EARLY / LATE / MISTIMED
    reason: str
    # Every speech onset inside the window, nearest first. More than one
    # means the direction of the error is not decidable from the audio.
    candidates: Tuple[float, ...] = ()

    @property
    def late(self) -> bool:
        return self.verdict == LATE

    @property
    def early(self) -> bool:
        return self.verdict == EARLY


class SyncReport(NamedTuple):
    timings: Tuple[Timing, ...]
    tolerance: float
    window: float
    continuous_audio: bool

    @property
    def measured(self) -> Tuple[Timing, ...]:
        return tuple(t for t in self.timings if t.state == MEASURED)

    @property
    def off(self) -> Tuple[Timing, ...]:
        """Measured cues whose verdict is not ON_TIME, worst first."""
        bad = [t for t in self.measured if t.verdict != ON_TIME]
        return tuple(sorted(bad, key=lambda t: -abs(t.offset or 0.0)))

    @property
    def over_silence(self) -> Tuple[Timing, ...]:
        return tuple(t for t in self.timings if t.state == NO_SPEECH)

    @property
    def median_offset(self) -> Optional[float]:
        """The shift a whole-file synchroniser would apply.

        Printed beside the per-cue findings on purpose: when the median is
        near zero and individual cues are badly off, shifting the file is
        exactly the wrong repair.
        """
        values = sorted(t.offset for t in self.measured if t.offset is not None)
        if not values:
            return None
        middle = len(values) // 2
        if len(values) % 2:
            return values[middle]
        return (values[middle - 1] + values[middle]) / 2.0

    @property
    def worst_offset(self) -> Optional[float]:
        values = [abs(t.offset) for t in self.measured if t.offset is not None]
        return max(values) if values else None

    def counts(self) -> Tuple[int, int, int]:
        """(measured, over silence, unmeasurable)"""
        return (len(self.measured), len(self.over_silence),
                sum(1 for t in self.timings if t.state == UNMEASURABLE))


def _onsets_near(audio: Audio, moment: float,
                 window: float) -> Tuple[float, ...]:
    """Every speech onset within `window` of `moment`, nearest first.

    All of them, not the nearest one, because the nearest is not reliably the
    right one. Speakers pause inside a sentence, and `silencedetect` reports
    that pause as the end of one stretch of speech and the start of another.
    A cue that has drifted late can therefore sit closer to a pause in the
    middle of its own line than to the start of it -- measured on a real
    file: a cue pushed 1.50s late came out as 1.45s early, because a mid-line
    breath 1.445s ahead beat the true onset 1.465s behind.

    The magnitude was right and the direction was inverted, which is the
    worst shape an error can take here: it tells someone to retime a line in
    the wrong direction. So when more than one onset could explain a cue, the
    verdict is MISTIMED and the candidates are printed, rather than a
    confident guess at the sign.
    """
    near = [o for o in audio.onsets if abs(o - moment) <= window]
    return tuple(sorted(near, key=lambda o: abs(o - moment)))


def _span_is_silent(audio: Audio, cue: Cue) -> bool:
    """True when no speech overlaps the cue at all."""
    for interval in audio.speech:
        if interval.start < cue.end and interval.end > cue.start:
            return False
    return True


def time_cues(cues: Sequence[Cue], audio: Audio,
              tolerance: float = DEFAULT_TOLERANCE,
              window: float = DEFAULT_WINDOW) -> SyncReport:
    """Classify and, where possible, measure every cue against the audio."""
    timings: List[Timing] = []

    for cue in cues:
        if audio.continuous:
            timings.append(Timing(
                cue=cue, state=UNMEASURABLE, offset=None, onset=None,
                verdict=None,
                reason="the audio has almost no silence in it, so there is "
                       "no onset to measure any cue against"))
            continue

        if _span_is_silent(audio, cue):
            timings.append(Timing(
                cue=cue, state=NO_SPEECH, offset=None, onset=None,
                verdict=None,
                reason="nothing is spoken for the whole %.2fs this line is "
                       "on screen" % cue.duration))
            continue

        candidates = _onsets_near(audio, cue.start, window)
        if not candidates:
            timings.append(Timing(
                cue=cue, state=UNMEASURABLE, offset=None, onset=None,
                verdict=None,
                reason="speech is already running here and no new speech "
                       "starts within %.1fs, so this cue has no anchor"
                       % window))
            continue

        onset = candidates[0]
        offset = onset - cue.start
        if abs(offset) <= tolerance:
            verdict = ON_TIME
            reason = "within %.2fs of the speech" % tolerance
        elif len(candidates) > 1:
            verdict = MISTIMED
            reason = ("%.2fs from the nearest speech start, but %d speech "
                      "starts lie within %.1fs (%s), so the audio cannot say "
                      "which way it is off"
                      % (abs(offset), len(candidates), window,
                         ", ".join("%.2fs" % c for c in candidates[:3])))
        elif offset > 0:
            verdict = EARLY
            reason = "on screen %.2fs before anyone speaks" % offset
        else:
            verdict = LATE
            reason = ("%.2fs after the speech began -- the viewer hears it "
                      "first and reads it afterwards" % -offset)

        timings.append(Timing(cue=cue, state=MEASURED, offset=offset,
                              onset=onset, verdict=verdict, reason=reason,
                              candidates=candidates))

    return SyncReport(timings=tuple(timings), tolerance=tolerance,
                      window=window, continuous_audio=audio.continuous)
