"""The technical terms of a pasted text, for Extra terms (server/settings.py, speech_terms).

A job posting, a resume or notes name the products and techniques an interview will be about, and write them in Latin
letters, in English text and in Korean text alike. Speech recognition writes such words right more often when it is given
them before the sound (server/transcriber.py, prompt), so the panel's Pick from text finds them here, and the person
chooses which go into Extra terms (docs/DECISIONS.md, note 131).

A word is taken by how it is written, not by a dictionary:

- a technical shape, wherever it stands: an inner capital (LangGraph, PostgreSQL, gRPC), all capitals of 2 to 10 letters
  (AWS, HPA), letters with digits (n8n, K8s, H100), or a mark inside or at its end (C++, C#, .NET, CI/CD, TensorRT-LLM,
  Node.js);
- a capitalized word (Python, Kafka) where it stands inside a sentence or a list, beside Korean, or alone on a line: at the
  start of a sentence, or after another capitalized word (a title, a person's name), a capital says nothing;
- two words in a row as one name (GitHub Actions, Apache Kafka, Argo CD), when the second is never written without the
  first: a technical shape and a capitalized word, two capitalized words, or a capitalized word and an abbreviation of
  one or two letters; two technical shapes in a row are two terms (AWS EKS);
- a lowercase word (pandas, kubectl) only beside Korean, where Latin letters are kept for names.

Common words and the words every posting or resume has are left out (STOP), and so are numbers, years, numbers with units
(16GB, 100ms), versions (v1.2), e-mail addresses, web addresses and domains (a name such as Node.js stays).

Nothing here keeps, logs or sends the text: it is read and let go.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

from .settings import WORD_MAX

TEXT_MAX = 64 * 1024   # the most a pasted text may hold, in bytes of UTF-8: some 21,000 Korean characters, 65,000 English ones
TERMS_MAX = 60         # the candidates given at most: a few more than Extra terms hold (50), so some can be passed over

# Addresses go before anything is read: their pieces are no terms (careers@example.com, https://example.com/jobs/12, www.).
# An e-mail address is tried only from the head of a run of its letters: tried from each letter of a long run, it read the
# rest of the run again each time, and 64 KB of letters took seconds
ADDRESS = re.compile(r"(?:https?|ftp)://\S+|www\.\S+|(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I)
GONE = " \x1f "        # what an address leaves: a mark that is no letter, no list mark and no end of a sentence
# A run of Latin letters and digits, joined inside by . / - and ending in + or # (C++, C#), after a dot of its own (.NET).
# The underscore is part of it, so that a name from code (MAX_BODY) is one token, left out whole: nobody says one
TOKEN = re.compile(r"\.?[A-Za-z0-9_]+(?:[./-][A-Za-z0-9_]+)*(?:\+\+|\+|#)?")
HANGUL = re.compile(r"[가-힣ㄱ-ㆌ]")   # syllables and letters; not ㆍ (U+318D), Korean's mark between list items
# What stands between the items of a list: commas, slashes, middle dots, bars, brackets and quotes, in either script's forms
LIST_MARKS = frozenset(",/·ㆍ・|()[]{}<>\"'“”‘’，、（）「」")
OPENERS = frozenset("([{<\"'“‘（「")                   # a word right after one of these starts no sentence: "(Python or Go)"
# A line's own mark before its words: a bullet, or a number or letter of a numbered list ("1.", "2)", "(3)", "a.", "①")
BULLET = re.compile(r"\s*(?:[-*•·▪◦‣⁃○●■□►▶✓✔→>※+]+|\(?\d{1,3}[.)]|[a-z][.)]|[①-⑳])\s+")
# Short words a dot follows inside a sentence: the capital after "e.g." starts no sentence
ABBREVIATIONS = frozenset({"e.g", "i.e", "eg", "ie", "etc", "vs", "incl", "ex", "esp", "approx", "cf"})
WRAPPED = 6            # the words of a line that ends mid-sentence, at least, for the next line to go on with it (a PDF's lines)

# A number, alone or with a unit, a range or a plus: a year, a date, a phone number, 16GB, 100ms, 3x, 1st, 4K, 5+. Units in
# lower case, and the few written in capitals (GB, K, M): 3D, 5G and 2FA are no units and stay
NUMBER = re.compile(r"\d[\d.,:/~-]*(?:[a-z]{1,3}|[KMGTP]i?B|[KMB])?\+?")
VERSION = re.compile(r"[vV]\d+(?:\.\d+)*[a-z]?")        # v1, v2.0, v1.2.3: a release, not a name
# The endings of web addresses, in lower case: example.com is an address, ASP.NET and Socket.IO are names
DOMAINS = frozenset({"com", "net", "org", "edu", "gov", "io", "co", "kr", "ai", "dev", "app", "me", "jp", "cn", "us", "uk",
                     "de", "info", "biz", "xyz", "so", "ly", "gg", "tv", "sh"})
CODE_ENDINGS = frozenset({"js", "ts", "py", "cpp", "rs", "rb", "go", "jl"})   # a dotted name all in lower case: llama.cpp
PLAIN = re.compile(r"[a-z]+")                          # a plain lowercase word, as in "AI-driven", "end-to-end", "and/or"
SHORT_CAPS = re.compile(r"[A-Z0-9]{1,2}")              # the short capitals of one compound: CI/CD, UI/UX, TCP/IP, I/O
PLURAL = re.compile(r"[A-Z]{2,}s")                     # an abbreviation's plural: APIs, LLMs, GPUs, which are API, LLM, GPU

# Words that are no term to give speech recognition, however they are written, compared in lower case: the words of any
# English sentence; what every posting and resume says of the job, the person and the place, and a posting's culture and
# perks, written in English inside Korean postings as often as in English ones (Remote First, Culture Fit); the words of every
# technical posting that speech recognition writes right unaided; a resume line's first verbs and words of praise;
# places, months and days; and abbreviations that are no technical term
STOP = frozenset("""
a an the and or but nor of to in on at by for with without within from into onto over under about above after before as
is are was were be been being am do does did done have has had having will would can could shall should may might must not
no yes if then than so such that this these those it its we our ours us you your yours they their them he she his her him
me my who whom whose what which when where why how all any each every both either neither some more most other others also
very just only well too here there now via per vs etc eg ie incl ok okay hello thanks thank please

