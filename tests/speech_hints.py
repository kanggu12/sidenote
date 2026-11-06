"""What the speech model is given and which one runs: the hint lists by language, Extra terms in front of them, the 223 tokens
Whisper keeps, the Speech model choice and what happens when a model cannot be had. A stand-in for WhisperModel records what
each decode was given, so no model is loaded. And what the engines are told about what was heard: the rule on stories, one
language for a spoken problem, and no emoji in the local model's headings.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/speech_hints.py
"""
import asyncio
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_TRANSCRIBER="null", SIDENOTE_RUNNER_URL="", SIDENOTE_SEARCH_URL="",
                  SIDENOTE_LOG_DIR=tempfile.mkdtemp(prefix="sidenote-hints-"), SIDENOTE_STALL_WARN_SEC="0", SIDENOTE_STALL_EXIT_SEC="0")
os.environ.pop("SIDENOTE_WHISPER_HINT", None)
os.environ.pop("SIDENOTE_WHISPER_MODEL", None)
ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from server import app as A                     # noqa: E402
from server import transcriber as tr            # noqa: E402
from server.config import CONFIG, WHISPER_HINTS, Config   # noqa: E402
from server.settings import SETTINGS, WORD_MAX, WORDS_MAX   # noqa: E402

SETTINGS.path = None   # nothing written beside the logs
PASS, FAIL = [], []
PCM = b"\0\0" * 16000   # a second of sound: what it says is the stand-in's


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {str(detail)[:300]}" if detail != "" and not ok else ""))


class Tokens:
    """Whisper's tokenizer as far as the transcriber asks of it: here a word or a mark is a token."""

    def encode(self, text, add_special_tokens=False):
        return types.SimpleNamespace(ids=text.replace(",", " ,").split())


class Info:
    def __init__(self, language):
        self.language = language
        self.all_language_probs = [(language, 0.9)]


class Model:
    """A stand-in for WhisperModel: `said` is the language each detection comes back with, and each call is recorded."""

    def __init__(self):
        self.said = "ko"
        self.calls = []            # (the language asked for, the prompt given)
        self.hf_tokenizer = Tokens()

    def transcribe(self, audio, language=None, vad_filter=True, initial_prompt=None, **how):
        self.calls.append((language, initial_prompt))
        lang = language or self.said
        return iter([types.SimpleNamespace(text=f"<{lang}>")]), Info(lang)


def make(language="auto", hint=None):
    t = tr.FasterWhisperTranscriber.__new__(tr.FasterWhisperTranscriber)
    t._np = np
    t._language = language
    t._vote = {x: 0.0 for x in tr.LANGS}
    t.voted, t.last_language = "", ""
    t.hints = tr.hint_words(WHISPER_HINTS if hint is None else hint)
    t.extra, t._prompts = [], {}
    t._model = Model()
    return t


print("[the lists, one a language]")
check("each speech language has its own list", set(WHISPER_HINTS) == set(tr.LANGS) and all(WHISPER_HINTS.values()))
check("the default hint is the lists", Config().whisper_hint == WHISPER_HINTS)
os.environ["SIDENOTE_WHISPER_HINT"] = "only these words."
check("SIDENOTE_WHISPER_HINT gives one text for both instead", tr.hint_words(Config().whisper_hint) == {"ko": "only these words.", "en": "only these words."})
os.environ["SIDENOTE_WHISPER_HINT"] = ""
check("...and empty turns it off", tr.hint_words(Config().whisper_hint) == {})
os.environ.pop("SIDENOTE_WHISPER_HINT")
hangul = lambda s: any("가" <= c <= "힣" for c in s)   # noqa: E731
check("the Korean list keeps the words Korean speech says in Hangul", hangul(WHISPER_HINTS["ko"]))
check("the English list is in the letters English speech is written in", not hangul(WHISPER_HINTS["en"]))
for lang, text in WHISPER_HINTS.items():
    check(f"the {lang} list holds no word twice", len({w.strip() for w in text.rstrip('.').split(',')}) == len(text.rstrip('.').split(',')), text)

