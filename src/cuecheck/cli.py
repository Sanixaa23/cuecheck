"""The command line, and three exit codes that mean three different things.

    0   checked, nothing to report
    1   checked, and here is what is wrong
    2   could not check

The third one is the point. A tool that returns success when it failed to
measure anything teaches whoever put it in their pipeline that silence means
quality, and the first file it cannot read then ships unchecked. So a missing
audio stream, an unreadable subtitle file, a wall of music with no silence in
it -- all of them are 2, and the message says which.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional, Sequence

from . import __version__
from .audio import (DEFAULT_MIN_SILENCE, DEFAULT_THRESHOLD_DB, FfmpegMissing,
                    NoAudioStream, analyse)
from .cues import format_timestamp, parse_path
from .reading import DEFAULT_STANDARD, STANDARDS, check
from .sync import (DEFAULT_TOLERANCE, DEFAULT_WINDOW, EARLY, LATE, MEASURED,
                   NO_SPEECH, ON_TIME, UNMEASURABLE, time_cues)

SUBTITLE_EXTENSIONS = (".srt", ".vtt")

OK = 0
FINDINGS = 1
CANNOT_CHECK = 2


def _make_output_printable() -> None:
    """Keep a narrow console from turning a report into a crash.

    The report carries arrows and a dash or two, and a Windows console on a
    legacy code page cannot encode them. Replacing the character is a far
    better failure than a traceback over a file the user wanted checked.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _split_inputs(paths: Sequence[str]):
    subtitles: List[str] = []
    media: List[str] = []
    for path in paths:
        if path.lower().endswith(SUBTITLE_EXTENSIONS):
            subtitles.append(path)
        else:
            media.append(path)
    return subtitles, media


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cuecheck",
        description="Finds the subtitle lines that are mistimed or too fast "
                    "to read, one line at a time.")
    p.add_argument("paths", nargs="+", metavar="FILE",
                   help="a subtitle file (.srt/.vtt), and optionally the "
                        "video or audio it belongs to")
    p.add_argument("--standard", choices=sorted(STANDARDS),
                   default="netflix",
                   help="which published reading-speed limits to apply "
                        "(default: netflix)")
    p.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                   metavar="SECONDS",
                   help="how far a cue may sit from the speech and still "
                        "count as on time (default: %.2f)" % DEFAULT_TOLERANCE)
    p.add_argument("--window", type=float, default=DEFAULT_WINDOW,
                   metavar="SECONDS",
                   help="how far to look for the speech onset belonging to a "
                        "cue (default: %.1f)" % DEFAULT_WINDOW)
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_DB,
                   metavar="DB",
                   help="level below which audio counts as silence "
                        "(default: %g)" % DEFAULT_THRESHOLD_DB)
    p.add_argument("--min-silence", type=float, default=DEFAULT_MIN_SILENCE,
                   metavar="SECONDS",
                   help="how long a quiet stretch must last to be a pause "
                        "(default: %g)" % DEFAULT_MIN_SILENCE)
    p.add_argument("--json", action="store_true",
                   help="machine-readable output")
    p.add_argument("--version", action="version",
                   version="cuecheck %s" % __version__)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    _make_output_printable()
    args = _parser().parse_args(argv)

    subtitles, media = _split_inputs(args.paths)
    if not subtitles:
        print("cuecheck: give me a subtitle file (.srt or .vtt). Nothing to "
              "check without one.", file=sys.stderr)
        return CANNOT_CHECK
    if len(subtitles) > 1:
        print("cuecheck: one subtitle file at a time; got %d."
              % len(subtitles), file=sys.stderr)
        return CANNOT_CHECK

    subtitle_path = subtitles[0]
    if not os.path.exists(subtitle_path):
        print("cuecheck: %s does not exist." % subtitle_path, file=sys.stderr)
        return CANNOT_CHECK

    with open(subtitle_path, "r", encoding="utf-8", errors="replace") as handle:
        parsed = parse_path(subtitle_path, handle.read())

    if not parsed.usable:
        print("cuecheck: could not read a single cue out of %s."
              % subtitle_path, file=sys.stderr)
        for defect in parsed.defects:
            print("  line %d: %s" % (defect.line_number, defect.detail),
                  file=sys.stderr)
        return CANNOT_CHECK

    standard = STANDARDS.get(args.standard, DEFAULT_STANDARD)
    reading = check(parsed.cues, standard)

    sync = None
    audio = None
    audio_error = None
    if media:
        try:
            audio = analyse(media[0], args.threshold, args.min_silence)
            sync = time_cues(parsed.cues, audio, args.tolerance, args.window)
        except (FfmpegMissing, NoAudioStream, FileNotFoundError,
                RuntimeError) as error:
            audio_error = str(error)

    if args.json:
        print(json.dumps(_as_json(subtitle_path, parsed, reading, sync,
                                  audio, audio_error), indent=1))
    else:
        _print_report(subtitle_path, parsed, reading, sync, audio, audio_error)

    if audio_error is not None:
        return CANNOT_CHECK
    if parsed.defects or reading.findings or (sync and sync.off) \
            or (sync and sync.over_silence):
        return FINDINGS
    if sync is None and media:
        return CANNOT_CHECK
    return OK


