# Tests

The suites CI runs, in two groups. How they fit with CI and the deploy is in [docs/QA.md](../docs/QA.md).

- **Server and capture.** The server's code in mock mode (no GPU, no network, no cloud agent), and the capture
  program against made-up screens and sound devices.
- **Panel.** A copy of `panel/` served and driven in headless Chromium through Playwright, with a stand-in for the
  server's socket.

Each suite is a script that prints one line per check and a tally at the end, and exits non-zero when a check
failed.

```bash
tests/run.sh              # every suite
tests/run.sh server       # the server and capture suites
tests/run.sh panel        # the panel suites
tests/run.sh --list       # what a run would start (also with a group), without running anything
tests/run.sh --check      # every suite on disk is in a list and in this file
```

`tests/run.sh` prints one line per suite (its tally, and what it skipped), keeps each suite's whole output in
`logs/<suite>.log` in the output folder, and exits non-zero if any suite failed. Every suite runs with
`SIDENOTE_ANALYZER=mock` and `SIDENOTE_LANG=ko`, so the server's words are in Korean, as the checks read them
(`i18n_check.py` unsets it and checks both languages).

| Variable | What it is | Default |
|:---|:---|:---:|
| `PY` | an interpreter with the server's packages: runs the server group, and writes what the panel group needs from the server's own code | `python3` |
| `PW` | an interpreter with Playwright: runs the panel group | `python3` |
| `SIDENOTE_TEST_OUT` | where the logs, screenshots, the served copy of the panel and the settings message go | a new temporary folder |
| `SIDENOTE_BENCH` | the local model bench: real screenshots, and the answers the models wrote for them (`out-depth/`) | `scratch/local-llm-bench` |
| `SIDENOTE_CORPUS` | the public problem corpus, whose drawn figures the face cover must leave alone | `scratch/corpus-data` |
| `SIDENOTE_FACES` | the face photo the face cover is checked with (`face.jpg`, any frontal face) | `scratch/smoke/fixtures/faces` |

## Running them locally

The server group needs the server's packages (`server/requirements.txt` and `server/requirements-audio.txt`) and
`websocket-client`, which the capture program imports: the `.venv` that [CONTRIBUTING.md](../CONTRIBUTING.md) sets up
has them. `integ.py` also runs answers' code with `gcc`, `g++`, `node` and `bash`, as the code runner does.

The panel group needs Playwright with its Chromium, in a virtual environment of its own:

```bash
python3 -m venv .venv-panel
.venv-panel/bin/pip install -r tests/requirements-panel.txt
.venv-panel/bin/python -m playwright install chromium
```

and the panel's libraries, which are fetched (and checked against their checksums) rather than kept in git:

```bash
python3 docker/fetch_vendor.py docker/vendor.json panel/vendor
```

Then run every suite with those two interpreters. `./sidenote qa` does the same, with these defaults:

```bash
PY=.venv/bin/python PW=.venv-panel/bin/python tests/run.sh
```

One suite on its own runs the same way, from the repository's root:

```bash
SIDENOTE_ANALYZER=mock .venv/bin/python tests/integ.py
.venv/bin/python tests/server_review.py gap                     # only the named sections
PY=.venv/bin/python .venv-panel/bin/python tests/panel_viz.py   # PY: the prompt's examples come from the server
ONLY="bug 3,design 5" .venv-panel/bin/python tests/panel_review.py   # only the groups named
SKIP="motion" .venv-panel/bin/python tests/panel_layout.py            # all the groups but those named
SUITES="panel_layout" PW=.venv-panel/bin/python tests/run.sh panel   # only the suites named (SKIP_SUITES: all but those)
PANEL_DIR=/an/older/copy/of/panel .venv-panel/bin/python tests/panel_churn.py   # watch a check fail there
```

The suites that load the capture program take another copy of it as their first argument
(`tests/audio_path.py /path/to/capture.py`), and `tests/launcher_args.sh` another copy of the control script.

## In CI

Each group runs in a job of its own (`.github/workflows/ci.yml`), with one interpreter that has what the group
needs. `PY` and `PW` are left unset there, so both are that job's Python:

