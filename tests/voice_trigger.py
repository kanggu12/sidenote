"""What counts as a problem read aloud, and what is only the room's sound.

    SIDENOTE_ANALYZER=mock .venv/bin/python tests/voice_trigger.py

The microphone records the loopback of the speakers, so most of what arrives is whatever the PC is
playing. Two things in the voice path turned that into work:

  - the VAD opens an utterance on a blip, and Whisper does not come back empty-handed from one. Of
    the 313 utterances of one day, 178 were under 0.8 s and 172 of those came back as English on
    a Korean speaker's machine, one of them 70 characters from 0.3 s of sound.
  - the question-word test read the whole of recent_speech(), up to two minutes of what was heard,
    so one "why" in a video's dialogue made every sentence after it queue a problem of its own: 43 of
    them in one hour, against two answers worth reading.

The real _voice_pass runs here against a stub transcriber: the checks say where the speech is and
what it says, and read back what the worker was handed.
"""
import asyncio
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("SIDENOTE_ANALYZER", "mock")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the repository: this file is in tests/

from server import app as A                      # noqa: E402
from server.transcriber import UtteranceTracker   # noqa: E402

SR = 16000
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok " if cond else "FAIL ") + name + (f"  - {detail}" if detail and not cond else ""))


class Stub:
    """A transcriber that hears exactly what a check tells it to.

    `spans` is where the speech is, in seconds from the start of the stream; `said` is what each of
    those spans says, in the same order. Every transcribe() is recorded, so a check can tell that a
    blip was dropped before it ever reached this point, which is where the work would have gone."""

    available = True
    last_language = "ko"

    def __init__(self):
        self.spans = []     # [(start_sec, end_sec)] of speech in the stream
        self.said = {}      # start_sec -> what that span says
        self.asked = []     # (seconds, text) for every span that was actually transcribed

    def speech_segments(self, tail, sr):
        # The pass hands over the end of the buffer and then adds back where that tail begins, so
        # what belongs here is positions inside the tail, not inside the stream. Returning stream
        # positions reads correctly only while the whole stream still fits in the tail, which is how
        # this stub hid three of four sentences the first time it was written.
        off = A.STATE.audio_total // 2 - len(tail) // 2
        return [(int(s * sr) - off, int(e * sr) - off) for s, e in self.spans]

    def transcribe(self, pcm, sr):
        secs = len(pcm) / 2 / sr
        # Which span this is: the one whose length matches what was handed over.
        for s, e in self.spans:
            if abs((e - s) - secs) < 0.05:
                self.asked.append((round(secs, 2), self.said.get(s, "")))
                return self.said.get(s, "")
        self.asked.append((round(secs, 2), "?"))
        return ""


def fresh_state(seconds=10.0):
    """A clean state with `seconds` of audio in the buffer and nothing heard yet."""
    A.STATE.__init__()
    A.STATE.audio_sr = SR
    A.STATE.push_audio(b"\0\0" * int(SR * seconds), SR)
    A.broadcast = lambda msg: asyncio.sleep(0)
    return UtteranceTracker(SR, A.CONFIG.utter_end_silence, A.CONFIG.utter_max_sec)


async def heard(stub, tracker, spans, said, upto):
    """Run one speech pass: `spans` is where the speech is, `said` what it says, `upto` how much
    audio has arrived by now (an utterance closes on the silence after it)."""
    stub.spans, stub.said = spans, said
    have = A.STATE.audio_total // 2 / SR
    if upto > have:
        A.STATE.push_audio(b"\0\0" * int(SR * (upto - have)), SR)
    await A._voice_pass(stub, tracker, asyncio.get_running_loop(), True)


async def case_a_blip_is_not_speech():
    """A VAD blip never reaches the transcriber, so it cannot be written into a sentence."""
    stub, tracker = Stub(), fresh_state()
    await heard(stub, tracker, [(2.0, 2.3)], {2.0: "Thank you for watching this video."}, upto=10.0)
    check("a 0.3 s blip is never transcribed", stub.asked == [], f"{stub.asked}")
    check("and leaves no utterance behind", A.STATE.utterances == [], f"{A.STATE.utterances}")
    check("and queues no problem", A.STATE.voice_pending is False)

    await heard(stub, tracker, [(4.0, 6.5)], {4.0: "이 문제 어떻게 푸는지 알려 줘"}, upto=12.0)
    check("2.5 s of speech is transcribed", len(stub.asked) == 1, f"{stub.asked}")
    check("and queues the problem", A.STATE.voice_pending is True)


async def case_a_video_question_does_not_stick():
    """A question word in the video's dialogue does not make every sentence after it a problem."""
    stub, tracker = Stub(), fresh_state()
    await heard(stub, tracker, [(2.0, 5.0)], {2.0: "그래서 이게 왜 중요한 걸까요 여러분"}, upto=10.0)
    check("the sentence that asks something is taken as a problem", A.STATE.voice_pending is True,
          "the dialogue asked a question; it is answered once and that is not the defect")

    A.STATE.voice_pending = False          # the worker took it
    # The dialogue carries on after a pause longer than speech_group_gap: its own spoken problem,
    # and nothing in it asks anything.
    gap = A.CONFIG.speech_group_gap + 3
    await heard(stub, tracker, [(5.0 + gap, 8.0 + gap)], {5.0 + gap: "다음 시간에는 이것을 더 자세히 보겠습니다"},
                upto=13.0 + gap)
    check("a sentence of its own with nothing asked in it is not a problem",
          A.STATE.voice_pending is False, "the question word two sentences ago used to carry here")
    check("it only waits for the speaker to stop", A.STATE.voice_waiting is True)
    check("and both sentences were heard", len(A.STATE.utterances) == 2, f"{A.STATE.utterances}")


