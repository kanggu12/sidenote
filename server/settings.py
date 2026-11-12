"""Runtime settings: every stage of the pipeline can be switched from the panel.

Each setting has a default taken from the environment (config.py), a kind the panel draws a control
for, a label and one line of help (English in the code, translated by server/i18n.py when the settings are sent),
and the settings it depends on.
Values the panel changes are kept in `.settings.json` beside the logs, so they survive a restart; the
screen and sound switches and pause stay in `.switches.json` (server/app.py), as before.

Nothing here talks to the network or the GPU: the server reads `SETTINGS.get(key)` when it needs a
value, so a change applies to the next analysis without a restart.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import telemetry
from .config import CONFIG, agent_name
from .i18n import t
from .updates import allowed as update_allowed

log = logging.getLogger("sidenote.settings")

SOLVE_TYPES = ["mcq", "short", "essay", "coding", "algorithm", "work", "math", "diagram", "other"]
# Settings that last for one run of the server and are never written to the settings file. The drawn region: a
# region drawn on one screen and left set hid every problem that came after it, twice (the second time, a
# region drawn the day before kept the models on a patch of desktop icons while a problem sat beside it).
NOT_KEPT = {"roi_box"}
# An agent model chosen by version before the list named families: the family it belongs to, so the choice of Opus
# stays a choice of Opus and follows its next release.
FAMILY = {"claude-opus": "opus", "claude-sonnet": "sonnet", "claude-haiku": "haiku"}
# Keys a settings file written before the cloud agent was general may hold, and what each is called now.
RENAMED = {"claude_mode": "agent_mode", "claude_payload": "agent_payload", "claude_hard_types": "agent_hard_types",
           "claude_model_name": "agent_model_name", "claude_effort": "agent_effort",
           "claude_hourly_usd": "agent_hourly_usd", "claude_confirm": "agent_confirm"}
TYPE_NAMES = {"mcq": "Multiple choice", "short": "Short answer", "essay": "Essay", "coding": "Coding",
              "algorithm": "Algorithm", "work": "Work", "math": "Math", "diagram": "Diagram", "other": "Other"}
# Skip windows: while a window on screen has one of these in its title or its program's name, the capture program
# sends no screen at all. The common password managers and the browsers' private windows. client/capture.py keeps a
# copy for the moments before the server's word arrives, and tests/capture_skip.py checks the two are the same.
SKIP_WINDOWS = ["1Password", "Bitwarden", "KeePass", "KeePassXC", "LastPass", "Dashlane", "Keeper", "Enpass",
                "NordPass", "Proton Pass", "InPrivate", "Incognito", "Private Browsing", "시크릿", "사생활 보호"]
WORDS_MAX, WORD_MAX = 50, 60   # a list of free words: at most this many, each at most this many characters
# Seconds on the clock a sentence of 5 s takes to be written down with each speech model, four threads, int8, on the test
# PC with other work running: 0.29, 0.81 and 0.84 s for each second of speech (docs/DECISIONS.md, note 129). The live line
# is read with small beside the larger two, at small's cost (note 106)
SPEECH_SENTENCE = {"small": "1.5", "medium": "4", "large-v3-turbo": "4"}
SPEECH_MODELS = ("small", "medium", "large-v3-turbo")


@dataclass
class Setting:
    key: str
    kind: str                      # bool | choice | multi | box | int | words
    default: Any
    section: str
    label: str
    help: str = ""
    options: list = field(default_factory=list)   # choice / multi: [(value, label)]
    needs: list = field(default_factory=list)     # keys that must be on (truthy) for this one to apply
    # choice: one line per option, shown for the option in force. A paragraph that explains four
    # options at once is read by nobody: the panel shows the line for what is chosen now.
    opt_help: dict = field(default_factory=dict)

    def clean(self, v: Any) -> Any:
        """The value as it is kept: free words trimmed, with the empty ones dropped (a comma left at the end of what was
        typed). Any other kind, and anything that is not a list of strings, comes back as it came, for valid() to judge."""
        if self.kind == "words" and isinstance(v, list) and all(isinstance(x, str) for x in v):
            return [x.strip() for x in v if x.strip()]   # each word trimmed, and the empty ones gone
        return v

    def valid(self, v: Any) -> bool:
        if self.kind == "bool":
            return isinstance(v, bool)
        if self.kind == "choice":
            return any(v == o[0] for o in self.options)
        if self.kind == "multi":   # strings only: a list inside the list is unhashable, and raised out of the panel's loop
            allowed = {o[0] for o in self.options}
            return (isinstance(v, list) and all(isinstance(x, str) and x in allowed for x in v)
                    and len(set(v)) == len(v))
        if self.kind == "box":
            if v is None:
                return True
            # numbers, not true and false: bool is an int to Python, and [false, false, true, true] was kept as a box
            return (isinstance(v, list) and len(v) == 4 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)
                    and 0 <= v[0] < v[2] <= 1 and 0 <= v[1] < v[3] <= 1
                    and v[2] - v[0] >= 0.02 and v[3] - v[1] >= 0.02)
        if self.kind == "int":
            return isinstance(v, int) and not isinstance(v, bool) and any(v == o[0] for o in self.options)
        if self.kind == "words":   # cleaned first (clean): no word left empty or with spaces round it
            return (isinstance(v, list) and len(v) <= WORDS_MAX
                    and all(isinstance(x, str) and 0 < len(x) <= WORD_MAX and x == x.strip() for x in v))
        return False


def _encodable(value: Any) -> bool:
    """Whether `value` can be written out as JSON in UTF-8: a lone surrogate in a string cannot."""
    try:
        json.dumps(value, ensure_ascii=False).encode("utf-8")
        return True
    except (TypeError, ValueError):
        return False


def with_default(options: list, default: Any, label: str) -> list:
    """The options, with the environment's own value among them when it is not one of them (SIDENOTE_AGENT_HOURLY_USD=3,
    SIDENOTE_LOCAL_IDLE_MIN=15): otherwise the panel showed no option chosen, the value could not be chosen again once
    moved, and Reset failed on it. Placed in order among the numbers (the negative ones, such as Keep loaded, stay last)."""
    if any(default == o[0] for o in options):
        return options
    keep, below = [o for o in options if o[0] >= 0], [o for o in options if o[0] < 0]
    if default < 0:   # a negative one is of the kind the negatives are (Keep loaded): after the numbers, with them
        return keep + sorted(below + [(default, label)], key=lambda o: o[0])
    return sorted(keep + [(default, label)], key=lambda o: o[0]) + below


def _defs() -> list[Setting]:
    """Every setting with its words in the current language: called again for each settings message (Settings.meta),
    so a panel that changed the language gets the new words."""
    local_default = CONFIG.analyzer in ("local", "mock")
    # With the local model, the cloud agent (server/agents.py) solves the types in agent_hard_types (algorithm, coding,
    # math, and work, essay and other, whose local answers were found shallow) and any problem
    # the local model would be local_slow_ratio times as slow to start answering (pipeline.Speed), and is given only the
    # problem (signed out, it stays out; docs/DESIGN-local-first.md, section 13); without the local model, the agent is
    # the only engine and solves everything from the screen, as before.
    agent_default = "hard" if local_default else "all"
    payload_default = "crop" if local_default else "screen"
    name = agent_name()   # as the panel shows it; the Korean sentences say it, the English ones say "the agent"
    if CONFIG.agent == "codex":
        # Codex's models change with its releases: its own pick, or the one the environment names
        models = [("", t("As Codex picks"))]
        efforts = [("", t("Default")), ("low", t("Low")), ("medium", t("Medium")), ("high", t("High"))]
    else:
        # Family names, not versions: the agent takes `opus`, `sonnet` and `haiku` as the newest model of each, so a
        # new release (Opus 6 after Opus 5.5) is used without a change here. A version is pinned through
        # SIDENOTE_AGENT_MODEL (claude-opus-5-5), which the list then offers as well.
        models = [("", t("As the agent picks", agent=name)), ("opus", t("Latest Opus (smartest)")),
                  ("sonnet", t("Latest Sonnet (fast)")), ("haiku", t("Latest Haiku (fastest)"))]
        efforts = [("", t("Default")), ("low", t("Low")), ("medium", t("Medium")), ("high", t("High")),
                   ("xhigh", t("Very high")), ("max", t("Max"))]
    if CONFIG.agent_model and all(CONFIG.agent_model != m for m, _ in models):
        models.append((CONFIG.agent_model, CONFIG.agent_model))   # the environment's own choice is always offered
    if CONFIG.agent_effort and all(CONFIG.agent_effort != e for e, _ in efforts):
        efforts.append((CONFIG.agent_effort, CONFIG.agent_effort))
    return [
        # solving
        Setting("local_llm", "bool", local_default, "solve", t("Local model"),
                t("The model that solves on this PC's GPU. Off: the agent solves everything", agent=name)),
        Setting("local_think", "choice", CONFIG.local_think, "solve", t("Think before answering"),
                t("Auto: thinks first only on problems that need working out, such as multiple choice, calculations "
                  "and code. Always: slower, works out every problem"),
                [("auto", t("Auto")), ("always", t("Always")), ("never", t("Never"))], ["local_llm"]),
        Setting("local_model", "choice", CONFIG.local_model, "solve", t("Model"),
                t("One of the pulled models. Auto: the largest that fits the GPU's memory"),
                [("auto", t("Auto (fits the GPU)"))] + ([(CONFIG.local_model, CONFIG.local_model)] if CONFIG.local_model != "auto" else []),
                ["local_llm"]),
        Setting("local_busy_model", "choice", CONFIG.local_busy_model, "solve", t("Model when the GPU is busy"),
                t("When a busy GPU slows it below half speed, this model solves instead. Back to the usual model after "
                  "{sec} s", sec=f"{CONFIG.local_busy_hold_sec:g}"),
                [("", t("Don't switch")), ("auto", t("Auto (a smaller model)"))]
                + ([(CONFIG.local_busy_model, CONFIG.local_busy_model)] if CONFIG.local_busy_model not in ("", "auto") else []),
                ["local_llm"]),
        Setting("web_search", "bool", bool(CONFIG.search_url), "solve", t("Web search"),
                t("Looks up recent facts and options it is unsure of. The search words go to a search engine"),
                needs=["local_llm"]),
        Setting("web_fetch", "bool", bool(CONFIG.search_url), "solve", t("Read pages"),
                t("Reads a page when the search summary is not enough (public addresses only)"),
                needs=["local_llm", "web_search"]),
        # Beside the searches, the one other request this server makes of the internet by itself (server/updates.py). On
        # wherever the environment allows the check, as the search is where there is a search server: with
        # SIDENOTE_UPDATE_CHECK=0 (or in mock mode) it starts off, nothing turns it on, and the panel says why.
        Setting("update_check", "bool", update_allowed(), "solve", t("Check for new versions"),
                t("Asks GitHub once a day for the latest release. Only Sidenote's version goes out")),
        # the cloud agent
        Setting("agent_mode", "choice", agent_default, "agent", t("Problems the agent solves", agent=name),
                t("Signed out (for the API, with no key), the agent counts as off", agent=name),
                [("off", t("Off")), ("verify", t("Check answers")), ("hard", t("Hard problems")), ("all", t("All"))],
                opt_help={
                    "off": t("The agent is not used. Only the local model solves", agent=name),
                    "verify": t("The local model solves and the agent checks the answer. If they differ, the fixed "
                                "solution is added", agent=name),
                    "hard": t("Only the types ticked under 'Types the agent solves' in Solver settings go to the agent, the rest "
                              "to the local model (to the agent when it would be over 1.5 times slower). If the agent fails, "
                              "the local model", agent=name),
                    "all": t("The agent solves every problem found", agent=name),
                }),
        Setting("agent_payload", "choice", payload_default, "agent", t("What is sent to the agent", agent=name),
                t("Written-out words that hold resident registration, phone, card or account numbers are not sent: the local model solves. A spoken problem sends its words only"),
                [("crop", t("Problem area")), ("text", t("Problem text")), ("screen", t("Whole screen"))],
                opt_help={
                    "crop": t("Sends only the problem, cut at full resolution. When it cannot be found, the written-out "
                              "text"),
                    "text": t("Sends only the written-out text. A picture that cannot be written out goes as the problem "
                              "area"),
                    "screen": t("Sends the whole screen, the windows beside the problem too"),
                }),
        Setting("agent_hard_types", "multi", ["algorithm", "coding", "math", "work", "essay", "other"], "agent",
                t("Types the agent solves", agent=name),
                t("The types 'Hard problems' hands to the agent. The local model thinks through the rest", agent=name),
                [(k, t(TYPE_NAMES[k])) for k in SOLVE_TYPES]),
        # The model and how hard it thinks: the environment sets where they start, the panel moves
        # them from there, and the next problem starts a CLI with the new ones.
        Setting("agent_model_name", "choice", CONFIG.agent_model, "agent", t("Agent model", agent=name),
                t("Empty: as the agent is set up. Latest: the newest model of that family. To pin one, "
                  "SIDENOTE_AGENT_MODEL", agent=name), models),
        Setting("agent_effort", "choice", CONFIG.agent_effort, "agent", t("Thinking effort"),
                t("Higher is stronger on hard problems, slower and dearer"), efforts),
        Setting("agent_hourly_usd", "choice", CONFIG.agent_hourly_usd, "agent", t("Hourly cost limit"),
                t("When the last hour's cost reaches this, automatic sending stops. Reanalyze and questions still go. Codex signed in with ChatGPT is not counted"),
                with_default([(0.0, t("No limit")), (1.0, "$1"), (2.0, "$2"), (5.0, "$5"), (10.0, "$10")],
                             CONFIG.agent_hourly_usd, f"${CONFIG.agent_hourly_usd:g}")),
        # The rule: with the agent at a limit, the answers come from this PC's model where they
        # can, not from another agent. With that model switched on it answers then already; this is for one switched off.
        Setting("local_fallback", "bool", True, "agent", t("The local model stands in at a limit"),
                t("When the agent reaches a limit or is signed out, the local model, switched off, solves instead. Off "
                  "the GPU once the agent can be asked again", agent=name)),
        # A reply without the head is the agent declining a screen, or answering nothing. On, this PC's model, already
        # loaded, solves the same screen (pipeline.solve); off, or with that model off, the agent's reply is the card.
        Setting("local_on_decline", "bool", True, "agent", t("The local model answers when the agent declines", agent=name),
                t("When the agent declines a screen or answers nothing, the local model solves it instead. Off: the "
                  "agent's reply is shown as it came", agent=name), needs=["local_llm"]),
        Setting("agent_confirm", "bool", False, "agent", t("Confirm before sending"),
                t("Shows what goes to the agent first, and sends it only on Send. Not sent when not pressed within 2 "
                  "minutes", agent=name)),
        # screen processing
        Setting("history_keep", "bool", True, "screen", t("Keep answers"),
                t("Keeps answers and their screens on the server for {days} days (up to {mb} MB), starred ones until unstarred. Clear them with Clear history in the menu",
                  days=f"{CONFIG.history_days:g}", mb=f"{CONFIG.history_mb:g}")),
        Setting("face_mask", "bool", True, "screen", t("Cover faces"),
                t("A face (a video call, a photo) is greyed out before a model sees it. Off: left as it is")),
        # The capture program gets the words in its control message (server/app.py, control_message) and reads the
        # windows itself: their titles and their programs' names never leave that program (client/capture.py).
        Setting("skip_windows", "words", list(SKIP_WINDOWS), "screen", t("Skip windows"),
                t("While a window whose title or program has one of these words is on screen, no screen is sent (sound still is). Comma-separated, any case. Not on Wayland")),
        Setting("dedupe", "bool", True, "screen", t("Don't solve the same problem again"),
                t("Solves again only when the answer's problem area changes. Off: on every screen change")),
        Setting("roi", "bool", True, "screen", t("Zoom in on the problem"),
                t("When thinking, also gives the problem cut at full resolution. Better with small text"),
                needs=["local_llm"]),
        Setting("roi_box", "box", None, "screen", t("Drawn region"),
                t("Looks only inside the region drawn on the screen card. Clear it to see the whole screen")),
        Setting("roi_windows", "bool", True, "screen", t("Cut at window edges"),
                t("Cuts at the edges of the problem's window so the windows beside it stay out. Off: only adds a margin "
                  "to the area the model gave"), needs=["local_llm"]),
        Setting("extract", "bool", True, "screen", t("Write out the problem text"),
                t("The local model writes the problem out as text. Used to send text to the agent and to check the "
                  "examples", agent=name), needs=["local_llm"]),
        # code
        Setting("run_button", "bool", True, "code", t("Run button"),
                t("A run button on code answers (a separate container with no internet)")),
        Setting("autocheck", "bool", True, "code", t("Check the examples"),
                t("Runs the code of algorithm and coding answers on the problem's examples and adds the result. Python, Java, C++, JavaScript, TypeScript, Kotlin, Go, C and Bash"),
                needs=["run_button", "local_llm", "extract"]),
        # speech
        Setting("voice_auto", "bool", CONFIG.voice_trigger, "speech", t("Solve spoken problems"),
                t("When the speaker stops, what was said is solved as a problem. Off: shown only")),
        Setting("whisper_hint", "bool", bool(CONFIG.whisper_hint), "speech", t("Technical term hints"),
                t("Gives speech recognition technical terms in advance (Kubernetes, hash table and the like)")),
        # Ahead of the built-in words, and given with them switched off too: these were typed on purpose
        Setting("speech_terms", "words", [], "speech", t("Extra terms"),
                t("Words speech recognition should spell as written, such as product names. Comma-separated, ahead of the built-in hints")),
        # Measured on 126 spans of real recordings: 32 of the 108 Korean ones were read as
        # English by the automatic pick, and not one of the 18 English ones was read as Korean. The
        # session's own evidence takes that down (server/transcriber.py), but pinning the language is
        # the only thing that removes it, so the help says so.
        Setting("speech_lang", "choice", CONFIG.speech_lang, "speech", t("Speech language"),
                t("Auto picks Korean or English for each utterance and sometimes misreads short Korean. Pin it when "
                  "only one is spoken"),
                [("auto", t("Auto")), ("ko", "한국어"), ("en", "English")]),
        # What each costs is measured on the test PC (docs/DECISIONS.md, note 106). A model the environment names is
        # always offered as well, as the agent's models are.
        Setting("whisper_model", "choice", CONFIG.whisper_model, "speech", t("Speech model"),
                t("The model that writes down each sentence heard, on the CPU; the live words are read with small. One not "
                  "downloaded yet is fetched when first chosen"),
                [(m, m) for m in SPEECH_MODELS]
                + ([(CONFIG.whisper_model, CONFIG.whisper_model)] if CONFIG.whisper_model not in SPEECH_MODELS else []),
                opt_help={"small": t("A sentence of 5 s in about {s} s on the test PC. The lightest, and the worst at technical terms",
                                     s=SPEECH_SENTENCE["small"]),
                          "medium": t("A sentence of 5 s in about {s} s on the test PC", s=SPEECH_SENTENCE["medium"]),
                          "large-v3-turbo": t("A sentence of 5 s in about {s} s on the test PC. Hears technical terms best, "
                                              "for the cost of medium", s=SPEECH_SENTENCE["large-v3-turbo"])}),
        # Everything heard passes through this, other people and whatever is playing included, so it is off until asked for
        Setting("speech_keep", "bool", False, "speech", t("Keep what is heard"),
                t("Saves each sentence heard, with its time, on this PC only, for {days} days (up to {mb} MB), other voices and playback included. Clear it with Clear history in the menu", days=f"{CONFIG.history_days:g}", mb=f"{CONFIG.heard_mb:g}")),
        # capture
        Setting("stitch", "bool", False, "capture", t("Join scrolled screens"),
                t("Joins a problem taller than the screen while it is scrolled, and sends it at once")),
        # The monitors themselves are only known once a capture program says hello, and the choice has to
        # be there before that (a monitor chosen with nothing running is what the next start uses). So the
        # list always holds every monitor at once and the first two, and a capture program that connects
        # replaces it with the real ones. Without that, the panel's list held "1" alone with nothing connected,
        # so all monitors could not be chosen at all.
        Setting("monitor", "int", 1, "capture", t("Monitor"),
                t("All monitors takes them as one picture and sees a problem on any of them. On Windows the panel's "
                  "own window is covered before it is sent"),
                [(0, t("All monitors")), (1, t("Monitor {i}", i=1)), (2, t("Monitor {i}", i=2))]),
        # The capture program carries it out (client/capture.py, ScreenFollow), told in its control message: off, it
        # reads the monitor above and nothing else. It looks at the others now and then to know where a new screen
        # rests, which costs a grab of each (docs/DECISIONS.md, note 130), so it is off until asked for
        Setting("monitor_follow", "bool", False, "capture", t("Follow the changing screen"),
                t("Switches to the monitor where a new screen settles, and back again. Off: only the monitor chosen "
                  "above")),
        # resources
        Setting("gpu_idle_min", "int", CONFIG.local_idle_min, "resource", t("Free the GPU when idle"),
                t("Takes the model off the GPU this long after its last use. Loading it again takes some tens of "
                  "seconds"),
                with_default([(0, t("At once")), (5, t("{n} min", n=5)), (10, t("{n} min", n=10)), (30, t("{n} min", n=30)),
                              (-1, t("Keep loaded"))], CONFIG.local_idle_min,
                             t("Keep loaded") if CONFIG.local_idle_min < 0 else t("{n} min", n=CONFIG.local_idle_min)), ["local_llm"]),
    ]


def sections() -> list[tuple[str, str]]:
    """The order the panel draws them in, with each section's title in the current language: what solves first, then
    what it is given, then where that comes from (the monitor was at the bottom, under settings about the answers)."""
    return [("solve", t("Solving")), ("agent", agent_name()),
            ("screen", t("Screen")), ("capture", t("Capture")),
            ("speech", t("Speech")), ("code", t("Code")), ("resource", "GPU")]


# Settings whose choices are known only once the server runs (the local models there are, the monitors the capture program
# reports): a saved value of theirs cannot be checked against its choices when the file is read, so it is checked for its
# shape. A model's name as Ollama writes it (letters, digits and . _ : / @ + -, as in hf.co/user/model:Q4_K_M), or none;
# a monitor's number. The file can come from elsewhere (./sidenote restore), and these values are printed: in a terminal
# (./sidenote status, which the desktop shortcut's starter reads for its marked lines) a carriage return or an escape
# code in one was a line of its own, or the terminal's own command
RUNTIME_CHOICES = ("local_model", "local_busy_model", "monitor")
MODEL_NAME = re.compile(r"[A-Za-z0-9._:/@+-]{1,200}")


def runtime_shaped(key: str, value: Any) -> bool:
    """Whether a saved value of a setting whose choices are filled at runtime has its kind's shape."""
    if key == "monitor":
        return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 64
    return isinstance(value, str) and (value == "" or bool(MODEL_NAME.fullmatch(value)))


