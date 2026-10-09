from pathlib import Path
from typing import Optional

from app.media.download import download_reel
from app.media.frames import extract_frames
from app.media.transcribe import transcribe
from app.models import MediaBundle


async def build_bundle(
    video: Path, reel_id: str, caption: Optional[str], user_hint: Optional[str] = None
) -> MediaBundle:
    import asyncio

    frames, transcript = await asyncio.gather(extract_frames(video), transcribe(video))
    return MediaBundle(
        reel_id=reel_id, frames_b64=frames, caption=caption,
        transcript=transcript, user_hint=user_hint,
    )


async def bundle_from_url(
    url: str, reel_id: str, caption: Optional[str], user_hint: Optional[str] = None
) -> MediaBundle:
    return await build_bundle(await download_reel(url, reel_id), reel_id, caption, user_hint)