team teams project projects experience experiences experienced role roles position positions job jobs career careers company
companies skill skills requirement requirements required qualification qualifications preferred preference responsibility
responsibilities duty duties task tasks benefit benefits perk perks salary compensation location office remote hybrid onsite
full time part contract intern internship apply applicant application hiring hire process interview culture mission vision
value values offer offers look welcome meet overview summary profile objective contact email mail phone mobile address
website blog portfolio linkedin
education university college school degree bachelor bachelors master masters phd major gpa award awards certification
certifications certificate license language languages interests hobbies references publications activities volunteer
achievements introduction description details notes present current year years month months week weeks day days level
native fluent business communication english korean global junior senior mid lead principal staff head chief manager
management director member members engineer engineers engineering developer developers development scientist researcher
research analyst architect designer specialist consultant officer optional first looking together people flexible hours
anywhere fit ownership transparency trust respect integrity excellence innovation passion curiosity impact growth speed
focus mindset autonomy series funding stock options equity lunch dinner health insurance vacation holiday relocation visa
welfare

product products service services solution solutions platform platforms system systems software hardware data code coding
program programming tech technology technologies technical stack tool tools framework frameworks library libraries backend
frontend fullstack front back end server servers client web app apps cloud infra infrastructure network networking security
database databases operations test testing deploy deployment release review quality performance scale scaling machine
learning deep model models computer science pipeline pipelines teamwork

build built design develop manage maintain improve work own drive ensure support create collaborate use using help operate
run ran write wrote keep kept ship scale monitor debug cut led move migrate automate deliver launch mentor define establish
integrate partner communicate analyze implement optimize reduce increase evaluate train serve tune document plan coordinate
contribute participate mention talk join grow learn take make made set get see find solve handle developed designed managed
implemented created improved optimized reduced increased migrated deployed maintained automated worked launched delivered
achieved supported contributed responsible strong excellent good great solid proven nice plus bonus new hot

