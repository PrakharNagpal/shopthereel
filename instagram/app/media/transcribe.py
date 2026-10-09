import asyncio
import tempfile
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings


async def transcribe(video: Path) -> Optional[str]:
    """Speech to text. Returns None on any failure; never blocks the pipeline."""
    try:
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "a.wav"
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=60)
            if not wav.exists():
                return None
            client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=45)
            with wav.open("rb") as f:
                res = await client.audio.transcriptions.create(
                    model=settings.openai_transcribe_model, file=f
                )
            return (res.text or "").strip() or None
    except Exception:
        return None
