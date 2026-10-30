# cuecheck

Finds the subtitle lines that are mistimed or too fast to read — one line at a
time, measured against the audio and against published reading-speed limits.

```bash
pip install git+https://github.com/Sanixaa23/cuecheck
cuecheck lecture.mp4 lecture.srt
```

No runtime dependencies. The audio side shells out to `ffmpeg`, which is a
program rather than a wheel that can fail to build. Nothing is uploaded; the
file never leaves the machine.

![cuecheck naming the two mistimed lines in a file whose median offset is 0.047s](docs/demo.gif)

Every character above came out of a real run. `tools/demo.py` runs cuecheck
against the committed fixture and draws the bytes it captured, so the picture
changes when the output does; nothing was typed into a transcript. Two things
are added and nothing else: colour, and the line wrapping a 96-column terminal
would do. It is silent, as every GIF is.

---

## The failure every other tool is blind to

Every subtitle synchroniser answers one question: **by how much is this whole
file shifted?** `ffsubsync`, `subsync`, `alass` — they cross-correlate the
speech against the cue times, produce a single number, and move everything by
it. That is the right tool for a file muxed against the wrong frame rate.

It is blind to the failure that actually reaches viewers: a file whose
**median offset is zero** and whose five hardest lines are a second and a half
out, because someone retimed the middle by hand. Shift that file by its
median and nothing changes — and the tool reports success.

Here is that exact situation, measured. Two cues were moved by known amounts;
the rest are correct:

```
## Timing  (10 measurable, 0 over silence, 0 without an anchor)
  median offset +0.037s -- what a whole-file synchroniser would shift by
  00:00:12,333 mistimed +1.445s  1.45s from the nearest speech start, but 2 speech starts lie within 2.0s (13.78s, 10.87s), so the audio cannot say which way it is off
  00:00:35,167 early  +1.249s  on screen 1.25s before anyone speaks
```

`+0.037s` is what the whole-file tools would correct. The two lines that are
actually broken are off by more than a second, and they are named.

## Three outcomes per cue, not two

A cue can only be timed against a moment the audio itself marks, and
`silencedetect` gives exactly one such moment: speech starting after a pause.
A cue sitting in the middle of a continuous sentence has no onset near it, and
that is **normal** — dialogue does not pause between lines. Calling it late
would be a false positive, and a false positive here tells someone to go and
retime a line that was already correct.

So every cue lands in one of three states, and the counts are printed:

| state | meaning |
|---|---|
| `measured` | a silence ended near this cue, so the offset is a number |
| `no-speech` | the cue's whole span is silent — a line over nothing |
| `unmeasurable` | speech is already running; there is no anchor to use |

Only `measured` cues get a verdict. `10 measurable, 0 over silence, 0 without
an anchor` tells you what the verdict covers.

Under a music bed there may be no silence at all. That is not a file with
perfect subtitles; it is a file this method cannot measure, and it says so
rather than printing zeroes.

## It will not guess the direction it cannot see

Found while testing, and worth more than the feature it broke. A cue was
pushed **1.50s late** on purpose. The checker reported it **1.45s early**.

The cause is real: the speaker pauses in the middle of that line, and
`silencedetect` reports the pause as speech starting again. That mid-line
breath sat 1.445s ahead of the cue; the true start of the line sat 1.465s
behind it. Nearest-onset matching picked the breath, by twenty milliseconds.

The magnitude was right and the sign was inverted — the worst shape an error
can take here, because it sends someone to move a line the wrong way. So when
more than one onset could explain a cue, the verdict is `mistimed`, the
magnitude is given, the candidate onsets are listed, and the direction is
left alone. A test pins it: the cue with a clean anchor keeps its direction,
the cue with a pause inside it does not get one.

## Reading speed, with a citation

A subtitle can be perfectly synchronised and still unusable. Sixty characters
held for eight tenths of a second is on time and unreadable, and it is the
more common failure in material made by people who are not subtitlers — a
lecturer captioning their own slides sets the timings from the speech and
never asks how fast the result has to be read.

Unlike sync tolerance, this has published numbers, so none of the thresholds
are mine and every finding names its source:

| standard | rate | min duration | chars/line | lines |
|---|---|---|---|---|
| `netflix` | 17 cps | 5/6 s | 42 | 2 |
| `netflix-children` | 13 cps | 5/6 s | 42 | 2 |
| `bbc` | 180 wpm ≈ 18 cps | 1 s | 37 | 2 |

The same file, checked for a children's audience instead of an adult one:

```
## Reading speed  (Netflix (children) -- Netflix Timed Text Style Guide, English)
  00:00:10,833 too-fast        101 characters in 6.92s is 14.6 per second (limit 13)
  00:00:06,167 too-fast        59 characters in 4.21s is 14.0 per second (limit 13)
  00:00:00,000 too-fast        77 characters in 5.72s is 13.5 per second (limit 13)
```