korea south seoul busan incheon daegu daejeon gwangju ulsan sejong suwon seongnam pangyo gangnam yeouido jeju gyeonggi usa
america japan tokyo china singapore london asia europe january february march april june july august september october
november december jan feb mar apr jun jul aug sep sept oct nov dec monday tuesday wednesday thursday friday saturday sunday
mon tue wed thu fri sat sun

inc corp co ltd llc gmbh labs startup it hr pm am ceo cto cfo coo cpo vp kpi okr roi b2b b2c faq tbd asap fyi eta id pc uk eu
kst usd krw eur toeic toefl ielts opic q1 q2 q3 q4 h1 h2 ii iii iv vi vii viii ix xi xii
""".split())


def past(word: str) -> bool:
    """A past tense of five letters or more (Developed, Migrated, Distributed): a resume's lines start with one, and one
    heads a title (Distributed Systems). Red of Red Hat is shorter; Memcached is one too, and stays where it stands alone."""
    return len(word) >= 5 and word.isalpha() and word.lower().endswith("ed")


def common(word: str) -> bool:
    """A word that is no part of a name, and no name before the word after it: one of STOP, or a past tense."""
    return word.lower() in STOP or past(word)


@dataclass
class Token:
    """One word of the text as found, with what stands around it on its line."""

    text: str                 # as written
    at: int                   # its place in the whole text: the order words first appear in
    gap: str = ""             # what stands between it and the next word on its line, or the line's end
    korean: bool = False      # beside Korean, or in a list that is
    listed: bool = False      # one item of a list: a comma, a slash or a bracket between it and a neighbour
    inside: bool = False      # inside a sentence: after a lowercase or common word, a digit, an opening bracket
    alone: bool = False       # the whole of its line, the line's bullet aside


@dataclass
class Line:
    """The tokens of one line, and whether it starts with a bullet (an item of a list, not a title or a name)."""

    tokens: list = field(default_factory=list)
    bulleted: bool = False
    body: str = ""            # the line without its bullet and the marks at its end


@lru_cache(maxsize=4096)
def kind_of(word: str) -> str | None:
    """How a word is written: "shape" (a technical shape, a term wherever it stands), "cap" (a capitalized word, a name
    only where it stands inside a sentence), "lower" (a plain lowercase word, a name only beside Korean), or None for a
    word that is no term at all (a number, a version, an address, a name from code, a single letter, one too long).
    Kept for the words met before: a text says its words many times over."""
    if "_" in word or len(word) < 2 or len(word) > WORD_MAX:   # code (MAX_BODY), a single letter, longer than a term may be
        return None
    if NUMBER.fullmatch(word) or VERSION.fullmatch(word):      # 2024, 16GB, 100ms, 3+, v1.2
        return None
    letters = [c for c in word if c.isalpha()]
    if not letters:                                             # marks and digits alone
        return None
    if word[-1] in "+#":                                        # C++, C#, F#: no common word ends in either
        return "shape"
    if word[0] == ".":                                          # .NET: a name only when what follows the dot is one
        return "shape" if kind_of(word[1:]) == "shape" else None
    if "." in word:                                             # Node.js, ASP.NET, Qwen2.5, or an address, or e.g.
        return dotted(word)
    if "-" in word or "/" in word:                              # what pieces() left whole: TensorRT-LLM, CI/CD, GPT-4o
        if any(c.isdigit() for c in word):                      # letters with digits on the whole: GPT-4o, Llama-3, x86-64
            return "shape"
        return "shape" if any(kind_of(p) == "shape" for p in re.split(r"[-/]", word)) else None
    if any(c.isdigit() for c in word):                          # letters with digits: n8n, K8s, S3, H100, 2FA
        return "shape"
    if all(c.isupper() for c in letters):                       # all capitals: AWS, HPA, RAG, up to ten letters
        return "shape" if len(word) <= 10 else None
    if any(c.isupper() for c in word[1:]):                      # a capital inside, beside lowercase: LangGraph, gRPC, MLOps
        return "shape"
    if word[0].isupper():                                       # Python, Kafka: a name where it stands inside a sentence
        return "cap"
    return "lower" if len(word) >= 3 else None                  # pandas, kubectl: a name beside Korean only


def dotted(word: str) -> str | None:
    """A word with a dot inside: a name (Node.js, llama.cpp, ASP.NET, Socket.IO, Qwen2.5) or not (example.com, e.g., No.1)."""
    parts = word.split(".")
    first, last = parts[0], parts[-1]
    if last in DOMAINS:                                         # example.com, github.io: an address, written in lower case
        return None
    if any(len(p) < 2 and not p.isdigit() for p in parts):      # e.g, i.e, U.S, Ph.D: single letters with dots
        return None
    if any(c.isdigit() for c in first):                         # Qwen2.5, Python3.11: a name with its number
        return "shape"
    if re.fullmatch(r"[A-Z]{2,4}", last):                       # ASP.NET, Socket.IO
        return "shape"
    if last in CODE_ENDINGS:                                    # Node.js, Vue.js, llama.cpp
        return "shape"
    return None                                                 # README.md, No.1, end.Next (a missing space): no name


@lru_cache(maxsize=4096)
def pieces(word: str) -> tuple[str, ...]:
    """The words a token stands for. One with a plain lowercase word between its hyphens or slashes is cut there and keeps
    its technical pieces ("AI-driven" is AI, "end-to-end" nothing); names joined by a slash are each a word of their own
    ("AWS/GCP", "Python/Go"), where a compound of short capitals stays one (CI/CD, UI/UX, TCP/IP, I/O, PL/SQL)."""
    if "-" not in word and "/" not in word:                     # nothing to cut
        return (word,)
    parts = re.split(r"[-/]", word)
    if any(PLAIN.fullmatch(p) for p in parts):                  # a plain word inside: the technical pieces alone
        return tuple(p for p in parts if kind_of(p) == "shape")
    if "/" in word and not any(SHORT_CAPS.fullmatch(p) for p in word.split("/")):   # one name or another: each its own
        return tuple(x for p in word.split("/") for x in pieces(p))
    return (word,)                                              # one name: TensorRT-LLM, gRPC-Web, CI/CD


def beside_hangul(line: str, i: int, step: int) -> bool:
    """Whether the nearest character from `i` in the direction of `step` (-1 back, +1 on), past spaces and list marks, is
    Hangul: "Python을", "Python 경험", "(Docker)를"."""
    while 0 <= i < len(line) and (line[i].isspace() or line[i] in LIST_MARKS):
        i += step
    return 0 <= i < len(line) and bool(HANGUL.match(line[i]))


def nearest(line: str, i: int, step: int) -> str:
    """The nearest character from `i` in the direction of `step` that is not a space, or "" past the line's end."""
    while 0 <= i < len(line) and line[i].isspace():
        i += step
    return line[i] if 0 <= i < len(line) else ""


