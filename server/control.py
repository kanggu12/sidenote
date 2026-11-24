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


def _read_setting(key: str):
    """One setting's value, as the API gives it."""
    import urllib.request
    port = os.environ.get("SIDENOTE_PORT", "8777")
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/settings/{key}", timeout=TIMEOUT) as r:
        return json.load(r).get("value")


def _lent_file():
    """Where `gpu off` keeps what it changed, for `gpu on` to put back: beside the logs, which outlive a restart."""
    from . import telemetry
    return os.path.join(telemetry.LOG_DIR, ".gpu_lent.json") if telemetry.LOG_DIR else None


def gpu(what: str) -> int:
    """`gpu off` gives the GPU back (the local model is switched off and unloaded; the agent keeps working),
    `gpu on` takes it again, `gpu status` says who holds it."""
    value = {"off": False, "on": True, "status": None}.get(what)
    if what not in ("off", "on", "status"):
        print(t("Usage: ./sidenote gpu off | on | status"), file=sys.stderr)
        return 2
    lent = _lent_file()
    try:
        if value is False:   # given back means given back: not loaded again at the agent's limit either (design 89)
            # what the stand-in was before, for gpu on to put back: it switched it on whatever it had been, so one switched
            # off by hand came back on with the GPU
            if lent:
                with open(lent, "w", encoding="utf-8") as f:
                    json.dump({"local_fallback": _read_setting("local_fallback")}, f)
            asyncio.run(_setting("local_fallback", False))
        state = asyncio.run(_setting("local_llm", value))
        if value is True and lent and os.path.exists(lent):
            with open(lent, encoding="utf-8") as f:
                before = json.load(f).get("local_fallback")
            if isinstance(before, bool):
                asyncio.run(_setting("local_fallback", before))
            os.remove(lent)
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
    if what == "off":   # who answers meanwhile, and how it comes back; what it sends is the guide's to say (Lending the GPU)
        print(t("The agent solves meanwhile · ./sidenote gpu on takes the GPU again"))
    return 0


if __name__ == "__main__":
    i18n.set_lang(i18n.cli_lang())   # a terminal's language, not a panel's
    sys.exit(gpu(sys.argv[2] if len(sys.argv) > 2 else "status") if sys.argv[1:2] == ["gpu"]
             else (print(t("Usage: python -m server.control gpu off | on | status"), file=sys.stderr) or 2))