class Settings:
    """Current values with persistence. `get` never fails: an unknown or broken value falls back to
    the default."""

    def __init__(self, path: Path | None):
        self.defs = {s.key: s for s in _defs()}
        self.path = path
        self.values: dict[str, Any] = {k: s.default for k, s in self.defs.items()}
        self.dynamic_options: dict[str, list] = {}   # filled at runtime (models, monitors)
        # Whether a setting switched off is to count as on for now, and why ("" for no): this PC's model standing in
        # for the agent at its limit (Pipeline.standing_in). It changes what on() says and nothing the panel shows,
        # so the switch keeps the value it was set to, and the settings that need it (the thinking, the web search, the
        # smaller model on a busy GPU) work while it stands in as they do when it is switched on.
        self.stand_in: Callable[[str], str] = lambda key: ""

    def load(self) -> None:
        if not self.path or not self.path.is_file():
            return
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("settings not restored (%s)", exc)
            return
        for k, v in saved.items():
            k = RENAMED.get(k, k)   # a key written before the cloud agent could be other than the agent
            if k == "agent_model_name" and isinstance(v, str):
                v = FAMILY.get(v.rsplit("-", 2)[0], v) if v.startswith("claude-") else v   # a version once chosen
            s = self.defs.get(k)
            if k in NOT_KEPT:   # written by an older server: not brought back
                continue
            v = s.clean(v) if s else v   # a file edited by hand: its words trimmed as the panel's are
            if s and isinstance(v, bool) and s.kind in ("choice", "int") and not any(isinstance(o[0], bool) for o in s.options):
                continue                 # true kept by an older server for a number ($1, monitor 1) is not one
            if s and (s.valid(v) or (s.kind in ("choice", "int") and k in RUNTIME_CHOICES and runtime_shaped(k, v))):
                self.values[k] = v
        log.info("settings restored: %s", {k: v for k, v in self.values.items() if v != self.defs[k].default})

    def save(self) -> None:
        if not self.path:
            return
        try:
            changed = {k: v for k, v in self.values.items() if v != self.defs[k].default and k not in NOT_KEPT}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except (OSError, ValueError) as exc:   # ValueError: text that cannot be written as UTF-8
            log.warning("settings not saved (%s)", exc)

    def get(self, key: str) -> Any:
        return self.values.get(key, self.defs[key].default)

    def on(self, key: str) -> bool:
        """The setting and everything it needs are on (or standing in for it, stand_in)."""
        return (bool(self.get(key)) or bool(self.stand_in(key))) and all(self.on(n) for n in self.defs[key].needs)

    def options(self, key: str) -> list:
        """The choices of a setting with their labels in the current language. One filled at runtime (set_options) may
        carry a label as (English text, {placeholder: value}), which is filled in here."""
        dynamic = self.dynamic_options.get(key)
        if not dynamic:
            return next((d.options for d in _defs() if d.key == key), self.defs[key].options)
        return [(v, t(label[0], **label[1]) if isinstance(label, tuple) else t(label)) for v, label in dynamic]

    def set(self, key: str, value: Any) -> tuple[bool, str]:
        s = self.defs.get(key)
        if s is None:
            return False, t("Unknown setting")
        value = s.clean(value)   # free words trimmed and the empty ones dropped, before they are judged
        options = self.dynamic_options.get(key, s.options) if s.kind in ("choice", "int") else []
        if isinstance(value, bool) and options and not any(isinstance(o[0], bool) for o in options):
            ok = False   # true is 1 to Python: it passed as $1 or as monitor 1, and was kept as true
        elif not _encodable(value):
            ok = False   # a lone surrogate (JSON can carry one) could not be saved, and broke every answer that showed it
        elif s.kind in ("choice", "int") and key in self.dynamic_options:
            # of the kind the options are as well as equal to one: 2.0 equals monitor 2, and was kept as 2.0
            ok = (any(value == o[0] for o in self.dynamic_options[key])
                  and (s.kind != "int" or (isinstance(value, int) and not isinstance(value, bool))))
        else:
            ok = s.valid(value)
        if not ok:
            label = next((d.label for d in _defs() if d.key == key), s.label)   # in the language of now
            # words as the panel sends them, too many or one too long: the limits are what to say
            if s.kind == "words" and isinstance(value, list) and all(isinstance(x, str) for x in value):
                return False, t("'{label}' takes up to {n} words of up to {m} characters each", label=label,
                                n=WORDS_MAX, m=WORD_MAX)
            return False, t("Not a value for '{label}'", label=label)
        self.values[key] = value
        self.save()
        telemetry.event("setting", key=key, value=value if key != "roi_box" else (value and [round(x, 3) for x in value]))
        return True, ""

    def set_options(self, key: str, options: list) -> None:
        self.dynamic_options[key] = options

    def snapshot(self) -> dict:
        return dict(self.values)

    def meta(self) -> dict:
        """What the panel needs to draw the settings sheet, its words in the current language (built again here, so a
        changed language is sent with the next message)."""
        words = {d.key: d for d in _defs()}
        return {"sections": sections(),
                "items": [{"key": s.key, "kind": s.kind, "section": s.section, "label": words[s.key].label,
                           "help": words[s.key].help, "opt_help": words[s.key].opt_help,
                           "options": self.options(s.key), "needs": s.needs, "default": s.default}
                          for s in self.defs.values()]}


SETTINGS = Settings(Path(telemetry.LOG_DIR) / ".settings.json" if telemetry.LOG_DIR else None)