async def case_one_run_of_speech_cannot_queue_for_ever():
    """A video's dialogue is one unbroken group: it starts a few analyses, not one per sentence."""
    stub, tracker = Stub(), fresh_state()
    tries = A.CONFIG.speech_group_tries
    queued, at = 0, 2.0
    # Sentences three seconds long, two seconds apart: under speech_group_gap, so one group
    # throughout, and the first of them asks something the way a narrator does.
    for i in range(tries + 4):
        said = "그러면 이게 왜 이렇게 되는 걸까요" if i == 0 else f"그래서 {i} 번째 이야기를 이어서 하겠습니다"
        await heard(stub, tracker, [(at, at + 3.0)], {at: said}, upto=at + 8.0)
        queued += 1 if A.STATE.voice_pending else 0
        A.STATE.voice_pending = False      # the worker takes each one as it is queued
        at += 8.0 - 3.0 + 3.0              # the next sentence, within speech_group_gap of this one
    check(f"one unbroken group queues at most {tries}", queued == tries, f"queued {queued}")
    check("every sentence was still heard", len(A.STATE.utterances) == tries + 4,
          f"{len(A.STATE.utterances)}")
    check("and what is still being read waits for the speaker to stop",
          A.STATE.voice_waiting is True)


async def case_a_problem_read_in_several_sentences():
    """The sentences after the question word extend the same problem, until the speaker stops."""
    stub, tracker = Stub(), fresh_state()
    await heard(stub, tracker, [(2.0, 5.0)], {2.0: "다음 중 옳은 것을 고르시오"}, upto=10.0)
    check("the question is queued", A.STATE.voice_pending is True)

    A.STATE.voice_pending = False           # the worker started on the shorter version
    # The next sentence follows within speech_group_gap: the same problem, read further.
    await heard(stub, tracker, [(11.0, 14.0)], {11.0: "첫째 보기는 리스트의 길이가 n 일 때"}, upto=18.0)
    check("the sentence that follows it extends the same problem", A.STATE.voice_pending is True,
          f"asked={A.STATE.voice_asked}")

    A.STATE.voice_pending = False
    # And now a pause longer than speech_group_gap: whatever is said next is its own.
    gap = A.CONFIG.speech_group_gap + 3
    await heard(stub, tracker, [(18.0 + gap, 21.0 + gap)], {18.0 + gap: "그 부분은 저도 잘 모르겠네요"},
                upto=26.0 + gap)
    check("after a pause the question word no longer carries", A.STATE.voice_pending is False,
          f"asked={A.STATE.voice_asked}")


async def case_silence_is_never_written_down():
    """Nobody is speaking: the live window is not handed to the transcriber at all.

    This is the loop's whole cost. Writing down transcript_window_sec of silence takes 2.30 s of
    CPU every transcribe_interval and comes back empty, which held 1.5 cores on a locked screen;
    the VAD answers the same question over the same audio in 0.016 s."""
    stub, tracker = Stub(), fresh_state(seconds=2.0)
    app = types.SimpleNamespace(state=types.SimpleNamespace(transcriber=stub))
    was = A.CONFIG.transcribe_interval
    A.CONFIG.transcribe_interval = 0.2
    stub.spans = []                            # the VAD hears nothing in the window
    task = asyncio.create_task(A.transcription_worker(app))
    for _ in range(5):                         # sound keeps arriving, which is what wakes each pass
        A.STATE.push_audio(b"\0\0" * int(SR * 0.2), SR)
        await asyncio.sleep(0.22)
    check("silence is never transcribed", stub.asked == [], f"{stub.asked}")
    check("and the live transcript stays empty", A.STATE.transcript == "", f"{A.STATE.transcript!r}")

    stub.spans, stub.said = [(1.0, 2.0)], {1.0: "이건 어떻게 푸는 거야"}   # now somebody speaks
    for _ in range(5):
        A.STATE.push_audio(b"\0\0" * int(SR * 0.2), SR)
        await asyncio.sleep(0.22)
    check("speech in the window is written down", any(t for _, t in stub.asked), f"{stub.asked}")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    A.CONFIG.transcribe_interval = was


async def case_asking_to_be_told_is_a_question():
    """Asking how many, or asking to be told, goes the moment the sentence ends; offering to tell waits."""
    for said, asks in (("도커 엔진 최신 버전이 몇이에요. 패치 버전까지 알려주세요.", True),
                       ("지금 파이썬 최신 버전 알려 줘", True),
                       ("이건 다음 시간에 자세히 알려 드릴게요 여러분", False)):
        stub, tracker = Stub(), fresh_state()
        await heard(stub, tracker, [(2.0, 6.0)], {2.0: said}, upto=10.0)
        check(f"{said!r}: {'queued at once' if asks else 'waits for the speaker to stop'}",
              A.STATE.voice_pending is asks and A.STATE.voice_waiting is (not asks),
              f"pending={A.STATE.voice_pending} waiting={A.STATE.voice_waiting}")


async def main():
    for case in (case_a_blip_is_not_speech, case_a_video_question_does_not_stick,
                 case_a_problem_read_in_several_sentences, case_one_run_of_speech_cannot_queue_for_ever,
                 case_silence_is_never_written_down, case_asking_to_be_told_is_a_question):
        print(case.__doc__.splitlines()[0])
        await case()
    print(f"\n  ==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
    if FAIL:
        print("FAILURES:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
