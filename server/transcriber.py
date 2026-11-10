"""Audio transcription backends.

The core pipeline runs without any speech dependency (NullTranscriber). Install
server/requirements-audio.txt to enable faster-whisper; "auto" picks it up.
Transcription is CPU-bound, so callers run .transcribe() in a thread executor.
"""
from __future__ import annotations

import logging
import os
import re

from . import forksafe

log = logging.getLogger("sidenote.transcriber")


class NullTranscriber:
    """No-op backend: audio is buffered but never transcribed."""

    available = False

    def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str:
        return ""


LANGS = ("ko", "en")  # speech languages the tool supports

# Whisper decides the language from the utterance in front of it, and a short one does not hold
# enough of it. Measured on 126 spans cut out of real recordings: 32 of the 108 Korean
# ones were read as English, while not one of the 18 English ones was read as Korean. English is
# where it lands when a clip is too short to tell. The confidence it hands back does not mark the
# wrong ones (median p(en) 0.96 on them); length does (15 of 42 spans of 0.8 s wrong against 6 of 42
# of 2 s); and deciding by which language the decoder scores the sound higher is worse still (38 of
# 126 wrong, because an English reading of Korean speech comes back as a confident stock phrase).
#
# So the session votes: each utterance adds its length times the odds Whisper gave each language to
# a decayed vote, and an utterance read as English while the session has been speaking Korean is
# decoded again as Korean. Only that direction. Letting the vote push Korean into English as well
# was measured and is worse than doing nothing: over one sitting it turned 12 utterances back to
# Korean but pushed 8 Korean ones into English, where Whisper writes down things nobody said
# ("Thank you for watching. Have a nice weekend." for small talk about the weather).
#
# Measured over one sitting that goes Korean, then English, then Korean again, which is the hardest
# case for this because the English part is spoken into a Korean vote: 32 of 126 read as the wrong
# language without it, 16 with. Korean read as English 32 -> 14, English read as Korean 0 -> 2 (one
# of those two came back in English anyway, the other came back empty). The wrong ones long enough
# to be sent on as a question, which is what costs an answer nobody asked for: 19 -> 12. The second
# decode it sometimes needs costs 4 ms on a median utterance of 1270.
#
# Those spans were all 2 s or shorter. A whole sentence is another matter, and Whisper can tell it: of 73 English sentences read by
# people, held to Korean 30 came back in Korean with what was said lost, 12 of them as one phrase over and over, while each had
# p(en) of 0.97 or more (0.94 or more over its first 3 s). Of 457 Korean ones, clean and with noise over a phone's band, cut from
# 3 s up to the whole, 13 of 1830 were read as English and none of those reached 0.6, where at 2 s one reached 0.9. So what is at
# least HOLD_SEC long and that sure stays as it sounds.
#
# Pinning the language in the panel remains the whole fix; this is for `auto`.
VOTE_MIN = 1.0      # seconds of evidence (length x odds) before the vote decides anything
VOTE_SHARE = 0.6    # how much of the vote the leading language needs
VOTE_DECAY = 0.7    # per utterance: the vote remembers about the last three, so somebody who
                    # switches language is followed instead of overruled for the next ten
VOTE_TOWARDS = "ko"  # the one language the vote may move an utterance to
HOLD_SEC = 3.0       # an utterance this long is held to the vote only when Whisper is not sure of it: shorter ones it can be wrong about
HOLD_SURE = 0.8      # the odds that count as sure, between the Korean misread at 0.6 at most and the English at 0.94 at least
HELD_SENTENCE_SEC = 12.0   # as long as a sentence is: decoded once when the vote holds it to Korean

