"""Audio transcription backends.

The core pipeline runs without any speech dependency (NullTranscriber). Install
server/requirements-audio.txt to enable faster-whisper; "auto" picks it up.
Transcription is CPU-bound, so callers run .transcribe() in a thread executor.
"""
from __future__ import annotations

import logging

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
# Pinning the language in the panel remains the whole fix; this is for `auto`.
VOTE_MIN = 1.0      # seconds of evidence (length x odds) before the vote decides anything
VOTE_SHARE = 0.6    # how much of the vote the leading language needs
VOTE_DECAY = 0.7    # per utterance: the vote remembers about the last three, so somebody who
                    # switches language is followed instead of overruled for the next ten
VOTE_TOWARDS = "ko"  # the one language the vote may move an utterance to

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
                 hint: str = "", cpu_threads: int = 4):
        # Lazy, heavy imports kept inside so the module import stays cheap.
        import numpy  # noqa: F401  (validated here, used in transcribe)
        from faster_whisper import WhisperModel

        self._np = numpy
        self._language = language if language in LANGS else "auto"
        self._vote = {l: 0.0 for l in LANGS}   # the session's evidence for each language
        self.voted = ""              # the language the vote settled on, "" while it is undecided
        self.last_language = ""      # what the last transcription was decoded as
        # Technical words Whisper otherwise mishears in Korean speech, given as the previous text.
        self.hint = hint or None
        log.info("loading faster-whisper model=%s compute=%s lang=%s threads=%s",
                 model_size, compute_type, self.language, cpu_threads)
        # cpu_threads: without it CTranslate2 decodes on every core the container has, which is
        # the lag the tool is supposed to save the user. num_workers 1: one utterance at a time.
        # Built under the spawn lock: it loads in the background now, beside the CLI checks and the analyses, and its
        # int8 conversion can run in a native parallel region, which a fork must not meet (forksafe.py)
        with forksafe.native_work():
            self._model = WhisperModel(model_size, device="cpu", compute_type=compute_type,
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

    def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str:
        audio = self._audio(pcm_bytes, sample_rate)
        if audio is None:
            return ""
        lang = self._language if self._language in LANGS else None
        # The lock keeps a fork() out of the decode (server/forksafe.py). It covers the reading of
        # the segments too: transcribe() settles the language up front and decodes lazily while
        # they are read, so a rejected auto pick costs a detection pass, not a decode.
        with forksafe.native_work():
            segments, info = self._model.transcribe(audio, language=lang, vad_filter=True, initial_prompt=self.hint)
            if lang is None:
                probs = dict(info.all_language_probs or [])
                # Whichever of the two this utterance looks like on its own, then what the session has
                # voted for. The vote is counted from the odds, not from the decision, so an utterance
                # decoded against it still says what it sounded like.
                pick = info.language if info.language in LANGS else max(LANGS, key=lambda l: probs.get(l, 0.0))
                if self.voted == VOTE_TOWARDS and pick != VOTE_TOWARDS:
                    pick = self.voted
                self._count(probs, len(audio) / 16000.0)   # counted after, so it never votes on itself
                if pick != info.language:
                    segments, info = self._model.transcribe(audio, language=pick, vad_filter=True,
                                                            initial_prompt=self.hint)
            text = " ".join(seg.text.strip() for seg in segments).strip()
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


def make_transcriber(cfg) -> "NullTranscriber | FasterWhisperTranscriber":
    if not cfg.audio_enabled or cfg.transcriber == "null":
        return NullTranscriber()
    if cfg.transcriber in ("auto", "faster-whisper"):
        try:
            return FasterWhisperTranscriber(cfg.whisper_model, cfg.whisper_compute, cfg.speech_lang,
                                            cfg.whisper_hint, getattr(cfg, "whisper_threads", 4))
        except Exception as exc:  # pragma: no cover - env dependent
            if cfg.transcriber == "faster-whisper":
                raise
            log.warning("faster-whisper unavailable (%s); transcription disabled", exc)
            return NullTranscriber()
    return NullTranscriber()
