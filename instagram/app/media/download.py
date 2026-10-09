import asyncio
import hashlib
import sys
from pathlib import Path

import httpx

MAX_BYTES = 50 * 1024 * 1024


class DownloadError(Exception):
    pass


async def download_reel(url: str, reel_id: str) -> Path:
    """Fetch the reel video. Direct GET first, yt-dlp fallback. Capped at 50 MB."""
    out = Path("/tmp") / f"{hashlib.sha1(reel_id.encode()).hexdigest()[:16]}.mp4"
    try:
        await _direct(url, out)
        return out
    except Exception:
        out.unlink(missing_ok=True)
    await _ytdlp(url, out)
    return out


async def _direct(url: str, out: Path) -> None:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        async with c.stream("GET", url) as r:
            r.raise_for_status()
            if "video" not in r.headers.get("content-type", ""):
                raise DownloadError("not a video")
            size = 0
            with out.open("wb") as f:
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise DownloadError("too large")
                    f.write(chunk)


async def _ytdlp(url: str, out: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "yt_dlp", "--max-filesize", "50M", "--write-info-json",
        "-o", str(out), "-f", "mp4/best", "--no-playlist", url,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
        raise DownloadError("yt-dlp timed out")
    if proc.returncode != 0 or not out.exists():
        raise DownloadError("yt-dlp failed")