# The live line is read from whatever the last seconds hold, a sentence cut off in mid-word among it. A few cuts send Whisper
# round on one sound ("the database kept ffffffff") to the limit of its tokens, and with its retries at each higher
# temperature one pass took 26 s of a quiet CPU and 67 s of a busy one. The utterances wait behind it in the same loop, and
# what was said meanwhile fell out of the tail, a question among it. So this reading gets no retries, and no more tokens
# than speech makes, which ends the same pass in 5 s. Fast Korean is about 14 tokens a second.
LIVE_TOKENS_PER_SEC = 15
LIVE_TOKENS_MAX = 200    # with the longest prompt (PROMPT_TOKENS) Whisper's 448 leaves about this; asked for more it raises an error
LOOP_RATIO = 2.4         # the compression ratio over which Whisper itself calls a text a loop, and would try again
LOOP_RE = re.compile(r"(\S.{0,11}?)\1{4,}", re.S)   # a piece of up to 12 characters, five times running or more

# What Whisper writes when it is given near silence. Heard here every few seconds with nothing but
# room noise ("Thank you." over and over), which filled the live transcript and the
# log with words nobody said. Only a whole transcription that is one of these is dropped; the same
# words inside a real sentence are left alone.
FILLER = {
    "thank you", "thank you.", "thanks for watching", "thanks for watching!", "thank you for watching",
    "you", "bye", "bye.", "please subscribe", "subscribe to my channel", "작은 소리", "음악",
    "감사합니다", "감사합니다.", "시청해주셔서 감사합니다", "구독과 좋아요 부탁드립니다", "다음 영상에서 만나요",
    "자막 제공 배달의민족", "mbc 뉴스", "시청해 주셔서 감사합니다",
}


def filler(text: str) -> bool:
    """The whole of what was heard is one of Whisper's stock phrases for silence."""
    t = " ".join(text.lower().split()).strip(" .!?~…\"'")
    return bool(t) and (t in FILLER or t.rstrip(".") in FILLER)


# Whisper keeps the last 223 tokens of the text it is given before the audio: half its 448-token context, less one
# (faster_whisper's WhisperModel.get_prompt). A longer prompt loses its beginning, which is where a person's own words
# go, so the prompt is cut to this before it is handed over, from its end.
PROMPT_TOKENS = 223


def unlooped(segment) -> str:
    """A segment's words without the sound Whisper went round on, for a reading that does not try again."""
    text = segment.text.strip()
    if getattr(segment, "compression_ratio", 0.0) <= LOOP_RATIO:
        return text
    loop = LOOP_RE.search(text)
    return text[:loop.start()].strip() if loop else text


def hint_words(hint) -> dict:
    """The hint as {language: text}: one text serves both languages, a dict is taken as it is, nothing is no hint."""
    if isinstance(hint, dict):
        return {lang: str(text) for lang, text in hint.items() if text}
    return {lang: str(hint) for lang in LANGS} if hint else {}


