"""Image -> 5s 1080x1920 MP4 (static reel) via FFmpeg (100% free, local).

Encoding targets Instagram Reels API specs:
  - MP4, H.264, yuv420p, 30 fps, faststart (moov atom at front)
  - silent AAC track (some IG flows expect an audio stream)
  - exactly 5.0 s, 1080x1920 (9:16)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import common


class VideoError(Exception):
    pass


def _ffmpeg_bin() -> str:
    if os.environ.get("WFB_FFMPEG"):
        return os.environ["WFB_FFMPEG"]
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:  # pip fallback (imageio-ffmpeg ships a static binary)
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise VideoError("ffmpeg not found. Install it: https://ffmpeg.org (or: apt install ffmpeg)")


def make_video(cfg: dict, image_path: Path, out_path: Path) -> Path:
    v = cfg["video"]
    W, H = cfg["canvas"]["width"], cfg["canvas"]["height"]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg_bin(), "-y",
        "-loop", "1", "-t", str(v["duration_seconds"]), "-i", str(image_path),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-vf", f"scale={W}:{H}:flags=lanczos,format=yuv420p",
        "-r", str(v["fps"]),
        "-c:v", "libx264", "-preset", v.get("preset", "medium"), "-crf", str(v.get("crf", 20)),
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise VideoError(f"ffmpeg failed:\n{p.stderr[-900:]}")
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise VideoError("ffmpeg produced no output file")
    return out_path


def probe(path: Path) -> dict:
    """Return {duration, width, height, vcodec, acodec, size_mb}. Works with
    ffprobe if available, else parses `ffmpeg -i` output."""
    path = Path(path)
    out = {"duration": None, "width": None, "height": None,
           "vcodec": None, "acodec": None,
           "size_mb": round(path.stat().st_size / 1048576, 2)}
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        p = subprocess.run(
            [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True, text=True,
        )
        if p.returncode == 0:
            data = json.loads(p.stdout)
            out["duration"] = float(data.get("format", {}).get("duration") or 0)
            for s in data.get("streams", []):
                if s.get("codec_type") == "video":
                    out["width"] = s.get("width")
                    out["height"] = s.get("height")
                    out["vcodec"] = s.get("codec_name")
                elif s.get("codec_type") == "audio":
                    out["acodec"] = s.get("codec_name")
            return out
    # fallback: parse ffmpeg -i stderr
    p = subprocess.run([_ffmpeg_bin(), "-i", str(path)], capture_output=True, text=True)
    import re
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", p.stderr)
    if m:
        out["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"Video:\s*([^,]+)", p.stderr)
    if m:
        out["vcodec"] = m.group(1).strip()
        dim = re.search(r"(\d{3,5})x(\d{3,5})", p.stderr)
        if dim:
            out["width"], out["height"] = int(dim.group(1)), int(dim.group(2))
    if re.search(r"Audio:\s*aac", p.stderr):
        out["acodec"] = "aac"
    return out


def validate_video(cfg: dict, path: Path) -> list[str]:
    """Return list of problems (empty = pass)."""
    problems: list[str] = []
    v = cfg["video"]
    W, H = cfg["canvas"]["width"], cfg["canvas"]["height"]
    info = probe(path)
    if info.get("width") != W or info.get("height") != H:
        problems.append(f"dimensions {info.get('width')}x{info.get('height')} != {W}x{H}")
    if info.get("vcodec") != "h264":
        problems.append(f"video codec {info.get('vcodec')} != h264")
    dur = info.get("duration") or 0
    if not (v["duration_seconds"] - 0.25 <= dur <= v["duration_seconds"] + 0.3):
        problems.append(f"duration {dur:.2f}s outside {v['duration_seconds']}s window")
    if info.get("acodec") != "aac":
        problems.append(f"audio codec {info.get('acodec')} (want aac)")
    if info.get("size_mb", 0) > v.get("max_size_mb", 25):
        problems.append(f"size {info['size_mb']}MB > {v['max_size_mb']}MB")
    if info.get("size_mb", 0) > 100:
        problems.append("exceeds Instagram 100MB API limit")
    return problems
