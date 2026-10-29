import json
import subprocess
from pathlib import Path

# long edge capped at 1024px (~800 vision tokens/frame); portrait phone videos keep their aspect ratio
_SCALE = "scale='if(gte(iw,ih),min(1024,iw),-2)':'if(gte(iw,ih),-2,min(1024,ih))'"


def duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def extract_frames(video: Path, out_dir: Path, n: int = 8, start: float = 0.0, end: float | None = None) -> list[Path]:
    """Grab n evenly spaced frames from [start, end); file names carry the timestamp (f03_007.5s.jpg)."""
    total = duration(video)
    start = max(0.0, start)
    end = total if end is None else min(end, total)
    if end <= start:
        raise ValueError(f"empty range {start}-{end} (video is {total:.1f}s)")

    out_dir.mkdir(parents=True, exist_ok=True)
    step = (end - start) / n
    frames = []
    for i in range(n):
        t = start + step * (i + 0.5)
        path = out_dir / f"f{i + 1:02d}_{t:05.1f}s.jpg"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video),
             "-frames:v", "1", "-vf", _SCALE, "-q:v", "3", str(path)],
            check=True, timeout=60,
        )
        frames.append(path)
    return frames


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "t.mp4"
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=10:size=1080x1920:rate=30",
             "-pix_fmt", "yuv420p", str(src)],
            check=True,
        )
        assert abs(duration(src) - 10) < 0.2
        frames = extract_frames(src, Path(tmp) / "all")
        assert len(frames) == 8 and all(f.stat().st_size > 0 for f in frames)
        assert frames[0].name == "f01_000.6s.jpg", frames[0].name
        zoom = extract_frames(src, Path(tmp) / "zoom", n=4, start=6, end=8)
        assert zoom[0].name == "f01_006.2s.jpg", zoom[0].name
        w, h = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
             "-of", "csv=p=0", str(frames[0])], capture_output=True, text=True,
        ).stdout.strip().split(",")
        assert (int(w), int(h)) == (576, 1024), (w, h)
        print("video.py ok")