class FasterWhisperTranscriber:
    """faster-whisper backend. Expects 16-bit mono PCM.

    language: "ko" | "en" pins the speech language; "auto" detects it but only between
    Korean and English: plain auto-detect can call a short clip Japanese or Chinese,
    so a detection outside those two is redone with the likelier of ko/en, and a session
    that has been speaking Korean has an utterance read as English decoded as Korean
    (VOTE_TOWARDS above). It is settable at runtime so the panel can switch it, and
    switching clears the vote.
    """

    available = True

    def __init__(self, model_size: str = "base", compute_type: str = "int8", language: str = "auto",
                 hint: str | dict = "", cpu_threads: int = 4):
        # Lazy, heavy imports kept inside so the module import stays cheap.
        import numpy  # noqa: F401  (validated here, used in transcribe)
        from faster_whisper import WhisperModel, download_model

        self._np = numpy
        self._language = language if language in LANGS else "auto"
        self._vote = {l: 0.0 for l in LANGS}   # the session's evidence for each language
        self.voted = ""              # the language the vote settled on, "" while it is undecided
        self.last_language = ""      # what the last transcription was decoded as
        # Technical words Whisper otherwise mishears, given as the previous text: a list for each language, so
        # English speech is primed with English spellings and Korean speech with the way Korean writes them
        self.hints = hint_words(hint)
        self.extra: list[str] = []   # the person's own words (Extra terms), ahead of the built-in ones
        self._prompts: dict = {}     # the prompt for each language, built once per change (prompt())
        log.info("loading faster-whisper model=%s compute=%s lang=%s threads=%s",
                 model_size, compute_type, self.language, cpu_threads)
        # cpu_threads: without it CTranslate2 decodes on every core the container has, which is
        # the lag the tool is supposed to save the user. num_workers 1: one utterance at a time.
        # Fetched first, outside the spawn lock: a first download takes minutes, and the model in use and every agent's
        # process would wait on that lock for as long.
        where = model_size if os.path.isdir(model_size) else download_model(model_size)
        # Built under the spawn lock: it loads in the background now, beside the CLI checks and the analyses, and its
        # int8 conversion can run in a native parallel region, which a fork must not meet (forksafe.py)
        with forksafe.native_work():
            self._model = WhisperModel(where, device="cpu", compute_type=compute_type,
                                       cpu_threads=max(1, int(cpu_threads)), num_workers=1)

    @property
    def language(self) -> str:
        return self._language

    @language.setter
    def language(self, value: str) -> None:
        """Set by the panel while the tool runs. A new choice starts the vote over: what was heard
        under the old one says nothing about the new, and leaving it would carry a Korean session's
        vote into a decode the user has just pinned to English and back."""
        self._language = value if value in LANGS else "auto"
        self._vote = {l: 0.0 for l in LANGS}
        self.voted = ""

    def set_hints(self, hint, extra=()) -> None:
        """The built-in hint ({language: text}, a text for both, or nothing to switch it off) and the person's own
        words, from the panel's settings. The prompts are built again at the next decode."""
        self.hints = hint_words(hint)
        self.extra = [w.strip() for w in extra if isinstance(w, str) and w.strip()]
        self._prompts = {}

    def _tokens(self, text: str) -> int:
        """How many tokens Whisper counts for `text`, as it encodes a prompt (a space before it)."""
        tok = getattr(getattr(self, "_model", None), "hf_tokenizer", None)
        if tok is None:
            return len(text)   # one a character: never fewer than Whisper's own count for these words
        return len(tok.encode(" " + text, add_special_tokens=False).ids)

    def prompt(self, lang: str) -> str | None:
        """What Whisper is given before the audio for a decode in `lang`: the person's own words, then the built-in
        ones for that language, cut from the end to the tokens Whisper keeps. None when there is nothing to give."""
        if lang in self._prompts:
            return self._prompts[lang]
        # each word on its own, so a cut never splits one, and the person's first: those are the last to go here. In an
        # utterance over 30 s Whisper's later windows also take its own text before these, which goes before all of them
        words = self.extra + [w.strip() for w in self.hints.get(lang, "").rstrip(".").split(",") if w.strip()]
        text = ", ".join(words)
        while words and self._tokens(text + ".") > PROMPT_TOKENS:
            words.pop()                    # the last of the built-in words first, then the person's own last ones
            text = ", ".join(words)
        if len(words) < len(self.extra):   # the person's words alone did not fit: said once per change
            log.warning("speech hint: %d of the %d extra terms fit in what Whisper keeps", len(words), len(self.extra))
        self._prompts[lang] = (text + ".") if text else None   # ended as a sentence, as the hint was measured
        return self._prompts[lang]

    def _decide(self) -> str:
        """The language the session has voted for, or "" while too little has been heard."""
        total = sum(self._vote.values())
        if total < VOTE_MIN:
            return ""
        lead = max(LANGS, key=self._vote.get)
        return lead if self._vote[lead] / total >= VOTE_SHARE else ""

    def _count(self, probs: dict, seconds: float) -> None:
        """Add one utterance to the vote: its length times the odds Whisper gave each language, so a
        half-second guess weighs a fraction of what a long sentence does."""
        for lang in LANGS:
            self._vote[lang] = self._vote[lang] * VOTE_DECAY + seconds * float(probs.get(lang, 0.0))
        settled = self._decide()
        if settled and settled != self.voted:
            log.info("speech language settled on %s (vote ko %.1f / en %.1f)", settled,
                     self._vote["ko"], self._vote["en"])
        self.voted = settled

    def _audio(self, pcm_bytes: bytes, sample_rate: int):
        """16-bit mono PCM -> float32 at 16 kHz (what faster-whisper and its VAD want)."""
        if not pcm_bytes:
            return None
        audio = self._np.frombuffer(pcm_bytes, dtype=self._np.int16).astype(self._np.float32) / 32768.0
        if sample_rate != 16000:
            # cheap linear resample is fine here
            ratio = 16000 / float(sample_rate)
            n_out = int(len(audio) * ratio)
            if n_out <= 0:
                return None
            audio = audio[(self._np.arange(n_out) / ratio).astype(self._np.int64)]
        return audio

    def speech_segments(self, pcm_bytes: bytes, sample_rate: int) -> list[tuple[int, int]]:
        """Silero VAD over 16-bit mono PCM -> [(start, end)] speech spans, in samples of
        the input rate. Fine-grained (short silence/pad) so utterance ends are accurate."""
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        audio = self._audio(pcm_bytes, sample_rate)
        if audio is None:
            return []
        k = sample_rate / 16000.0
        opts = VadOptions(min_silence_duration_ms=300, speech_pad_ms=100)
        with forksafe.native_work():
            spans = get_speech_timestamps(audio, opts)
        return [(int(s["start"] * k), int(s["end"] * k)) for s in spans]

    def transcribe_live(self, pcm_bytes: bytes, sample_rate: int) -> str:
        """The words on the panel's live line, read quickly from the last seconds of sound: no retries and no more tokens
        than speech makes (LIVE_TOKENS_PER_SEC). In whatever language they sound like, where an utterance is held to the
        vote: a window of steady English held to Korean took 14 s for words no use to anyone, and a window is long enough
        for its language to be told."""
        return self.transcribe(pcm_bytes, sample_rate, live=True)

    def transcribe(self, pcm_bytes: bytes, sample_rate: int, live: bool = False) -> str:
        audio = self._audio(pcm_bytes, sample_rate)
        if audio is None:
            return ""
        lang = self._language if self._language in LANGS else None
        seconds = len(audio) / 16000.0
        quick = {}
        held = False
        if live:
            quick = {"temperature": 0.0, "max_new_tokens": min(LIVE_TOKENS_MAX, int(LIVE_TOKENS_PER_SEC * seconds) + 16)}
        # The hint is chosen by the language the decode runs in, and on auto that is known only once the language
        # is detected: the first call is given the hint of the language this session most likely speaks, and is
        # asked again with the right one when the utterance turns out to be in the other
        first = lang or self.voted or self.last_language or LANGS[0]
        # The lock keeps a fork() out of the decode (server/forksafe.py). It covers the reading of
        # the segments too: transcribe() settles the language up front and decodes lazily while
        # they are read, so a rejected auto pick costs a detection pass, not a decode.
        with forksafe.native_work():
            segments, info = self._model.transcribe(audio, language=lang, vad_filter=True,
                                                    initial_prompt=self.prompt(first), **quick)
            if lang is None:
                probs = dict(info.all_language_probs or [])
                # Whichever of the two this utterance looks like on its own, then what the session has
                # voted for. The vote is counted from the odds, not from the decision, so an utterance
                # decoded against it still says what it sounded like.
                pick = info.language if info.language in LANGS else max(LANGS, key=lambda l: probs.get(l, 0.0))
                if not live and self.voted == VOTE_TOWARDS and pick != VOTE_TOWARDS \
                        and (seconds < HOLD_SEC or probs.get(pick, 0.0) < HOLD_SURE):
                    pick = self.voted
                # Counted after, so it never votes on itself; an utterance only (DECISIONS note 12). The live line reads the same
                # 15 s window every 2 s, so it counted that sound about seven times, and one short remark misread as English
                # turned a Korean vote
                if not live:
                    self._count(probs, seconds)
                # Asked again in the language picked, or with that language's hint: nothing has been decoded yet, and
                # a call with the language given detects nothing, so the second call adds no decode and no detection
                if pick != info.language or self.prompt(pick) != self.prompt(first):
                    # Held to Korean against what it sounds like, a sentence reads as poor text and Whisper tries it again
                    # at each higher temperature: English of 5 s took 5 to 8 s to come to the words the first try wrote in
                    # 1 s. Longer speech goes round on one phrase at that first try, so the retries stay for it.
                    held = pick != info.language and seconds <= HELD_SENTENCE_SEC
                    segments, info = self._model.transcribe(audio, language=pick, vad_filter=True, initial_prompt=self.prompt(pick),
                                                            **(quick or ({"temperature": 0.0} if held else {})))
            # With no retries a reading may go round on one sound or phrase, which is nothing anyone said
            text = " ".join((unlooped(seg) if live or held else seg.text.strip()) for seg in segments).strip()
        self.last_language = info.language
        if filler(text):
            log.debug("dropped a stock phrase from silence: %r", text)
            return ""
        return text


