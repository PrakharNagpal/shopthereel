"""Run the agent brain on a MediaBundle JSON (from scripts.media_local) or a folder of JPEGs.

  .venv/bin/python -m scripts.recognize_local demo_reels/headphones.bundle.json
  .venv/bin/python -m scripts.recognize_local ./frames_dir --caption "Sony XM5 review"
"""
import argparse
import asyncio
import base64
import hashlib
from pathlib import Path

from app.agent.search import recognize_and_search
from app.models import MediaBundle


def load(path: Path, caption: str | None, hint: str | None) -> MediaBundle:
    if path.is_dir():
        files = sorted(path.glob("*.jp*g"))[:8]
        frames = [base64.b64encode(f.read_bytes()).decode() for f in files]
        rid = hashlib.sha1("".join(f.name for f in files).encode()).hexdigest()[:12]
        return MediaBundle(reel_id=rid, frames_b64=frames, caption=caption, user_hint=hint)
    b = MediaBundle.model_validate_json(path.read_text())
    if caption:
        b.caption = caption
    if hint:
        b.user_hint = hint
    return b


ap = argparse.ArgumentParser()
ap.add_argument("path", type=Path)
ap.add_argument("--caption")
ap.add_argument("--hint")
a = ap.parse_args()
r = asyncio.run(recognize_and_search(load(a.path, a.caption, a.hint)))
print(r.model_dump_json(indent=2))
