import asyncio
import base64
import tempfile
from pathlib import Path


async def _run(*args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ValueError("Video processing timed out")
    if proc.returncode != 0:
        raise ValueError("Video could not be decoded")


def _encode(files: list[Path]) -> list[str]:
    return [base64.b64encode(f.read_bytes()).decode() for f in files]


async def extract_frames(video: Path, max_frames: int = 8) -> list[str]:
    """Scene-change keyframes; falls back to 1 fps spaced frames when too few."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        await _run(
            "ffmpeg", "-y", "-i", str(video), "-t", "120",
            "-vf", "select='gt(scene,0.3)',scale=768:-2",
            "-fps_mode", "vfr", "-frames:v", str(max_frames), str(tmp / "s_%02d.jpg"),
        )
        files = sorted(tmp.glob("s_*.jpg"))
        if len(files) < 4:
            await _run(
                "ffmpeg", "-y", "-i", str(video), "-t", "120",
                "-vf", "fps=1,scale=768:-2", str(tmp / "f_%03d.jpg"),
            )
            all_f = sorted(tmp.glob("f_*.jpg"))
            if all_f:
                step = max(len(all_f) / max_frames, 1)
                files = [all_f[int(i * step)] for i in range(min(max_frames, len(all_f)))]
        return _encode(files[:max_frames])
