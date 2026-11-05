"""The session language vote, without loading Whisper.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/lang_vote.py

server/transcriber.py decodes an utterance in the language the session has voted for, so a short one
Whisper calls English in the middle of Korean speech is decoded as Korean (measured on real
recordings: 32 of 108 Korean spans were read as English without this). The vote itself is arithmetic
over the odds Whisper hands back, so it is checked here with a stand-in model that hands back
whatever each case wants, and the real recordings are measured separately (lang_vote.py in the
bench folder).
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from server import transcriber as tr  # noqa: E402

PASS = FAIL = 0


def check(name, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print(f"  ok {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}: got {got!r}, want {want!r}")


class Info:
    """What faster-whisper returns beside the segments."""

    def __init__(self, language, probs):
        self.language = language
        self.all_language_probs = list(probs.items())


class Model:
    """A stand-in for WhisperModel: each call answers from the script the case set, and records the
    language it was asked for so the test can see which decode actually ran."""

    def __init__(self):
        self.script = []      # (detected language, {odds}) per call made with language=None
        self.asked = []       # the `language` argument of every call
        self.how = []         # what else every call was given (temperature, max_new_tokens)

    def transcribe(self, audio, language=None, vad_filter=True, initial_prompt=None, **how):
        self.asked.append(language)
        self.how.append(how)
        if language is None:
            lang, probs = self.script.pop(0)
            return iter([types.SimpleNamespace(text=f"<{lang}>")]), Info(lang, probs)
        # a pinned decode: the text says which language it ran in
        return iter([types.SimpleNamespace(text=f"<{language}>")]), Info(language, {})


def make(language="auto"):
    """A transcriber with the stand-in model, skipping the real __init__ (which loads Whisper)."""
    t = object.__new__(tr.FasterWhisperTranscriber)
    t._np = np
    t._language = language
    t._vote = {lang: 0.0 for lang in tr.LANGS}
    t.voted = ""
    t.last_language = ""
    t.hints, t.extra, t._prompts = {}, [], {}
    t._model = Model()
    return t


def pcm(seconds):
    """`seconds` of 16 kHz 16-bit mono silence: only its length matters here."""
    return np.zeros(int(seconds * 16000), dtype=np.int16).tobytes()


def feed(t, seconds, detected, probs):
    t._model.script.append((detected, probs))
    text = t.transcribe(pcm(seconds), 16000)
    return t.last_language, text


KO = {"ko": 0.95, "en": 0.03}
EN = {"ko": 0.03, "en": 0.95}
EN_SURE = {"ko": 0.04, "en": 0.96}   # the odds measured on Korean spans that were read as English

print("[the vote only decides once it has heard enough]")
t = make()
check("nothing voted for at the start", t.voted, "")
# 0.5 s x 0.95 = 0.475 of evidence, under VOTE_MIN
feed(t, 0.5, "ko", KO)
check("half a second is not enough", t.voted, "")
feed(t, 2.0, "ko", KO)
check("two more seconds settle it", t.voted, "ko")

print("\n[a short utterance read against the session is decoded in the session's language]")
t = make()
feed(t, 3.0, "ko", KO)
got, text = feed(t, 0.8, "en", EN_SURE)
check("decoded as korean", got, "ko")
check("the korean decode is what came back", text, "<ko>")
check("the second decode was asked for korean", t._model.asked[-1], "ko")

print("\n[the vote only ever moves an utterance to korean, never away from it]")
t = make()
for _ in range(3):
    feed(t, 3.0, "en", EN)
check("voted english", t.voted, "en")
got, _ = feed(t, 0.8, "ko", KO)
check("a korean-looking utterance is left korean", got, "ko")
check("and was not decoded twice for it", t._model.asked[-1], None)

print("\n[an english session is left alone]")
t = make()
feed(t, 3.0, "en", EN)
check("voted english", t.voted, "en")
got, _ = feed(t, 0.8, "en", EN)
check("english stays english", got, "en")
check("no second decode was needed", t._model.asked[-1], None)

print("\n[a language outside the two is still redone as the likelier of them]")
t = make()
got, _ = feed(t, 1.0, "ja", {"ko": 0.4, "en": 0.1, "ja": 0.5})
check("japanese becomes korean", got, "ko")

print("\n[the vote turns around when the speaker really does change language]")
t = make()
feed(t, 3.0, "ko", KO)
check("korean first", t.voted, "ko")
for _ in range(8):
    feed(t, 3.0, "en", EN)
check("english after eight english utterances", t.voted, "en")

print("\n[switching the setting in the panel clears the vote]")
t = make()
feed(t, 3.0, "ko", KO)
t.language = "en"
check("pinned to english", t.language, "en")
check("the vote is cleared", t.voted, "")
check("no vote evidence is left", sum(t._vote.values()), 0.0)
t.language = "auto"
got, _ = feed(t, 0.8, "en", EN_SURE)
check("back on auto, nothing carried over", got, "en")

print("\n[a pinned language never runs the vote]")
t = make("ko")
t._model.script.append(("ko", KO))
t.transcribe(pcm(0.8), 16000)
check("asked for korean straight away", t._model.asked, ["ko"])
check("still nothing voted for", t.voted, "")

print("\n[the live line: read quickly, in the language it sounds like]")
t = make()
for _ in range(3):
    feed(t, 2.0, "ko", KO)
check("the session has voted Korean", t.voted, "ko")
t._model.asked.clear(), t._model.how.clear()
t._model.script.append(("en", EN_SURE))
words = t.transcribe_live(pcm(15), 16000)
check("a window of English is not held to the vote", (words, t._model.asked), ("<en>", [None]))
check("...is given no retries and no more tokens than speech makes, within what Whisper allows beside the longest prompt",
      t._model.how, [{"temperature": 0.0, "max_new_tokens": tr.LIVE_TOKENS_MAX}])
t._model.how.clear()
t._model.script.append(("en", EN_SURE))
t.transcribe_live(pcm(4), 16000)
check("...and a short one fewer of them", t._model.how, [{"temperature": 0.0, "max_new_tokens": 76}])

print("\n[an utterance held to the vote]")


def voted_korean():
    """A session that has spoken Korean, with nothing else on the stand-in's record: what it hears next may move the vote."""
    v = make()
    for _ in range(3):
        feed(v, 2.0, "ko", KO)
    v._model.asked.clear(), v._model.how.clear()
    return v