print("[chosen by the language of the decode]")
t = make("ko")
t.transcribe(PCM, 16000)
check("speech pinned to Korean gets the Korean list", t._model.calls == [("ko", WHISPER_HINTS["ko"])], t._model.calls)
t = make("en")
t.transcribe(PCM, 16000)
check("speech pinned to English gets the English list", t._model.calls == [("en", WHISPER_HINTS["en"])], t._model.calls)
t = make("auto")
t.last_language = "en"
t._model.said = "en"
t.transcribe(PCM, 16000)
check("on auto, English after English is decoded once, with the English list", t._model.calls == [(None, WHISPER_HINTS["en"])], t._model.calls)
t = make("auto")
t.last_language = "ko"
t._model.said = "en"
t.transcribe(PCM, 16000)
check("on auto, English after Korean is asked again with the English list, so what is decoded has the right words",
      [c for c in t._model.calls][-1] == ("en", WHISPER_HINTS["en"]) and len(t._model.calls) == 2, t._model.calls)
check("...and the language it was heard in is kept", t.last_language == "en", t.last_language)
t = make("auto")
t.last_language = "en"
t._model.said = "ko"
t.transcribe(PCM, 16000)
check("and Korean after English with the Korean list", t._model.calls[-1] == ("ko", WHISPER_HINTS["ko"]) and len(t._model.calls) == 2, t._model.calls)
t = make("auto", "one text for both.")
t.last_language = "ko"
t._model.said = "en"
t.transcribe(PCM, 16000)
check("one text for both needs no second call for its sake", t._model.calls == [(None, "one text for both.")], t._model.calls)
t = make("en", "")
t.transcribe(PCM, 16000)
check("no hint, no prompt", t._model.calls == [("en", None)], t._model.calls)

print("[Extra terms]")
t = make("en")
t.set_hints(WHISPER_HINTS, ["Zabbix", " Open OnDemand "])
t.transcribe(PCM, 16000)
check("the person's words go in front of the list", t._model.calls[-1][1].startswith("Zabbix, Open OnDemand, " + WHISPER_HINTS["en"].split(",")[0]), t._model.calls[-1][1][:60])
check("...once each, the list's words still there", t.prompt("en").count("Zabbix") == 1 and "kubectl" in t.prompt("en"), t.prompt("en")[:80])
t.set_hints(None, ["Zabbix"])
check("with the hints off, the person's words alone", t.prompt("en") == "Zabbix." and t.prompt("ko") == "Zabbix.", t.prompt("en"))
t.set_hints(None, [])
check("with neither, nothing", t.prompt("en") is None)
t.set_hints(WHISPER_HINTS, ["Zabbix"])
first = t.prompt("ko")
t.set_hints(WHISPER_HINTS, ["Jira"])
check("a change is what the next decode gets", t.prompt("ko").startswith("Jira,") and first.startswith("Zabbix,"), t.prompt("ko")[:40])

print("[the 223 tokens Whisper keeps]")
check("the limit is half of Whisper's context, less one", tr.PROMPT_TOKENS == 223)
long_list = {"en": ", ".join(f"word{i}" for i in range(400)) + ".", "ko": "하나, 둘."}
t = make("en", long_list)
said = []


class Said(logging.Handler):
    def emit(self, record):
        said.append(record.getMessage())


logging.getLogger("sidenote.transcriber").addHandler(Said())
t.set_hints(long_list, ["mine1", "mine2"])
p = t.prompt("en")
check("a list past the limit is cut to it", t._tokens(p) <= tr.PROMPT_TOKENS, t._tokens(p))
check("...from its end: the person's words and the list's first stay", p.startswith("mine1, mine2, word0, word1,") and "word399" not in p, p[:40])
check("...each word whole, ended as a sentence", p.endswith(".") and all(w.strip() for w in p.rstrip(".").split(",")), p[-20:])
check("nothing is said while the person's words all fit", not said, said)
many = [f"mine{i}" for i in range(300)]
t.set_hints(long_list, many)
p = t.prompt("en")
check("the person's own words alone past the limit: their last go", p.startswith("mine0, mine1,") and t._tokens(p) <= tr.PROMPT_TOKENS and "word0" not in p, p[:30])
check("...and the log says so, once", sum("extra terms fit" in x for x in said) == 1, said)
t.prompt("en")
check("...not at every decode", sum("extra terms fit" in x for x in said) == 1, said)
del t.__dict__["_model"]
check("with no tokenizer a character counts as a token: never more than Whisper keeps", t._tokens("abc") == 3)