```bash
# the server job
pip install -r server/requirements.txt -r server/requirements-audio.txt -c docker/constraints.txt
pip install websocket-client -c docker/constraints.txt
tests/run.sh server

# the panel job
pip install -r tests/requirements-panel.txt -r server/requirements.txt -c docker/constraints.txt
python -m playwright install --with-deps chromium
python docker/fetch_vendor.py docker/vendor.json panel/vendor
tests/run.sh panel
```

The panel group runs as four jobs at once, chosen with `SUITES` and `SKIP_SUITES`, and `panel_layout` split by its
groups with `ONLY` and `SKIP` (the matrix in `ci.yml`): its longest group is the release notice in the band.

The measurement data is not there, so the checks that read it are skipped, and each suite that skipped some says how
many and why in its line (see "The measurement data" below). Every other check runs as it does locally.

`launcher_args.sh` runs the launcher itself, with every Windows program it calls stood in for. The launcher reaches
Windows through WSL: it finds the capture program's path with `wslpath` and starts Windows programs from `/mnt/c`. A
machine that is not WSL has neither, so `tests/run.sh` skips that suite there and says so in its line.

## The server as an ordinary user

`tests/nonroot_check.sh` brings up `compose.yaml`'s server and code runner with real images, as this user (as uid 1000
when this user is root), under another project's name and port, beside any Sidenote that is running. With made-up login
files it checks what no stand-in can show: the server reads the 600 logins and the CLIs find them, it writes in every
place it writes, a log folder an older image turned over to root comes back, the volume stays the user's in the next
container, and the socket lets the server in and keeps a run out. The `images` job of CI runs it.

```bash
tests/nonroot_check.sh                                # sidenote:local and sidenote-runner:local
tests/nonroot_check.sh sidenote:ci sidenote-runner:ci
```

`tests/offline_check.sh` brings up the same server and code runner on a network with no way out, set up as
[docs/air-gapped.md](../docs/air-gapped.md) says. It fails when a start waits on the internet or the page loads anything
from outside. CI's image job runs it after the build:

```bash
tests/offline_check.sh                                # sidenote:local and sidenote-runner:local
tests/offline_check.sh sidenote:ci sidenote-runner:ci
```

## The Helm chart on a cluster

