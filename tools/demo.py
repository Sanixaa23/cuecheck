"""Draw the README's GIF from output this script actually captured.

The picture is rendered rather than screen-recorded, which is only honest if
every character in it came out of a real run. So this script runs cuecheck
against the committed fixture, keeps the bytes, and draws those. Nothing is
typed into a transcript, and if the tool's output changes the GIF changes
with it on the next run.

Two things are added to the captured text and nothing else is:

  * Colour. The captured stream is plain -- cuecheck emits no escape codes --
    so the dim grey, the amber on the median line and the red on the two
    findings are the drawing's, not the program's.
  * Line wrapping at 96 columns, with a hanging indent, exactly as a terminal
    of that width would wrap it. The characters are untouched; only where the
    line breaks is chosen here.

The GIF is silent, as every GIF is. It is a preview of the report, not of a
session with narration.

    python tools/demo.py

Writes docs/demo.gif.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

OUT = os.path.join(ROOT, "docs", "demo.gif")
FIXTURE = os.path.join(HERE, "make_fixture.py")
SUBTITLE = os.path.join("corpus", "legible-shifted.srt")
AUDIO = os.path.join("corpus", "legible-narration.m4a")

COLUMNS = 96
# Durations in milliseconds, per distinct picture. Repeating an identical
# frame to lengthen a beat is what made the first version of this file a
# megabyte: every repeat is stored again. One frame with a long duration
# costs nothing.
TYPE_MS = 55                 # per two characters of the command
BEAT_MS = 280                # between the command and its output
LINE_MS = 190                # per revealed line of the report
HOLD_MS = 2600               # the finished report, held so it can be read

BG = (18, 20, 24)
PROMPT = (126, 196, 124)
TYPED = (232, 232, 230)
DIM = (128, 134, 142)
HEADING = (142, 182, 230)
AMBER = (214, 168, 84)
RED = (214, 96, 90)
CURSOR = (232, 232, 230)

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\lucon.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/Library/Fonts/Menlo.ttc",
)
FONT_SIZE = 15
LINE_HEIGHT = 21
MARGIN = 18


def font() -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, FONT_SIZE)
    raise SystemExit(
        "no monospace font found. A proportional font would misalign every "
        "column in the report, so this refuses rather than drawing it wrong.")


def capture() -> Tuple[str, List[str], int]:
    """Run cuecheck for real and return (command, output lines, exit code)."""
    if not os.path.exists(os.path.join(ROOT, AUDIO)):
        subprocess.run([sys.executable, FIXTURE], check=True,
                       capture_output=True)

    command = "cuecheck %s %s" % (SUBTITLE.replace("\\", "/"),
                                  AUDIO.replace("\\", "/"))
    done = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'src');"
         " from cuecheck.cli import main; sys.exit(main(sys.argv[1:]))",
         SUBTITLE, AUDIO],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    text = (done.stdout or "") + (done.stderr or "")
    if not text.strip():
        raise SystemExit("cuecheck produced no output; nothing to draw.")
    return command, text.rstrip("\n").split("\n"), done.returncode


def wrap(line: str, width: int = COLUMNS) -> List[str]:
    """Break a long line the way a terminal of `width` columns would.

    Wrapped continuations are indented to the start of the text, so a long
    reason stays visually attached to its timestamp.
    """
    if len(line) <= width:
        return [line]
    indent = len(line) - len(line.lstrip(" "))
    hanging = " " * min(indent + 2, width - 20)
    out: List[str] = []
    rest = line
    first = True
    while rest:
        room = width - (0 if first else len(hanging))
        if len(rest) <= room:
            out.append(rest if first else hanging + rest)
            break
        cut = rest.rfind(" ", 0, room)
        if cut <= 0:
            cut = room
        out.append(rest[:cut] if first else hanging + rest[:cut])
        rest = rest[cut:].lstrip(" ")
        first = False
    return out


def colour(line: str) -> Tuple[int, int, int]:
    stripped = line.strip()
    if stripped.startswith("##"):
        return HEADING
    if "median offset" in line:
        return AMBER
    if any(word in line for word in (" mistimed ", " early ", " late ",
                                     " silent ")):
        return RED
    if stripped.startswith("overlap") or "line-too-long" in line:
        return DIM
    return TYPED


def draw(lines: Sequence[str], command: str, revealed: int,
         typed: Optional[int], size: Tuple[int, int],
         glyph: float, show_cursor: bool) -> Image.Image:
    image = Image.new("RGB", size, BG)
    pen = ImageDraw.Draw(image)
    face = font()

    y = MARGIN
    pen.text((MARGIN, y), "$", font=face, fill=PROMPT)
    shown = command if typed is None else command[:typed]
    pen.text((MARGIN + int(glyph * 2), y), shown, font=face, fill=TYPED)
    if show_cursor:
        x = MARGIN + int(glyph * (2 + len(shown)))
        pen.rectangle([x, y + 2, x + int(glyph) - 1, y + FONT_SIZE + 2],
                      fill=CURSOR)
    y += LINE_HEIGHT * 2

    for line in lines[:revealed]:
        pen.text((MARGIN, y), line, font=face, fill=colour(line))
        y += LINE_HEIGHT

    return image


def main() -> int:
    command, raw, code = capture()

    lines: List[str] = []
    for line in raw:
        lines.extend(wrap(line))

    face = font()
    glyph = face.getlength("M")
    width = MARGIN * 2 + int(glyph * (COLUMNS + 2)) + 2
    height = MARGIN * 2 + LINE_HEIGHT * (len(lines) + 2)
    size = (width, height)

    frames: List[Image.Image] = []
    delays: List[int] = []

    def add(image: Image.Image, ms: int) -> None:
        frames.append(image)
        delays.append(ms)

    # The command being typed, then a beat before the output.
    for index in range(1, len(command) + 1, 2):
        # revealed=0: nothing of the report is on screen while it is typed.
        add(draw(lines, command, 0, index, size, glyph, True), TYPE_MS)
    add(draw(lines, command, 0, None, size, glyph, True), BEAT_MS)

    # The report, a line at a time. One picture each, not one per tick.
    for count in range(1, len(lines) + 1):
        add(draw(lines, command, count, None, size, glyph, False), LINE_MS)
    delays[-1] = HOLD_MS

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # One palette for every frame, taken from the final one, which contains
    # all the colours. Quantising each frame separately gives each its own
    # palette, and a frame with its own palette cannot be stored as a diff of
    # the frame before it -- which is where the size goes.
    reference = frames[-1].convert("P", palette=Image.ADAPTIVE, colors=16)
    quantised = [f.quantize(palette=reference, dither=Image.NONE)
                 for f in frames]
    quantised[0].save(OUT, save_all=True, append_images=quantised[1:],
                      duration=delays, loop=0, optimize=True)

    print("captured %d lines of real output, exit code %d" % (len(raw), code))
    print("%s" % OUT)
    print("%dx%d, %d frames, %.1fs, %.0f KB" % (
        width, height, len(frames), sum(delays) / 1000.0,
        os.path.getsize(OUT) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