print("[the setting]")
item = SETTINGS.defs["speech_terms"]
check("Extra terms is a box of free words in the Speech section, empty by default", (item.kind, item.section, item.default) == ("words", "speech", []))
ok, why = SETTINGS.set("speech_terms", ["  Zabbix ", "", "Jira"])
check("trimmed, with the empty ones gone", ok and SETTINGS.get("speech_terms") == ["Zabbix", "Jira"], SETTINGS.get("speech_terms"))
ok, why = SETTINGS.set("speech_terms", ["x" * (WORD_MAX + 1)])
check("a word past the limit is refused, and the limits are said", not ok and str(WORD_MAX) in why, why)
ok, why = SETTINGS.set("speech_terms", [f"w{i}" for i in range(WORDS_MAX + 1)])
check("too many words are refused", not ok and str(WORDS_MAX) in why, why)
ok, _ = SETTINGS.set("speech_terms", [])


async def apply(key, value):
    """Through the panel's own way in: what a change from the panel does."""
    ok, _ = await A.apply_setting(APP, key, value)
    return ok


BROADCAST = []
A.broadcast = lambda msg: (BROADCAST.append(msg), asyncio.sleep(0))[1]
APP = types.SimpleNamespace(state=types.SimpleNamespace(transcriber=None, transcribe_worker=None))


def model_in_use():
    """The model the transcriber in use runs, None for one without (a NullTranscriber): a fault leaves one there, and a check reads None."""
    return getattr(APP.state.transcriber, "model_size", None)


class Stand:
    """A transcriber as apply_setting and the swap see it."""

    available = True
    language = "auto"

    def __init__(self, model="small"):
        self.model_size = model
        self.given = None

    def set_hints(self, hint, extra=()):
        self.given = (hint, list(extra))


async def settings_act_at_once():
    APP.state.transcriber = Stand()
    await apply("speech_terms", ["Zabbix"])
    check("a change of Extra terms reaches the transcriber at once", APP.state.transcriber.given == (CONFIG.whisper_hint, ["Zabbix"]), APP.state.transcriber.given)
    await apply("whisper_hint", False)
    check("switching the hints off leaves the person's words", APP.state.transcriber.given == (None, ["Zabbix"]), APP.state.transcriber.given)
    await apply("whisper_hint", True)
    check("and on again brings the lists back", APP.state.transcriber.given == (CONFIG.whisper_hint, ["Zabbix"]), APP.state.transcriber.given)
    await apply("speech_terms", [])


