#!/usr/bin/env python3
"""The ffmpeg renderer, and the studio's media utility (docs/animation-studio.md §6).

Runs inside the ai-workspace/renderer-ffmpeg image with the project folder
mounted at /project. Subcommands:

  render   /project/artifacts/07-render/plan.json -> /project/artifacts/final-candidate.mp4
  frames   final-candidate.mp4 -> /project/artifacts/07-render-frames/frame-NN.jpg
  probe    <file>  -> JSON summary of streams on stdout
  publish  final-candidate.mp4 -> /project/final.mp4 (H.264/AAC/yuv420p/faststart) + /project/preview.jpg
  rasterize <in.svg> <out.png> [width height]   paths relative to artifacts/

plan.json:
  {
    "width": 1080, "height": 1920, "fps": 30,
    "audio": "05-voice.mp3",                    # optional, relative to artifacts/
    "shots": [
      {"text": "Why do cats purr?", "duration": 2.5, "color": "#1b1b2f"},
      {"image": "05-shot-1.png", "text": "...", "duration": 4},
      {"svg": "05-shot-2.svg", "text": "...", "duration": 4}
    ]
  }
Each shot is a still -- an image, an SVG (rasterised here at the frame size:
the studio's code-made image engine), or a flat colour -- with an optional
caption.
"""

import json
import shlex
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

PROJECT = Path("/project")
ARTIFACTS = PROJECT / "artifacts"
CANDIDATE = ARTIFACTS / "final-candidate.mp4"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def run(argv: list[str], log) -> None:
    log.write("$ " + " ".join(shlex.quote(a) for a in argv) + "\n")
    log.flush()
    result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {argv[0]} ...")


def caption_fontsize(height: int) -> int:
    return max(24, height // 26)


def wrap_caption(text: str, width: int, fontsize: int) -> str:
    """Break a caption into lines that fit 90 % of the frame width.

    drawtext never wraps: the first real render cut "Why does your cat purr?"
    off at both edges. DejaVu Sans Bold averages about 0.6 em per character.
    """
    per_line = max(8, int(width * 0.9 / (fontsize * 0.6)))
    return "\n".join(textwrap.wrap(text, per_line) or [""])


def caption_filter(text: str, width: int, height: int, tmp: Path, index: int) -> str:
    if not text:
        return "null"
    fontsize = caption_fontsize(height)
    # ffmpeg's filter syntax can't escape every character inside text='...'
    # (an apostrophe breaks it); a textfile has no such problem.
    caption = tmp / f"caption-{index:02d}.txt"
    caption.write_text(wrap_caption(text, width, fontsize), encoding="utf-8")
    return (
        f"drawtext=fontfile={FONT}:textfile={caption}:fontcolor=white:fontsize={fontsize}"
        f":line_spacing={fontsize // 5}:text_align=C"
        f":box=1:boxcolor=black@0.55:boxborderw=18:x=(w-text_w)/2:y=h-h/5-text_h"
    )


def rasterize(svg: Path, png: Path, width: int, height: int, log) -> None:
    """SVG -> PNG at the frame size, aspect kept (rsvg-convert pads nothing:
    the scale/pad filter in render() centres it on the frame)."""
    if not svg.is_file():
        raise RuntimeError(f"svg not found: {svg}")
    run(["rsvg-convert", "--keep-aspect-ratio", "--width", str(width), "--height", str(height),
         "--output", str(png), str(svg)], log)


def render(log) -> None:
    plan = json.loads((ARTIFACTS / "07-render" / "plan.json").read_text(encoding="utf-8"))
    width, height, fps = int(plan.get("width", 1080)), int(plan.get("height", 1920)), int(plan.get("fps", 30))
    shots = plan["shots"]
    if not shots:
        raise RuntimeError("plan has no shots")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        parts = []
        for i, shot in enumerate(shots):
            duration = float(shot.get("duration", 3))
            out = tmp / f"shot-{i:02d}.mp4"
            vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,{caption_filter(shot.get('text', ''), width, height, tmp, i)},format=yuv420p"
            if shot.get("svg"):
                png = tmp / f"shot-{i:02d}.png"
                rasterize(ARTIFACTS / shot["svg"], png, width, height, log)
                src = ["-loop", "1", "-t", str(duration), "-i", str(png)]
            elif shot.get("image"):
                src = ["-loop", "1", "-t", str(duration), "-i", str(ARTIFACTS / shot["image"])]
            else:
                color = shot.get("color", "#101010")
                src = ["-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:d={duration}:r={fps}"]
            run(["ffmpeg", "-y", "-loglevel", "error", *src, "-vf", vf, "-r", str(fps),
                 "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", str(out)], log)
            parts.append(out)
        concat = tmp / "list.txt"
        concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        video = tmp / "video.mp4"
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(video)], log)
        audio = plan.get("audio")
        if audio:
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(ARTIFACTS / audio),
                 "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(CANDIDATE)], log)
        else:
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c", "copy", "-movflags", "+faststart", str(CANDIDATE)], log)
    log.write(f"wrote {CANDIDATE}\n")


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    return {
        "container": data["format"].get("format_name"),
        "duration": float(data["format"].get("duration", 0)),
        "video_codec": video and video.get("codec_name"),
        "pix_fmt": video and video.get("pix_fmt"),
        "width": video and video.get("width"),
        "height": video and video.get("height"),
        "audio_codec": audio and audio.get("codec_name"),
    }


