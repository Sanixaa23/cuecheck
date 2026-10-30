"""cuecheck -- which subtitle line is mistimed, not how far the file is off.

Two checks, and both of them cite something outside this program. The timing
comes from the audio itself, measured with one ffmpeg filter, so the same
file gives the same numbers on any machine. The reading speed comes from
published subtitle guidelines, named in every finding.

The third exit code matters as much as the other two: when cuecheck cannot
measure a file it says so and returns 2, rather than returning success and
letting a pipeline conclude the subtitles were checked.
"""
from __future__ import annotations

__version__ = "0.1.0"