async def model_choice():
    print("[the speech model]")
    item = SETTINGS.defs["whisper_model"]
    check("a choice of the Speech section, small by default, medium beside it",
          item.kind == "choice" and item.section == "speech" and item.default == "small" and [o[0] for o in item.options] == ["small", "medium"], item.options)
    help_words = next(i for i in SETTINGS.meta()["items"] if i["key"] == "whisper_model")
    check("what each costs is in the line for the choice", all(any(c.isdigit() for c in help_words["opt_help"][k]) for k in ("small", "medium")), help_words["opt_help"])
    ok, _ = SETTINGS.set("whisper_model", "tiny-nonsense")
    check("a model not offered is refused", not ok and SETTINGS.get("whisper_model") == "small")
    was = A.CONFIG.whisper_model
    A.CONFIG.whisper_model = "base"
    offered = [o[0] for o in SETTINGS.options("whisper_model")]
    A.CONFIG.whisper_model = was
    check("the one the environment names is offered too", "base" in offered, offered)
    cfg = Config()
    asked = []

    class Fake:
        available = True

        def __init__(self, model, *a):
            asked.append(model)
    real = tr.FasterWhisperTranscriber
    tr.FasterWhisperTranscriber = Fake
    cfg.transcriber, cfg.audio_enabled, cfg.whisper_model = "auto", True, "small"
    tr.make_transcriber(cfg)
    tr.make_transcriber(cfg, "medium")
    tr.FasterWhisperTranscriber = real
    check("the transcriber is made with the model named, else the environment's", asked == ["small", "medium"], asked)

    # The download of a model not there yet, outside the lock the model in use and every agent's process wait on
    import faster_whisper
    from server import forksafe
    during = {}

    class Built:
        hf_tokenizer = Tokens()

        def __init__(self, where, **k):
            during["built_from"] = where
            during["locked_building"] = forksafe.native_work().locked()

    def fetch(name):
        during["locked_fetching"] = forksafe.native_work().locked()
        return "/somewhere/fetched"
    real_built, real_fetch = faster_whisper.WhisperModel, faster_whisper.download_model
    faster_whisper.WhisperModel, faster_whisper.download_model = Built, fetch
    try:
        tr.FasterWhisperTranscriber("medium", "int8", "auto", "", 4)
    finally:
        faster_whisper.WhisperModel, faster_whisper.download_model = real_built, real_fetch
    check("a model not there yet is fetched outside the lock: the one in use goes on hearing", during.get("locked_fetching") is False, during)
    check("...and built under it, from where it was fetched to", during.get("locked_building") is True and during.get("built_from") == "/somewhere/fetched", during)

    # chosen in the panel: it loads beside the one in use, which goes on until it is ready
    old = Stand("small")
    APP.state.transcriber = old
    APP.state.transcribe_worker = asyncio.create_task(asyncio.sleep(60))
    release = asyncio.Event()
    made = []

    def maker(cfg, model=""):
        made.append(model)
        return Stand(model)
    real_make = A.make_transcriber
    A.make_transcriber = maker
    BROADCAST.clear()
    await apply("whisper_model", "medium")
    check("the old model goes on while the new one loads", APP.state.transcriber is old)
    await APP.state.speech_model_task
    check("the choice loads that model", made == ["medium"], made)
    check("...and it takes over, hints and language as the settings say", model_in_use() == "medium" and APP.state.transcriber.given == (CONFIG.whisper_hint, []), APP.state.transcriber.__dict__)
    notes = [m.get("text") for m in BROADCAST if m.get("type") == "notice"]
    check("the panel is told it loads, and when it is ready", len(notes) == 2 and all("medium" in n for n in notes), notes)
    check("the panel hears that speech is there", any(m.get("type") == "status" and m.get("audio") for m in BROADCAST), BROADCAST)

    # one that cannot be had: a download with no network
    def no_model(cfg, model=""):
        raise OSError("no connection to the model's site")
    A.make_transcriber = no_model
    now = APP.state.transcriber
    BROADCAST.clear()
    await apply("whisper_model", "small")
    await APP.state.speech_model_task
    check("a model that cannot be had leaves the one in use", APP.state.transcriber is now)
    check("...and the choice back on it, so the next start finds a model", SETTINGS.get("whisper_model") == "medium", SETTINGS.get("whisper_model"))
    warned = [m for m in BROADCAST if m.get("type") == "notice" and m.get("level") == "bad"]
    check("...and says so", len(warned) == 1 and "small" in warned[0]["text"], BROADCAST)
    check("...and the panel's choice shows it", any(m.get("type") == "settings" and m.get("values") == {"whisper_model": "medium"} for m in BROADCAST), BROADCAST)
    A.make_transcriber = lambda cfg, model="": tr.NullTranscriber()   # "auto": no faster-whisper for it, and no exception
    await apply("whisper_model", "small")
    await APP.state.speech_model_task
    check("one that comes back empty-handed counts the same", APP.state.transcriber is now and SETTINGS.get("whisper_model") == "medium")

    # two choices one after the other: the last one stands
    gate = asyncio.Event()

    def slow(cfg, model=""):
        return Stand(model)
    A.make_transcriber = slow
    await apply("whisper_model", "small")
    await apply("whisper_model", "medium")
    await asyncio.sleep(0.2)
    check("the last of two quick choices is the one in use", model_in_use() == "medium", model_in_use())
    APP.state.transcribe_worker.cancel()

    # the next start: a saved model that cannot be had gives way to the environment's
    print("[the next start]")
    SETTINGS.values["whisper_model"] = "medium"
    tried = []

    def start_maker(cfg, model=""):
        tried.append(model)
        return tr.NullTranscriber() if model == "medium" else Stand(model)
    A.make_transcriber = start_maker
    worker = A.transcription_worker
    A.transcription_worker = lambda app: asyncio.sleep(0)
    was_tr, was_audio = A.CONFIG.transcriber, A.CONFIG.audio_enabled
    A.CONFIG.transcriber, A.CONFIG.audio_enabled = "auto", True
    await A.load_speech(APP)
    check("a saved model that cannot be had gives way to the environment's at the next start", tried == ["medium", "small"] and model_in_use() == "small", tried)
    check("...and the choice says which runs", SETTINGS.get("whisper_model") == "small", SETTINGS.get("whisper_model"))
    SETTINGS.values["whisper_model"] = "medium"
    tried.clear()

    def raising(cfg, model=""):   # SIDENOTE_TRANSCRIBER=faster-whisper raises when it cannot load
        tried.append(model)
        if model == "medium":
            raise OSError("no connection to the model's site")
        return Stand(model)
    A.make_transcriber = raising
    await A.load_speech(APP)
    check("so does one that raises", tried == ["medium", "small"] and model_in_use() == "small" and SETTINGS.get("whisper_model") == "small", tried)
    # A choice made while the start's load runs: that choice's own load settles it
    SETTINGS.values["whisper_model"] = "small"
    mine = Stand("medium")
    APP.state.transcriber = mine

    def choose_meanwhile(cfg, model=""):
        SETTINGS.values["whisper_model"] = "medium"
        return Stand(model)
    A.make_transcriber = choose_meanwhile
    await A.load_speech(APP)
    check("the start's load does not undo a choice that has taken over while it ran", APP.state.transcriber is mine and SETTINGS.get("whisper_model") == "medium", model_in_use())
    # ...and with that choice still loading, the start's model hears meanwhile, and is what is left when the choice cannot be had
    SETTINGS.values["whisper_model"] = "small"
    APP.state.transcriber = tr.NullTranscriber()
    A.make_transcriber = choose_meanwhile
    await A.load_speech(APP)
    check("a choice still loading: the start's model hears meanwhile", model_in_use() == "small" and SETTINGS.get("whisper_model") == "medium", APP.state.transcriber.__dict__)
    SETTINGS.values["whisper_model"] = "medium"
    A.make_transcriber = lambda cfg, model="": tr.NullTranscriber()
    now = APP.state.transcriber
    await A.change_speech_model(APP, "small", "medium")
    check("...and when it cannot be had, the panel's choice and what runs agree", APP.state.transcriber is now and SETTINGS.get("whisper_model") == "small")
    BROADCAST.clear()
    SETTINGS.values["whisper_model"] = "medium"
    A.make_transcriber = lambda cfg, model="": tr.NullTranscriber() if model == "medium" else Stand(model)
    await A.load_speech(APP)
    check("a panel open at the start hears that the saved model gave way", any(m.get("type") == "settings" and m.get("values") == {"whisper_model": "small"} for m in BROADCAST), BROADCAST)
    SETTINGS.values["whisper_model"] = "medium"
    tried.clear()
    A.make_transcriber = lambda cfg, model="": (tried.append(model), Stand(model))[1]
    await A.load_speech(APP)
    check("a saved model that loads is the one that runs", tried == ["medium"] and model_in_use() == "medium", tried)
    # A choice that loaded first has its worker running: the start's load, ending after it, starts no second one
    SETTINGS.values["whisper_model"] = "small"
    started = []
    A.transcription_worker = lambda app: (started.append(app), asyncio.sleep(0))[1]
    A.make_transcriber = lambda cfg, model="": Stand(model)
    running = asyncio.create_task(asyncio.sleep(60))
    APP.state.transcribe_worker = running
    await A.load_speech(APP)
    check("a worker already running is the one that goes on: a second would cut every sentence twice",
          started == [] and APP.state.transcribe_worker is running and model_in_use() == "small", started)
    running.cancel()
    await asyncio.gather(running, return_exceptions=True)
    await A.load_speech(APP)
    check("...and one that has ended is started again", len(started) == 1 and APP.state.transcribe_worker is not running, started)
    await asyncio.gather(APP.state.transcribe_worker, return_exceptions=True)
    A.make_transcriber = real_make
    A.transcription_worker = worker
    A.CONFIG.transcriber, A.CONFIG.audio_enabled = was_tr, was_audio


