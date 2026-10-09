"""Download only validated Instagram shares; signed media URLs never reach the model."""
import hashlib
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse
import httpx
from app.media.pipeline import build_bundle, bundle_from_url

MAX_BYTES = 20 * 1024 * 1024


def trusted_media(raw: str) -> bool:
    try:
        u=urlparse(raw)
        return len(raw)<=8192 and u.scheme=='https' and u.hostname=='lookaside.fbsbx.com' and u.port in (None,443) and not u.username and not u.password and u.path.startswith('/ig_messaging_cdn/')
    except ValueError:
        return False


def permalink(message: dict) -> str | None:
    match=re.search(r'https?://(?:www\.)?instagram\.com/(?:reel|reels|p|tv)/[A-Za-z0-9_-]+/?',str(message))
    return match.group(0).replace('http://','https://') if match else None


async def from_message(message: dict):
    url=permalink(message)
    if url:
        return await bundle_from_url(url,hashlib.sha256(url.encode()).hexdigest(),None)
    for a in message.get('attachments',[]):
        raw=a.get('payload',{}).get('url','')
        if a.get('type') not in ('ig_reel','reel','share','video','image') or not trusted_media(raw):
            continue
        caption=str(a.get('payload',{}).get('caption') or a.get('payload',{}).get('title') or '')[:1500]
        caption=re.sub(r'https?://\S+','[link]',caption)
        async with httpx.AsyncClient(timeout=20,follow_redirects=False) as c:
            for _ in range(4):
                async with c.stream('GET',raw) as response:
                    if response.status_code in (301,302,303,307,308):
                        raw=urljoin(raw,response.headers.get('location',''))
                        if not trusted_media(raw):raise ValueError('Untrusted redirect')
                        continue
                    response.raise_for_status()
                    mime=response.headers.get('content-type','').split(';')[0]
                    if mime not in ('video/mp4','video/quicktime','video/webm','image/jpeg','image/png','image/webp'):raise ValueError('Unsupported media')
                    data=bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data)>MAX_BYTES:raise ValueError('Media too large')
                    if not data:raise ValueError('Empty media')
                    rid=hashlib.sha256(data).hexdigest()
                    with tempfile.TemporaryDirectory() as d:
                        path=Path(d)/'shared-media';path.write_bytes(data)
                        return await build_bundle(path,rid,caption)
        raise ValueError('Too many redirects')
    raise ValueError('No supported Instagram media')
