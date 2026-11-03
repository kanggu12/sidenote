#!/usr/bin/env python3
"""A stand-in for the `claude` CLI in stream-json mode, for the warm-session checks in integ.py: one result per
input line, with total_cost_usd as a running total for the process, as the real CLI reports it.

FAKE_MODE: "error2" makes the second turn an error result; "slow" takes 2 s before each result."""
import json
import os
import sys
import time

mode = os.environ.get("FAKE_MODE", "")
total = 0.0
turn = 0
for line in sys.stdin:
    if not line.strip():
        continue
    turn += 1
    total += 0.05                      # every turn costs 0.05, so a turn's own cost is easy to tell from the total
    out = sys.stdout
    out.write(json.dumps({"type": "system", "model": "claude-fake"}) + "\n")
    out.write(json.dumps({"type": "stream_event", "event": {"type": "content_block_delta",
                          "delta": {"type": "text_delta", "text": "TYPE: coding\nANSWER: x\n"}}}) + "\n")
    out.flush()
    if mode == "slow":
        time.sleep(2)                  # the answer still being written when the panel changes a setting
    error = mode == "error2" and turn == 2
    out.write(json.dumps({"type": "result", "is_error": error,
                          "result": "API Error: 500 overloaded" if error else "ok",
                          "usage": {"input_tokens": 10, "output_tokens": 1 if error else 5},
                          "total_cost_usd": round(total, 4)}) + "\n")
    out.flush()
