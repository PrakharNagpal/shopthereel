"""Send a text DM to a tester IGSID.

  .venv/bin/python -m scripts.send_test_dm --igsid <IGSID> --text "hello"
"""
import argparse
import asyncio

from app.meta.send import send_text

ap = argparse.ArgumentParser()
ap.add_argument("--igsid", required=True)
ap.add_argument("--text", default="hello")
a = ap.parse_args()
asyncio.run(send_text(a.igsid, a.text))
print("sent")
