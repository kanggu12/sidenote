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
import time
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


# What is asked of the listener, what only sounds like it, and what is neither. All made up.
ASKED = ("보기 중 정답은 뭘까", "이 설정이 맞나", "List joins.", "Name three kinds of locks.", "Give me an example of a race.", "Solve this for x.",
         "Show me a merge.", "최댓값을 구하는 함수를 작성하시오.", "문자열을 출력하는 프로그램을 만드는 문제입니다.", "What is GTID?", "TCP와 UDP의 차이가 뭔가요?", "GTID가 뭔가요?", "Can you explain the difference between a process and a thread?",
         "So what is the difference between a mutex and a semaphore?", "and what about IPv6?", "what port does redis use by default",
         "how many bytes are in an ipv6 address", "Why is UDP faster than TCP?", "explain how a bloom filter works",
         "Could you walk me through a TLS handshake", "Write a function that reverses a list.", "Now, compare REST and gRPC.",
         "Question five. Which of these is not a property of a B-tree?", "true or false, a heap is always balanced",
         "Is Redis single threaded?", "Is this right?", "What is correct here?", "Does Python have a GIL?",
         "What does the CAP theorem say, you know?", "What is a deadlock, right?", "I was wondering, what is a race condition?",
         "I'm asking, what is a B+ tree?", "Let me ask you this. What is a segment tree?", "Tell me about garbage collection.",
         "레디스 기본 포트가 뭐예요", "도커랑 쿠버네티스 차이 좀 알려 주세요", "해시맵 시간 복잡도는 얼마인가요", "이 코드 출력이 뭐지", "인덱스는 왜 쓰는 거예요",
         "정규화가 뭐죠", "격리 수준은 뭐가 있죠?", "스택과 큐의 차이를 설명해 주세요.", "다음 중 옳은 것을 고르시오", "최댓값을 구하시오", "이 코드를 작성해 보세요",
         "트랜잭션이 뭔지 말씀해 주세요", "맞으면 O, 틀리면 X를 쓰세요", "TCP의 3-way handshake는 몇 단계인가요?", "그럼 왜 그런 걸까요?",
         "뭘 써야 하죠?", "가격이 얼마죠?", "어딜 고쳐야 하죠?", "메모리는 얼마나 필요하죠?", "설명해 주실 수 있나요?", "이 쿼리 설명해 봐", "최댓값을 구해 보세요",
         "If someone asked you to design a rate limiter, how would you do it?", "What is the most frequently asked question about Kubernetes?",
         "So, like, what is a pod?", "이게 뭔지 물어봐도 될까요?", "TCP랑 UDP 차이가 뭐냐고 묻는다면 어떻게 답할 건가요?")
TOLD = ("Is that right?", "Okay?", "So one restart costs us about nine minutes, right?", "The disk was full, you know?", "We kept the old index, okay?",
        "Then the pager went off, yeah?", "The certificate had expired, correct?", "That was the old cluster, isn't it?",
        "It writes to the log first, doesn't it?", "So that took two hours right?", "Right?", "You know?", "Does that make sense?", "Is that correct?",
        "The on-call engineer kept asking, was the disk full or did the replica fall behind?", "In the review somebody asked, could we have caught this?",
        "They were asking whether their data was safe?", "He was wondering how it got past the tests?",
        "And she said, why is it down?", "So he was like, what is this?", "Guess what?", "You know what?", "So what?", "And what happened next?",
        "So what did we do?", "Why did we pick Kafka?", "How did I fix it?", "What happened after that?",
        "그래서 사십 분쯤 걸렸어요, 그렇죠?", "서버가 또 죽었어요, 맞죠?", "다들 아시죠?", "그건 다 알죠?", "그렇죠?", "맞죠?", "알죠?", "서버가 죽었잖아요?", "아시겠어요?",
        "왜 카프카를 골랐냐고요?", "왜 그런지 물어보시길래 그래프를 보여 드렸어요?", "Sorry?", "Is it?", "Really?", "Pardon?", "He was like, what is this?")