class UtteranceTracker:
    """Cut a live audio stream into utterances, from VAD spans over its recent tail.

    Positions are absolute sample counts since the stream began, so spans found in
    successive passes over a sliding tail line up. An utterance opens at the first
    speech after the previous one closed and closes at a pause of `end_silence` s --
    found between spans inside the tail, so a pass that runs late (a busy CPU) still
    sees the pause instead of fusing two utterances, or when it reaches `max_len` s
    (continuing speech then carries on in the next one).
    """

    def __init__(self, sample_rate: int, end_silence: float, max_len: float):
        self.end_gap = int(sample_rate * end_silence)
        self.max_len = int(sample_rate * max_len)
        self.jitter = int(sample_rate * 0.3)   # VAD edges wobble between passes over a moving tail
        self.start: int | None = None   # open utterance's first speech sample
        self.last: int | None = None    # latest speech sample heard in it
        self.closed_at = 0              # end of the last closed utterance
        self.split = False              # last close was a max_len cut in mid-speech

    def update(self, spans: list[tuple[int, int]], now: int) -> list[tuple[int, int]]:
        """spans: absolute (start, end) speech spans in the recent tail, in order; now:
        samples received so far. Returns the (start, end) of utterances that closed."""
        done = []
        for s, e in spans:
            if e <= self.closed_at + self.jitter:
                continue                 # speech of a closed utterance (edges wobble)
            if s < self.closed_at:
                if not self.split:
                    continue             # straddles a pause we already closed on: old speech
                s = self.closed_at       # a max_len cut: carry on from the cut
            if self.start is not None and s - self.last >= self.end_gap:
                done.append(self._close(split=False))   # a full pause inside the tail
            if self.start is None:
                self.start, self.split = s, False
            self.last = max(self.last or 0, e)
        if self.start is not None:
            if now - self.last >= self.end_gap:
                done.append(self._close(split=False))
            elif self.last - self.start >= self.max_len:
                done.append(self._close(split=True))
        return done

    def _close(self, split: bool) -> tuple[int, int]:
        done = (self.start, self.last)
        self.closed_at, self.start, self.last, self.split = self.last, None, None, split
        return done

    def flush(self) -> tuple[int, int] | None:
        """Close the open utterance now (e.g. the audio stopped arriving)."""
        return self._close(split=False) if self.start is not None else None


def make_transcriber(cfg, model: str = "") -> "NullTranscriber | FasterWhisperTranscriber":
    """The speech model: `model` when it is named (the panel's choice), else the one the environment names. One not
    downloaded yet is fetched by faster-whisper on the way."""
    if not cfg.audio_enabled or cfg.transcriber == "null":
        return NullTranscriber()
    if cfg.transcriber in ("auto", "faster-whisper"):
        try:
            return FasterWhisperTranscriber(model or cfg.whisper_model, cfg.whisper_compute, cfg.speech_lang,
                                            cfg.whisper_hint, getattr(cfg, "whisper_threads", 4))
        except Exception as exc:  # pragma: no cover - env dependent
            if cfg.transcriber == "faster-whisper":
                raise
            log.warning("faster-whisper unavailable (%s); transcription disabled", exc)
            return NullTranscriber()
    return NullTranscriber()
