"""Reading a subtitle file without quietly losing any of it.

Every defect this project reports about a subtitle rests on having parsed the
file correctly, so this module's rule is that nothing is ever skipped in
silence. A parser that drops a malformed cue produces a report saying the
file is fine, which is worse than refusing to read it: the person then ships
subtitles that a deaf viewer cannot follow, believing they were checked.

So a cue that cannot be parsed becomes a `Defect` with its line number, and
the caller decides. The four malformations that actually occur in files
people hand you, as opposed to the ones a spec worries about:

  * A cue that ends before it starts, or lasts zero milliseconds. Players
    show it for one frame or not at all, and every editor exports it happily.
  * Cues out of chronological order, usually after a hand edit in the middle
    of a file.
  * Overlapping cues. Two lines on screen at once is sometimes deliberate
    and usually not, so it is reported and not corrected.
  * A comma where a dot belongs. SRT writes milliseconds with a comma and
    WebVTT with a dot; players are lenient about it and tooling often is
    not, so both are accepted here and the mixture is reported.

Timestamps are kept as floating-point seconds, which is what the audio side
measures in. Milliseconds are the file's unit, not the measurement's.
"""
from __future__ import annotations

import re
from typing import List, NamedTuple, Optional, Sequence, Tuple

SRT = "srt"
VTT = "vtt"

# Defect kinds. These name a property of the file, never a judgement about
# whoever wrote it.
BAD_TIMESTAMP = "bad-timestamp"
REVERSED = "reversed"
EMPTY_DURATION = "empty-duration"
OUT_OF_ORDER = "out-of-order"
OVERLAP = "overlap"
EMPTY_TEXT = "empty-text"
MIXED_DECIMAL = "mixed-decimal-separator"
NO_CUES = "no-cues"

# hh:mm:ss,mmm and hh:mm:ss.mmm, plus WebVTT's optional mm:ss.mmm form.
_TIME = re.compile(r"""
    (?:(?P<h>\d{1,3}):)?        # hours are optional in WebVTT
    (?P<m>\d{1,2}):
    (?P<s>\d{1,2})
    (?P<sep>[.,])
    (?P<ms>\d{1,3})
    """, re.VERBOSE)

_ARROW = re.compile(r"-->")


class Cue(NamedTuple):
    index: int                 # position in the file, 1-based, not the file's own number
    start: float               # seconds
    end: float                 # seconds
    lines: Tuple[str, ...]
    line_number: int           # where the cue's timestamp sits in the file

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def text(self) -> str:
        return " ".join(self.lines)

    @property
    def characters(self) -> int:
        """Characters a viewer has to read.

        The line break counts as one character, because it stands in for the
        space that would be there on a single line. Dropping it instead makes
        the same words look cheaper to read once they are split across two
        lines, which is backwards: breaking a line does not make it shorter.
        """
        if not self.lines:
            return 0
        return sum(len(line) for line in self.lines) + len(self.lines) - 1


class Defect(NamedTuple):
    kind: str
    line_number: int
    detail: str
    cue_index: Optional[int] = None


class Parsed(NamedTuple):
    fmt: str
    cues: Tuple[Cue, ...]
    defects: Tuple[Defect, ...]

    @property
    def usable(self) -> bool:
        """True when there is something to measure.

        A file whose cues all failed to parse is not a file with no problems.
        """
        return bool(self.cues)


def _seconds(match: "re.Match[str]") -> float:
    hours = int(match.group("h") or 0)
    minutes = int(match.group("m"))
    secs = int(match.group("s"))
    # "1" in the millisecond field means 100ms, not 1ms -- it is a decimal
    # fraction, so it is padded on the right.
    ms = int(match.group("ms").ljust(3, "0"))
    return hours * 3600 + minutes * 60 + secs + ms / 1000.0


def detect_format(path: str, source: str) -> str:
    if source.lstrip("﻿").startswith("WEBVTT"):
        return VTT
    return VTT if path.lower().endswith(".vtt") else SRT


def parse(source: str, fmt: str = SRT) -> Parsed:
    """Parse an SRT or WebVTT body into cues plus the defects found."""
    text = source.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    lines = text.split("\n")

    cues: List[Cue] = []
    defects: List[Defect] = []
    separators = set()

    i = 0
    n = len(lines)
    index = 0
    while i < n:
        line = lines[i]
        if not _ARROW.search(line):
            i += 1
            continue

        times = list(_TIME.finditer(line))
        if len(times) < 2:
            defects.append(Defect(
                BAD_TIMESTAMP, i + 1,
                "a cue boundary line with no two readable timestamps: %r"
                % line.strip()))
            i += 1
            continue

        start = _seconds(times[0])
        end = _seconds(times[1])
        for match in times[:2]:
            separators.add(match.group("sep"))

        body: List[str] = []
        j = i + 1
        while j < n and lines[j].strip() != "":
            # A following timestamp line means the previous cue's text was
            # never terminated by a blank line. Stop rather than swallow it.
            if _ARROW.search(lines[j]) and len(list(_TIME.finditer(lines[j]))) >= 2:
                break
            body.append(lines[j])
            j += 1

        index += 1
        stripped = tuple(l.strip() for l in body if l.strip() != "")
        cue = Cue(index=index, start=start, end=end, lines=stripped,
                  line_number=i + 1)

        if end < start:
            defects.append(Defect(
                REVERSED, i + 1,
                "ends %.3fs before it starts" % (start - end), index))
        elif end == start:
            defects.append(Defect(
                EMPTY_DURATION, i + 1,
                "zero duration at %.3fs" % start, index))

        if not stripped:
            defects.append(Defect(
                EMPTY_TEXT, i + 1, "no text between the timestamps", index))

        if cues:
            previous = cues[-1]
            if start < previous.start:
                defects.append(Defect(
                    OUT_OF_ORDER, i + 1,
                    "starts %.3fs before the previous cue at %.3fs"
                    % (previous.start - start, previous.start), index))
            elif start < previous.end:
                defects.append(Defect(
                    OVERLAP, i + 1,
                    "starts %.3fs before the previous cue ends"
                    % (previous.end - start), index))

        cues.append(cue)
        i = j

    if len(separators) > 1:
        defects.append(Defect(
            MIXED_DECIMAL, 0,
            "the file uses both ',' and '.' before the milliseconds"))

    if not cues:
        defects.append(Defect(
            NO_CUES, 0,
            "no cue in the file had two readable timestamps"))

    return Parsed(fmt=fmt, cues=tuple(cues), defects=tuple(defects))


def parse_path(path: str, source: str) -> Parsed:
    return parse(source, detect_format(path, source))


def format_timestamp(seconds: float, fmt: str = SRT) -> str:
    """Render seconds back in the file's own notation."""
    if seconds < 0:
        seconds = 0.0
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    if ms == 1000:
        whole += 1
        ms = 0
    sep = "." if fmt == VTT else ","
    return "%02d:%02d:%02d%s%03d" % (
        whole // 3600, (whole % 3600) // 60, whole % 60, sep, ms)
