"""One-shot probe of a real analysis.

Validates an analyzer path (the local model or the cloud agent) without the full capture rig: runs one analysis
on an image file (or a synthetic coding-problem screenshot) and streams the answer
to stdout, then prints token usage + estimated cost. Needs credentials
(a CLI agent uses this PC's login, Claude Code's or Codex's; the Anthropic API agent needs ANTHROPIC_API_KEY).

Run:  python -m server.probe [image.png]
"""
from __future__ import annotations

import asyncio
import base64
import io
import sys

from PIL import Image, ImageDraw, ImageFont

from .analyzer import make_analyzer
from .config import CONFIG


def _font(sz):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", sz)
    except Exception:
        return ImageFont.load_default()


def _synthetic() -> Image.Image:
    img = Image.new("RGB", (1100, 560), (250, 250, 250))
    d = ImageDraw.Draw(img)
    d.text((40, 30), "Problem: Valid Parentheses", fill=(15, 15, 15), font=_font(30))
    body = [
        "Given a string s of '()[]{}', determine whether the input",
        "string is valid: every bracket must close in the correct order.",
        "",
        'Example:  s = "([{}])"  ->  true',
        'Example:  s = "(]"       ->  false',
    ]
    y = 100
    for ln in body:
        d.text((40, y), ln, fill=(20, 20, 20), font=_font(22))
        y += 36
    return img


def _load(path: str | None) -> str:
    img = Image.open(path).convert("RGB") if path else _synthetic()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


async def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else None
    b64 = _load(path)

    try:
        analyzer = make_analyzer(CONFIG)
    except Exception as exc:
        print(f"[probe] could not init analyzer ({CONFIG.analyzer}): {type(exc).__name__}: {exc}")
        return

    print(f"[probe] backend={analyzer.name}  (image: {path or 'synthetic'})\n")

    async def on_delta(text: str) -> None:
        print(text, end="", flush=True)

    try:
        result = await analyzer.analyze(b64, "", on_delta)
    except Exception as exc:
        print(f"\n\n[probe] analysis failed: {type(exc).__name__}: {exc}")
        if CONFIG.agent == "anthropic-api":
            print("[probe] API mode: set ANTHROPIC_API_KEY.")
        else:
            print(f"[probe] CLI mode: the analyzer uses this PC's {CONFIG.agent} login; if it is not signed in, run "
                  "./sidenote login (codex: ./sidenote login codex).")
        return

    print("\n\n---")
    print(f"[probe] backend={result.model}  usage={result.usage}  cost=${result.cost_usd}")


if __name__ == "__main__":
    asyncio.run(main())
