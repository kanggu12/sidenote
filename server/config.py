"""Runtime configuration for the sidenote server.

All knobs are environment-driven so the same code runs in mock mode (no API
key, no heavy deps) and in the real setup with a cloud agent and audio. Prefix: SIDENOTE_*.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass, field

from .i18n import t

# A setting that is empty or not a number keeps its default (with a warning in the server log):
# one stray value in .env must not stop the server from starting.


def _ignored(name: str, raw: str, default) -> None:
    print(f"sidenote: ignoring {name}={raw!r}; using {default!r}", file=sys.stderr)


def env_str(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = None
    if value is None or not math.isfinite(value):   # inf and nan too: a stray value never stops the start
        _ignored(name, raw, default)
        return default
    return value


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(float(raw)) if raw else default   # "2.0" is 2
    except (ValueError, OverflowError):              # "inf" overflowed, "nan" is not a number either
        _ignored(name, raw, default)
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    if raw:
        _ignored(name, raw, default)
    return default


# What Whisper is given as the text before the audio, so it spells technical terms as they are written, one list for
# each speech language and chosen by the language each utterance is decoded in (server/transcriber.py). The Korean
# list keeps the words Korean speech says in Hangul and writes the rest as they are written in Korean technical text,
# in Latin letters. Each list ends on the words Whisper most often gets wrong, today's AI and infrastructure names (vLLM,
# SGLang, LangGraph, Dify, n8n: in spoken interview questions `small` wrote them as "s질랭", "랭그레프", "DP나 NADN"), and starts on
# words a model mostly writes right unaided. Whisper keeps the last 223 tokens of a prompt, and the person's own words go
# in front of these (Extra terms), so a list cut to fit loses its first words (transcriber.py, prompt). They take 209 and
# 191 of the 223. Measured on 88 spoken interview questions full of terms, through a meeting app's codec (DECISIONS.md,
# note 129): `small` wrote 79% of the terms right with the lists before these and 86% with these, its character errors
# 5.7% and 4.5%; the lists before these were measured in note 106.
WHISPER_HINTS = {
    "ko": (
        "쿠버네티스, 파드, 레디스, 카프카, 엔진엑스, 임베딩, 파인튜닝, 양자화, 레이턴시, 온프레미스, 데브옵스, API, gRPC, OAuth, JWT, WebSocket, S3, IAM, "
        "kubectl, Helm, Terraform, Prometheus, Grafana, Slurm, InfiniBand, NCCL, CUDA, GPU, NFS, SMB, PostgreSQL, "
        "Elasticsearch, Airflow, Kubeflow, MLOps, CI/CD, PyTorch, Triton, TensorRT-LLM, LoRA, KV cache, RAG, LLM, "
        "VLM, Ollama, vLLM, SGLang, LangChain, LangGraph, Dify, n8n."),
    "en": (
        "Kubernetes, kubectl, etcd, Helm, Docker, Slurm, InfiniBand, RDMA, NCCL, CUDA, NVLink, NVIDIA, GPU, NFS, SMB, "
        "LDAP, Prometheus, Grafana, Terraform, Ansible, PyTorch, nginx, Redis, Kafka, PostgreSQL, MySQL, "
        "Elasticsearch, Airflow, Kubeflow, MLOps, gRPC, OAuth, JWT, WebSocket, DNS, API, YAML, GitHub, S3, IAM, "
        "Triton, TensorRT-LLM, LoRA, KV cache, prefill, RAG, LLM, VLM, Ollama, vLLM, SGLang, LangChain, LangGraph, "
        "Dify, n8n."),
}


@dataclass
class Config:
    # Network
    # Loopback only when run directly: the panel has no auth and shows screen thumbnails. In the
    # container compose sets 0.0.0.0 and publishes the port on the host's 127.0.0.1 only.
    host: str = env_str("SIDENOTE_HOST", "127.0.0.1")
    port: int = env_int("SIDENOTE_PORT", 8777)

    # Who solves by default (each can be switched in the panel afterwards, server/settings.py):
    #   "local" -> the vision LLM on this PC (compose service "llm", Ollama on the GPU) with web search, and the
    #              cloud agent below for the hard problems while it is signed in (default)
    #   "agent" -> the cloud agent alone ("cli" and "api", the earlier names of this mode, still mean it)
    #   "mock"  -> canned answers for both engines, no network (tests)
    analyzer: str = env_str("SIDENOTE_ANALYZER", "local")
    # The cloud agent (server/agents.py): claude-code (this PC's Claude Code login), codex (this PC's Codex login),
    # anthropic-api (ANTHROPIC_API_KEY) or off. SIDENOTE_CLAUDE, its earlier name, is read when this is not set.
    agent: str = env_str("SIDENOTE_AGENT", "") or env_str("SIDENOTE_CLAUDE", "")

    # Local LLM (analyzer="local"). Any OpenAI-compatible server works (Ollama, llama.cpp
    # server, vLLM, LM Studio); the model must take images. The default URL is the compose
    # service, reached over a network with no internet.
    local_url: str = env_str("SIDENOTE_LOCAL_URL", "http://llm:11434/v1")
    # The model to solve with, or "auto": the largest measured model the local server has that fits the GPU
    # (server/models.py). `./sidenote llm pull` fetches the one that fits, as a tuned copy with a larger batch.
    local_model: str = env_str("SIDENOTE_LOCAL_MODEL", "auto")
    # "ollama", "openai" (any other OpenAI-compatible server: llama.cpp, vLLM, LM Studio; it can only answer, so the
    # panel cannot load or unload its model) or "auto" (asks the server once)
    local_backend: str = env_str("SIDENOTE_LOCAL_BACKEND", "auto")
    # The GPU memory to size "auto" by, in GB, when it cannot be read (0: read it from the GPU)
    local_vram_gb: float = env_float("SIDENOTE_LOCAL_VRAM_GB", 0)
    # The panel may download a model through the local server (Ollama's /api/pull) when it has none: where that server
    # reaches the internet, as on one PC (the desktop app sets it). Off in compose, whose llm container has no route out
    # (./sidenote llm pull fetches in a container of its own).
    local_pull: bool = env_bool("SIDENOTE_LOCAL_PULL", False)
    # Started by the desktop app (desktop/app.py), not by ./sidenote: the panel's directions then name what the app
    # has (a terminal for the agent's own login, Ollama to install) instead of the launcher's commands.
    desktop: bool = env_bool("SIDENOTE_DESKTOP", False)
    # The first request after a start loads the model into GPU memory (tens of seconds).
    # The whole of one agent turn, not the quiet between its lines: a turn that keeps writing held the
    # worker and the session for 923 s and 130,000 output tokens once.
    cli_turn_budget: float = env_float("SIDENOTE_CLI_TURN_BUDGET", 300)
    local_timeout: float = env_float("SIDENOTE_LOCAL_TIMEOUT", 180)
    # The first pass only says what kind of problem is on the screen, which takes a second or two. When
    # the GPU has no room left it can instead bring nothing at all, and waiting the full timeout for that
    # costs three minutes an answer: measured on this machine with its owner working, screen after screen.
    # Giving up early counts as a busy GPU, so the smaller model takes over.
    local_fast_timeout: float = env_float("SIDENOTE_LOCAL_FAST_TIMEOUT", 45)
    # When the agent can take the screen, the first pass gets this long for its first token once the model is in
    # place. It normally comes within a second or two (p90 2.0 s over a week of screens);
    # nothing by then means another program has the GPU, and the screen goes to the agent instead of waiting out
    # local_fast_timeout, as each busy screen did that week (13 times, 45 s each). Without the agent the first pass
    # waits as before, there being nothing else to answer with.
    local_first_token_sec: float = env_float("SIDENOTE_LOCAL_FIRST_TOKEN_SEC", 6)
    # The same for a model that has not answered since it was loaded: its prompt cache is empty (design note 94)
    local_cold_first_token_sec: float = env_float("SIDENOTE_LOCAL_COLD_FIRST_TOKEN_SEC", 45)
    # When the agent can take the problem, the thinking pass gets this long for its first token of any kind (thinking
    # counts), and local_stuck_sec for each one after, before the problem goes to the agent (design note 117). On a GPU
    # a video call held, its prompt was read at 60 to 300 tokens a second and the next request waited minutes behind one
    # the runtime had been told to drop; without the agent the pass waits as before.
    local_think_first_token_sec: float = env_float("SIDENOTE_LOCAL_THINK_FIRST_TOKEN_SEC", 30)
    # A request that has brought no token for this long, while the model's server streamed nothing to any other
    # request of this server either, is checked with a one-token request given local_probe_sec to answer. A runtime
    # stuck inside an image answers nothing, and the model is taken off the GPU, which makes Ollama
    # start it again and hand it the waiting request; such a wait ran out local_timeout (180 s) before and ended in an
    # error. The longest first token measured from a runtime that was not stuck is 45 s, the first request a newly
    # created container serves; a runner started again in a warm one gave its first image pass's first token in 1.9 to
    # 4.7 s (scratch/local-llm-bench/cold_runner.py). Longer than the first pass's own limit, which ends it first.
    local_stuck_sec: float = env_float("SIDENOTE_LOCAL_STUCK_SEC", 60)
    # The one-token request takes a tenth of a second on a warm runner, also beside a thinking pass, and waits for an
    # image being encoded beside it: 1.5 to 4.2 s just after the runner starts, 14 to 16 s in a new container.
    local_probe_sec: float = env_float("SIDENOTE_LOCAL_PROBE_SEC", 20)
    # The rule: when the local model would take this many times as long as the agent to
    # start its answer, agent answers, whatever the kind of problem; the local model answers only when the agent
    # cannot (switched off, declined, failed, offline, over its spending limit). Compared on the time to the
    # first word of the answer, which is what is waited for, kept per way of answering (pipeline.Speed).
    local_slow_ratio: float = env_float("SIDENOTE_LOCAL_SLOW_RATIO", 1.5)
    # A problem the capture program scrolled together within this many seconds of the last answer is that answer's
    # problem read on: the answer is filled out from the whole of it under the same card (app.run_followup, the
    # continuation) instead of solved again from the start as a new card. Only a problem cut off by scrolling or the
    # like is carried on this way, and that case has to be detected reliably. 0 turns it off.
    continue_window_sec: float = env_float("SIDENOTE_CONTINUE_WINDOW_SEC", 600)
    # When the local model thinks before answering: auto (answer at once, and think only when the
    # problem needs reasoning: calculation, code tracing, algorithms; see server/analyzer.py),
    # always, or never (fastest). SIDENOTE_FAST=1 means never.
    local_think: str = env_str("SIDENOTE_LOCAL_THINK", "auto")
    # Web search for the local model (tool calls): a SearXNG instance, the compose service
    # "searxng" by default. Empty turns it off. Page reads go to public addresses only
    # (server/search.py).
    search_url: str = os.environ.get("SIDENOTE_SEARCH_URL", "http://searxng:8080/search").strip()
    search_timeout: float = env_float("SIDENOTE_SEARCH_TIMEOUT", 8)
    search_rounds: int = env_int("SIDENOTE_SEARCH_ROUNDS", 3)   # tool calls per answer, at most
    # Minutes after the last local call before the model is unloaded from the GPU (-1: never;
    # changeable in the panel).
    local_idle_min: int = env_int("SIDENOTE_LOCAL_IDLE_MIN", 10)
    # A smaller model for while another program keeps the GPU busy (empty: never switch; changeable in
    # the panel). WSL2 hides other programs' GPU memory, so a busy GPU is told by speed: an answer that
    # generates at under local_busy_ratio of that model's usual rate (the median of its recent ones)
    # switches to this model for local_busy_hold_sec seconds, then the chosen model is tried again
    # (docs/DESIGN-local-first.md, section 13).
    local_busy_model: str = env_str("SIDENOTE_LOCAL_BUSY_MODEL", "auto")
    local_busy_ratio: float = env_float("SIDENOTE_LOCAL_BUSY_RATIO", 0.5)
    # How long the smaller model keeps answering before the chosen one is tried again. In seconds: ten
    # minutes meant a busy moment cost the better model for the rest of a sitting, and even one minute was too
    # long. A retry that finds the GPU still busy costs one slower answer and holds again.
    local_busy_hold_sec: float = env_float("SIDENOTE_LOCAL_BUSY_HOLD_SEC",
                                           env_float("SIDENOTE_LOCAL_BUSY_HOLD_MIN", 0.5) * 60)
    # A retry that finds the GPU still busy doubles the hold, up to this many seconds (GpuPace._hold): through a long
    # video call the chosen model is tried again ever less often instead of every half minute.
    local_busy_hold_max_sec: float = env_float("SIDENOTE_LOCAL_BUSY_HOLD_MAX_SEC", 600)

    # The cloud agent's CLI, model and effort (SIDENOTE_CLAUDE_BIN, _MODEL and _EFFORT, the earlier names, are read when
    # these are not set). An empty binary is the agent's own command (agent, codex); an empty model or effort is the
    # CLI's own default, which is kept strong for quality. Effort: low|medium|high|xhigh|max for the agent,
    # low|medium|high for Codex.
    agent_bin: str = env_str("SIDENOTE_AGENT_BIN", "") or env_str("SIDENOTE_CLAUDE_BIN", "")
    agent_model: str = env_str("SIDENOTE_AGENT_MODEL", "") or env_str("SIDENOTE_CLAUDE_MODEL", "")
    agent_effort: str = env_str("SIDENOTE_AGENT_EFFORT", "") or env_str("SIDENOTE_CLAUDE_EFFORT", "")
    cli_timeout: float = env_float("SIDENOTE_CLI_TIMEOUT", 120)
    # One-switch fast profile: the agent on the newest Sonnet at effort low (Codex at effort low).
    # Measured ~46% lower warm-turn latency (ttft 0.64s vs 1.44s, total 2.98s vs
    # 5.53s) with equal quality on a standard coding problem. An explicit
    # SIDENOTE_AGENT_MODEL / SIDENOTE_AGENT_EFFORT still wins (see __post_init__).
    fast: bool = env_bool("SIDENOTE_FAST", False)
    # Persistent warm session (Claude Code): keep one `claude` process alive so turns skip process
    # spawn + cold cache (much faster first token). Restart every N turns to bound
    # context growth (each turn is instructed to analyze only the latest screenshot).
    cli_session: bool = env_bool("SIDENOTE_CLI_SESSION", True)
    # Measured on one session: input tokens climb 7.6k, 12.8k, 18.1k, 23.3k, 28.6k, 33.8k
    # as each turn carries the ones before it, and start over at 7.6k with the next process. The cost
    # per turn stayed flat ($0.046) because the carried part is cached, so what this really bounds is
    # how much of an earlier problem is still in front of the model when a new one arrives.
    cli_session_turns: int = env_int("SIDENOTE_CLI_SESSION_TURNS", 8)

    # Anthropic API (SIDENOTE_AGENT=anthropic-api): model + effort. A family name (opus, sonnet, haiku) is the newest
    # model of that family the API lists when the server starts (agents.AnthropicApiAgent), so a new release is used
    # without a change; a full name (claude-opus-5-5) pins that version. For lower latency set SIDENOTE_MODEL=sonnet
    # (or haiku) and SIDENOTE_EFFORT=low.
    model: str = env_str("SIDENOTE_MODEL", "opus")
    effort: str = env_str("SIDENOTE_EFFORT", "medium")  # low|medium|high|xhigh|max
    max_tokens: int = env_int("SIDENOTE_MAX_TOKENS", 8000)

    # Gate: avoid re-analyzing the same screen and bursting the API.
    # High-pass signature distance (MAD) below this = "same screen", skip.
    # Biased toward sensitivity: missing a new problem is worse than an extra call.
    # ~0.44 = theme toggle (skip), ~0.87 = a different problem on the same template (fire).
    change_threshold: float = env_float("SIDENOTE_CHANGE_THRESHOLD", 0.5)
    # Once an answer names where its problem is on screen (its REGION line), a frame is
    # new only if the signature changed this much *inside that region*: a one-word change
    # there clears it, typing, a video or another window elsewhere does not count at all.
    region_threshold: float = env_float("SIDENOTE_REGION_THRESHOLD", 0.25)
    # A frame that changed this much outside the cells that keep moving is the screen being driven, and the settle
    # waits for it to rest again: below the capture program's own 0.1 (it sends nothing that changed less), so every
    # frame it sends for a change counts. It was change_threshold (0.5), the mark of a new problem, and a line typed
    # into an editor (0.12 to 0.23) no longer held the settle: an analysis started every three seconds during typing.
    driven_threshold: float = env_float("SIDENOTE_DRIVEN_THRESHOLD", 0.08)
    # An analysis cancelled by a screen change this many times in a row is let finish:
    # a screen that keeps changing (another window in use) must not starve every answer.
    supersede_limit: int = env_int("SIDENOTE_SUPERSEDE_LIMIT", 2)
    # An analysis that has run this long is in its long pass and a screen change no longer stops it: of the 16 analyses stopped
    # after 30 s or more, 9 were followed by screens with nothing to solve, their answers thrown away for nothing.
    # Stopped ones run 1.35 s at the median, so this leaves the usual case alone.
    supersede_keep_sec: float = env_float("SIDENOTE_SUPERSEDE_KEEP_SEC", 20.0)
    # The screen must have come to rest for this long before it is asked about by itself. A screen
    # still being driven, by typing, scrolling or a window opening, is not the screen an answer is
    # wanted about, and asking about it anyway was where most of the work went: of the 1869 s of
    # model time in one day, 855 s went to 70 analyses the next frame cancelled, and 37% of the
    # day's frames arrived within a second of the one before (scratch/analyze/digest.py). The capture
    # client has its own settle (two still polls, ~0.7 s at 3 fps) and this one is about the screens
    # that pass it: a frame that waits here is replaced by the next, so the screen that was stopped
    # on is the one that gets asked, not the first frame of the burst.
    settle_sec: float = env_float("SIDENOTE_SETTLE_SEC", 1.2)
    # One rest is not like another. A frame that arrives after a long calm is somebody who has just
    # arrived at something; frames arriving one after another are somebody driving the screen, and
    # the rest between two of those means nothing. Measured over 14 minutes of real use:
    # frames came 2.0 s apart at the median and 1.0 s apart at the first quarter,
    # and of 50 analyses the next frame cancelled, 37 were cancelled within 2 s of starting and the
    # median was 1.0 s. With one settle for both cases the tool spent the whole stretch starting on
    # screens that were about to change: 122 starts, 50 of them thrown away. So a frame whose
    # predecessor came less than busy_gap ago has to rest settle_busy before it is asked about, and
    # the case actually waited for, a problem appearing on a calm screen, still goes
    # at settle_sec.
    settle_busy: float = env_float("SIDENOTE_SETTLE_BUSY", 3.0)
    busy_gap: float = env_float("SIDENOTE_BUSY_GAP", 4.0)
    # A screen that never comes to rest (a video in a corner, a progress bar) would starve the
    # watching, so a frame that has waited this long for quiet is analyzed as it stands. 0 turns the
    # settle off altogether.
    settle_max_sec: float = env_float("SIDENOTE_SETTLE_MAX_SEC", 8)
    # Minimum seconds between two analysis calls.
    min_analyze_interval: float = env_float("SIDENOTE_MIN_INTERVAL", 1.5)
    # Watching quietly after a run of empty answers. The screen is mostly someone working, and the
    # tool cannot know that without looking, but it can notice that looking keeps finding nothing.
    # Measured with the local model on: 325 analyses in 59 minutes, 291 of the
    # 293 answers "nothing to solve", 954,784 input tokens, 522 s of the GPU, two cards. After this
    # many empty automatic answers in a row a *small* screen change waits quiet_sec instead of
    # min_analyze_interval. A wholesale change goes at once whatever the run (quiet_jump_ratio), and
    # anything found, a question, Reanalyze or a drawn region ends the run. 0 turns this off.
    quiet_after: int = env_int("SIDENOTE_QUIET_AFTER", 8)
    # 15 s at first, halved after a session of watching it: the wait is paid by whoever is waiting
    # for the next problem to be noticed, and with the run of empty answers engaged it was the whole
    # of why the tool felt slow to use (the worst case was this wait, then the 17-36 s the local
    # model takes). What the 15 s was there to stop, a desktop being worked on and asked about three
    # times a second for nothing, is now mostly stopped a step earlier by settle_busy, which cut
    # the starts on a real 14-minute stretch by a third (203 -> 138) without touching the case this
    # wait hurts: a problem appearing on a screen that had gone quiet.
    quiet_sec: float = env_float("SIDENOTE_QUIET_SEC", 8)
    # What counts as a wholesale change while watching quietly, as a multiple of change_threshold.
    # 1.6 puts it at 0.8 with the default threshold, just under the ~0.87 that the next problem on the
    # same template measured (change_threshold above has the landmarks), so that case is never held
    # back; a theme toggle at ~0.44 is well below, and so is typing or scrolling the same page.
    quiet_jump_ratio: float = env_float("SIDENOTE_QUIET_JUMP_RATIO", 1.6)
    # Change-detection gate: signature (pixel, cheap) | ocr | hybrid | auto. The pipeline
    # is capture -> the agent, so the default runs no OCR; ocr/hybrid/auto are opt-in
    # (server/requirements-ocr.txt). Note the bundled RapidOCR model reads Chinese and
    # English only: on Korean screens its text is noise.
    gate: str = env_str("SIDENOTE_GATE", "signature")
    # Fraction of OCR text that must differ (0-1) to count as a new screen.
    text_threshold: float = env_float("SIDENOTE_TEXT_THRESHOLD", 0.15)
    # Problem-region crop: trim the image sent to the model, dropping wallpaper/
    # taskbar/margins -> fewer vision tokens and a more focused view. Needs OCR (opt-in,
    # off by default); a silent no-op when OCR is off.
    #   off        -> never crop
    #   auto       -> margin trim: crop to the union of ALL text boxes (+padding),
    #                 keeping every word; fires only for a worthwhile sub-rectangle
    #   aggressive -> isolate the dominant text block (cluster the boxes, keep the
    #                 largest block) when one clearly dominates; else fall back to auto
    crop: str = env_str("SIDENOTE_CROP", "off")
    # Growing the model's problem box out to the piece of writing it lands in, before the crop is
    # cut (pipeline.grow_to_block). The model draws its box by eye and often lands inside a
    # paragraph, so the crop sent out holds part of the problem and the answer is to a question
    # nobody asked. Measured on the 102 boxes four runs of the known-answer set recorded: the box
    # with its margin alone holds the whole problem on 95 of them, the ink walk on 99, and none of
    # it costs the picture a pixel of detail.
    #   ink      -> walk the ink out to the gutters around it (free, needs nothing installed)
    #   detector -> and ask the text detector (server/requirements-ocr.txt) wherever the ink walk
    #               ran out of room instead of meeting a gutter. Measured and not taken as the
    #               default: it is reached on 18 of the 102 recorded boxes and holds the whole
    #               problem on none more than the ink walk does, for about 1.2 s of CPU each time
    #               and some 70 MB in the image.
    #               Only the boxes are used, never the text, so a Korean screen is fine.
    #   off      -> cut the box as the model drew it
    crop_snap: str = env_str("SIDENOTE_CROP_SNAP", "ink")

    # A brake on the agent answering "nothing to solve" over and over. Measured with a game on the
    # screen and people talking: 93 agent turns in 21 minutes, every one of them
    # empty, 1.53M input tokens, $3.61. The tool cannot know a game from an exam paper, but it can
    # notice that it keeps asking about nothing. After this many empty answers in a row it stops
    # sending by itself for agent_cool_sec; Reanalyze, a question and a drawn region always go.
    agent_empty_streak: int = env_int("SIDENOTE_AGENT_EMPTY_STREAK", env_int("SIDENOTE_CLAUDE_EMPTY_STREAK", 6))
    agent_cool_sec: float = env_float("SIDENOTE_AGENT_COOL_SEC", env_float("SIDENOTE_CLAUDE_COOL_SEC", 300))
    # What the last hour of the agent may cost before the tool stops sending by itself. 0 turns it off. Only an agent
    # that reports a price counts toward it (the agent, the Anthropic API); a Codex login reports none.
    agent_hourly_usd: float = env_float("SIDENOTE_AGENT_HOURLY_USD", env_float("SIDENOTE_CLAUDE_HOURLY_USD", 2.0))

    # Audio
    audio_enabled: bool = env_bool("SIDENOTE_AUDIO", True)
    # "auto" uses faster-whisper if importable, else silently disables transcription.
    transcriber: str = env_str("SIDENOTE_TRANSCRIBER", "auto")  # auto|null|faster-whisper
    # Speech language: auto (detect, but only between Korean and English) | ko | en.
    # Switchable at runtime from the panel.
    speech_lang: str = env_str("SIDENOTE_SPEECH_LANG", "auto")
    # The model that writes down each sentence heard. large-v3-turbo: on 88 interview questions full of technical terms,
    # through a meeting app's codec, 3.1% character errors and 89% of the terms right against 5.7% and 79% for small,
    # for 5.5 s of the clock a sentence of 7 s against 1.9 s, four threads on the test PC (DECISIONS.md, note 129).
    # The live line stays on small (whisper_live_model). SIDENOTE_WHISPER_MODEL=small is the light choice
    whisper_model: str = env_str("SIDENOTE_WHISPER_MODEL", "large-v3-turbo")
    # The live line is read every two seconds while somebody speaks, a sentence once when it is over: a heavier model for
    # the sentences reads the live line with this one (server/transcriber.py, live_model; DECISIONS note 129)
    whisper_live_model: str = env_str("SIDENOTE_WHISPER_LIVE_MODEL", "small")
    whisper_compute: str = env_str("SIDENOTE_WHISPER_COMPUTE", "int8")
    # Threads faster-whisper decodes with. Left to itself it takes every core the container has
    # (measured: eight, held for 95 minutes), which lags the PC it is meant to help.
    whisper_threads: int = env_int("SIDENOTE_WHISPER_THREADS", 4)
    # Words passed to Whisper as preceding text so it spells technical terms right, one list for each speech
    # language (WHISPER_HINTS above). SIDENOTE_WHISPER_HINT gives one text for both instead; empty turns it off.
    whisper_hint: dict | str = field(default_factory=lambda: os.environ.get("SIDENOTE_WHISPER_HINT", WHISPER_HINTS))
    # What the log keeps about speech: short (how long and how many characters) | full (the words
    # too, for working out why something was taken as a problem) | off. Everything the tool hears
    # passes through here, including other people and whatever is playing, so the words are not
    # written to a file that lives for SIDENOTE_LOG_DAYS unless they are asked for.
    log_speech: str = env_str("SIDENOTE_LOG_SPEECH", "short")
    # the answers kept for looking back (server/history.py): how long and how much
    history_days: float = env_float("SIDENOTE_HISTORY_DAYS", 90)
    history_mb: float = env_float("SIDENOTE_HISTORY_MB", 200)
    # An answer deleted by itself stays in Recently deleted this many days, where it can be put back, and then goes; 0 keeps
    # it until Recently deleted is emptied by hand. Past SIDENOTE_HISTORY_MB what was deleted goes before any answer shown.
    deleted_days: float = env_float("SIDENOTE_DELETED_DAYS", 7)
    # What was heard, with Keep what is heard on, has a limit of its own beside the answers': a day of steady speech
    # is about a megabyte, in Korean, so this holds some twenty such days. The oldest lines go first.
    heard_mb: float = env_float("SIDENOTE_HEARD_MB", 20)
    transcript_window_sec: float = env_float("SIDENOTE_TRANSCRIPT_WINDOW", 15)  # live bar
    # Problems given by voice. Speech is cut into utterances (Silero VAD): one opens at
    # speech onset and closes after utter_end_silence s of quiet (or at utter_max_sec);
    # the whole utterance is then transcribed and starts an analysis, so a problem read
    # aloud is solved even when the screen never changes. Utterances within
    # speech_context_sec are joined, so a problem read in several sentences arrives whole
    # (each new sentence supersedes the analysis of the shorter version).
    voice_trigger: bool = env_bool("SIDENOTE_VOICE_TRIGGER", True)
    utter_end_silence: float = env_float("SIDENOTE_UTTER_END", 1.5)
    utter_max_sec: float = env_float("SIDENOTE_UTTER_MAX", 90)
    # Shorter than this and the VAD found a blip, not speech: it is not transcribed at all. Whisper
    # does not come back empty-handed from noise, it writes something. Of the 313 utterances in
    # one day, 178 were under 0.8 s and 172 of those came back as English on a Korean speaker's
    # machine, one of them 70 characters from 0.3 s of sound, which nobody can say. Thirteen of them
    # were long enough to be taken for a spoken problem. A real spoken problem takes longer than
    # this to say: "GTID가 뭔가요?" took 1.6 s in a synthetic voice.
    utter_min_sec: float = env_float("SIDENOTE_UTTER_MIN", 0.8)
    speech_min_chars: int = env_int("SIDENOTE_SPEECH_MIN_CHARS", 12)  # ignore short remarks
    # A sentence that looks like a question is no remark: "GTID가 뭔가요?" is under the limit above, and was dropped
    speech_question_chars: int = env_int("SIDENOTE_SPEECH_QUESTION_CHARS", 6)
    speech_context_sec: float = env_float("SIDENOTE_SPEECH_CONTEXT", 120)
    # A pause longer than this between utterances starts a new spoken problem; shorter
    # pauses are sentences of the same one.
    speech_group_gap: float = env_float("SIDENOTE_SPEECH_GAP", 6)
    # How many analyses one unbroken group of speech may start. A problem read aloud is a few
    # sentences and each one supersedes the analysis of the shorter version, but a video's dialogue
    # is also one unbroken group and it runs for minutes: in one hour that queued 43 problems.
    # Whatever is still being read is analysed whole once the speaker stops, so this only cuts
    # the versions in between. 0 means only the sentence that asks something starts anything.
    speech_group_tries: int = env_int("SIDENOTE_SPEECH_GROUP_TRIES", 3)
    audio_history_sec: float = env_float("SIDENOTE_AUDIO_HISTORY", 180)  # must hold a whole utterance
    # Continuous transcription: a background loop re-transcribes the rolling audio
    # window every N seconds and keeps the latest transcript ready, so analysis never
    # blocks on transcription and the panel can show speech live. 0 disables the loop
    # (falls back to transcribing on demand at analysis time).
    transcribe_interval: float = env_float("SIDENOTE_TRANSCRIBE_INTERVAL", 2.0)

    # Screenshot sent to the model is downscaled to this max width to cap tokens. Lowering it was
    # measured twice and is not done either time.
    # With the agent it saved input tokens and did not reduce latency; there the levers are the model
    # and the effort (below / SIDENOTE_FAST).
    # With the local model it does reduce latency, because the width decides how many tiles the
    # vision encoder makes of the screen rather than how many tokens the text is: the first pass
    # takes about 79% as long at 1280 as at 1600, for 93% of the tokens. It is still not done,
    # because what it costs is the screens this tool is for. On the 43 real screens, a first pass at
    # 1280 reads four problems as nothing against one at 1600, and all three it adds are a problem
    # sitting in a corner of a desktop with several windows open on it; boxes holding the whole
    # problem on those desktops fall from 5 of 12 to 2 of 8. Graded end to end over 56 cases: 48
    # answered against 50, with the crowded desktops going from 9 of 12 to 7, whether both passes
    # are narrowed or only the first one.
    # Measured with scratch/local-llm-bench/triage_width.py and bench5.py. The first
    # version of triage_width.py read only the screens with one window filling them, and on those a
    # narrower first pass is strictly better: as accurate, 25% quicker, more boxes holding the whole
    # problem. That is the whole trap.
    max_image_width: int = env_int("SIDENOTE_MAX_IMAGE_WIDTH", 1600)

    # Code runner: the panel can actually run the code in a solution and show its real output.
    # The runner is a separate, network-isolated container (compose service "runner"). Empty
    # URL turns the feature off (the panel hides the run button).
    runner_url: str = env_str("SIDENOTE_RUNNER_URL", "")
    runner_timeout: float = env_float("SIDENOTE_RUNNER_TIMEOUT", 10.0)
    # A runner reached over TCP (Kubernetes, where there is no shared Unix socket) is open to anything that can reach
    # its port, the runs it starts included: with a token set there (RUNNER_TOKEN), the server sends it with every
    # request. compose's Unix socket, which only the server may open, needs none.
    runner_token: str = env_str("SIDENOTE_RUNNER_TOKEN", "")

    # Who may connect besides this container itself: compose publishes the port on the host's 127.0.0.1, and Docker's
    # proxy connects from the default route's gateway, so that gateway is trusted. In Kubernetes the gateway is the
    # node's bridge, which anything on the node can come from, while kubectl port-forward arrives on loopback: the
    # Helm chart sets this off so that only loopback is trusted.
    trust_gateway: bool = env_bool("SIDENOTE_TRUST_GATEWAY", True)

    # A stuck event loop answers nothing while it holds the CPU (measured: 95 minutes
    # at eight cores, with the panel showing the server as off). server/watchdog.py writes every
    # thread's stack when the loop goes quiet for this long, and ends the process when it stays
    # quiet. 0 turns either step off.
    stall_warn_sec: float = env_float("SIDENOTE_STALL_WARN_SEC", 45)
    stall_exit_sec: float = env_float("SIDENOTE_STALL_EXIT_SEC", 180)

    # The check for a newer release (server/updates.py): GitHub's latest release, a minute after the start and then once
    # a day, with Sidenote's version in its User-Agent and nothing else. 0 turns it off for good, for an offline install:
    # no request at all, and the panel's "Check for new versions" has nothing to turn on. Unset, it is on everywhere but
    # in mock mode, which every suite and CI run in: there only 1 turns it on (a suite, against its stand-in for GitHub).
    update_check: str = env_str("SIDENOTE_UPDATE_CHECK", "")
    # Where it asks: this repository's latest release on GitHub's API; a suite points it at its stand-in
    update_url: str = env_str("SIDENOTE_UPDATE_URL", "https://api.github.com/repos/kanggu12/sidenote/releases/latest")

    def __post_init__(self) -> None:
        # SIDENOTE_FAST fills in the agent's speed knobs only where the user left them at the
        # default, so an explicit SIDENOTE_AGENT_MODEL / SIDENOTE_AGENT_EFFORT always wins.
        self.local_url = self.local_url.rstrip("/")
        # How a setting is spelled is not the user's problem: SIDENOTE_AGENT=OFF means "send
        # nothing to the agent", and used to miss every spelling below and fall back to the CLI, which
        # sends everything. Each of these is checked against its own list right after.
        for name in ("analyzer", "agent", "gate", "crop", "crop_snap", "transcriber", "speech_lang", "local_think",
                     "log_speech"):
            setattr(self, name, str(getattr(self, name) or "").strip().lower())
        if self.gate not in ("signature", "ocr", "hybrid", "auto"):
            _ignored("SIDENOTE_GATE", self.gate, "signature")
            self.gate = "signature"
        if self.crop_snap not in ("off", "ink", "detector"):
            _ignored("SIDENOTE_CROP_SNAP", self.crop_snap, "ink")
            self.crop_snap = "ink"
        if self.crop not in ("off", "auto", "aggressive"):
            _ignored("SIDENOTE_CROP", self.crop, "off")
            self.crop = "off"
        if self.transcriber not in ("auto", "null", "faster-whisper"):
            _ignored("SIDENOTE_TRANSCRIBER", self.transcriber, "auto")
            self.transcriber = "auto"
        if self.log_speech not in ("short", "full", "off"):
            _ignored("SIDENOTE_LOG_SPEECH", self.log_speech, "short")
            self.log_speech = "short"
        if self.speech_lang not in ("auto", "ko", "en"):
            _ignored("SIDENOTE_SPEECH_LANG", self.speech_lang, "auto")
            self.speech_lang = "auto"
        if self.analyzer not in ("local", "agent", "cli", "api", "claude", "mock"):
            _ignored("SIDENOTE_ANALYZER", self.analyzer, "local")
            self.analyzer = "local"
        # the earlier names: "cli" meant Claude alone through its CLI, "api" and "claude" through the API
        by_mode = {"cli": "claude-code", "api": "anthropic-api", "claude": "anthropic-api", "mock": "mock"}
        if not self.agent:    # follows the analyzer: the agent-only modes name it, local uses the CLI login
            self.agent = by_mode.get(self.analyzer, "claude-code")
        if self.analyzer in ("cli", "api", "claude"):
            self.analyzer = "agent"
        self.agent = {"cli": "claude-code", "api": "anthropic-api", "claude": "claude-code",
                      "claude-cli": "claude-code"}.get(self.agent, self.agent)   # SIDENOTE_CLAUDE's own values
        if self.agent not in ("claude-code", "codex", "anthropic-api", "off", "mock"):
            _ignored("SIDENOTE_AGENT", self.agent, "claude-code")
            self.agent = "claude-code"
        if self.local_think not in ("auto", "always", "never"):
            _ignored("SIDENOTE_LOCAL_THINK", self.local_think, "auto")
            self.local_think = "auto"
        # the release check's switch as one of three: "1" on, "0" off for good, "" the default (on, but in mock mode)
        update = self.update_check.strip().lower()
        self.update_check = ("1" if update in ("1", "true", "yes", "on") else "0" if update in ("0", "false", "no", "off")
                             else "")
        if update and not self.update_check:
            _ignored("SIDENOTE_UPDATE_CHECK", update, "")
        if self.fast and not os.environ.get("SIDENOTE_LOCAL_THINK", "").strip():
            self.local_think = "never"
        if self.fast:
            if not self.agent_model and self.agent == "claude-code":
                self.agent_model = "sonnet"     # the newest Sonnet, whichever it is
            if not self.agent_effort:
                self.agent_effort = "low"


# The cloud agents by the name SIDENOTE_AGENT takes, with the name the panel and the log show for each (server/agents.py).
AGENT_LABELS = {"claude-code": "Claude Code", "codex": "Codex", "anthropic-api": "Anthropic API", "mock": "Mock agent"}


# A shorter name for where room is short (the panel's header signal, which wrapped to two lines at 360 px with
# "Claude Code" in it).
AGENT_SHORT = {"claude-code": "Claude", "codex": "Codex", "anthropic-api": "API", "mock": "Mock"}


def agent_short(provider: str) -> str:
    """The short name for an agent ("Claude", "Codex"), or its full name when it has none."""
    return AGENT_SHORT.get(provider) or agent_label(provider)


def agent_label(provider: str) -> str:
    """The name an agent is shown by ("Claude Code", "Codex"), or the provider's own spelling for one not listed."""
    return AGENT_LABELS.get(provider, provider or "")


CONFIG = Config()


def agent_name() -> str:
    """The word for the cloud agent in the panel's own sentences, in the current language. One word whichever it is
    (Claude Code, Codex, any other a server is given): which product it is is said once, on the agent's card
    (engines.agent.product)."""
    return t("Agent")