def read(text: str) -> list[Line]:
    """The text's tokens, line by line, each with what stands around it (Token)."""
    out: list[Line] = []
    at = 0                                                      # the place of each token in the whole text
    wrapped = False                                             # the line before ended mid-sentence: this one goes on with it
    for line in ADDRESS.sub(GONE, text).splitlines():
        bullet = BULLET.match(line)
        body = (line[bullet.end():] if bullet else line).strip().rstrip(".,;:!?").strip()
        row = Line(bulleted=bool(bullet), body=body)
        found = list(TOKEN.finditer(line))
        for k, m in enumerate(found):
            prev = found[k - 1].group() if k else ""           # the word before it on its line
            spaced = not line[found[k - 1].end():m.start()].strip() if k else False   # nothing but spaces between the two
            before, after = nearest(line, m.start() - 1, -1), nearest(line, m.end(), 1)
            inside = (
                # after a lowercase word, a digit or a common word ("with Kafka", "3 years of Python", "Strong Python")
                (spaced and (prev[0].islower() or prev[0].isdigit() or common(prev)))
                or before in OPENERS                            # "(Python or Go)"
                or (before == "." and k > 0 and prev.lower() in ABBREVIATIONS)   # "e.g. Kafka"
                or (before == ":" and (after == "" or after in LIST_MARKS))      # a list after a colon: "Languages: Python"
                or (k == 0 and wrapped and not bullet))          # first on a line that goes on with the one before
            row.tokens.append(Token(
                text=m.group(), at=at,
                gap=line[m.end():found[k + 1].start()] if k + 1 < len(found) else line[m.end():],
                korean=beside_hangul(line, m.start() - 1, -1) or beside_hangul(line, m.end(), 1),
                inside=inside, alone=body == m.group()))
            at += 1
        # A list: words with a comma, a slash or a bracket between them, each one an item. Beside Korean is said of all
        # of it when one of its words is: "pandas, numpy 등"
        start = 0
        for k in range(1, len(row.tokens) + 1):
            gap = row.tokens[k - 1].gap
            if k < len(row.tokens) and gap.strip() and all(c.isspace() or c in LIST_MARKS for c in gap):
                continue                                        # the list goes on to the next word
            items = row.tokens[start:k]
            if len(items) > 1:                                  # two words or more: a list
                korean = any(t.korean for t in items)
                for t in items:
                    t.listed, t.korean = True, t.korean or korean
            start = k
        out.append(row)
        if line.strip():                                        # an empty line ends a sentence as a full stop does
            wrapped = len(line.split()) >= WRAPPED and bool(re.search(r"[a-z0-9,]$", line.rstrip()))
        else:
            wrapped = False
    return out