async def worker_follows_the_model():
    """The speech loop reads the transcriber at each pass, so the sentence being cut is not lost at a swap."""
    print("[the loop follows the choice]")

    class Ear(Stand):
        def __init__(self, model):
            super().__init__(model)
            self.asked = 0

        def speech_segments(self, tail, sr):
            return []

        def transcribe(self, pcm, sr):
            self.asked += 1
            return ""
    first, second = Ear("small"), Ear("medium")
    A.STATE.__init__()
    A.STATE.audio_sr = 16000
    app = types.SimpleNamespace(state=types.SimpleNamespace(transcriber=first))
    was = A.CONFIG.transcribe_interval
    A.CONFIG.transcribe_interval = 0.2
    first.speech_segments = second.speech_segments = lambda tail, sr: [(0, 16000)]
    task = asyncio.create_task(A.transcription_worker(app))
    for _ in range(4):
        A.STATE.push_audio(b"\0\0" * 3200, 16000)
        await asyncio.sleep(0.22)
    app.state.transcriber = second
    n = first.asked
    for _ in range(4):
        A.STATE.push_audio(b"\0\0" * 3200, 16000)
        await asyncio.sleep(0.22)
    check("the next pass writes with the new model, and the old one is asked no more", second.asked > 0 and first.asked == n, [first.asked, second.asked])
    check("...without starting over", not task.done())
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    A.CONFIG.transcribe_interval = was