NEITHER = ("출력하는 부분을 고쳤습니다.", "값을 구하는 함수를 짰습니다.", "반환하는 값이 없었어요.", "그러니까요.", "참고하세요.", "수고하세요.", "이게 맞나 싶었어요.",
           "List comprehensions were slow.", "Name resolution failed.", "Give up on that.", "We moved the whole team to GitHub Actions last year.", "That is why we moved to Postgres.", "So I had to write a small script to find the bad rows.",
           "We did not know what was going on.", "This is how we fixed it.", "It came back, which was a relief.", "What we did was drain the node first.",
           "What happened was the disk filled up.", "I will explain that later.", "We return the value and go on.",
           "My manager asked why the deploy had failed.", "디스크가 꽉 찬 거냐고 계속 물어보셨어요.",
           "작년에 깃허브 액션으로 옮겼어요.", "어느 날 서버가 죽었습니다.", "왜냐하면 디스크가 꽉 찼기 때문입니다.", "무엇보다 복제가 밀렸습니다.", "어떻게든 복구했습니다.",
           "안녕하세요 여러분.", "그래서 코드를 작성해서 배포했어요.", "제가 설명해 드릴게요.", "그게 뭐냐면 쓰기 전 로그입니다.",
           "로그를 찾아보니까 디스크가 꽉 찼어요.", "구현해보니까 생각보다 쉬웠습니다.", "계산해보면 열 배입니다.", "아까 말씀해주신 것처럼 재시작했어요.")


async def case_what_only_sounds_like_a_question():
    """A question asked of the listener starts at once; a tag, a reported question and a rhetorical one do not."""
    for said in ASKED:
        check(f"asks: {said!r}", A.question_kind(said) == "asked" and A.looks_like_question(said), A.question_kind(said))
    for said in TOLD:
        check(f"only sounds like it: {said!r}", A.question_kind(said) == "told" and not A.looks_like_question(said), A.question_kind(said))
    for said in NEITHER:
        check(f"neither: {said!r}", A.question_kind(said) == "" and not A.looks_like_question(said), A.question_kind(said))
    check("a sentence that asks after one that only sounds like it still asks",
          A.looks_like_question("So it took two hours, right? What is a better way to rebuild an index?"))
    check("a question that follows a long explanation still asks",
          A.looks_like_question("So that is how replication works. The primary writes the log and the replicas read it, you know? "
                                "Now, can you explain the difference between synchronous and asynchronous replication?"))
    check("and what is left of a sentence stays", A.asked_part("The disk was full, right?").startswith("The disk was full"), A.asked_part("The disk was full, right?"))
    # What Whisper writes runs through these on the event loop, and it can repeat itself for as long as an utterance lasts: 90 s
    # hold a few thousand characters at most
    for said in ("question " * 300 + "x", "so " * 1000 + "x", "right, " * 400, "what " * 600, "okay, so, and, " * 200 + "?", "뭐 " * 1500 + "?", ("a" * 3000) + "?", "well, " * 500 + "what"):
        began = time.perf_counter()
        A.question_kind(said)
        check(f"the patterns take no time on {said[:18]!r}... however it repeats itself", time.perf_counter() - began < 0.5, f"{time.perf_counter() - began:.2f}s")

    # through the speech pass: a tag does not start an analysis at once, it waits for the speaker to stop as any remark does
    stub, tracker = Stub(), fresh_state()
    await heard(stub, tracker, [(2.0, 5.0)], {2.0: "So one restart costs us about nine minutes, right?"}, upto=10.0)
    check("a tag question starts nothing at once", A.STATE.voice_pending is False and A.STATE.voice_asked is False, A.STATE.voice_pending)
    check("and only waits for the speaker to stop", A.STATE.voice_waiting is True)
    stub, tracker = Stub(), fresh_state()
    await heard(stub, tracker, [(2.0, 5.0)], {2.0: "The on-call engineer kept asking, was the disk full or did the replica fall behind?"}, upto=10.0)
    check("nor does a question the speaker reports", A.STATE.voice_pending is False and A.STATE.voice_waiting is True)
    stub, tracker = Stub(), fresh_state()
    await heard(stub, tracker, [(2.0, 5.0)], {2.0: "What is GTID and why would I turn it on?"}, upto=10.0)
    check("a real one starts at once", A.STATE.voice_pending is True)