def named(row: Line, k: int, written: Counter, follows: Counter) -> bool:
    """Whether the k-th word of a line and the one after it are one name. The two have only spaces between them, neither is
    a common word, and the second is never written without the first, so it is part of this name and no word of its own.
    Then by how they are written:

    - a technical shape and a capitalized word: the shape names the product the word is part of (GitHub Actions, AWS
      Lambda, SQL Server);
    - a capitalized word and an abbreviation of one or two letters, which says little alone (Argo CD, Power BI), where the
      capitalized word stands as a name does: inside a sentence or a list, beside Korean, or as a bulleted line's whole;
    - two capitalized words (Apache Kafka, Spring Boot) standing so, or going on into a sentence ("Apache Kafka is"): at
      the head of a line with nothing after them they are as often a person's name or a title;
    - two technical shapes are two terms (AWS EKS, REST API), and a lowercase word or a number is no part of a name."""
    a, b = row.tokens[k], row.tokens[k + 1]
    if not a.gap or a.gap.strip():                              # anything but spaces between them: two words
        return False
    if pieces(a.text) != (a.text,) or pieces(b.text) != (b.text,):   # a word cut at its hyphens or slashes: no half of a name
        return False
    if common(a.text) or common(b.text):                        # "Senior Engineer", "Our Team", "Managed Kafka"
        return False
    if written[b.text] != follows[(a.text, b.text)]:            # the second stands alone somewhere: a word of its own
        return False
    if len(a.text) + 1 + len(b.text) > WORD_MAX:                # longer than an Extra term may be
        return False
    after = row.tokens[k + 2] if k + 2 < len(row.tokens) else None
    stands = (a.inside or a.listed or a.korean or b.korean      # where a name stands: in a sentence, a list, Korean text
              or b.gap.strip()[:1] in LIST_MARKS                # or a list goes on after the two ("" is no mark)
              or (row.bulleted and row.body == f"{a.text} {b.text}"))      # or they are a bulleted line's whole
    goes_on = after is not None and not b.gap.strip() and after.text[0].islower()   # a sentence goes on after them
    kinds = (kind_of(a.text), kind_of(b.text))
    if kinds == ("shape", "cap"):                               # GitHub Actions, AWS Lambda
        return True
    if kinds == ("cap", "shape"):                               # Argo CD, Power BI: the short abbreviation alone says little
        return len(b.text) <= 2 and stands
    if kinds == ("cap", "cap"):                                 # Apache Kafka, Spring Boot, Cluster Autoscaler
        return stands or goes_on
    return False                                                # two shapes, a lowercase word, a number