async def what_the_engines_are_told():
    print("[what the engines are told about what was heard]")
    import server.pipeline as pl
    from server import analyzer as an
    from server.settings import SETTINGS as S
    words = "So the rebuild took two hours, right?"
    local_text = an.build_user_text(words, 0, True, False)
    check("the first pass is told what is and is not asked of the listener, with the words after it", an.SPEECH_RULE in local_text and local_text.endswith(words), local_text[:80])
    for said in ("듣는 사람에게 묻는", "긴 설명이나 이야기 뒤에 나온 질문도 풉니다", "남이 물었다고 전하는 물음", "스스로 답하는 물음", "right?", "맞죠?", "풀 대상이 없는 경우"):
        check(f"...the rule says: {said}", said in an.SPEECH_RULE, an.SPEECH_RULE)
    check("the words are no longer all declared the problem", "이것을 풀 대상으로 보고" not in local_text, local_text[:120])
    check("the agent is told the same rule", an.SPEECH_RULE in an.speech_request(words) and an.speech_request(words).endswith(words), an.speech_request(words)[:80])
    check("the picking out of the question for the agent knows it too", all(x in an.EXTRACT_SPEECH for x in ("남이 물었다고 전하는 물음", "스스로 답하는 물음", "right?", "`없음`")), an.EXTRACT_SPEECH)
    check("a screen's own request has no such rule", an.SPEECH_RULE not in an.build_user_text("", 0, False, True) and an.SPEECH_RULE not in an.build_user_text("the room's sound", 0, False, True))
    # through the pipeline's own way of making what goes to the agent
    engines = an.make_engines(A.CONFIG)

    async def nothing(*a, **k):
        return None
    hooks = pl.Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=nothing, stage=nothing, confirm=nothing, agent_failed=nothing)
    pipe = pl.Pipeline(engines, hooks)

    class Local:
        async def extract(self, images=(), speech=""):
            return "What is a checkpoint?"
    S.values["extract"] = True
    S.values["local_llm"] = True
    S.values["agent_payload"] = "crop"
    images, text, what, heard, _ = await pipe._agent_payload(1, Local(), None, [], 0, words, True, None)
    check("a spoken problem goes to the agent with the rule, and the question written out", images == [] and an.SPEECH_RULE in text and text.endswith("What is a checkpoint?") and heard == "What is a checkpoint?", text[:80])
    S.values["agent_payload"] = "screen"
    frame = types.SimpleNamespace(extra_b64=[], width=100, height=100)
    images, text, what, heard, _ = await pipe._agent_payload(1, Local(), frame, ["image"], 0, words, True, None)
    check("with Whole screen too", images == ["image"] and an.SPEECH_RULE in text, text[:80])
    S.values["agent_payload"] = S.defs["agent_payload"].default

    print("[a spoken problem with no question to pick out]")

    class Reads:
        """The local model: the first pass hands the words on, and the picking out of the question says what `picked` says."""
        region_scale = 1000
        model = "m"

        def __init__(self, picked=an.NO_QUESTION):
            self.picked, self.thought = picked, 0

        def busy_now(self):
            return False

        async def fast(self, images, text, on_delta, **k):
            return an.FastResult(text=None, head="TYPE: work\nROUTE: deep\n", type="work", route="deep", model="m")

        async def extract(self, images=(), speech=""):
            return self.picked

        async def deep(self, *a, **k):
            self.thought += 1
            return an.AnalysisResult(text="TYPE: work\nANSWER: 보고서", model="m (think)")

    class Agent:
        name = "stand-in"
        sent = 0

        def __init__(self):
            self.asked = []

        async def run(self, images, text, on_delta, **k):
            self.asked.append(text)
            self.sent += 1
            await on_delta("TYPE: work\nANSWER: 답")
            return an.AnalysisResult(text="TYPE: work\nANSWER: 답", model="agent")
    warned = []

    async def warn(text):
        warned.append(text)
    for key, value in (("agent_mode", "hard"), ("agent_confirm", False), ("extract", True), ("local_llm", True), ("agent_payload", "crop")):
        S.values[key] = value

    async def solve(picked, by_user=False):
        local, agent = Reads(picked), Agent()
        hooks = pl.Hooks(local_ok=lambda: True, agent_ok=lambda: True, notice=nothing, stage=nothing, confirm=nothing, agent_failed=nothing, warn=warn)
        pipe = pl.Pipeline(types.SimpleNamespace(local=local, agent=agent), hooks)
        out = await pipe.solve(1, None, words, True, nothing, by_user=by_user)
        return out, local, agent
    warned.clear()
    out, local, agent = await solve(an.NO_QUESTION)
    check("nothing to pick out: it ends as nothing to solve", out.text == "TYPE: none" and out.engine == "local", out.text)
    check("...with nothing sent", agent.asked == [] and out.sent == [], agent.asked)
    check("...no report written on somebody's story by the thinking pass", local.thought == 0)
    check("...and no notice", warned == [], warned)
    out, local, agent = await solve("What is a checkpoint?")
    check("a question picked out goes to the agent as before", len(agent.asked) == 1 and agent.asked[0].endswith("What is a checkpoint?") and out.engine == "agent", agent.asked)
    warned.clear()
    out, local, agent = await solve("")
    check("a reading that brought nothing says nothing: the local model answers, and the card says why", local.thought == 1 and agent.asked == [] and len(warned) == 1 and out.text.startswith("TYPE: work"), [local.thought, warned])
    out, local, agent = await solve(an.NO_QUESTION, by_user=True)
    check("asked for by hand, it is solved all the same", local.thought == 1 and out.text.startswith("TYPE: work"), out.text)
    real = an.LocalLlmAnalyzer(A.CONFIG)
    await real._client.aclose()

    async def says(text):
        async def plain(system, images, request, tokens):
            return text
        real._plain = plain
        return await real.extract(speech=words)
    check("the model's own word for none is told apart", await says("없음") == an.NO_QUESTION and await says("`없음`\n") == an.NO_QUESTION, await says("없음"))
    check("from a reading that brought nothing", await says("") == "" and await says("  \n") == "", repr(await says("")))
    check("and from a question", (await says("What is a checkpoint?")) == "What is a checkpoint?")
    S.values["agent_mode"] = S.defs["agent_mode"].default

    print("[one answer language for a spoken problem]")
    rule = "음성으로 들어온 문제는 어느 언어로 들렸든 ANSWER 줄, 답안 문단, 해설을 모두 한국어로 쓴다"
    for name, prompt in (("the agent", an.SYSTEM_PROMPT), ("the local model", an.LOCAL_SYSTEM_PROMPT)):
        check(f"{name} is told one language for a spoken problem", rule in prompt, prompt[:60])
        check(f"{name} is not told to follow the language it was heard in", "음성이 영어로 들어오면" not in prompt)
        check(f"{name} keeps the rule for a problem on the screen in English", "화면의 문제가 영어로 되어 있으면" in prompt)
    check("the local model's answer line says the same", "한국어 문제나 음성으로 들어온 문제면 요지" in an.LOCAL_SYSTEM_PROMPT)
    for text in (an.build_user_text(words, 0, True, False), an.speech_request(words)):
        check("and the request says it where the words are, the same for both engines", "들린 언어와 상관없이 ANSWER 줄과 본문을 모두 한국어로 씁니다" in text, text[:300])
    was = an.i18n.LANG
    an.i18n.LANG = "en"
    for name, prompt in (("the agent", an.in_answer_language(an.SYSTEM_PROMPT)), ("the local model", an.in_answer_language(an.LOCAL_SYSTEM_PROMPT))):
        check(f"with the panel in English, {name} is told English for a spoken problem", "음성으로 들어온 문제는 어느 언어로 들렸든 ANSWER 줄, 답안 문단, 해설을 모두 영어(English)로 쓴다" in prompt and rule not in prompt)
    for text in (an.build_user_text(words, 0, True, False), an.speech_request(words)):
        check("...and the request too", "모두 영어(English)로 씁니다" in text and "모두 한국어로" not in text, text[:300])
    an.i18n.LANG = was

    print("[the route's word where the type goes]")
    check("`TYPE: fast` is no kind of answer", an.without_route("TYPE: fast\nROUTE: fast\nANSWER: 답\n풀이") == "TYPE: other\nANSWER: 답\n풀이", an.without_route("TYPE: fast\nROUTE: fast\nANSWER: 답\n풀이"))
    check("...nor is `TYPE: deep`", an.without_route("TYPE: deep\nANSWER: 답") == "TYPE: other\nANSWER: 답")
    check("a real type stays, and only the head is read", an.without_route("TYPE: essay\nROUTE: fast\nANSWER: 답\nTYPE: fast") == "TYPE: essay\nANSWER: 답\nTYPE: fast", an.without_route("TYPE: essay\nROUTE: fast\nANSWER: 답\nTYPE: fast"))
    told = []

    async def wrote(text):
        told.append(text)
    gate = an._RouteGate(wrote)
    await gate.feed("TYPE: fast\nROUTE: fast\nANSWER: 답\n")
    check("through the first pass's gate, the panel gets a type it knows", "".join(told).startswith("TYPE: other\n") and gate.type == "other", ["".join(told), gate.type])

    print("[no emoji in the local model's headings]")
    feed = lambda text, step=3: "".join(f.feed(text[i:i + step]) for i in range(0, len(text), step))   # noqa: E731
    f = an._HeadingMarks()
    check("a mark before a heading's title goes, with its space", feed("### 💡 핵심 아이디어\n풀이") == "### 핵심 아이디어\n풀이", feed)
    f = an._HeadingMarks()
    check("whatever pieces the stream cuts it in", feed("#### ⚙️ 복잡도 분석\n", 1) == "#### 복잡도 분석\n")
    f = an._HeadingMarks()
    check("a bold line that stands as a heading too", feed("**✅ 1단계: 원인**\n") == "**1단계: 원인**\n")
    f = an._HeadingMarks()
    check("a mark in a table's cell stays: it can be all the cell says", feed("| GET | ✅ |\n") == "| GET | ✅ |\n")
    f = an._HeadingMarks()
    check("so does one in the body", feed("본문 💡 그대로\n") == "본문 💡 그대로\n")
    for line in ("* A ✅\n", "*   **A**: ✅\n", "**정답: ❌**\n", "### 1️⃣ 첫째\n", "### 정답 ✅\n", "- ✅ 항목\n"):
        f = an._HeadingMarks()
        check(f"and one that says something: {line.strip()}", feed(line) == line, feed)
    f = an._HeadingMarks()
    code = "```python\n# 💡 a comment\n** ✅\n```\n### 🔍 뒤\n"
    check("and one in code; the heading after the code is read again", feed(code) == "```python\n# 💡 a comment\n** ✅\n```\n### 뒤\n", feed)
    f = an._HeadingMarks()
    plain = "TYPE: essay\nANSWER: 답 → 값 ①\n\n### 제목 (C++ → Rust)\n- 항목\n"
    check("what is no emoji is not touched", feed(plain) == plain)

    # through the local model's own stream: what the panel is sent and what is kept
    import json as _json

    class Sse:
        def __init__(self, lines):
            self.lines = lines

        def stream(self, method, url, json=None):
            outer = self

            class Resp:
                status_code = 200

                async def aiter_lines(self):
                    for line in outer.lines:
                        yield line

                async def aread(self):
                    return b""

            class Ctx:
                async def __aenter__(self):
                    return Resp()

                async def __aexit__(self, *a):
                    return False
            return Ctx()

        async def aclose(self):
            pass
    local = an.LocalLlmAnalyzer(A.CONFIG)
    await local._client.aclose()

    async def ready(*a):
        return None
    local._ready = ready
    answer = "TYPE: essay\nANSWER: 답\n\n### 💡 핵심\n풀이 💡\n"
    chunk = lambda d: "data: " + _json.dumps({"choices": [{"delta": {"content": d}}]})   # noqa: E731
    local._client = Sse([chunk(answer[i:i + 4]) for i in range(0, len(answer), 4)] + ["data: [DONE]"])
    sent = []

    async def on_delta(text):
        sent.append(text)
    out, *_ = await local._stream({"model": "m", "messages": []}, on_delta)
    check("through the stream, the panel gets it without the mark", "".join(sent) == "TYPE: essay\nANSWER: 답\n\n### 핵심\n풀이 💡\n", "".join(sent))
    check("...and the answer kept is the same", out == "".join(sent), out)


async def main():
    await settings_act_at_once()
    await model_choice()
    await worker_follows_the_model()
    await what_the_engines_are_told()


asyncio.run(main())
print(f"==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)
