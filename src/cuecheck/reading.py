"""Whether a viewer can finish the line before it leaves the screen.

A subtitle can be perfectly synchronised and still unusable. Sixty characters
held for eight tenths of a second is on time and unreadable, and this is the
more common failure of the two in material made by people who are not
subtitlers -- a lecturer captioning their own slides sets the timings from
the speech and never asks how fast the result has to be read.

Unlike sync tolerance, this has published numbers, so none of the thresholds
here are mine. Each `Standard` carries the document it came from and every
finding names it, because "too fast" is an opinion and "above Netflix's 17
characters per second for adult programming" is a citation someone can go
and check.

Characters per second is counted over the characters a viewer reads, spaces
kept and the line break counted as one of them -- it stands in for the space
that would be there on a single line. Dropping the break instead makes the
same words look cheaper to read once they are split across two lines, which
is backwards: breaking a line does not shorten it. A test pins the two forms
to the same rate.
"""
from __future__ import annotations

from typing import List, NamedTuple, Optional, Sequence, Tuple

from .cues import Cue

TOO_FAST = "too-fast"
TOO_SHORT = "too-short"
LINE_TOO_LONG = "line-too-long"
TOO_MANY_LINES = "too-many-lines"
GAP_TOO_TIGHT = "gap-too-tight"


class Standard(NamedTuple):
    name: str
    source: str
    chars_per_second: float
    min_duration: float
    max_chars_per_line: int
    max_lines: int
    min_gap: float


# 17 cps, two lines of 42 characters, and a minimum of 5/6 second (20 frames
# at 24fps) with a two-frame gap between cues.
NETFLIX_ADULT = Standard(
    name="Netflix (adult)",
    source="Netflix Timed Text Style Guide, English",
    chars_per_second=17.0,
    min_duration=5.0 / 6.0,
    max_chars_per_line=42,
    max_lines=2,
    min_gap=2.0 / 24.0,
)

# The same guide drops the rate for children's programming.
NETFLIX_CHILDREN = NETFLIX_ADULT._replace(
    name="Netflix (children)",
    chars_per_second=13.0,
)

# The BBC states a target reading speed in words per minute; at an English
# average of about five characters plus a space per word, 180wpm is close to
# 17 characters per second, which is why the two guides agree in practice.
BBC = Standard(
    name="BBC",
    source="BBC Subtitle Guidelines, reading speed and line treatment",
    chars_per_second=180.0 * 6.0 / 60.0,
    min_duration=1.0,
    max_chars_per_line=37,
    max_lines=2,
    min_gap=1.0 / 25.0,
)

STANDARDS = {
    "netflix": NETFLIX_ADULT,
    "netflix-children": NETFLIX_CHILDREN,
    "bbc": BBC,
}
DEFAULT_STANDARD = NETFLIX_ADULT


class Finding(NamedTuple):
    kind: str
    cue: Cue
    detail: str
    measured: float
    limit: float
    standard: str

    @property
    def excess(self) -> float:
        """How far past the limit, in the finding's own unit."""
        if self.kind in (TOO_SHORT, GAP_TOO_TIGHT):
            return self.limit - self.measured
        return self.measured - self.limit


class ReadingReport(NamedTuple):
    standard: Standard
    findings: Tuple[Finding, ...]
    rates: Tuple[Tuple[Cue, float], ...]     # every cue's characters per second

    @property
    def worst(self) -> Tuple[Finding, ...]:
        return tuple(sorted(self.findings, key=lambda f: -f.excess))

    def of_kind(self, kind: str) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.kind == kind)


def characters_per_second(cue: Cue) -> Optional[float]:
    """Reading rate, or None for a cue with no duration to divide by."""
    if cue.duration <= 0:
        return None
    return cue.characters / cue.duration


def check(cues: Sequence[Cue],
          standard: Standard = DEFAULT_STANDARD) -> ReadingReport:
    """Measure every cue against one published standard."""
    findings: List[Finding] = []
    rates: List[Tuple[Cue, float]] = []

    for position, cue in enumerate(cues):
        rate = characters_per_second(cue)
        # A zero-duration cue is already reported by the parser as a defect;
        # dividing by it here would raise, and silently skipping it would
        # hide nothing, since the parser has it.
        if rate is not None:
            rates.append((cue, rate))
            if rate > standard.chars_per_second:
                findings.append(Finding(
                    kind=TOO_FAST, cue=cue,
                    detail="%d characters in %.2fs is %.1f per second"
                           % (cue.characters, cue.duration, rate),
                    measured=rate, limit=standard.chars_per_second,
                    standard=standard.name))

        if 0 < cue.duration < standard.min_duration:
            findings.append(Finding(
                kind=TOO_SHORT, cue=cue,
                detail="on screen for %.2fs" % cue.duration,
                measured=cue.duration, limit=standard.min_duration,
                standard=standard.name))

        for line in cue.lines:
            if len(line) > standard.max_chars_per_line:
                findings.append(Finding(
                    kind=LINE_TOO_LONG, cue=cue,
                    detail="a line of %d characters: %r"
                           % (len(line), line[:50]),
                    measured=float(len(line)),
                    limit=float(standard.max_chars_per_line),
                    standard=standard.name))

        if len(cue.lines) > standard.max_lines:
            findings.append(Finding(
                kind=TOO_MANY_LINES, cue=cue,
                detail="%d lines at once" % len(cue.lines),
                measured=float(len(cue.lines)),
                limit=float(standard.max_lines),
                standard=standard.name))

        if position + 1 < len(cues):
            following = cues[position + 1]
            gap = following.start - cue.end
            # A negative gap is an overlap, which the parser already reports;
            # reporting it twice under a reading-speed heading would make one
            # fault look like two.
            if 0 <= gap < standard.min_gap:
                findings.append(Finding(
                    kind=GAP_TOO_TIGHT, cue=cue,
                    detail="%.0fms before the next line appears"
                           % (gap * 1000),
                    measured=gap, limit=standard.min_gap,
                    standard=standard.name))

    return ReadingReport(standard=standard, findings=tuple(findings),
                         rates=tuple(rates))