def find(text: str, limit: int = TERMS_MAX) -> list[tuple[str, int]]:
    """The technical terms of `text`, each written as it is written most often, with how many times it appears: the most
    frequent first, and of those the first to appear; at most `limit`. Written in other capitals, a word is the same term
    (Kafka, kafka), and an abbreviation's plural is the abbreviation (APIs is API)."""
    lines = read(text)
    # How often each word is written as it is, and right after which: the second word of a name is never written alone
    written = Counter(t.text for row in lines for t in row.tokens)
    follows = Counter((a.text, b.text) for row in lines for a, b in zip(row.tokens, row.tokens[1:])
                      if a.gap and not a.gap.strip())
    counts: Counter = Counter()                                 # each term's appearances, by its lowercase key
    forms: dict = defaultdict(Counter)                          # how each term is written, and how often each way
    first: dict = {}                                            # where each term first appears: (token, piece of it)
    taken: set = set()                                          # the terms that stand as a term at least once

    def note(word: str, at: tuple, stands: bool) -> None:
        """One appearance of a word written as a term: counted, and the term taken when it stands as one here."""
        key = word.lower()
        if key in STOP:                                         # a common word, however it is written
            return
        counts[key] += 1
        forms[key][word] += 1
        first.setdefault(key, at)
        if stands:
            taken.add(key)

    for row in lines:
        k = 0
        while k < len(row.tokens):
            t = row.tokens[k]
            if k + 1 < len(row.tokens) and named(row, k, written, follows):
                note(f"{t.text} {row.tokens[k + 1].text}", (t.at, 0), True)   # the two as one name
                k += 2
                continue
            # the word right after, with nothing but spaces between: a capitalized one makes a past tense before it a title's
            title = k + 1 < len(row.tokens) and not t.gap.strip() and row.tokens[k + 1].text[:1].isupper()
            cut = pieces(t.text)
            for i, word in enumerate(cut):                      # each piece in its place: AWS before GCP in "AWS/GCP"
                word = word[:-1] if PLURAL.fullmatch(word) else word   # APIs is API
                kind = kind_of(word)
                if kind == "shape":                             # a technical shape: a term wherever it stands
                    note(word, (t.at, i), True)
                elif kind == "cap" and not (past(word) and title):   # Distributed Systems, Embedded Linux: no term
                    # a capitalized word: a term where it stands inside a sentence or a list, beside Korean, or alone
                    note(word, (t.at, i), t.korean or t.inside or t.listed or t.alone or len(cut) > 1)
                elif kind == "lower" and t.korean and not past(word):   # a lowercase word beside Korean: pandas, kubectl
                    note(word, (t.at, i), True)
            k += 1
    ranked = sorted(taken, key=lambda key: (-counts[key], first[key]))
    return [(forms[key].most_common(1)[0][0], counts[key]) for key in ranked[:limit]]


def hint_words(hints: dict) -> set[str]:
    """The words of the built-in lists ({language: "word, word, ..."}), in lower case, as the transcriber reads them."""
    return {w.strip().lower() for text in hints.values() for w in str(text).rstrip(".").split(",") if w.strip()}


def marked(found: list[tuple[str, int]], hints: dict, extra) -> list[dict]:
    """The terms found, each with whether the built-in lists give it to speech recognition already (`listed`) and whether
    Extra terms holds it (`have`), in any capitals, as the prompt says a word once (transcriber.py, prompt)."""
    listed = hint_words(hints)
    have = {w.strip().lower() for w in extra or () if isinstance(w, str) and w.strip()}
    return [{"word": w, "count": n, "listed": w.lower() in listed, "have": w.lower() in have} for w, n in found]