t = voted_korean()
t._model.script.append(("en", EN_SURE))
words = t.transcribe(pcm(5), 16000)
check("a sentence held to Korean is decoded once, with no retries", (words, t._model.asked, t._model.how),
      ("<ko>", [None, "ko"], [{}, {"temperature": 0.0}]))
t = voted_korean()
t._model.script.append(("en", EN_SURE))
t.transcribe(pcm(tr.HELD_SENTENCE_SEC + 1), 16000)
check("...and longer speech keeps Whisper's retries, as one try goes round on a phrase there", t._model.how, [{}, {}])
t = voted_korean()
t._model.script.append(("ko", KO))
t.transcribe(pcm(5), 16000)
check("one that sounds as it is voted is decoded as it always was", t._model.how, [{}])

print("\n[what the live line leaves out]")
said = types.SimpleNamespace(text=" We had an outage, and the database kept ffffffffffffffffffffffff", compression_ratio=9.0)
check("the sound Whisper went round on goes, and the words before it stay", tr.unlooped(said), "We had an outage, and the database kept")
said = types.SimpleNamespace(text="드라마에 비해 " * 8, compression_ratio=6.0)
check("...a phrase too", tr.unlooped(said), "")
said = types.SimpleNamespace(text=" 하하하하하하 정말요", compression_ratio=1.2)
check("what Whisper itself does not call a loop stays", tr.unlooped(said), "하하하하하하 정말요")
said = types.SimpleNamespace(text=" no compression ratio on this one")
check("...and a segment that does not say", tr.unlooped(said), "no compression ratio on this one")

print(f"\n==== {PASS} passed, {FAIL} failed ====")
sys.exit(1 if FAIL else 0)