async def case_short_questions_and_what_is_not_taken():
    """A short question is taken; a sentence too short to be one is said on the panel, not dropped in silence."""
    said = []
    ok_len = A.CONFIG.speech_question_chars
    check("a closed sentence that looks like a question is taken from 6 characters, by default", ok_len == 6, ok_len)

    def listening():
        said.clear()

        async def tell(msg):
            said.append(msg)
        A.broadcast = tell
    stub, tracker = Stub(), fresh_state()
    listening()
    await heard(stub, tracker, [(2.0, 4.0)], {2.0: "GTID가 뭔가요?"}, upto=10.0)
    check("'GTID가 뭔가요?', under the limit for a remark, is taken", A.STATE.voice_pending is True and [u["text"] for u in A.STATE.utterances] == ["GTID가 뭔가요?"], A.STATE.utterances)
    check("...and the panel is told nothing is wrong with it", [m.get("why") for m in said if m["type"] == "utterance"] == [None], said)
    stub, tracker = Stub(), fresh_state()
    listening()
    await heard(stub, tracker, [(2.0, 4.0)], {2.0: "What's TCP?"}, upto=10.0)
    check("so is 'What's TCP?'", A.STATE.voice_pending is True)
    stub, tracker = Stub(), fresh_state()
    listening()
    await heard(stub, tracker, [(2.0, 4.0)], {2.0: "정답은 뭘까"}, upto=10.0)
    check("so is '정답은 뭘까', with no question mark, which has no pause to go at", A.STATE.voice_pending is True and [m.get("why") for m in said if m["type"] == "utterance"] == [None], said)
    stub, tracker = Stub(), fresh_state()
    listening()
    await heard(stub, tracker, [(2.0, 4.0)], {2.0: "뭐야?"}, upto=10.0)
    check("under 6 characters even a question is not", A.STATE.voice_pending is False and A.STATE.utterances == [], A.STATE.utterances)
    check("...and the panel is told it was too short, with its words", [(m["text"], m["why"]) for m in said if m["type"] == "utterance"] == [("뭐야?", "short")], said)
    stub, tracker = Stub(), fresh_state()
    listening()
    await heard(stub, tracker, [(2.0, 4.0)], {2.0: "그렇군요 네"}, upto=10.0)
    check("a remark under the limit is not taken", A.STATE.voice_pending is False and A.STATE.voice_waiting is False and A.STATE.utterances == [])
    check("...and the panel is told", [m.get("why") for m in said if m["type"] == "utterance"] == ["short"], said)
    stub, tracker = Stub(), fresh_state()
    listening()
    await heard(stub, tracker, [(2.0, 4.0)], {2.0: "Yes, right?"}, upto=10.0)
    check("a tag under the limit for a remark is a remark", A.STATE.voice_pending is False and [m.get("why") for m in said if m["type"] == "utterance"] == ["short"], said)
    stub, tracker = Stub(), fresh_state()
    listening()
    await heard(stub, tracker, [(2.0, 5.0)], {2.0: "We moved the whole team to GitHub Actions last year."}, upto=10.0)
    check("a long remark has no note yet: it waits for the first pass", [m.get("why") for m in said if m["type"] == "utterance"] == [None] and A.STATE.voice_waiting is True, said)
    stub, tracker = Stub(), fresh_state()
    listening()
    await heard(stub, tracker, [(2.0, 4.0)], {2.0: ""}, upto=10.0)
    check("a sentence that came back empty is nothing to say", said == [], said)
    was = A.SETTINGS.values.get("voice_auto")
    A.SETTINGS.values["voice_auto"] = False
    stub, tracker = Stub(), fresh_state()
    listening()
    await heard(stub, tracker, [(2.0, 4.0)], {2.0: "짧아요"}, upto=10.0)
    A.SETTINGS.values["voice_auto"] = was
    check("with Solve spoken problems off the card says that already: nothing is noted", said == [], said)
    A.broadcast = lambda msg: asyncio.sleep(0)


