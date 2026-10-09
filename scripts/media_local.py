"""Local .mp4 in, MediaBundle JSON out.

  .venv/bin/python -m scripts.media_local demo_reels/headphones.mp4 --caption "Sony XM5"
Writes demo_reels/<name>.bundle.json
"""
import argparse
import asyncio
from pathlib import Path

from app.media.pipeline import build_bundle

ap = argparse.ArgumentParser()
ap.add_argument("video", type=Path)
ap.add_argument("--caption")
ap.add_argument("--hint")
a = ap.parse_args()
b = asyncio.run(build_bundle(a.video, a.video.stem, a.caption, a.hint))
out = a.video.with_suffix(".bundle.json")
out.write_text(b.model_dump_json())
print(f"{len(b.frames_b64)} frames, transcript={'yes' if b.transcript else 'no'} -> {out}")
