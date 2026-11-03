"""Switches of the running server from the command line (`./sidenote gpu off|on|status`), sent the way the panel
sends them, over the panel's WebSocket on this container's loopback. The server has no endpoint that changes
anything over HTTP on purpose: a page open in the browser could post to one.

  python -m server.control gpu off | on | status

It prints in the terminal's language: SIDENOTE_LANG, else Korean for a Korean locale, else English (i18n.cli_lang).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from . import i18n
from .i18n import t

TIMEOUT = 15.0
SETTLE = 3.0    # after a change, how long the server is listened to for the state that follows it


async def _setting(key: str, value) -> dict:
    """Set one setting the way the panel does (`value` None: only read), and return what the server says about
    the engines afterwards. The state of the engines rides on a status message, and the one worth reading is the
    last one after the change: unloading the model and asking the local server take a moment."""
    import websockets

    port = os.environ.get("SIDENOTE_PORT", "8777")
    state: dict = {}

    async def until(done) -> None:
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("engines"):
                state["engines"] = msg["engines"]
            if msg.get("type") == "settings" and key in (msg.get("values") or {}):
                state["value"] = msg["values"][key]
            if done():
                return

    async with websockets.connect(f"ws://127.0.0.1:{port}/panel", max_size=None) as ws:
        if value is None:
            await asyncio.wait_for(until(lambda: "engines" in state), TIMEOUT)
            return state
        await ws.send(json.dumps({"type": "setting", "key": key, "value": value}))
        await asyncio.wait_for(until(lambda: "value" in state), TIMEOUT)
        try:   # whatever else the server says while it settles; the last of it is the state to print
            await asyncio.wait_for(until(lambda: False), SETTLE)
        except asyncio.TimeoutError:
            pass
        return state


def gpu(what: str) -> int:
    """`gpu off` gives the GPU back (the local model is switched off and unloaded; the agent keeps working),
    `gpu on` takes it again, `gpu status` says who holds it."""
    value = {"off": False, "on": True, "status": None}.get(what)
    if what not in ("off", "on", "status"):
        print(t("Usage: ./sidenote gpu off | on | status"), file=sys.stderr)
        return 2
    try:
        if value is False:   # given back means given back: not loaded again at the agent's limit either (design 89)
            asyncio.run(_setting("local_fallback", False))
        state = asyncio.run(_setting("local_llm", value))
        if value is True:
            asyncio.run(_setting("local_fallback", True))
    except Exception as exc:   # noqa: BLE001 (the server is down, or it did not answer)
        print(t("Cannot reach the server: {why}", why=f"{type(exc).__name__}: {exc}"), file=sys.stderr)
        return 1
    local = (state.get("engines") or {}).get("local") or {}
    loaded = local.get("loaded") or {}
    on = local.get("on")
    gb = loaded.get("vram_gb")
    if loaded.get("model"):
        where = t(", on the GPU: {model}", model=loaded["model"]) + (f" ({gb} GB)" if gb else "")
    elif loaded.get("unknown"):   # the local server did not say; something may well be on the GPU
        where = t(", what is on the GPU is unknown")
    else:
        where = t(", the GPU is empty")
    stand_in = t(" (standing in for the agent)") if not on and local.get("stand_in") else ""
    print(t("Local model: {state}{stand_in}{where}", state=t("on") if on else t("off"), stand_in=stand_in,
            where=where))
    if what == "off":   # what it means while it is off, so the next problem is no surprise
        print(t("While it is off, the agent solves every problem found, and sends the whole screen when it cannot cut "
                "the problem out. The model is not loaded again when the agent reaches a limit either "
                "(./sidenote gpu on brings it back)"))
    return 0


if __name__ == "__main__":
    i18n.set_lang(i18n.cli_lang())   # a terminal's language, not a panel's
    sys.exit(gpu(sys.argv[2] if len(sys.argv) > 2 else "status") if sys.argv[1:2] == ["gpu"]
             else (print(t("Usage: python -m server.control gpu off | on | status"), file=sys.stderr) or 2))