def browser_safe(info: dict) -> bool:
    return (
        info["video_codec"] == "h264"
        and info["pix_fmt"] == "yuv420p"
        and (info["audio_codec"] in (None, "aac"))
        and "mp4" in (info["container"] or "")
    )


def frames(log) -> None:
    info = probe(CANDIDATE)
    out_dir = ARTIFACTS / "07-render-frames"
    out_dir.mkdir(exist_ok=True)
    n = 6
    step = max(info["duration"] / n, 0.1)
    for i in range(n):
        t = min(i * step + step / 2, max(info["duration"] - 0.05, 0))
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(CANDIDATE),
             "-frames:v", "1", "-vf", "scale=-2:480", str(out_dir / f"frame-{i + 1:02d}.jpg")], log)
    log.write(f"wrote {n} frames to {out_dir}\n")


def publish(log) -> None:
    info = probe(CANDIDATE)
    final = PROJECT / "final.mp4"
    if browser_safe(info):
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(CANDIDATE), "-c", "copy", "-movflags", "+faststart", str(final)], log)
    else:
        log.write(f"not browser-safe ({info}); transcoding\n")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(CANDIDATE), "-c:v", "libx264", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(final)], log)
    final_info = probe(final)
    if not browser_safe(final_info):
        raise RuntimeError(f"still not browser-safe after transcoding: {final_info}")
    t = 1.0 if final_info["duration"] > 1.2 else 0.0
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(final), "-frames:v", "1",
         "-vf", "scale=-2:720", str(PROJECT / "preview.jpg")], log)
    print(json.dumps(final_info))


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "probe":
        print(json.dumps(probe(Path(rest[0]))))
        return 0
    if cmd == "rasterize":
        svg, png = ARTIFACTS / rest[0], ARTIFACTS / rest[1]
        width, height = (int(rest[2]), int(rest[3])) if len(rest) >= 4 else (1080, 1920)
        with (ARTIFACTS / "rasterize.log").open("a", encoding="utf-8") as log:
            try:
                rasterize(svg, png, width, height, log)
            except Exception as exc:  # noqa: BLE001
                log.write(f"ERROR: {exc}\n")
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
        return 0
    # Same names the API appends to, so each step has exactly one log + sidecar.
    log_path = ARTIFACTS / {"render": "07-render.log", "frames": "07-frames.log", "publish": "08-publish.log"}.get(cmd, f"{cmd}.log")
    with log_path.open("a", encoding="utf-8") as log:
        try:
            {"render": render, "frames": frames, "publish": publish}[cmd](log)
        except KeyError:
            print(f"unknown command {cmd!r}", file=sys.stderr)
            return 2
        except Exception as exc:  # noqa: BLE001 -- the log is the point
            log.write(f"ERROR: {exc}\n")
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