Those lines pass at 17 cps and fail at 13. Which standard applies is the
user's call, not the tool's.

The line break counts as one character, because it stands in for the space
that would be there on one line. Dropping it makes the same words look cheaper
to read once they are split in two, which is backwards: breaking a line does
not shorten it. A test pins both forms to the same rate.

## Ground truth, derived rather than written

Testing a timing checker needs ground truth, and ground truth is the one thing
a subtitle file never carries — you cannot tell from a `.srt` whether its
numbers are right.

So the fixture is derived. [`legible`](https://github.com/Sanixaa23/legible)'s
short video was rendered scene by scene, each scene lasting exactly as long as
its own narration clip plus a fixed breath, snapped to whole frames. Those ten
clips are committed here in `corpus/narration/`, so `tools/make_fixture.py`
measures them, recomputes the same boundaries the renderer used, and lays the
clips back out as one audio track on that same grid. The subtitle file and the
audio are correct relative to each other **by construction**, because the cues
and the speech come from one measurement.

Both sides live in this repository on purpose. They did not at first, and the
two tests that carry the central claim skipped themselves for anyone who
cloned only this project — which is the same as not having them.

```bash
python tools/make_fixture.py
```

Then it writes a second copy with two cues moved by stated amounts. Two tests
hold the claim: the derived file must produce no findings, and the shifted
file must name **exactly** cues 3 and 7 — missing one is the obvious failure,
reporting a third is the expensive one.

```
## Timing  (10 measurable, 0 over silence, 0 without an anchor)
  median offset +0.036s -- what a whole-file synchroniser would shift by
  every measurable cue is within 0.25s of its speech
```

That `+0.036s` is the mp3's own lead-in below the −40 dB gate, and it does not
accumulate across the 63 seconds.

## The file itself

Every defect report rests on having parsed the file correctly, so nothing is
ever skipped in silence. A cue that cannot be parsed is reported with its line
number and still returned; a parser that dropped it would produce a report
saying the file is fine.

```
## The file itself
  overlap                  line 17: starts 1.053s before the previous cue ends
  overlap                  line 32: starts 0.763s before the previous cue ends
```

Reported and not corrected: two lines on screen at once is sometimes
deliberate. The rest — cues that end before they start, zero-duration cues,
cues out of order, a missing blank line that would swallow the next cue, SRT
commas mixed with WebVTT dots — all parse, all report.

## Three exit codes

```
0   checked, nothing to report
1   checked, and here is what is wrong
2   could not check
```

The third one is the point. A tool that returns success when it measured
nothing teaches whoever put it in their pipeline that silence means quality,
and the first file it cannot read then ships unchecked. A missing audio
stream, an unreadable subtitle file, a wall of music with no silence in it —
all of them are `2`, and the message says which.

## Usage

```
cuecheck SUBTITLE [MEDIA]        # timing needs the media; reading speed does not

  --standard netflix|netflix-children|bbc
  --tolerance SECONDS            # how far a cue may sit from its speech (default 0.25)
  --window SECONDS               # how far to look for the onset (default 2.0)
  --threshold DB                 # silence level (default -40)
  --min-silence SECONDS          # how long a quiet stretch must last (default 0.25)
  --json
```

`--tolerance` is the one number here that is mine rather than a standard's: no
body states how many milliseconds a subtitle may lead its audio. 0.25s is
where the measurement's own resolution stops dominating, and it is an argument
so anyone who disagrees can set their own and watch the report change.

## Development

```bash
pip install -e ".[dev,ffmpeg]"
python -m pytest -q          # 31 tests
```

Most tests build the speech intervals by hand and need no ffmpeg and no media
file, so the expected offsets are arithmetic rather than opinion. The two
ground-truth tests build their own audio from `corpus/narration/` on first
run and skip only if ffmpeg is unavailable.

CI runs the suite on Linux and Windows, and a skipped test fails the job --
the two tests that carry the central claim used to skip themselves, and a
test that skips where it matters is the same as not having it. A second job
reinstalls without `imageio-ffmpeg` and measures with the distribution's own
ffmpeg instead of the bundled build, because `silencedetect` is the whole
measurement: if two builds disagreed about where the speech starts, the
offsets above would be true of one machine and nowhere else. A third job
exercises all three exit codes, including a file it must refuse to judge --
a green pipeline that cannot go red is theatre.

## What it does not do

It does not align text to audio, so it cannot tell you which words belong to
which cue — that is why an ambiguous anchor is reported as ambiguous instead
of resolved. It does not translate, retime, or rewrite anything: it reads the
file and the audio, and writes nothing.

## Licence

MIT.
