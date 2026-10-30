"""Where the speech actually is, measured rather than assumed.

One ffmpeg filter does the whole job. `silencedetect` reports every stretch
quieter than a threshold for longer than a minimum, and the speech is what is
left between those stretches. No model, no training, no network: the same
numbers come back on every machine for the same file, which is the only
reason a per-cue offset is worth printing at all.

The threshold is the honest part. `silencedetect` finds silence, not speech,
so it is only as good as the gap between the two:

  * Under a music bed or room tone there may be no silence at all. The
    filter then reports nothing, the whole file looks like one unbroken
    stretch of sound, and there is no onset to measure a cue against. That
    is not a file with perfect subtitles -- it is a file this method cannot
    measure, so `Audio.continuous` says so and the caller must refuse to
    report offsets rather than print zeroes.
  * A threshold set too high clips quiet speech into silence and invents
    onsets in the middle of sentences. -40dB with a 0.25s minimum is the
    default here because it is the pair I measured against known-truth
    narration, and both are arguments so a caller can change them and see
    what changes.

Nothing here writes to the file it reads. ffmpeg is invoked with `-f null`,
which decodes and discards, so pointing this at someone's master is safe.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import List, NamedTuple, Optional, Tuple

DEFAULT_THRESHOLD_DB = -40.0
DEFAULT_MIN_SILENCE = 0.25

# Below this proportion of silence the file offers nothing to anchor against.
CONTINUOUS_AUDIO_RATIO = 0.02

_DURATION = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")
_SILENCE_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")
_AUDIO_STREAM = re.compile(r"Stream #\d+:\d+.*: Audio:")


class FfmpegMissing(RuntimeError):
    pass


class NoAudioStream(RuntimeError):
    pass


class Interval(NamedTuple):
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class Audio(NamedTuple):
    path: str
    duration: float
    speech: Tuple[Interval, ...]
    silence: Tuple[Interval, ...]
    threshold_db: float
    min_silence: float
    continuous: bool

    @property
    def onsets(self) -> Tuple[float, ...]:
        """The moment each stretch of speech begins."""
        return tuple(i.start for i in self.speech)

    @property
    def speech_ratio(self) -> float:
        if self.duration <= 0:
            return 0.0
        return sum(i.duration for i in self.speech) / self.duration

    def speaking_at(self, moment: float) -> bool:
        return any(i.start <= moment <= i.end for i in self.speech)


def ffmpeg() -> str:
    """The ffmpeg binary: the bundled one if present, else one on PATH."""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise FfmpegMissing(
        "ffmpeg not found. Install it, or `pip install imageio-ffmpeg` to "
        "use the bundled build.")


def _run(path: str, threshold_db: float, min_silence: float) -> str:
    command = [
        ffmpeg(), "-hide_banner", "-nostdin",
        "-i", path,
        "-af", "silencedetect=noise=%gdB:d=%g" % (threshold_db, min_silence),
        "-f", "null", "-",
    ]
    # ffmpeg writes both the stream summary and the filter's findings to
    # stderr, and exits non-zero for an unreadable file; the text is the
    # result either way, so it is parsed rather than trusted to the code.
    done = subprocess.run(command, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return done.stderr or ""


def _intervals_from(report: str, duration: float) -> Tuple[Tuple[Interval, ...],
                                                           Tuple[Interval, ...]]:
    starts = [float(m.group(1)) for m in _SILENCE_START.finditer(report)]
    ends = [float(m.group(1)) for m in _SILENCE_END.finditer(report)]

    silence: List[Interval] = []
    for idx, start in enumerate(starts):
        # A silence still running at the end of the file has a start and no
        # end; it closes at the duration.
        end = ends[idx] if idx < len(ends) else duration
        if end > start:
            silence.append(Interval(max(0.0, start), min(end, duration)))

    speech: List[Interval] = []
    cursor = 0.0
    for gap in silence:
        if gap.start > cursor:
            speech.append(Interval(cursor, gap.start))
        cursor = max(cursor, gap.end)
    if duration > cursor:
        speech.append(Interval(cursor, duration))

    return tuple(speech), tuple(silence)


def analyse(path: str, threshold_db: float = DEFAULT_THRESHOLD_DB,
            min_silence: float = DEFAULT_MIN_SILENCE) -> Audio:
    """Measure where the speech is in a media file."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    report = _run(path, threshold_db, min_silence)

    if not _AUDIO_STREAM.search(report):
        raise NoAudioStream(
            "%s has no audio stream, so there is nothing to measure the "
            "subtitles against." % os.path.basename(path))

    match = _DURATION.search(report)
    if not match:
        raise RuntimeError(
            "ffmpeg did not report a duration for %s; the file may be "
            "truncated or not a media file." % os.path.basename(path))
    duration = (int(match.group(1)) * 3600 + int(match.group(2)) * 60
                + float(match.group(3)))

    speech, silence = _intervals_from(report, duration)
    silent_total = sum(i.duration for i in silence)
    continuous = (duration > 0
                  and silent_total / duration < CONTINUOUS_AUDIO_RATIO)

    return Audio(path=path, duration=duration, speech=speech, silence=silence,
                 threshold_db=threshold_db, min_silence=min_silence,
                 continuous=continuous)
