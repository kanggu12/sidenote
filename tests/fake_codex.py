#!/usr/bin/env python3
"""A stand-in for the `codex` CLI, as server/agents.py calls it: `codex exec --json ... -` and `codex login status`.

FAKE_CODEX_MODE picks how it answers:
  stream   the answer as one agent message growing by item.updated, then item.completed and turn.completed (default)
  whole    the answer only at item.completed, as the docs show it
  two      two agent messages, one after the other
  fail     turn.failed with an authentication error
  die      a line on stderr ("Not logged in") and exit 1, no events
  noauth   `login status` says "Not logged in" (exit 1); otherwise "Logged in using ChatGPT"
What it was given (its arguments, the request on stdin, and whether each --image file was a PNG) is written as JSON
to FAKE_CODEX_LOG when set."""
import json
import os
import sys
import time

mode = os.environ.get("FAKE_CODEX_MODE", "stream")
args = sys.argv[1:]
if args[:2] == ["login", "status"]:
    if mode == "noauth":
        print("Not logged in")
        sys.exit(1)
    print("Logged in using ChatGPT")
    sys.exit(0)
if args[:1] != ["exec"]:
    print(f"fake codex: unexpected {args}", file=sys.stderr)
    sys.exit(2)
request = sys.stdin.read()
images = [args[i + 1] for i, a in enumerate(args) if a == "--image"]
if os.environ.get("FAKE_CODEX_LOG"):
    with open(os.environ["FAKE_CODEX_LOG"], "w", encoding="utf-8") as f:
        json.dump({"args": args, "request": request,
                   "images": [open(p, "rb").read(8) == b"\x89PNG\r\n\x1a\n" for p in images],
                   "cwd": os.getcwd()}, f)


def emit(ev):
    print(json.dumps(ev), flush=True)
    time.sleep(0.01)


if mode == "die":
    print("Error: Not logged in", file=sys.stderr)
    sys.exit(1)
emit({"type": "thread.started", "thread_id": "fake-thread"})
emit({"type": "turn.started"})
if mode == "fail":
    emit({"type": "error", "message": "unexpected status 401 Unauthorized"})
    emit({"type": "turn.failed", "error": {"message": "unexpected status 401 Unauthorized: token expired"}})
    sys.exit(1)
answer = "TYPE: algorithm\nANSWER: 해시맵으로 한 번 훑기\n\n본문입니다."
emit({"type": "item.started", "item": {"id": "item_0", "type": "reasoning", "text": "thinking"}})
emit({"type": "item.completed", "item": {"id": "item_0", "type": "reasoning", "text": "thinking it through"}})
if mode == "stream":
    for end in (12, 30, len(answer)):
        emit({"type": "item.updated", "item": {"id": "item_1", "type": "agent_message", "text": answer[:end]}})
emit({"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": answer}})
if mode == "two":
    emit({"type": "item.completed", "item": {"id": "item_2", "type": "agent_message", "text": "덧붙임."}})
emit({"type": "turn.completed", "usage": {"input_tokens": 9000, "cached_input_tokens": 6000, "output_tokens": 120,
                                          "reasoning_output_tokens": 40}})
