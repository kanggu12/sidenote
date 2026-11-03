"""The local models Sidenote knows how to drive, and which one fits a given GPU.

A profile says what the server needs to know about one model: the name Ollama pulls, the tuned copy Sidenote makes
from it, how much GPU memory it takes with Sidenote's context, the grid its boxes are written on, how its thinking is
turned off, the smaller model used while another program keeps the GPU busy, and whether it has been measured on
Sidenote's bench. A model with no profile gets GENERIC, which assumes the common conventions, so any vision model a
local server offers can be chosen in the panel.

The standard library only: `./sidenote` and the installers read it through server/hardware.py before anything else
is installed.

To add a model: a Profile below with its numbers, its key in TIERS when it should be suggested for a GPU, and a
measurement on real problems before `tested=True` (CONTRIBUTING.md, "Add a local model").
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

# Ollama's default batch of 512 caps an image at 512 tokens, which blurs small code text in a screenshot; the tuned
# copy takes 1152 (627 image tokens, 21.9 of 23 GB for the 26b on a 24 GB card)
TUNED_BATCH = {"num_batch": 1152}
# Room left beside the model on the GPU (the desktop, the browser) before a size is said to fit
MARGIN_GB = 0.5


@dataclass(frozen=True)
class Profile:
    key: str                      # a short name: family and size ("gemma4:26b")
    pattern: str                  # a regular expression matched against a model's full name, tag included
    pull: str                     # what the local server pulls
    tuned: str = ""               # the copy Sidenote creates from `pull` with `params` ("" to use `pull` as it is)
    params: dict = field(default_factory=dict)   # the tuned copy's model parameters
    vram_gb: float = 0.0          # GPU memory it needs with Sidenote's context and image size
    box_scale: int = 1000         # the grid of the boxes it writes: 1000 for 0-1000, 100 for percent
    think_off: dict = field(default_factory=lambda: {"reasoning_effort": "none"})   # request fields that turn thinking off (Ollama)
    smaller: str = ""             # the profile used while another program keeps the GPU busy
    tested: bool = False          # measured on Sidenote's bench: answers, boxes and timing
    note: str = ""                # one line for the setup page
    size_gb: float = 0.0          # what the download weighs, as Ollama lists it (0: not known), said beside the Download button

    @property
    def name(self) -> str:
        """The name the server asks the local model server for."""
        return self.tuned or self.pull

    def matches(self, model: str) -> bool:
        return re.search(self.pattern, model or "", re.IGNORECASE) is not None

    def to_dict(self) -> dict:
        return {**asdict(self), "name": self.name}


PROFILES: tuple[Profile, ...] = (
    Profile("gemma4:26b", r"^(sidenote-)?gemma4:26b", "gemma4:26b", "sidenote-gemma4:26b", TUNED_BATCH, 22.0,
            smaller="gemma4:e4b", tested=True, note="Mixture of experts, about 4B active: fast for its size", size_gb=18.0),
    Profile("gemma4:31b", r"^(sidenote-)?gemma4:31b", "gemma4:31b", "sidenote-gemma4:31b", TUNED_BATCH, 26.0,
            smaller="gemma4:e4b", note="Dense; slower than the 26b"),
    # Measured with the agent off: 34 of 56, every spoken question and every problem area cut right, 3 of 7 coding answers,
    # a screen with nothing on it in 0.7 s.
    Profile("gemma4:e4b", r"^(sidenote-)?gemma4(:e4b|:latest)?$", "gemma4:e4b", "sidenote-gemma4:e4b", TUNED_BATCH, 9.0,
            smaller="gemma4:e2b", tested=True, note="Finds and cuts problems well; code is better left to the agent",
            size_gb=6.6),
    # Measured on the known-answer set with the agent off: 24 of 56 answers right, a screen with nothing on it in
    # 0.65 s, 7 of 8 spoken questions, but 1 of 7 coding answers and no current facts: on an 8 GB GPU it finds the
    # problems and answers the short ones, and the cloud agent should take the rest.
    Profile("gemma4:e2b", r"^(sidenote-)?gemma4:e2b", "gemma4:e2b", "sidenote-gemma4:e2b", TUNED_BATCH, 6.0,
            tested=True, note="Finds problems and answers short ones; leave the hard ones to the agent", size_gb=4.6),
)
GENERIC = Profile("generic", r".", "")
# The sizes suggested for a GPU, the largest first: the first that fits is suggested. Only measured ones are here
TIERS: tuple[str, ...] = ("gemma4:26b", "gemma4:e4b", "gemma4:e2b")


def by_key(key: str) -> Profile | None:
    return next((p for p in PROFILES if p.key == key), None)


def profile_for(model: str | None) -> Profile:
    """The profile of a model by its name (tuned copy or not), or GENERIC."""
    return next((p for p in PROFILES if p.matches(model or "")), GENERIC)


def fits(vram_gb: float | None) -> Profile | None:
    """The largest suggested model that fits this much GPU memory, or None (use a cloud agent, or the CPU)."""
    if vram_gb is None:
        return None
    for key in TIERS:
        p = by_key(key)
        if p is not None and p.vram_gb + MARGIN_GB <= vram_gb:
            return p
    return None


def choose(pulled: list[str], vram_gb: float | None = None) -> str | None:
    """The model to use when none is set: among those the local server has, the largest measured one that fits the
    GPU (any measured one when the GPU's memory is not known), else the first it has. None when it has none."""
    if not pulled:
        return None
    ranked = []
    for name in pulled:
        p = profile_for(name)
        fit = vram_gb is None or p is GENERIC or p.vram_gb + MARGIN_GB <= vram_gb
        # those that fit first, then the measured ones, then the larger, then the tuned copy over the plain pull
        ranked.append((fit, p.tested, p.vram_gb, name == p.tuned, name))
    return max(ranked)[-1]


def smaller_for(model: str | None, pulled: list[str]) -> str:
    """The smaller model for a busy GPU, when the local server has it ("" otherwise)."""
    p = by_key(profile_for(model).smaller)
    if p is None:
        return ""
    return next((n for n in (p.tuned, p.pull) if n and n in pulled), "")


def wanted(model: str | None) -> list[str]:
    """What `./sidenote llm pull` and the setup page fetch for a model: the model, and its smaller one."""
    p = profile_for(model)
    if p is GENERIC:
        return [model] if model else []
    small = by_key(p.smaller)
    return [p.name] + ([small.name] if small is not None else [])