async def case_sound_too_short_to_write_down():
    """Sound too short to write down can stand on the card all the same: the live pass wrote it, and it says so."""
    said = []

    async def noted(msg):
        said.append((msg.get("text"), msg.get("why")))

    def anew():
        said.clear()
        tracker = fresh_state()
        A.broadcast = noted
        return Stub(), tracker

    stub, tracker = anew()
    A.STATE.transcript = "그렇군요."
    await heard(stub, tracker, [(2.0, 2.6)], {}, upto=10.0)
    check("the words the live pass wrote of it say it was too short", said == [("그렇군요.", "short")], said)
    check("...and it is still not transcribed", stub.asked == [], stub.asked)
    check("...and nothing is queued", A.STATE.voice_pending is False)
    await heard(stub, tracker, [(11.0, 11.4)], {}, upto=15.0)
    check("a second one says nothing more about it", len(said) == 1, said)

    stub, tracker = anew()
    await heard(stub, tracker, [(2.0, 4.0)], {2.0: "GTID가 뭔가요?"}, upto=10.0)
    said.clear()
    A.STATE.transcript = "GTID가 뭐예요?"     # the live pass wrote the same sound apart
    await heard(stub, tracker, [(11.0, 11.3)], {}, upto=15.0)
    check("a cough after a question leaves the question alone", said == [], said)

    stub, tracker = anew()
    await heard(stub, tracker, [(2.0, 6.0)], {2.0: "그래서 그 일을 끝내는 데 사십 분 걸렸어요, 맞죠."}, upto=10.0)
    said.clear()
    A.STATE.transcript = "그래서 그 일을 끝내는 데 사십 분 걸렸어요. 맞죠."     # its last words, as a sentence of their own
    await heard(stub, tracker, [(11.0, 11.3)], {}, upto=15.0)
    check("...and the end of a long one too", said == [], said)

    stub, tracker = anew()
    await heard(stub, tracker, [(2.0, 6.0)], {2.0: "그래서 그 일을 끝내는 데 사십 분 걸렸어요."}, upto=10.0)
    said.clear()
    A.STATE.transcript = "그래서 그 일을 끝내는 데 사십 분 걸렸어요. 그렇군요."
    await heard(stub, tracker, [(11.0, 11.6)], {}, upto=15.0)
    check("a short remark after a long sentence says so", said == [("그렇군요.", "short")], said)

    stub, tracker = anew()
    A.STATE.transcript = "그렇군요. 그런데 이"
    await heard(stub, tracker, [(2.0, 2.5), (8.5, 10.5)], {}, upto=11.0)
    check("speech going on after it: the last words are that speech's", said == [], said)

    stub, tracker = anew()
    A.STATE.transcript = "Thank you for watching this video."
    await heard(stub, tracker, [(2.0, 2.3)], {}, upto=10.0)
    check("words too long for such a sound get no such note", said == [], said)

    stub, tracker = anew()
    A.STATE.transcript = "그렇군요."
    await heard(stub, tracker, [(2.0, 4.0)], {2.0: ""}, upto=10.0)
    check("a span written as nothing is the same", said == [("그렇군요.", "short")], said)

    was = A.SETTINGS.values.get("voice_auto")
    A.SETTINGS.values["voice_auto"] = False
    stub, tracker = anew()
    A.STATE.transcript = "그렇군요."
    await heard(stub, tracker, [(2.0, 2.6)], {}, upto=10.0)
    A.SETTINGS.values["voice_auto"] = was
    check("with Solve spoken problems off nothing is noted", said == [], said)

    stub, tracker = anew()
    await heard(stub, tracker, [(2.0, 2.6)], {}, upto=10.0)
    check("and with nothing on the card there is nothing to say", said == [], said)
    A.broadcast = lambda msg: asyncio.sleep(0)


async def main():
    for case in (case_a_blip_is_not_speech, case_a_video_question_does_not_stick,
                 case_a_problem_read_in_several_sentences, case_one_run_of_speech_cannot_queue_for_ever,
                 case_silence_is_never_written_down, case_asking_to_be_told_is_a_question,
                 case_what_only_sounds_like_a_question, case_short_questions_and_what_is_not_taken,
                 case_sound_too_short_to_write_down):
        print(case.__doc__.splitlines()[0])
        await case()
    print(f"\n  ==== {len(PASS)} of {len(PASS) + len(FAIL)} as expected")
    if FAIL:
        print("FAILURES:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
