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
    video = await download_reel(url, reel_id)
    if not caption:
        caption = _caption_from_info(video)
    try:
        return await build_bundle(video, reel_id, caption, user_hint)
    finally:
        video.unlink(missing_ok=True)
        video.with_suffix(".info.json").unlink(missing_ok=True)


def _caption_from_info(video: Path) -> Optional[str]:
    """yt-dlp writes <video>.info.json next to the video; its description is the post caption."""
    import json

    info = video.with_suffix(".info.json")
    try:
        text = json.loads(info.read_text()).get("description") or ""
        info.unlink(missing_ok=True)
        return text.strip()[:500] or None
    except Exception:
        return None