`tests/k3d_check.sh` installs the chart on a throwaway k3d cluster with the images given (by default the ones
`./sidenote up` built) and checks what only a running cluster can show: the pods come up, `kubectl port-forward`
reaches the panel, the runner opens no connection and only the server reaches it, a run needs the runner's token
(also from inside the runner's pod), a request from the node is refused because the server trusts loopback alone,
the runner cleans up what a run left when its container restarts, the token survives an upgrade, and with Codex the
login is copied into a writable home. The local model stays off, so no GPU is used. The cluster is deleted at the
end and `~/.kube/config` is not touched.

```bash
tests/k3d_check.sh                                   # sidenote:local and sidenote-runner:local
K3D=/path/to/k3d HELM=/path/to/helm tests/k3d_check.sh sidenote:e2e sidenote-runner:e2e
```

The chart-e2e workflow runs it on a push that changes the chart, the images or the code inside them, and by hand.

## The measurement data

It stays out of the repository for its size and for what it holds: screenshots of other people's sites, the answers
the models wrote for them, and a photo of a face. The checks that read it find it through the variables above. When a
file is missing, the group of checks that needs it is skipped from the point where it asks for the file, and the
suite prints one line before its tally: how many groups it skipped, which, and what was missing.

| Data | Read by |
|:---|:---|
| `SIDENOTE_BENCH/real/spec/code_bj_ab.png`, a problem page from Baekjoon | `integ.py`: the face cover group, every check in it |
| `SIDENOTE_FACES/face.jpg`, a face photo pasted beside that problem | `integ.py`: the same group |
| `SIDENOTE_CORPUS/doocs/solution/...`, three problem figures (`illu_1.jpg`, `list.jpg`, `bomb2-grid.jpg`) | `integ.py`: the three checks that a drawn figure is not taken for a face, each on its own |
| `SIDENOTE_BENCH/out-depth/sidenote-gemma4_26b+both_dbase/*.md`, answers the local model wrote | `panel_review.py`: bug 1, 2, 3, 4, 7 and 9, design 1, 5, 8, 9 and 10. `panel_viz.py`: frame (F1 to F5). `panel_churn.py`: churn (C2 to C4), confirm (C5 to C7), continuation (C8, C9), redraw (C12), layout index (C18, C19), layout toast (C22, C23), rail (R4 to R6) |

## The suites

Server and capture (`PY`):

| Suite | What it checks |
|:---|:---|
| `integ.py` | the pipeline with the mock engines: settings, answer heads, routing between the local model and the agent, the spend brake, crops and windows, the example check run against real compilers, search, the face cover, the theme tokens |
| `agent_first.py` | the agent first, and the local model when the agent cannot: routing by speed and GPU, the first-token deadline, the thinking progress, a video beside a still problem, a drawn region, the verify mode on a 4K screen |
| `server_review.py` | thirteen defects of the server, each a check: the first-token hand-off, which scrolled problems continue an answer, a spoken question a screen stopped, the spend brake, the retry and continuation slots, the idle release, the GPU button, the example check between analyses |
| `worker_order.py` | the analysis worker: what starts, waits or is canceled between the screen and a spoken problem, an answer being written let finish with the newest speech waiting for it, the settle, the quiet after empty answers |
| `voice_trigger.py` | what counts as a problem read aloud and what is only the room's sound: tag questions, reported and rhetorical questions, a question from 6 characters, and what the panel is told about a sentence too short to take, or sound too short to write down that the live words show |
| `speech_hints.py` | what the speech model is given: a list of terms for each speech language, chosen by the language of the decode, **Extra terms** in front of them, the 223 tokens Whisper keeps; **Speech model**: the model chosen taking over at the next pass, and one that cannot be had leaving the one in use; what the engines are told about what was heard: the rule on stories and one answer language for both, a spoken problem with no question to pick out ending as nothing to solve, no emoji in the local model's headings |
| `heard_keep.py` | **Keep what is heard**: the table in `history.sqlite`, its age and size limits, that a long transcript pushes no answer out of the size cap, **Clear history**, what the speech pass writes with the switch on and off, `/heard` |
| `lang_vote.py` | the session's language vote over Whisper's odds, with a stand-in model |
| `stall_guard.py` | the watchdog that ends a stuck event loop, and the guard that keeps fork() away from speech decoding |
| `capture_loop.py` | the capture program's screen loop on made-up screens: a scrolled problem joined into one page, typing is no scroll, control and quit messages, no grabbing without a server |
| `up_wait.py` | `./sidenote up` waits while the server is in use (its `in_use` function against `/health` answers) |
| `ci_gate.py` | the CI check before a deploy (`SIDENOTE_CI_GATE=1`): a failed commit is refused, `--when-green` waits, what CI has not seen goes up and says so (the launcher's `ci_state` and `ci_gate`, with a stand-in `gh`) |
| `server_scenarios.py` | what real use has done to the server and the capture program: a restart in the middle of a problem, a reading mistaken for a busy GPU, a plan's limit outliving a new sign-in, a late probe of the agent's CLI, the averages, example headings, a tray menu whose program has gone |
| `models_check.py` | which local model fits which GPU: the GPU readers on NVIDIA, AMD (amd-smi, rocm-smi, sysfs) and DXGI output, the model profiles and the choice among pulled models, "auto" in the server, and a local server that is not Ollama |
| `desktop_check.py` | Sidenote on one PC without Docker (`desktop/`): the server's environment on the host, the data folder on each system, the capped logs, the port check, the watch that starts a stopped child again, the capture program's restart code, `python -c` in the built app, and a whole start and stop with stand-in models |
| `i18n_check.py` | the server's words in English or Korean: English with no language set, the panel's language on `ui_lang` and back, the settings, a notice and the agent's card in that language, a level on every notice, a Korean entry for every word the code asks for, `./sidenote report` in the terminal's language, and the line asking the models for an English answer only in English |
| `history_star.py` | starred answers in `history.sqlite`: a file from 0.1.0 gaining the column with its rows kept, a star set and taken off over the panel's socket and heard by a second panel, a refused id, the starred answers alone from `/history`, the pruning that keeps them past the age limit and outside the size cap, and **Clear history** |
| `report_period.py` | `./sidenote report`: the period's numbers by engine, the agent's cost split, the GPU and the example checks |
| `capture_update.py` | a deploy brings the capture program onto its new code: its code mark, the quiet restart, `capture_follow` |
| `capture_panel.py` | the capture program paints over this tool's own panel, and the panel's updates are no new screen |
| `capture_skip.py` | **Skip windows**: the window in front read on Windows and on X11 (both stood in for, and X11 on a private Xvfb display where Xvfb is installed), a word in its title or its program's name in any case, the default list, no screen grabbed or sent while one is in front and the same problem not sent again after it, sound going on, nothing of the window in the log, the words in the server's `control` message and their checks, a skip passed on to the panel, and the tray's state line |
| `scroll_auto.py` | a scroll told from a new screen, under a fixed header too; the tray icon's address and picture |
| `poll_rate.py` | the screen loop looks less often at a still screen and comes straight back on a change |
| `crop_grow.py` | the crop grows a box only where it is meant to: blocks of writing, halves of a screen, a drawn region, lines across a window |
| `audio_path.py` | the sound device is read on time while a send is stuck, and not at all without a server |
| `audio_gaps.py` | the line about dropped sound says whether this program fell behind |
| `tray_switch.py` | the tray's screen and sound switches go through the server, as the panel's do |
| `codex_agent.py` | Codex through its CLI, the agent chosen by the environment, the newest model of a family |
| `repeats_check.py` | a problem seen again (scrolled, moved, come back to) is not solved again, and an agent at its usage limit rests until it comes back |
| `limits_check.py` | why analyses stopped and what the agent was paid for, from the log; the local model, switched off, standing in for the agent at its limit; the thinking pass's last sentence; code run on made-up inputs when a problem shows none; Codex's reset times and missing prices, the API agent's stop reasons, a status code inside a request id; the chart's runner token rendered without a cluster ([note 89](../docs/DECISIONS.md#note-89)) |
| `update_check.py` | the check for a newer release, against a stand-in for GitHub: a newer release, the same, an older one, a pre-release, a draft, a reply that is not JSON, a timeout and the rate limit; the User-Agent, no token, the ETag, no retry before the next day's; a release page outside this repository refused; "Check for new versions", `SIDENOTE_UPDATE_CHECK=0` and mock mode each making no request; the loop stopping when the server closes down, a cancellation as the switch wakes it included; the notice reaching a panel that connects later |
| `changelog_check.py` | CHANGELOG.md and the notes release.yml takes from it: every release's section and link, the newest being `server/version.py`'s number, a section printed whole, a tag with no notes stopped before anything is built |
| `version_check.py` | one version: `server/version.py` and the Helm chart agree, the release step's script (`.github/check_version.py`) with matching and mismatching fake tags and trees, `release.yml`'s release job running it before it builds or pushes anything, `./sidenote version` printing the number, the chart's README and NOTES naming no other version or path, what a pre-release tag publishes, the winget token staying in its one step, and the small facts the docs state |
| `launcher_args.sh` | what `./sidenote` hands to Windows, and how it behaves when a program it calls is missing or broken |

Panel (`PW`):

| Suite | What it checks |
|:---|:---|
| `panel_scroll.py` | the page is the one scroller, and no card of the rail is clipped |
| `panel_run.py` | the run box when code reads input and none is typed, and the marks on its bar |
| `panel_asks.py` | the follow-up buttons under the newest answer |
| `panel_settings.py` | the settings sheet: no native dropdowns, the keyboard in a dropdown, lists not cut off, one family of controls, and the box of words of **Skip windows** (its look beside the dropdown, Enter, Tab and Escape, a redraw while it is typed in, a press after typing) |
| `panel_review.py` | ten bugs and eleven design faults of the panel, each a check |
| `panel_viz.py` | charts and diagrams in an answer under the server's CSP, tilde ranges, code read as in an editor, the frame round the sheets |
| `panel_churn.py` | superseded looks, redraws that keep a press, a caret and an open follow-up, the layout, the rail, code still being written |
| `panel_limits.py` | the thinking's last sentence while it thinks, finding and exporting the answers, a notice that brings its answer into view, the agent resting at its limit with the local model standing in |
| `panel_new.py` | the highlighter, the contents inside their card, the rail's rows, history over a reconnect, the filters, Export and a long answer drawn live, on Classic (New (Beta) is switched off; one check keeps it off) |
| `panel_star.py` | starred answers: the star key on an answer's head and what pressing it sends, the server's star drawn on every panel and on the contents' row, stars from the history and after a reconnect, the **Starred** choice in the contents and the notebook, Export of it, and **Clear history** |
| `panel_heard.py` | the spoken side of the panel: why a sentence on **What is heard** was not taken, under that sentence; the keys to what is kept and its sheet (a day's lines with their times, **Copy all**, a `.md` file, the ways out); **Keep what is heard**, **Extra terms** and **Speech model** in the Speech section; two answers one after the other when speech goes on while one is written |
| `panel_scenarios.py` | whole sittings: the place in the thread through focus, picks, filters and resizes, a dropped connection, messages out of order, hostile and broken answers, a sitting of 400 answers, boxes on portrait and ultrawide screens, the keys |
| `panel_study.py` | Practice: an answer kept back as it arrives, its hints in order and the answer last, across a reload, with nothing of it in the contents, their search, Problem text, the copy keys or a screen reader's note, and the answers from before left alone; the keyboard shortcuts, and nothing while typing or with a modifier held; the Anki file read as Anki reads it, for answers with code, tables and formulas; a Korean word for every word the panel shows |
| `panel_design.py` | what the design promises, measured: one color down the column off a screenshot, the column at 5 widths by 8 heights, the ribbon, contrast, and each answer drawn from its words with none lost; Practice's keys, the gear menu, the keys' sheet and Export's menu at 8 widths from 360 to 2560 px in both themes, with their contrast; the box of **Skip windows** and the screen card's **Skipped window** in both themes from 360 to 2560 px; **What is heard** with its note and its key, the sheet of what was kept, and the Speech section in both themes from 360 to 2560 px; the release notice from 360 to 2560 px, in both themes and both languages |
| `panel_lang.py` | the panel's language: English for an English browser, with no Hangul in what it shows across the page's states other than what answers say; Korean for a Korean browser or `?lang=ko`; the language told to the server first; the Korean particle after a word; a notice's level. The other panel suites open Korean pages (`support.LOCALE`) and read the Korean words |
| `panel_layout.py` | an audit of the page as laid out, over 33 states of the column at 11 sizes, 22 shapes of answer and what opens over the page (Practice's menu and card, the keys' sheet, Export's menu and the sheet of what was heard among them, from 360 to 2560 px, each found with a fault planted in it; the settings sheet with the server's settings in it at six sizes too): words cut, out of their box or over each other, rows and columns a few pixels off, keys with their words off the middle; and the release notice in the band at 9 widths, in both themes and both languages. Plants a defect of each kind to see it found. The panel's parts, check by check (the star key at 11 widths from 360 to 2560 px in both themes), and motion: nothing loops at rest, what comes in comes once and ends where it would have stood. `ONLY="the audit,motion"`, `LAYOUT_SIZES=1920x1080` and `AUDIT_REPORT=path` narrow it |
| `panel_update.py` | the version at the foot of the gear menu, and a newer release as one line in the band: its link to the release notes, a link outside the repository left out, the close key hiding it for that version (with the browser's storage refused too), the switch off hiding it, the switch saying why when `SIDENOTE_UPDATE_CHECK=0` leaves it nothing to do, in English and Korean |

`data/answers/` holds answers written by hand in the shape of eight of the bench's, for the groups of `panel_review`,
`panel_churn` and `panel_viz` that read them: with the bench missing, as in CI, those groups run on these instead of
being skipped.

Beside them: `fake_claude.py` and `fake_codex.py` stand in for the `claude` and `codex` CLIs (`integ.py` and
`codex_agent.py` run them), and `support.py` holds what the suites share: the paths above, the settings message, a
fresh copy of the panel and the skip line.
