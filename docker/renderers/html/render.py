#!/usr/bin/env python3
"""The html renderer (docs/animation-studio.md §6).

Runs inside the ai-workspace/renderer-html image with the project mounted at
/project. One subcommand:

  render   an HTML canvas animation -> /project/artifacts/final-candidate.mp4

The page is the one the style-explainer writes: a canvas plus
`window.seek(t)` (draw the frame at time t), `window.DURATION` (seconds),
optionally `window.ready` (a promise to await before the first frame) and
`window.scoreSound` with the SOUND kit (`SOUND.renderOffline`) for audio.

Which page: artifacts/07-render/index.html, else artifacts/07-render/*.html,
else artifacts/explainer.html.

Quality (`render [standard|high]`, default standard):
  standard  30 fps, x264 CRF 18, the canvas's own size
  high      60 fps, x264 CRF 12 / preset slow, scaled up to 1080 lines
            (lanczos), AAC 256k. A page that sets `window.RENDER_SCALE`
            support -- i.e. reads `window.RENDER_SCALE` (we set it to 2 in
            high) and draws its canvas that many times larger -- gets real
            extra detail; any other page is upscaled.
`window.FPS`, if the page sets it, wins over the preset's frame rate.
"""

import base64
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path("/project")
ARTIFACTS = PROJECT / "artifacts"
CANDIDATE = ARTIFACTS / "final-candidate.mp4"
LOG = ARTIFACTS / "07-render.log"


def find_page(artifacts: Path) -> Path:
    render_dir = artifacts / "07-render"
    if (render_dir / "index.html").is_file():
        return render_dir / "index.html"
    if render_dir.is_dir():
        pages = sorted(render_dir.glob("*.html"))
        if pages:
            return pages[0]
    if (artifacts / "explainer.html").is_file():
        return artifacts / "explainer.html"
    raise RuntimeError("no page to render: put it at artifacts/07-render/index.html or artifacts/explainer.html")


# The canvas to record: the largest one on the page.
GRAB = """() => {
  const cs = [...document.querySelectorAll('canvas')];
  if (!cs.length) throw new Error('page has no canvas');
  const c = cs.sort((a, b) => b.width * b.height - a.width * a.height)[0];
  return c.toDataURL('image/png');
}"""
SIZE = """() => {
  const cs = [...document.querySelectorAll('canvas')];
  const c = cs.sort((a, b) => b.width * b.height - a.width * a.height)[0];
  return [c.width, c.height];
}"""
# Offline audio as 16-bit stereo PCM, base64; null when the page has none.
AUDIO = """async () => {
  if (!window.scoreSound || !window.SOUND || !SOUND.renderOffline) return null;
  const r = await SOUND.renderOffline(window.scoreSound, window.DURATION, 48000, { voiceover: false });
  const pcm = new Int16Array(r.inter.length);
  for (let i = 0; i < r.inter.length; i++) pcm[i] = Math.max(-1, Math.min(1, r.inter[i])) * 32767;
  let s = ''; const b = new Uint8Array(pcm.buffer);
  for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
  return { pcm: btoa(s), sr: r.sr };
}"""


def wav(pcm: bytes, sr: int) -> bytes:
    import struct
    n = len(pcm)
    return b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 2, sr, sr * 4, 4, 16) + b"data" + struct.pack("<I", n) + pcm


QUALITY = {
    "standard": {"fps": 30, "crf": 18, "preset": "medium", "height": None, "scale": 1, "abr": "192k"},
    "high": {"fps": 60, "crf": 12, "preset": "slow", "height": 1080, "scale": 2, "abr": "256k"},
}


def render(log, quality: str = "standard") -> None:
    from playwright.sync_api import sync_playwright

    q = QUALITY[quality]
    log.write(f"quality: {quality} {q}\n")

    page_path = find_page(ARTIFACTS)
    log.write(f"page: {page_path.relative_to(PROJECT)}\n")
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.add_init_script(f"window.RENDER_SCALE = {q['scale']};")
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(page_path.resolve().as_uri(), wait_until="load", timeout=60_000)
        page.wait_for_function("() => typeof window.seek === 'function' && typeof window.DURATION === 'number'", timeout=30_000)
        page.evaluate("async () => { if (window.ready) await window.ready; await document.fonts.ready; }")
        duration = float(page.evaluate("() => window.DURATION"))
        fps = int(page.evaluate(f"() => window.FPS || {q['fps']}"))
        if not 0 < duration <= 600:
            raise RuntimeError(f"bad DURATION: {duration}")
        width, height = page.evaluate(SIZE)
        frames = max(1, round(duration * fps))
        log.write(f"duration {duration}s, {fps} fps, {frames} frames, {width}x{height}\n")
        video = tmp / "video.mp4"
        enc = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "png", "-i", "-",
             "-c:v", "libx264", "-preset", q["preset"], "-crf", str(q["crf"]), "-pix_fmt", "yuv420p",
             "-vf", (f"scale=-2:{q['height']}:flags=lanczos" if q["height"] and height < q["height"] else "scale=trunc(iw/2)*2:trunc(ih/2)*2"),
             str(video)],
            stdin=subprocess.PIPE,
        )
        for i in range(frames):
            page.evaluate(f"() => window.seek({i / fps})")
            data_url = page.evaluate(GRAB)
            enc.stdin.write(base64.b64decode(data_url.split(",", 1)[1]))
            if i % (fps * 5) == 0:
                log.write(f"frame {i}/{frames}\n"); log.flush()
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError("ffmpeg failed while encoding frames")
        audio = None
        try:
            audio = page.evaluate(AUDIO)
        except Exception as exc:  # noqa: BLE001 -- a silent video beats no video
            log.write(f"audio skipped: {exc}\n")
        if errors:
            log.write("page errors:\n" + "\n".join(errors[:20]) + "\n")
        browser.close()
        if audio:
            wav_path = tmp / "sound.wav"
            wav_path.write_bytes(wav(base64.b64decode(audio["pcm"]), int(audio["sr"])))
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(wav_path),
                 "-c:v", "copy", "-c:a", "aac", "-b:a", q["abr"], "-shortest", "-movflags", "+faststart", str(CANDIDATE)], log)
        else:
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c", "copy", "-movflags", "+faststart", str(CANDIDATE)], log)
    log.write(f"wrote {CANDIDATE} ({'with' if audio else 'no'} sound)\n")


def run(argv: list[str], log) -> None:
    log.write("$ " + " ".join(shlex.quote(a) for a in argv) + "\n")
    result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {argv[0]} ...")


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "render" or (len(argv) > 1 and argv[1] not in QUALITY):
        print(__doc__)
        return 2
    quality = argv[1] if len(argv) > 1 else "standard"
    with LOG.open("a", encoding="utf-8") as log:
        try:
            render(log, quality)
        except Exception as exc:  # noqa: BLE001 -- the log is the point
            log.write(f"ERROR: {exc}\n")
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
