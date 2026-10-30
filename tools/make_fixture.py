"""Build a subtitle file whose correct timings are known, not guessed.

Testing a timing checker needs ground truth, and ground truth is the one
thing a subtitle file never carries: you cannot tell from a .srt whether its
numbers are right. So the fixture is derived instead of written.

`legible-short.mp4` was rendered scene by scene, each scene lasting exactly
as long as its own narration clip plus a fixed breath, snapped to whole
frames. Those clips are committed here in `corpus/narration/`, so this script
measures them, recomputes the same boundaries the renderer used, and lays the
clips back out on that grid as one audio track. The result is a subtitle file
and an audio file that are correct relative to each other by construction --
every cue starts where its line of speech starts, because both come from the
same measurement.

Building the audio here rather than pointing at the video is what makes the
claim checkable from a clone of this repository alone. Depending on a sibling
checkout meant the two tests that matter most skipped themselves for anyone
who cloned only this project, which is the same as not having them.

Then it writes a second copy with two cues deliberately moved by amounts
printed on screen. A checker worth anything must name those two and leave
the rest alone. Reporting a third is a false positive, and in a tool that
tells people to retime their work, a false positive is the expensive error.

    python tools/make_fixture.py

Writes corpus/legible-clean.srt and corpus/legible-shifted.srt.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from cuecheck.audio import ffmpeg                       # noqa: E402
from cuecheck.cues import format_timestamp              # noqa: E402

# The renderer's own constants. PAD is the breath after each line; the video
# is 30fps, and a scene can only be a whole number of frames long.
PAD = 0.45
FPS = 30.0

NARRATION = os.path.join(ROOT, "corpus", "narration")
AUDIO_OUT = os.path.join(ROOT, "corpus", "legible-narration.m4a")

# The script as generated, in order. The text is what is actually spoken, so
# the characters-per-second figures this fixture produces are real.
SCRIPT: Tuple[Tuple[str, str], ...] = (
    ("01_hook", "You just read a whole page. Be honest —\ncan you remember one single sentence?"),
    ("02_not_you", "It is not your attention span.\nIt is the shape of the text."),
    ("03_wall", "Sixty words before a single break. Your eyes\nhave to carry all of it before any of it means anything."),
    ("04_break", "So we broke it apart.\nSixty words, down to twenty-eight."),
    ("05_same_words", "Same words. Every single one. Nothing rewritten,\nnothing summarised, nothing deleted."),
    ("06_nobody_checks", "Here's what nobody checks. Tools that simplify\ntext quietly change what it says."),
    ("07_antibiotics", "Antibiotics do not work against viruses becomes\nantibiotics work against viruses. Opposite meaning."),
    ("08_counts", "So this one counts what has to survive.\nEvery number. Every name. Every not."),
    ("09_proof", "Thirteen out of thirteen. Kept."),
    ("10_end", "It's called legible. Free, offline, open source.\nYour text never leaves your machine."),
)

# Cue number (1-based) -> seconds to move it by. Both are far outside any
# sane tolerance, and in opposite directions, so a checker that only looks
# for a single global shift cannot explain them.
SHIFTS = {3: +1.50, 7: -1.20}

_DURATION = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")


def clip_seconds(path: str) -> float:
    done = subprocess.run([ffmpeg(), "-hide_banner", "-i", path],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    match = _DURATION.search(done.stderr or "")
    if not match:
        raise SystemExit("cannot read the length of %s" % path)
    return (int(match.group(1)) * 3600 + int(match.group(2)) * 60
            + float(match.group(3)))


# Filled in by boundaries(): (clip name, spoken seconds, scene seconds).
_scenes: List[Tuple[str, float, float]] = []


def boundaries() -> List[Tuple[float, float, str]]:
    """(start, end, text) for every line, on the renderer's own grid."""
    out: List[Tuple[float, float, str]] = []
    del _scenes[:]
    cursor = 0.0
    for name, text in SCRIPT:
        clip = os.path.join(NARRATION, name + ".mp3")
        if not os.path.exists(clip):
            raise SystemExit(
                "%s is missing. This fixture is derived from the narration "
                "clips; without them there is no ground truth to derive."
                % clip)
        spoken = clip_seconds(clip)
        frames = max(1, int(round((spoken + PAD) * FPS)))
        scene = frames / FPS
        # The cue covers the speech, not the breath after it.
        out.append((cursor, cursor + spoken, text))
        _scenes.append((name, spoken, scene))
        cursor += scene
    return out


def write_srt(path: str, rows: List[Tuple[float, float, str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for number, (start, end, text) in enumerate(rows, 1):
            handle.write("%d\n%s --> %s\n%s\n\n" % (
                number, format_timestamp(start), format_timestamp(end), text))


def build_audio(scenes: List[Tuple[str, float, float]]) -> None:
    """Lay the clips back out on the renderer's grid, as one track.

    Each clip is padded to its scene's exact length, so the speech in the
    result starts where the subtitle file says it does. `apad=whole_dur`
    rather than `pad_dur`: the part has to be exactly as long as the scene,
    or every later line drifts by the rounding.
    """
    work = tempfile.mkdtemp(prefix="cuecheck-fixture-")
    parts = []
    for position, (name, _spoken, scene) in enumerate(scenes):
        clip = os.path.join(NARRATION, name + ".mp3")
        part = os.path.join(work, "%02d.wav" % position)
        subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", clip,
                        "-af", "apad=whole_dur=%.6f" % scene,
                        "-t", "%.6f" % scene,
                        "-ar", "44100", "-ac", "1", part], check=True)
        parts.append(part)

    listing = os.path.join(work, "list.txt")
    with open(listing, "w", encoding="utf-8") as handle:
        for part in parts:
            handle.write("file '%s'\n" % part.replace("\\", "/"))
    subprocess.run([ffmpeg(), "-y", "-v", "error", "-f", "concat",
                    "-safe", "0", "-i", listing,
                    "-c:a", "aac", "-b:a", "96k", AUDIO_OUT], check=True)
    shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    rows = boundaries()
    corpus = os.path.join(ROOT, "corpus")
    os.makedirs(corpus, exist_ok=True)
    build_audio(_scenes)

    clean = os.path.join(corpus, "legible-clean.srt")
    write_srt(clean, rows)

    shifted_rows = []
    for number, (start, end, text) in enumerate(rows, 1):
        move = SHIFTS.get(number, 0.0)
        shifted_rows.append((max(0.0, start + move), max(0.0, end + move), text))
    shifted = os.path.join(corpus, "legible-shifted.srt")
    write_srt(shifted, shifted_rows)

    print("ground truth, derived from the narration clips:")
    for number, (start, end, _) in enumerate(rows, 1):
        note = ""
        if number in SHIFTS:
            note = "   shifted by %+.2fs in legible-shifted.srt" % SHIFTS[number]
        print("  cue %2d  %s --> %s%s" % (
            number, format_timestamp(start), format_timestamp(end), note))
    print("\nwrote %s" % clean)
    print("wrote %s" % shifted)
    print("\nA checker must report exactly cues %s on the shifted file."
          % ", ".join(str(n) for n in sorted(SHIFTS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