def _print_report(path, parsed, reading, sync, audio, audio_error) -> None:
    fmt = parsed.fmt
    print("%s: %d cues, %s format" % (os.path.basename(path),
                                      len(parsed.cues), fmt))

    if parsed.defects:
        print("\n## The file itself")
        for defect in parsed.defects:
            where = "line %d" % defect.line_number if defect.line_number else "file"
            print("  %-24s %s: %s" % (defect.kind, where, defect.detail))

    if audio_error is not None:
        print("\n## Timing")
        print("  not checked: %s" % audio_error)
    elif sync is not None:
        measured, silent, unmeasurable = sync.counts()
        print("\n## Timing  (%d measurable, %d over silence, %d without an "
              "anchor)" % (measured, silent, unmeasurable))
        if sync.continuous_audio:
            print("  the audio has almost no silence in it, so no cue could "
                  "be timed against it")
        else:
            median = sync.median_offset
            if median is not None:
                print("  median offset %+.3fs -- what a whole-file "
                      "synchroniser would shift by" % median)
            for timing in sync.off:
                print("  %s %-6s %+.3fs  %s" % (
                    format_timestamp(timing.cue.start, fmt),
                    timing.verdict, timing.offset, timing.reason))
            for timing in sync.over_silence:
                print("  %s %-6s  %s" % (
                    format_timestamp(timing.cue.start, fmt),
                    "silent", timing.reason))
            if not sync.off and not sync.over_silence and measured:
                print("  every measurable cue is within %.2fs of its speech"
                      % sync.tolerance)

    print("\n## Reading speed  (%s -- %s)" % (reading.standard.name,
                                              reading.standard.source))
    if reading.findings:
        for finding in reading.worst:
            print("  %s %-15s %s (limit %.3g)" % (
                format_timestamp(finding.cue.start, fmt), finding.kind,
                finding.detail, finding.limit))
    else:
        print("  every cue is inside the limits")


def _as_json(path, parsed, reading, sync, audio, audio_error) -> dict:
    out = {
        "file": path,
        "format": parsed.fmt,
        "cues": len(parsed.cues),
        "defects": [d._asdict() for d in parsed.defects],
        "reading": {
            "standard": reading.standard.name,
            "source": reading.standard.source,
            "findings": [{
                "kind": f.kind, "cue": f.cue.index, "start": f.cue.start,
                "detail": f.detail, "measured": f.measured, "limit": f.limit,
            } for f in reading.worst],
        },
    }
    if audio_error is not None:
        out["timing"] = {"checked": False, "reason": audio_error}
    elif sync is not None:
        measured, silent, unmeasurable = sync.counts()
        out["timing"] = {
            "checked": True,
            "measurable": measured,
            "over_silence": silent,
            "without_anchor": unmeasurable,
            "median_offset": sync.median_offset,
            "worst_offset": sync.worst_offset,
            "tolerance": sync.tolerance,
            "off": [{
                "cue": t.cue.index, "start": t.cue.start,
                "offset": t.offset, "verdict": t.verdict, "reason": t.reason,
            } for t in sync.off],
        }
    return out


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
