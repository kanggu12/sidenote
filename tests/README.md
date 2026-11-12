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
reaches the panel, the runner opens no connection and only the server reaches it (a pod with another release's server
labels does not, one with this release's does), a run needs the runner's token
(also from inside the runner's pod), a request from the node is refused because the server trusts loopback alone,
the runner cleans up what a run left when its container restarts, the token survives an upgrade, and with Codex the
login is copied into a writable home. The local model stays off, so no GPU is used. The cluster is deleted at the
end and `~/.kube/config` is not touched.

```bash
tests/k3d_check.sh                                   # sidenote:local and sidenote-runner:local
K3D=/path/to/k3d HELM=/path/to/helm tests/k3d_check.sh sidenote:e2e sidenote-runner:e2e
```

The chart-e2e workflow runs it on a push that changes the chart, the images or the code inside them, and by hand.

`tests/chart_check.py` needs no cluster: it renders the chart for two releases in one namespace and checks that no two
objects share a name and none is cluster-wide, that every NetworkPolicy selects and lets in its own release's pods
only, that every container (init containers too) asks for CPU and memory and has a limit on both, and that no pod
gets a token for the cluster's API. It needs helm and PyYAML; the CI's chart job runs it.

```bash
.venv/bin/python tests/chart_check.py
```

## The Mac app as the Finder opens it

`tests/mac_app_open.py` opens a built `Sidenote.app` through LaunchServices, as a double-click in the Finder does,
with a data folder and a port of its own and a stand-in browser that writes down each address it is given. It checks
what only macOS itself can show: the server, the capture program and its menu bar icon come up and the panel is
opened; opening the app again while it runs starts no second copy and opens the panel again; and a quit sent as the
system sends one at log out ends the app and all it started, with the server's own close-down run. On CI it also puts a
stand-in for Claude Code's CLI in a folder that only the login shell's start-up files add to `PATH` (a line in
`~/.zprofile` and `~/.bash_profile`, taken out again at the end) and checks that the app finds it there. It needs a Mac
with no Sidenote running; the desktop workflow's macOS job runs it on the app it has just built.

```bash
python tests/mac_app_open.py dist/Sidenote.app
```

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
| `local_fallback.py` | this PC's model not answering and the agent taking the problem (design note 117): the thinking pass given up when no token comes by `local_think_first_token_sec` (a cold model by `local_cold_first_token_sec`) or its stream goes silent for `local_stuck_sec`, the GPU counted busy unless another request of this server was streaming; the problem handed to the agent on the same card with a note; not when the agent is off, braked, held back or has had it; both failing said on the card; the verify mode's direct pass the same |
| `server_review.py` | thirteen defects of the server, each a check: the first-token hand-off, which scrolled problems continue an answer, a spoken question a screen stopped, the spend brake, the retry and continuation slots, the idle release, the GPU button, the example check between analyses |
| `worker_order.py` | the analysis worker: what starts, waits or is canceled between the screen and a spoken problem, an answer being written let finish with the newest speech waiting for it, an answer done let end rather than cut and asked again, and a pause during its end starting nothing after it, the words a problem went out in kept once its card is done and not for a decline, the settle, the quiet after empty answers |
| `voice_trigger.py` | what counts as a problem read aloud and what is only the room's sound: tag questions, reported and rhetorical questions, a question from 6 characters, and what the panel is told about a sentence too short to take, or sound too short to write down that the live words show |
| `speech_hints.py` | what the speech model is given: a list of terms for each speech language, chosen by the language of the decode, **Extra terms** in front of them, the 223 tokens Whisper keeps; **Speech model**: the model chosen taking over at the next pass, and one that cannot be had leaving the one in use; what the engines are told about what was heard: the rule on stories and one answer language for both, a spoken problem with no question to pick out ending as nothing to solve, no emoji in the local model's headings |
| `heard_keep.py` | **Keep what is heard**: the table in `history.sqlite`, its age and size limits, that a long transcript pushes no answer out of the size cap, **Clear history**, what the speech pass writes with the switch on and off (from the moment it is turned on, not the sound before), `/heard` |
| `lang_vote.py` | the session's language vote over Whisper's odds, with a stand-in model; the live line does not vote |
| `stall_guard.py` | the watchdog that ends a stuck event loop, and the guard that keeps fork() away from speech decoding |
| `capture_loop.py` | the capture program's screen loop on made-up screens: a scrolled problem joined into one page, typing is no scroll, control and quit messages, no grabbing without a server |
| `up_wait.py` | `./sidenote up` waits while the server is in use (its `in_use` function against `/health` answers) |
| `ci_gate.py` | the CI check before a deploy (`SIDENOTE_CI_GATE=1`): a failed commit is refused, `--when-green` waits, what CI has not seen goes up and says so (the launcher's `ci_state` and `ci_gate`, with a stand-in `gh`) |
| `server_scenarios.py` | what real use has done to the server and the capture program: a restart in the middle of a problem, a reading mistaken for a busy GPU, a plan's limit outliving a new sign-in, a late probe of the agent's CLI, the averages, example headings, a tray menu whose program has gone |
| `models_check.py` | which local model fits which GPU: the GPU readers on NVIDIA, AMD (amd-smi, rocm-smi, sysfs) and DXGI output, the model profiles and the choice among pulled models, "auto" in the server, and a local server that is not Ollama |
| `desktop_check.py` | Sidenote on one PC without Docker (`desktop/`): the server's environment on the host, the data folder on each system, the capped logs, the port check, the watch that starts a stopped child again, the capture program's restart code, `python -c` in the built app, a whole start and stop with stand-in models, a start while another copy closes down (its server gone or still answering) or runs, and a server that ends at once with jobs still running on its threads, what it left running cancelled |
| `desktop_restart.py` | the desktop app's watch counts only the ends nobody asked for: a capture program restarted from its tray (exit code 75) five times in ten minutes no longer ends the app, and one another capture program took over from (exit code 77) is started again where an end with 0 would end the app, with real child processes standing in for the server and the capture program |
| `i18n_check.py` | the server's words in English or Korean: English with no language set, the panel's language on `ui_lang` and back, the settings, a notice and the agent's card in that language, a level on every notice, a Korean entry for every word the code asks for, `./sidenote report` in the terminal's language, and the line asking the models for an English answer only in English |
| `history_star.py` | starred answers in `history.sqlite`: a file from 0.1.0 gaining the column with its rows kept, a star set and taken off over the panel's socket and heard by a second panel, a refused id, the starred answers alone from `/history`, the pruning that keeps them past the age limit and outside the size cap, **Clear history**, and a new install told as one (no answer kept yet) for the setup guide |
| `history_delete.py` | one answer deleted, in `history.sqlite` and over the panel's socket: a file from 0.5 gaining the column with its rows kept, an answer deleted leaving the list, the search, the days and the starred count and held whole in **Recently deleted**, put back as it was, its days there (`SIDENOTE_DELETED_DAYS`, none for no end), the size cap taking the deleted first, **Delete for good** and **Empty** leaving none of its words in the file, the log beside it or the server's memory, a delete and an Undo heard by a second panel, an answer still being written refused, one the history never held put back by the panels, the last answer (no question about it while deleted, its follow-ups, Undo, a newer answer, the screen or the sound switched off meanwhile), its problem seen again pointing back to no card, **Clear history** taking **Recently deleted** too, and a server that starts knowing what was deleted |
| `stalled_panel.py` | a panel that stops reading, against a real server on a free port: every API write that sends to the panels goes at once, the other panel gets every message, the silent one is closed within its time, and SIGTERM ends the server within its shutdown wait with what it keeps at its end; and the container's and the desktop app's servers are started with that wait |
| `many_clients.py` | several clients of one server, against a real server on a free port: a capture program that connects while another feeds the server takes over (the one before is asked to quit with the reason and the newer one's name, what it still sends is not taken, the count and the card are the newer one's, the panels are told), one that does not end itself is closed 10 s on, a program's own earlier connection (the same run) is closed at once with no word, a --once run, a connection that never says hello and one taken over before its late hello take nothing over, client/capture.py's Sender never connects again once asked to quit and takes no restart after it, the capture program itself (on a private Xvfb display, its screen grabber stood in for) keeps running beside a real --once run with the drawn region kept and, taken over, ends with exit code 77 and says why, and 40 panels opening together with 32 let in and the rest refused at the handshake; with the server started as docker/entrypoint.sh starts it, 8 capture connections and the 9th refused, a panel's message over 2 MB closed with 1009, 512 connections held open and the next request a 503 with uvicorn's warning written once, and the desktop app's server started with the same cap |
| `session_end.py` | whoever starts the server stops it: what the tray's Quit may run (its own checkout's `./sidenote down` and nothing else, from a WSL path, in a login shell, or a checkout folder; another checkout refused), which ends run it (the person's Quit alone, never capture-stop, down, a take-over, a restart or the desktop app), the menu's words, and the capture program itself on a private Xvfb display: Quit Sidenote pressed ends it with 0 and runs ./sidenote down, and capture-stop, a take-over and a plain Quit run nothing |
| `api_check.py` | the API (`docs/API.md`): every message the panel sends has a route, in the index and on the page, and runs there as from the panel (the same replies, an open panel told the same); the reads; an answer followed from its screen to its follow-up, its star and **Clear history**; another site's page, a write that is not JSON (or holds `NaN`, a number past a float or a lone surrogate) and a Host not of this PC refused; a second download while one is under way refused; 8 questions at once taken and the next refused (429, and a warning to the panel that asked); a body just under 2 MB taken and one over it refused with 413 and its connection closed, said in advance or sent in pieces; the events from a real server on a port of its own, and the page's own examples run against it |
| `report_period.py` | `./sidenote report`: the period's numbers by engine, the agent's cost split, the GPU and the example checks |
| `capture_update.py` | a deploy brings the capture program onto its new code: its code mark, the quiet restart, `capture_follow` |
| `capture_panel.py` | the capture program paints over this tool's own panel, and the panel's updates are no new screen |
| `capture_skip.py` | **Skip windows**: the window in front read on Windows and on X11 (both stood in for, and X11 on a private Xvfb display where Xvfb is installed), a word in its title or its program's name in any case, the default list, no screen grabbed or sent while one is in front and the same problem not sent again after it, sound going on, nothing of the window in the log, the words in the server's `control` message and their checks, a skip passed on to the panel, and the tray's state line |
| `scroll_auto.py` | a scroll told from a new screen, under a fixed header too; the tray icon's address and picture |
| `poll_rate.py` | the screen loop looks less often at a still screen and comes straight back on a change |
| `crop_grow.py` | the crop grows a box only where it is meant to: blocks of writing, halves of a screen, a drawn region, lines across a window |
| `audio_path.py` | the sound device is read on time while a send is stuck, and not at all without a server |
| `audio_gaps.py` | the line about dropped sound says whether this program fell behind |
| `tray_switch.py` | the tray's screen and sound switches go through the server, as the panel's do; on macOS the icon runs on the main thread, a quit that comes before its loop runs is kept, and the app opened again opens the panel |
| `launch_window.py` | the desktop shortcut's windows (`client/launch.pyw`) wear the tray menu's colours and fonts and speak both languages; a failure and a note show in the same window, its end in view, closed by Esc or its key; a failure keeps a long line whole and shows the bar stopped where it failed, a note stands above the start's window, the start's bar fills its part under way and draws nothing before it has a length, the launcher's last line shows under it without its colour codes or markers, the logo is client/logo.png (with no Pillow the name is written and the bar kept), and over a white, a dark and a blue desk the frosted glass shows each (lighter, darker, blue) while every word on it keeps 4.5:1 and dots; drawn on a virtual display where Tk and Xvfb are at hand |
| `start_output.py` | the shortcut's start window reading the launcher's output as it is written (`client/launch.pyw`: `run`, `reader`, `latest_line`) on the system it runs on, with no window: Windows through a handle of its own (CreateFileW), POSIX at an offset; the line read follows the lines printed, one line at a time (a line cut as it is written, inside its number too, is one line's beginning; two run together are not), and the launcher's own output arrives whole and in order, at a start's pace and as fast as lines come. The desktop workflow runs it on Windows, macOS and Linux |
| `capture_single.py` | one capture program at a time for a server: the guard a capture program holds (a lock on a file, dropped with the process; the named mutex Windows uses is not reached here), a second start ending with exit code 76 and two lines before it connects or captures, the starts never refused (a program restarting itself, one under the desktop app, `--once`), and the desktop shortcut opening the panel where a program holds the guard |
| `launch_setup.py` | `client/launch.pyw` typed in a Windows terminal, for a WSL that cannot start Windows programs: `--setup` (the capture packages and the desktop shortcut, the start command for a Windows terminal, PowerShell's own words when the shortcut cannot be made) and `--remove`, with PowerShell and pip stood in for |
| `codex_agent.py` | Codex through its CLI, the agent chosen by the environment, the newest model of a family |
| `repeats_check.py` | a problem seen again (scrolled, moved, come back to) is not solved again, and an agent at its usage limit rests until it comes back |
| `limits_check.py` | why analyses stopped and what the agent was paid for, from the log; the local model, switched off, standing in for the agent at its limit; the thinking pass's last sentence; code run on made-up inputs when a problem shows none; Codex's reset times and missing prices, the API agent's stop reasons, a status code inside a request id; the chart's runner token rendered without a cluster ([note 89](../docs/DECISIONS.md#note-89)) |
| `update_check.py` | the check for a newer release, against a stand-in for GitHub: a newer release, the same, an older one, a pre-release, a draft, a reply that is not JSON, a timeout and the rate limit; the User-Agent, no token, the ETag, no retry before the next day's; a release page outside this repository refused; "Check for new versions", `SIDENOTE_UPDATE_CHECK=0` and mock mode each making no request; the loop stopping when the server closes down, a cancellation as the switch wakes it included; the notice reaching a panel that connects later |
| `changelog_check.py` | CHANGELOG.md and the notes release.yml takes from it: every release's section and link, the newest being `server/version.py`'s number, a section printed whole, a tag with no notes stopped before anything is built |
| `version_check.py` | one version: `server/version.py` and the Helm chart agree, the release step's script (`.github/check_version.py`) with matching and mismatching fake tags and trees, `release.yml`'s release job running it before it builds or pushes anything, `./sidenote version` printing the number, the chart's README and NOTES naming no other version or path, what a pre-release tag publishes, and the small facts the docs state |
| `launcher_args.sh` | what `./sidenote` hands to Windows, and how it behaves when a program it calls is missing or broken; a `capture --up` that brought the server up handing the capture program its checkout (and one that found it running, or whose container ran with `/health` late, handing nothing), on WSL's own start and on the one launch.pyw makes, and waiting for a down on its way; with interop off, the start handed to `client/launch.pyw` and its `--setup`, and `capture-stop` through the server; `uninstall` saying what it removes and keeps, and `--data`; `backup` and `restore` (never over a file that is there, the server stopped for the swap, what was there kept); `llm rm`; why `status` says the server is off (`.ended`, its exit code); the GPU file picked for AMD and its render group; the Compose plugin and its version in `doctor` |
| `entrypoint_loop.sh` | the loop a container's program runs in (`docker/keep-running.sh`) and the server's entrypoint: a program that keeps failing started 5 times and then left ended with `.ended` saying so, one that ends well not started again, the watchdog's `stall.txt` in the note, TERM and INT ending it and USR1 reaching it, the children a run killed outright left ended before the next run, compose.yaml running the model server, the code runner and SearXNG in the loop, and the shutdown wait and the cap on connections; under `/bin/sh` with stand-ins for uvicorn |

What only a real system draws is looked at on one, by `.github/look/`: `windows.py` draws the capture's windows on a
Windows runner's desktop and ends 1 when one has a taskbar button, takes the focus, draws no shadow or has a word under
4.5:1 (the desktop workflow's Windows job runs it), and `safari.py` measures the panel's top layers in Safari on a
macOS runner (the look workflow, run by hand). Both end at once anywhere but a runner: one draws over the whole
screen, the other drives Safari's own windows.

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
| `panel_delete.py` | deleting an answer: the delete key on every finished card (an error's on its title's line) and what pressing it sends, the card leaving every panel at the server's word, the notice with **Undo** (and `z`), the keyboard going on to the next card's key, messages still on their way about a deleted answer, a card the history never held, the **Recently deleted** sheet (**Restore**, **Delete for good** and **Empty**, each asking twice where it cannot be undone), **Clear history** taking it, an answer deleted while the connection was down, and the key, the notice and the sheet in a wide, a narrow and a low window, in English too |
| `panel_heard.py` | the spoken side of the panel: why a sentence on **What is heard** was not taken, under that sentence; the keys to what is kept and its sheet (a day's lines with their times, **Copy all**, a `.md` file, the ways out); **Keep what is heard**, **Extra terms** and **Speech model** in the Speech section; two answers one after the other when speech goes on while one is written |
| `panel_reading.py` | an answer read at a glance: what was heard in paragraphs, its first lines and the whole on a press, its end when folded; a summary of several sentences marked at its point and a line for each of the rest; the engines' cards folded on a key and kept so; and at its edges: a summary not cut inside a **bold** pair or after Dr., a folded tail keeping its end on a phone, the key only under a text that does not fit, a text opened whole kept so, the card name's tooltip; and what the fourth review found: the choices a list written with a word between them names, an image's alt text with arrows kept whole, no empty Solution row under an answer line alone, a head as tall while its answer is written as when it is done, the line read kept where it is as the answer around it ends, and the line under an answer on one baseline with the web fonts blocked |
| `panel_capture.py` | the Capture connection: opened from the menu, the capture card's foot, the band, the welcome and the tray's item (`?open=capture`, once, the address put back); its card in each state (none, connected, another release, a program that says nothing of itself, under the app); the wait with its seconds and, past a minute, where to look; the ways to start one by where the server runs (its own PC, another PC folded under it, a cluster's port-forward, the app), each command with its Copy key and the page's port, `py -3` from a browser on Windows; the tick for a program that comes while it is open and none for one that takes over; Restart and Quit sent, Quit asking twice; the settings it holds; the card's foot; and at 360 px |
| `panel_setup.py` | the setup guide: opened from the menu and once by itself on a new install, its five steps walked and closed; its first, the capture program's connection (the wait, the ways, the tick when one comes, and the screen step's way back to it); each step's states as the cards say them, its settings pressed as in Solver settings, the screen it receives, what is heard, and the sample problem followed to its answer; at 390 px; every way the sample can end (an error, a call-off, a repeat, a dropped connection, Practice, no head line); and what it keeps while the server talks (an open list, the picture, the words in a box at Escape, a screen asked for after it closed) |
| `panel_scenarios.py` | whole sittings: the place in the thread through focus, picks, filters and resizes, a dropped connection, messages out of order, hostile and broken answers, a sitting of 400 answers, boxes on portrait and ultrawide screens, the keys |
| `panel_study.py` | Practice: an answer kept back as it arrives, its hints in order and the answer last, across a reload, with nothing of it in the contents, their search, Problem text, the copy keys or a screen reader's note, and the answers from before left alone; the keyboard shortcuts, and nothing while typing or with a modifier held; the Anki file read as Anki reads it, for answers with code, tables and formulas; a Korean word for every word the panel shows |
| `panel_design.py` | what the design promises, measured: one color down the column off a screenshot, the column at 5 widths by 8 heights, the ribbon, contrast, and each answer drawn from its words with none lost; Practice's keys, the gear menu, the keys' sheet and Export's menu at 8 widths from 360 to 2560 px in both themes, with their contrast; the box of **Skip windows** and the screen card's **Skipped window** in both themes from 360 to 2560 px; **What is heard** with its note and its key, the sheet of what was kept, and the Speech section in both themes from 360 to 2560 px; the release notice from 360 to 2560 px, in both themes and both languages; the words read kept in place as an answer ends above them |
| `panel_lang.py` | the panel's language: English for an English browser, with no Hangul in what it shows across the page's states other than what answers say; Korean for a Korean browser or `?lang=ko`; the language told to the server first; the Korean particle after a word; a notice's level. The other panel suites open Korean pages (`support.LOCALE`) and read the Korean words |
| `panel_layout.py` | an audit of the page as laid out, over 33 states of the column at 11 sizes, 22 shapes of answer and what opens over the page (Practice's menu and card, the keys' sheet, Export's menu and the sheet of what was heard among them, from 360 to 2560 px, each found with a fault planted in it; the settings sheet with the server's settings in it at six sizes too): words cut, out of their box or over each other, rows and columns a few pixels off, keys with their words off the middle; and the release notice in the band at 9 widths, in both themes and both languages. Plants a defect of each kind to see it found. The panel's parts, check by check (the star key at 11 widths from 360 to 2560 px in both themes), and motion: nothing loops at rest, what comes in comes once and ends where it would have stood. `ONLY="the audit,motion"`, `LAYOUT_SIZES=1920x1080` and `AUDIT_REPORT=path` narrow it; and the column, the welcome and a phone's heads (the Local model's pill beside its English GPU key, the welcome with the server gone, a spoken problem's head on a phone, a choice's keys on a narrow sheet, the capture card's values in English) |
| `panel_update.py` | the version beside the name in the bar, linking to its release notes, and at the foot of the gear menu, and a newer release as one line in the band: its link to the release notes, a link outside the repository left out, the close key hiding it for that version (with the browser's storage refused too), the switch off hiding it, the switch saying why when `SIDENOTE_UPDATE_CHECK=0` leaves it nothing to do, in English and Korean |

`data/answers/` holds answers written by hand in the shape of eight of the bench's, for the groups of `panel_review`,
`panel_churn` and `panel_viz` that read them: with the bench missing, as in CI, those groups run on these instead of
being skipped.

Beside them: `fake_claude.py` and `fake_codex.py` stand in for the `claude` and `codex` CLIs (`integ.py` and
`codex_agent.py` run them), and `support.py` holds what the suites share: the paths above, the settings message, a
fresh copy of the panel and the skip line.
