"""WSL-side test client: exercises the full server pipeline without Windows.

Generates a synthetic "coding problem" screenshot with Pillow, sends it to
/ingest, then sends a second (different) screen. Also sends a short burst of
silent audio so the audio path is exercised. Use this to validate the server +
panel end-to-end before wiring up the real Windows capture client.

Run (server must be up):  python -m server.mock_capture
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os

from PIL import Image, ImageDraw, ImageFont

try:
    import websockets
except ImportError:  # pragma: no cover
    raise SystemExit("pip install websockets")

URL = os.environ.get("SIDENOTE_INGEST_URL", "ws://127.0.0.1:8777/ingest")


def _font(size: int) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _make_screen(title: str, lines: list[str], bg=(250, 250, 250), fg=(20, 20, 24)) -> bytes:
    img = Image.new("RGB", (1200, 760), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1200, 60], fill=tuple(max(0, c - 20) for c in bg))
    d.text((24, 16), title, fill=fg, font=_font(28))
    body = _font(22)
    y = 96
    for ln in lines:
        d.text((40, y), ln, fill=fg, font=body)
        y += 30
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _send_frame(ws, png: bytes) -> None:
    await ws.send(json.dumps({"type": "frame", "data": base64.b64encode(png).decode()}))


async def _send_silence(ws, seconds: float = 1.0, sr: int = 16000) -> None:
    pcm = bytes(int(sr * 2 * seconds))  # int16 mono silence
    await ws.send(json.dumps({"type": "audio", "sr": sr, "data": base64.b64encode(pcm).decode()}))


async def main() -> None:
    async with websockets.connect(URL, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "info": "mock_capture"}))

        screen1 = _make_screen(
            "Online Assessment  -  Problem 1",
            [
                "Two Sum",
                "",
                "Given an array of integers nums and an integer target,",
                "return the indices of the two numbers that add up to target.",
                "You may assume exactly one valid answer exists, and you",
                "may not use the same element twice.",
                "",
                "Example: nums = [2, 7, 11, 15], target = 9  ->  [0, 1]",
                "",
                "Constraints: 2 <= nums.length <= 1e4,  -1e9 <= nums[i] <= 1e9",
            ],
        )
        print("-> sending screen 1 (coding problem)")
        await _send_frame(ws, screen1)
        await _send_silence(ws, 1.0)

        # Give the worker time to pick it up and (mock-)analyze it.
        await asyncio.sleep(4)

        screen2 = _make_screen(
            "editor.py  -  no problem on screen",
            [f"def handler_{i}(request):  return render(ctx_{i})" for i in range(16)],
            bg=(24, 26, 32),
            fg=(220, 224, 230),
        )
        print("-> sending screen 2 (different screen)")
        await _send_frame(ws, screen2)
        await asyncio.sleep(4)
        print("done; leaving socket open briefly")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
