# Sidenote user guide

Sidenote solves the problems on your screen and in what you hear with a vision model on this PC's GPU (and, for
the problems that need reasoning, with a cloud agent you are signed in to: Claude Code, Codex or the Anthropic API)
and writes the solutions into a browser panel.

It runs in one of three ways:

- **The app** (Windows or Linux, no Docker): `Sidenote.exe` starts everything on this PC, with Ollama for the local
  model (section 3, "The app").
- **With Docker** (Linux, or Windows with WSL 2): `./sidenote <command>` from a terminal in this repository folder
  runs the server in containers and adds web search for the local model and the sandbox for code checks. `./sidenote
  help` lists the commands. Most of this guide describes this setup.
- **On Kubernetes**: the Helm chart (section 16).

The panel, the server's messages and the commands speak English, or Korean when the browser (for the panel) or the
system (for the commands and the capture program) is set to Korean. The panel's menu has **Language** to pick one by
hand, and `SIDENOTE_LANG=en` or `ko` picks one for the commands. This guide calls each control by its English name, and
section 18 gives the Korean label for each.

## 1. What runs where

| Part | Where | What it does |
|---|---|---|
| Capture program `client/capture.py` | Windows (Windows Python), or a Linux desktop (X11) | Captures the screen and speaker sound and sends them to the server |
| Analysis server `server/` | Docker container `sidenote` in WSL | Solves changed screens and spoken problems with the local model, and the problems that need reasoning with the cloud agent when it is signed in. Reads the web pages the local model asks for |
| Local model | Docker container `sidenote-llm` in WSL (GPU, no internet) | The vision model that solves (Ollama) |
| Web search | Docker container `sidenote-searxng` in WSL | Sends the local model's searches to search engines (SearXNG) |
| Panel `panel/index.html` | Browser, `http://127.0.0.1:8777` | Writes the solutions down one below the other, like a notebook |
| Code runner `runner/runner.py` | Docker container `sidenote-runner` in WSL (no network) | Runs the code you run from the panel and returns its real output |
| Cloud agent `server/agents.py` | The Claude Code or Codex CLI inside the `sidenote` container, or the Anthropic API | Solves the problems that need reasoning, signed in with this PC's own login (section 3) |

WSL cannot see the Windows screen or sound directly, so only the capture runs on Windows.
`./sidenote capture` starts the Windows capture program from the WSL terminal and returns at once: the
program runs without a window, with an icon in the notification area, and is ended from that icon or with
`./sidenote capture-stop` (section 4). On a Linux desktop the same command runs the capture program there, from a
virtual environment of its own (`.venv-capture`).

The app runs the same server, capture program and panel as processes on this PC, with the PC's own Ollama for the
local model. It has no web search for the local model and no code checks, which need their containers.

## 2. Requirements

- For the app: Windows 10 or 11, or Linux with an X11 desktop, and [Ollama](https://ollama.com/download) for the
  local model.
- For Docker: Docker with `docker compose` (inside WSL on Windows), and on Windows, Python 3 for Windows (the `py`
  command); `./sidenote setup-windows` installs the capture packages.
- For the local model, an NVIDIA or AMD GPU. Sidenote reads its memory and picks the largest measured model that
  fits: `gemma4:26b` on 24 GB, `gemma4:e4b` on 12 to 16 GB, `gemma4:e2b` on 8 GB. With less, or no GPU, the cloud
  agent solves everything (a model can still be pulled to run on the CPU, slowly). `SIDENOTE_LOCAL_MODEL` sets one.
- Optional, for the cloud agent: Claude Code in WSL (the `claude` command) signed in with an account that can use
  it, or Codex (the `codex` command in WSL, or the copy inside the server through `./sidenote login codex`), or an
  Anthropic API key. The server uses the CLI's login as it is (section 3).

## 3. First time

### The app

1. Install [Ollama](https://ollama.com/download).
2. Unzip `Sidenote-windows-x64.zip` (or `Sidenote-linux-x64.zip`) from the releases and run `Sidenote.exe` (or
   `Sidenote`). Windows may warn about an unknown publisher the first time: **More info**, then **Run anyway**.
3. The panel opens in the browser. When the model for this GPU is not there yet, the **Local model** card offers it:
   **Download**. The card shows how far it got; the model is ready when it says so.
4. For the cloud agent, install Claude Code or Codex and sign in once in a terminal (`claude`, or `codex login`).

The app starts Ollama when it is installed but not running, starts again any part that stops, and stops everything
when the capture program is quit from its tray icon. A second start only opens the panel. `SIDENOTE_*` settings
(section 12) are read from the environment it is started with. Options go after `Sidenote.exe` (or `Sidenote`):

| Option | Meaning |
|---|---|
| `--no-browser` | Start everything without opening the panel |
| `--no-capture` | Start the server and the panel only |
| `--port 8778` | The server's port on 127.0.0.1 (default 8777) |
| `--check` | Start the server with stand-in models on a free port, check that it answers, and stop |

The app keeps its files in a data folder: `%LOCALAPPDATA%\Sidenote` on Windows, `~/.local/share/sidenote` on Linux
(`$XDG_DATA_HOME/sidenote` when that is set), or the folder `SIDENOTE_DATA_DIR` names. Its `logs` folder holds the
server's log (`server.log`, `events.jsonl`), the panel's settings (`.settings.json`) and the kept answers
(`history.sqlite`), and beside them what each part printed (`server-console.log`, `capture.log`, `ollama.log`) and
what the app itself did (`app.log`).

`./sidenote stats`, `events`, `report` and `gpu` run inside the server's container, so the app has no counterpart to
them. `http://127.0.0.1:8777/stats` gives the data of `stats` as JSON, `events.jsonl` in the `logs` folder holds the
events, and **Solver settings** gives the GPU back: **This PC's model** off, and **This PC's model stands in at a
limit** off.

### With Docker

```bash
./sidenote install         # the server, the capture packages, the desktop shortcut on Windows, then a check
./sidenote llm pull        # the local model for this GPU and its smaller one, once (a few GB to tens of GB)
```

The GPU is found by itself: `./sidenote` uses `docker/compose.nvidia.yaml`, `docker/compose.amd.yaml` or `docker/compose.cpu.yaml` with
`compose.yaml` (`COMPOSE_FILE` in `.env` picks one by hand), and `./sidenote doctor` says which.

`install` runs the steps in the order they need and skips the ones already done, so it is safe to run again
after a change. It does not download the models by itself: they are tens of gigabytes, and it points at the
command above instead (`./sidenote install --with-models` does both). Until they are there, the cloud agent
solves everything, when it is signed in. The same steps by hand:

```bash
./sidenote up              # build the server image and start it (a few minutes the first time)
./sidenote setup-windows   # install the capture packages into Windows Python
./sidenote shortcut        # a desktop shortcut that starts the server and the capture program
./sidenote doctor          # check the setup
```

### The cloud agent

The problems that need reasoning go to a cloud coding agent by default (algorithm, coding, math, work, essay and
other, and any problem the local model would be 1.5 times as slow to start answering). **Solver settings** (in the
**Settings** menu) changes which problems, or switches the agent off. `SIDENOTE_AGENT` in `.env` chooses the agent (its other
settings are in section 12):

| `SIDENOTE_AGENT` | Uses | Sign in |
|---|---|---|
| `claude-code` (the default) | the Claude Code CLI with this PC's login (`~/.claude`) | `./sidenote login` |
| `codex` | the Codex CLI with this PC's login (`~/.codex`) | `./sidenote login codex` |
| `anthropic-api` | the Anthropic API | `ANTHROPIC_API_KEY` in `.env` |
| `off` | no cloud agent: the local model answers everything | |

The panel calls the agent **Agent**, whichever it is: its signal in the top bar, its card in the right column and its
section in **Solver settings**. The card names the product (Claude Code, Codex or Anthropic API) beside the account
it is signed in as. The CLI agents use this PC's own login as it is; there is no token to create or paste.
`./sidenote login` signs in the agent the server is set to use, when it is not signed in. `./sidenote login codex`
signs Codex in: with the `codex` command in WSL it signs in there, and without it the server's own copy shows an
address and a code to type there (the server has to be running, and the login lands in the same `~/.codex`). The
server notices a new login within 20 seconds, so there is no need to restart it. Without a login the local model
solves everything, but the agent's signal stays red and an alert asks for the login; setting **Problems the agent
solves** to **Off** clears both.

New models are used without a change: for Claude Code the model setting offers the families `opus`, `sonnet` and
`haiku`, each meaning the newest release of its family, and an empty setting uses the CLI's own default.
`SIDENOTE_AGENT_MODEL` pins a version (for example `claude-opus-5-5`). A Codex login reports no price, so the hourly
cost limit counts only the agents that report one (section 12).

`up` builds the Claude Code and Codex CLIs into the server image at the versions this PC has (after the PC's CLI
updates, the next `up` rebuilds the image), or at the versions `compose.yaml` names when the PC has none. The agent
runs as a helper with none of your own setup: Claude Code loads none of this PC's settings, hooks, plugins, MCP
servers or skills, Codex none of its config or rules, and neither keeps a session history. Claude Code is offered
no tools (a web search alone, for a question about the present), and Codex runs in a read-only sandbox that asks
for no approval. Claude Code's token refresh goes through its own lock, so it does not collide with other Claude
Code sessions on this PC.

## 4. Everyday use

```bash
./sidenote up        # start the server (if it is running, rebuild only what changed and show the status;
                     # while it is in use it waits until it rests: --now restarts at once. A commit CI failed
                     # does not go up: --no-ci takes it anyway, --when-green waits for CI's answer. docs/QA.md)
./sidenote capture   # start screen and sound capture (windowless, with a tray icon; the command returns at once)
./sidenote open      # open the panel (or type http://127.0.0.1:8777 in a browser)
```

When you are done, end the capture program with **Quit** in its tray icon's menu or with
`./sidenote capture-stop`, then stop the server with `./sidenote down`, which also ends a capture program still
running. To restart
the server, use `./sidenote restart` (this also covers changes to `.env` or the code).
The server does not start by itself when the PC or Docker restarts. `./sidenote capture-stop` also stops a
capture program left behind (one started with `--console` whose terminal was closed, for example), and if some
are still left, says how many.

The capture program reads its code when it starts. After `./sidenote up` deploys new code for it, it restarts
itself into that code at a quiet moment (the screen at rest for 20 seconds, nothing being analyzed or listened to,
no answer in the last minute), the way **Restart capture** in its tray menu does. `./sidenote capture-restart`
restarts it at once.

`./sidenote capture` starts it **windowless**: no console, no taskbar window, only the icon in the
notification area. What it prints goes to `capture.log` (kept under 4 MB, the newest half on a trim).
`--console` keeps it in the terminal instead, where Ctrl+C ends it; that is the way to see what stops it from
starting.

While it runs, the capture program puts an icon in the notification area. Clicking it opens the panel;
the right button opens it too (**Open the panel**), switches the screen and the sound (**Screen capture**,
**Sound capture**), starts the program again (**Restart capture**) or ends it (**Quit**; in the app,
**Quit Sidenote** ends the whole app). The menu uses the panel's look: the same icons, the same status pill (green
while it captures, red with no server) and the same switches. The icon needs `pystray`, which
`./sidenote setup-windows` installs; without it the program runs as before and says so once. Started
windowless it then has neither a window nor an icon, so `./sidenote capture` says so before it starts it, with
`./sidenote capture-stop` as the way to end it; `./sidenote install` installs the package and
`./sidenote doctor` reports it missing.

`./sidenote shortcut` puts a shortcut on the Windows desktop that starts the server, when it is not running, and
then the capture program, in one click and with no window: Windows Python's windowless launcher (`pyw.exe`) runs
`client/launch.pyw`, which runs `./sidenote capture --up` through wsl.exe without a console, so the tray icon is
all that appears. The first start after an update builds the server image for a few minutes with nothing on
screen; a second click meanwhile says a start is still going. When a start fails (Docker off, the port taken, the
capture program already running), a message box shows the launcher's last lines, and `./sidenote capture --up`
in a WSL terminal prints all of it (`./sidenote shortcut --remove` takes the shortcut away). The panel switches the
screen and the sound on and off, chooses the monitor and pauses the answers, but it cannot start the program
itself: the server runs in a Linux container and the capture program is a Windows program. Started once,
everything else is the panel's.
While you need the GPU for something else, `./sidenote gpu off` gives it back at once: this PC's model is switched off
and unloaded, and it is not loaded again at the agent's limit. The agent keeps working, and the panel shows the local
model as off. `./sidenote gpu on` takes the GPU again, and `./sidenote gpu status` says who holds it.

Capture options go after `./sidenote capture`.

| Option | Meaning |
|---|---|
| `--monitor 2` | Capture monitor 2 (default 1 = primary monitor, 0 = all monitors as one image) |
| `--list-monitors` | Only list the monitor numbers |
| `--stitch` | Join a problem longer than one screen while you scroll through it (section 10) |
| `--no-audio` | Do not capture sound |
| `--once` | Send the screen as it is now and exit (no sound, nothing left running). It runs in this terminal, which shows what it sent |
| `--no-tray` | Do not put an icon in the notification area (windowless, `./sidenote capture-stop` is then the way to end it) |
| `--console` | Keep it in this terminal instead of starting it windowless; Ctrl+C ends it |
| `--up` | Start the server first if it is not running (what the desktop shortcut runs, with no terminal). In a terminal, a failure waits for Enter before the script ends |
| `--no-auto-stitch` | Do not join a problem by itself when the screen is scrolled |
| `--no-auto-update` | Do not restart into new code when `./sidenote up` deploys it (it does, at a quiet moment, by default) |
| `--audio-device "part of the name"` | Choose the device to take sound from (default: the default speaker) |

Each option reaches the capture program as typed, so a device name with spaces goes in quotes as usual
(`--audio-device "Realtek USB2.0 Audio"`). The way there passes through cmd.exe, which would act on some
characters itself, so a value holding one of `" % & | < > ^` is refused with a message: give a part of the name
without it, since any part of a device's name finds it.

## 5. Reading the panel

```
 sidenote  ◆Server ◆Local model ◆(agent) ◆Screen ◆Sound  [Reanalyze] [Pause] [⚙]
 (alert bar: only when something needs doing)
 ┌ notebook ─────────────────────────────┐   ┌ Capture: screen/sound switches
 │ MCQ    │ ④                    Copy    │   ├ Local model, (agent): state, usage
 │ 10:21  │ solution ...                 │   ├ This answer's screen
 │ Short  │ ACID                         │   ├ What is heard
 └───────────────────────────────────────┘   └ Contents
 [ Ask more about the problem just solved ...  ] [Ask]
```

**Top bar**
- Five signals: **Server**, **Local model**, **Agent** (the cloud agent, whichever the server uses), **Screen** and
  **Sound**. Green is fine; orange means the capture program is off or the sound device could
  not be opened; red means the server connection is lost, or an engine that is switched on cannot answer (the local
  model is not downloaded or not answering, the agent needs signing in); gray means switched off or still checking.
  Hover over one for details.
- **Reanalyze**: solves the current screen again right away, including a screen that was skipped as
  unchanged.
- **Pause**: stops automatic analysis (and the analysis in progress); while paused the button reads **Continue**.
  Its mark is what pressing it does: the two bars while it watches (green), the triangle while paused (orange).
  While paused, **Reanalyze** still solves the current screen only, so it works as a manual mode that solves
  only when you ask.
- **Settings** menu (the gear): **Theme** (**Auto**, **Light**, **Dark**), **Motion**, **Language**, **Solver settings**
  (section 12) and **Clear history**
  (it takes a second press; an answer still being written stays). The speech language is in **Solver settings**,
  in its **Speech** section.
- There are no keyboard shortcuts. Everything is done with buttons.

**Alert bar**: appears only when something needs doing: the server connection is lost, the local model is not
downloaded or not answering, the agent is in use but needs signing in or its login was rejected (expired), no
engine can answer, the capture program is off, or analysis is paused.
**Copy command** in an alert copies the command to type in the terminal. If the server connection
drops or the capture program stops while you are reading further down, a short notice also appears at the
bottom of the screen.
A solution that was being written when the connection dropped stays as far as it got, marked "Stopped: connection
lost". Once the server is back, solve it again with **Reanalyze**.

**Notebook (center)**: solutions are written one below the other.
- The left margin shows the type (multiple choice, short answer, coding and so on), the time, and marks such as
  answer, solution and question.
- Only the answer line is highlighted. **Copy** beside it copies the answer line (its tooltip says **Copy the
  one-line answer**) and **Copy all** the whole solution; a copy button reads **Copied** for a moment after a
  press. Every code box has **Copy**, and Python, Java, C, C++, JavaScript, TypeScript, Kotlin, Go and Bash code
  boxes also have **Run**. Every table has **Copy** too: pasted into a spreadsheet or a document it keeps its rows
  and columns, and into plain text it comes as tab-separated lines.
- Headings, and a line that is only bold (a step such as "1. ..."), are written in the color of the problem's
  type, and bold key words in a darker shade of it, so the parts of a long solution can be found by eye. A
  table column of numbers is right-aligned. A range written with a tilde ("20~50") stays a tilde.
- Pictures: when values are compared or change, or a schedule, an exchange, a flow, a state machine or the
  relations of tables are explained, a solution can hold a chart (bars, stacked bars, lines, a Gantt chart for a
  CPU schedule) or a diagram (flowchart, sequence, state, ER). Under a chart, **View as a table** holds every
  value; under a diagram, **View the source** holds its text to copy. While the solution is being written a picture
  shows as **Drawing the diagram…**. One that cannot be drawn stays as its text, with the reason over it. The agent draws them
  where they help (measured with Claude Code); the local model draws the diagrams but writes numbers as tables and
  lists.
- A code box is read as an editor shows it: numbered lines, long lines wrapped onto the next row (hanging from
  their indentation) instead of a box that scrolls sideways, and indent guides. Resting the pointer on a built-in
  or library function (`len`, `heapq.heappush`, `std::sort`, `Arrays.sort`, `Math.max`, `strings.Split`) shows its
  signature and the reference's own English line, and on a Korean page also what it does in Korean, what goes in
  (**Input**) and what comes out (**Output**), as an editor's hover does: for Python from the code runner's own Python's
  documentation, for C++, Java, JavaScript and Go the most used ones. Copying and running take the code as written,
  without the line numbers.
- **Run** in the bar at the foot of a code box actually runs the code and shows its output below it (open
  **Input** beside it and type standard input to run with it). Runs happen one at a time, with limits, in a
  separate container with no internet. A shell block in an answer that is not a coding problem has no **Run**: it
  is commands for your own machine, which the container does not have.
  - A solution that fills in a function (solution, twoSum) comes with a runner under it: with **Input** empty it runs
    the problem's examples and prints each result beside what it should be; with values in **Input**, one argument a
    line as the examples write them (`"aabbaccc"`, `[1, 2, 3]`, `5`), it runs those instead. They may also be typed
    the way a problem shows them: an array over several lines, `nums = [2,7,11,15], target = 9`, or a whole LeetCode
    example with its `Input:` and `Output:`; the server lays them out one argument a line before the run.
  - A solution to a problem usually reads its case from standard input, and run with nothing to read it dies on
    its first line. So **Run** looks at the code first: if it reads input and the box is empty, the box opens and
    says what it needs instead of running. Press **Run** again to run it with no input anyway. What you typed is
    sent whether the box is open or folded away, and a run that did die on end-of-input says so in words with
    the original message kept underneath.
  - Limits: 10 seconds per run (`SIDENOTE_RUNNER_TIMEOUT`, at most 30 seconds, of which compiling may take up
    to 20), 512 MB of memory; output is shown up to 64 KB per stream and a run that writes more than 8 MB is
    stopped. Code may be up to 100,000 characters and input up to 20,000.
  - Python 3.12 with the standard library only, C as C11 (with the math library), C++ as C++23 with g++ 14 (code
    that does not compile so is tried as C++17, which a global named `count` beside `using namespace std` needs),
    JavaScript on Node 20 (run as a module if it uses `import`), TypeScript 4.9 with its types stripped and not
    checked, Java 21 (the file is named after the `public class`, and the class with `main` runs), Kotlin 2.0 (a
    compile takes about 3 seconds), Go 1.24 and Bash. Java and Kotlin get a 256 MB heap and Go a 256 MB memory
    target, and all three a 768 MB cap on the memory they write, instead of the 512 MB address-space cap, which
    they cannot start under. Every compile and every run of an example gets a user of its own, so none of them can
    read or change another's files, stop another's processes, or stop the runner itself. Every process a run
    leaves behind, every file it wrote and its System V shared memory are removed when it ends; if anything is
    left the runner takes no more code and the panel shows it as off until `./sidenote up`.
- Under the newest answer is **More**: **Go deeper** always, and a few that suit the kind of answer it is:
  **Another approach**, **Why this complexity** and **Find a counterexample** for an algorithm, **How to confirm**
  and **Other causes** for an operations answer. Each one asks the whole question for you and the reply is added
  under the same answer. The first pass stays short on purpose: most screens hold nothing to solve, and depth is
  worth paying for only when it is asked for.
- The three most recent solutions stay expanded; older ones keep only their answer line. **Show the solution**
  expands one again, and **Fold** folds it back.
- While you scroll up to read (even by one wheel step), a new answer does not pull the view down; a **New answer**
  button (with a down arrow) appears instead. The solution you are reading is not folded when new answers arrive. Any
  manual scroll, up or down, starts an 8-second count again, and after 8 seconds the view follows down again from the
  next new answer. It does not pull down while the same answer grows or finishes. A solution picked from the contents
  stays the current one until you scroll by hand, however long you read it. **New answer** jumps to the latest answer.
- Each answer is a page of its own. A flat red ribbon marks the current one, whose screen the right column shows, on its line in the contents.
- Once an answer is complete, the panel lays out its parts without asking a model and without dropping a word:
  numbered steps become a ladder (while it is written too), `**Name**: words` lines become cards, a chain of arrows
  becomes boxes, a stated complexity is placed on a scale from O(1) to O(2ᴺ), table figures get bars and verdicts
  their colors, a long answer gets a strip of links to its parts, and several answers in one key line become tiles
  that go to their parts. When the shape is unclear, the answer stays as written.
- Every table, picture and code block in an answer has a numbered title (**Table 1.**, **Figure 1.**, **Code 1.**, **Command 1.**)
  and what it is: the step it is in, or the nearest of a heading, a paragraph's leading bold words or a short line ending in a
  colon above it, else what it holds (a table's columns; a program's function, or what its judge wrapper's docstring says
  when that function is only `solution` or `main`; a command's program).
- The box at the bottom of the window asks more about the problem just solved (the last problem whose answer finished); it stays
  at the window's foot wherever the page is scrolled, and rests at the page's end. The
  answer is attached below that solution (a folded solution unfolds while the answer is written) and stays in
  view while it is written. A question being answered is not canceled when the screen changes. The box grows with a
  long question, up to six lines, and then scrolls: **Enter** sends it, **Shift+Enter** starts a new line, and the Enter
  that completes a Korean syllable is the input method's own.
- A solution stopped by pause or a switch stays as far as it got, marked **Stopped**. A solution replaced by a
  new screen or by **Reanalyze** gives way to the new solution. One that has run 20 seconds or more is in its long pass
  and finishes first, the newest screen looked at after it (`SIDENOTE_SUPERSEDE_KEEP_SEC`): most screens that stopped such a
  pass had nothing to solve.
- A screen with nothing to solve is left as one line, "No problem to solve".
- Under a solution, as they apply: **Tests** (its code run on the problem's examples), **Review** (the agent's
  verdict, in the **Check answers** mode), **Retry** (after a failed example) and **Details** (the tokens, the
  cost, and the search words and pages read for this answer). Sections 7 and 14 explain them.
- **Problem text** on the latest screen problem writes the problem out as text, to copy.

**Right column**
- The cards stand in one column. On a very wide window, 2400 pixels or more (2560 x 1440), they stand in two: the controls (capture, this PC's
  model, the agent) on the left, and the screen, the heard speech and the contents on the right. Every card shows all it holds at every size of
  window; nothing folds to fit. While the column fits under the top bar it follows you down the thread. Taller than the window, it
  follows too: going down it moves with the page until its foot is in the window and stays there, and going up it moves back until its
  head is under the top bar. It never scrolls inside itself.
- **Capture**: the **Screen capture** and **Sound capture** switches and the state of each (when the last screen arrived, which sound device).
  The **Screen capture** line reads **Watching quietly** while the watching has slowed itself down after a run of answers that found
  nothing, and says what brings it back (section 8).
- **Local model**: which one, whether it is on the GPU (**On GPU**, or **Idle** once the GPU was given back, with
  **Free the GPU** and **Load onto the GPU**), the GPU's load and memory, and what it has done today.
- **Agent**, with a switch of its own (off keeps the mode it had, so on brings it back): the account it is signed in
  as, with the product and its plan, in a box. With Claude Code, two meters show the plan's usage of its five-hour
  session and of its week (**Session**, **Week**), with when each starts again. They are read where Claude Code's own
  `/usage` reads them, with the CLI's own login, when a panel opens and every 90 seconds while one is; nothing is
  written or logged. A window whose reset time has passed shows as **Not started** until the next reading. A reading
  ten minutes old or more is drawn faint, with its age in the tooltip (the login's token runs out while Claude Code is
  not used, and the server never refreshes it). Signing in as another account empties the meters at once and reads
  them again. Under the meters come the problems it takes and what it is sent (**Takes**, **Sends**), its model and
  effort on one row, and what it has done in the last 24 hours.
- What an engine has done today stands in its own card, over a restart too: answers, the usual time taken, the average time to the first token and
  tokens a second, each answer as a bar (its lower part the wait for the first token, its tooltip the figures), the tokens, and for the agent the cost.
- **This answer's screen** (the screen card): a thumbnail of the screen that produced it. The highlighted box is
  where the model found the problem. **Draw a region** limits what is looked at, and sent, to a region you drag on
  the current screen, until **Clear the region**.
- **What is heard**: with sound on, recent speech runs by as text. KO and EN show the recognized language.
- **Contents**: the list of solutions, nine lines of it at a time, more on a window tall enough for the whole column
  (it scrolls inside its card for the rest), each day an index tab saying how many it holds, which stays at the top of
  the list as it scrolls. Click one to go to it; the arrow keys go down the list, and its row's tooltip has its whole
  text. The search box (**Find an answer**) looks through everything kept for the answers holding every word you type
  (in what was asked, the answer, its follow-ups or what was heard). The day and kind lists show one day's or one
  kind's answers in the notebook too; with a day chosen, the kind list offers that day's kinds, each with how many.
  **Export** saves what is shown, with what was asked and its follow-ups, as one Markdown file.
- The answers stay after a reload or a restart: the server keeps them with a small picture of their screen in
  `history.sqlite` in the log folder, for 90 days and 200 MB at most, the oldest going first (`SIDENOTE_HISTORY_DAYS`,
  `SIDENOTE_HISTORY_MB`). **Keep answers** stops it, and **Clear history** in the menu empties it.
- A band that needs you (paused, a limit, an engine down) stays right under the top bar as the thread scrolls, and the
  right column stays under it.
- The menu's **Motion** is **Full** unless you set it to **None** (or to **Auto**, which follows the system's
  setting): the cards come up as the panel opens, figures count to their values, meters and bars fill, and what
  changes moves once. Nothing moves at rest but what is at work.
- The menu's **Language** is **Auto** (the browser's language), **English** or **한국어**. A pick opens the panel again
  in that language, the server's messages too, and this browser keeps it. `?lang=en` or `?lang=ko` in the address
  picks one for that page alone.
- What an answer sets in bold wears the yellow highlighter, as the answer line does.
- Several problems answered at once are listed one line each. A block of commands has a `$` where a program has its
  line numbers. A diagram takes the width of the thread.

On a narrow window the right column moves below the notebook. Reloading the panel keeps follow-up questions
working, because the server remembers the last analysis.

## 6. Screen and sound switches

The switches in the **Capture** card turn screen and sound capture on and off separately.

- With the screen off, the capture program takes no screenshots, and the server drops incoming screens and the
  one it held from just before. Analyses and follow-up questions that include a screen stop, and the panel
  deletes the screen thumbnails it holds (they do not come back when you turn the screen on again, and later
  follow-up questions do not send that screen). Problems given only by voice are still solved. Turning the
  screen back on sends the current screen right away.
- With sound off, the capture program closes the sound device, and the server deletes the sound it heard and
  the text it wrote down so far. Solving a problem given by voice stops too. Sound from while it was off is
  never analyzed later.
- The server remembers the switches. A capture program started later begins in the state set in the panel.
- Restarting the server (`./sidenote restart`, or `down` then `up`) keeps the switches and pause as they were.
  With `./sidenote restart` a running capture program reconnects by itself when the server comes back, also
  with both switches off. `./sidenote down` ends the capture program as well, so after `down` and `up` start it
  again with `./sidenote capture`.
- If the sound device cannot be opened, the card says so. When the device is plugged back in or the default
  speaker changes (connecting earphones, for example), the capture program moves to that device within a few
  seconds. Pin a device with `--audio-device`, or run without sound with `--no-audio`; the card then shows
  **Running without sound**.
- The sound device is read by a thread of its own and what it read is sent by another, since a device that is
  not read on time drops what it recorded meanwhile and the socket is shared with the screen. If sending falls
  more than eight seconds behind, the oldest second is dropped rather than held, and the capture program says so
  once a minute (`[audio] ... dropped on the way out`): what the answer wants is what just played. Turning sound
  off empties what is waiting, so nothing recorded before that goes out after it.
- While the screen cannot be captured, such as on the lock screen or with an administrator window, the capture
  program retries every 2 seconds and sends the current screen once it can capture again.
- This tool's own panel is painted over before a screen is sent. What it shows is the answer to the screen
  behind it, so a screen with it on would be a screen answering itself. The capture program finds it by the
  window title (which never leaves that program), paints its area gray and pastes back any window in front of
  it, so a window over the panel keeps what it showed. A new answer appearing in the panel is then not a new
  screen either, so it starts nothing. To send less than the whole screen, draw a region on the screen card
  (a **Drawn region**): only that region goes to the model and to the agent. A drawn region lasts until the capture
  program starts again or the server restarts; it is not saved, because one left from an earlier sitting hid
  every problem outside it.

## 7. What it solves and how

Besides practice sites for coding, it solves problems on documents, slides, problem sets, forms, messengers,
email, logs and terminals and SQL consoles, and problems given by voice, each in the way its type needs.

It answers technical and knowledge problems only. On a technical topic it answers even when asked as an
opinion or a preference ("Which do you prefer, REST or GraphQL?"), with tradeoffs and criteria. Questions
about the person asking (experience, self-introduction, motivation, strengths, career direction), speaking tips
or answering strategy, and small talk unrelated to technology are not solved; they pass as "nothing to solve".

| Type | Example | How it answers |
|---|---|---|
| Multiple choice (including O/X) | "Which is NOT correct?", "Select all that apply" | The answer number or symbol first, then why it is right and why the others are wrong |
| Short answer | Fill in the blank, write the term | The answer and one or two lines of reasoning |
| Essay | "Explain ... (about 300 characters)" | A model answer paragraph ready to hand in (keeps the length limit) |
| Coding | Write or fix code, predict output, find a bug | Complete code, or the exact output and the reason |
| Algorithm | Practice coding problems | Code that runs, the idea, the complexity, checked against the examples |
| Work | Incident logs, design, SQL or configuration requests | Diagnosis, how to confirm it, and the fixes in order of priority |
| Math | Calculation, proofs | The steps and the final answer (math rendered) |
| Diagram | Whiteboard, architecture, data structures, flowcharts | An ASCII drawing in a code box and the order to draw it in |

Every solution starts with a one-line answer (multiple choice "④", short answer "ACID", essay and work a
one-line summary).
Several problems on one screen, or one problem with sub-problems, are all solved, as in "1) ③ 2) X" or
"(1) ③ (2) 42". Code boxes in coding and algorithm solutions can be run with **Run** (section 5).

An answer shows its working, not only its result: which other options are wrong and why, where a
complexity comes from, what command confirms a diagnosis, what to check arithmetic against. Press
**Go deeper** under the newest answer for more of it on demand.

### The local model and the agent

- The local model reads every problem first. What it can answer at once (an explanation, a term, a command) it
  answers in that pass. Multiple choice, math, code and algorithms, and whatever that pass marks as needing
  reasoning, are solved again with thinking (**Think before answering** in **Solver settings**: **Auto**,
  **Always**, **Never**). For a screen problem the thinking pass also gets the problem part cut out at the screen's
  own resolution (up to 1600 pixels on its long side), so small text reads well; the cut stops at the edge of the
  window the problem is in (**Cut at window edges**). That image never leaves the PC, so when the problem's place
  spans several windows it is cut as it is; on a wide 4K screen with no usable place for it (none found, nearly the
  whole screen, or over several windows and too large to read from one cut) the thinking pass gets the screen's two
  halves instead.
- While the thinking pass runs, the foot of the notebook shows the last sentence it finished, in gray italics,
  under how far it has got: something to read in the wait (with the 26b on a 24 GB GPU, often 30 s to the
  first word, and up to 100 s on a hard problem). It is the model's own reasoning, mostly in English.
- The thinking and the answer share one output limit (`SIDENOTE_MAX_TOKENS`, 8,000 tokens by default). When the
  thinking uses most of it and leaves the answer cut short, the answer is written once more without thinking, from
  the end of that thinking: the card says that the thinking reached the output limit while it does, and `cut`
  is added to the model name under the answer.
- When an answer depends on current facts (latest versions, releases, prices), the local model searches the
  web first, and such answers end with the pages they used (section 14 says what goes out).
- **Problems the agent solves** decides the rest, with the agent signed in:

| Choice | What happens |
|---|---|
| **Hard problems** (the default) | The local model answers what it can at once (it starts in about a second, faster than the agent). A problem that needs reasoning goes to the agent when its type is chosen in **Types the agent solves** (algorithm, coding, math, work, essay and other by default), and whatever its type when the local model would take 1.5 times as long as the agent to start its answer or another program has the GPU. The times compared are the medians of the last 15 of each, so the rule follows what this PC and the agent measure. The local model answers it only when the agent cannot: declined, failed, offline, signed out or over its spending limit |
| **Check answers** | The local model solves everything; after each answer the agent gets the problem and that answer, and either agrees or writes a corrected solution, shown under the answer as **Review** |
| **All** | Every problem goes to the agent |
| **Off** | The agent is not used |

- The agent gets only the problem: the problem part of the screen (**Problem area**, the default), the problem
  written out as text (**Problem text**), or the whole screen (**Whole screen**), as **What is sent to the agent**
  says. **Confirm before sending** shows it first and sends it only on **Send** (**Don't send**, or two minutes
  without a choice, sends nothing).
- With the problem part or the problem text, a coding problem also carries the name of the code language the
  local model reads off the screen (`C++`), because the code editor is not in what goes out: sent the problem
  part alone, Claude Code answered C++, Java, Kotlin, Go and JavaScript tests in Python every time.
- While the local model is off, not downloaded or not answering, a signed-in agent solves every problem; with
  nothing to find the problem part it gets the whole screen (or the region you drew).
- When the local model's first pass searched the web, its results go to the agent with the problem and today's
  date, and for a question about the present (a current version, a release, a price or the news) Claude Code may
  also search the web itself, in a process of its own.
- If the agent declines a screen or answers nothing, this PC's model answers it instead (**This PC's model answers
  when the agent declines**, on by default). The card says so, and still lists what went out before that. With the
  switch off, with no model on this PC, or when this PC's model fails on it too, the card shows the agent's reply as
  it came.

### Code checks

- For coding and algorithm answers, the local model reads the input/output examples off the problem, and the
  code runs on them in the code runner, in the language it was written in: a function in Python, Java, C++,
  JavaScript, TypeScript, Kotlin or Go is called with each example, and a program in any of those or in C or Bash
  is fed each example's input. Nothing asks for a language; with the C++ template of a coding site in the editor,
  the local model answered in C++ (6 of 6 times on two such screens). **Tests** on the card shows
  how many passed and in which language, and for a failure the input, the expected output and what came out (or
  the error that stopped it). A function that returns nothing (an in-place problem) is judged by its first list
  argument, as LeetCode judges it: when it says it returns nothing (`void`, `Unit`, `-> None`, `@return {void}`,
  `: void`) that argument has to end as expected, also in an example whose answer is its input; when it says
  nothing, it has to have changed it in some example; and Programmers' `solution`, or a function that says it
  returns a value, fails. A fraction counts within half the last place the example shows and at most 1e-5
  (0.73278 for 0.7327777...); a program's output only when an example shows more places than a double holds
  (Baekjoon's 0.33333333333333333333333333333333, then within 1e-9). Each example gets a new `Solution`, what the
  code prints itself is not kept, and an example's input ends with a newline as a judge's file does. Arguments
  given by name, or one argument not in a list, are put in the parameters' order, and parameters with a default
  may be left out. A whole number expected is not met by a double off by more than 1e-5. Code in LeetCode's form (a
  `class Solution` method with the problem's own name) gets what that judge adds without an import (Python's
  collections, heapq and the like, Java's java.util, every C++ header); Programmers' adds nothing, so a missing
  import there is an error. A function is called when its parameters are numbers, booleans, characters, strings
  and arrays or lists of them, or a binary tree or a linked list (next point); for anything else (a map, a
  pointer, LeetCode's `Node` in its other meanings: an n-ary tree, a graph, a random pointer, a circular list),
  for an answer in a language the runner does not have (Swift, C#, SQL and so on) and for code it cannot find,
  the card says why instead.
- A tree or a linked list is built from the level-order list the statement writes (`root = [3,9,20,null,null,15,7]`,
  `head = [1,2,3]`), in every language a function is called in, with the class that judge provides where the answer
  does not define one of that name. A node a statement gives by its value instead (`p = 5` beside a tree) is the
  node of that tree with that value, as its judge means it, and what comes back is compared as a statement writes
  it: a tree in level order with the trailing empties dropped, a list as its values, no node at all as the empty
  list, and a node shown as a plain value as that value. Measured against a public corpus of 2,463 LeetCode
  problems with their own reference solutions, in Python: 2,322 pass, 59 the check refuses with a reason, and the
  rest are problems whose statement allows more than one right answer. Of the same answers made wrong on purpose
  (2,313 of them), every one failed the check.
- A problem that asks for a class (an LRU cache, a min stack) states its example as three lists: the calls, the
  arguments of each, and what each returned. The class the answer defines is built once, called in that order, and
  each call compared with the list; the card says how many calls passed and names the call that did not match.
  Of 119 such corpus problems 104 to 107 pass every call between runs, the ten that fail being the ones whose
  answer is random or free in its order. For a class in a language whose harness cannot call one, or a call it
  cannot fill, the card says so.
- An answer written on a judge's page uses the names that judge has ready and imports nowhere, so the runner has
  them too: Python's collections, heapq and the like and sortedcontainers; every C++ header; Java's java.util and
  javafx.util.Pair, which is defined beside the answer; and in JavaScript and TypeScript a heap
  (MinPriorityQueue, MaxPriorityQueue, PriorityQueue), a deque and lodash, which are there as names a run only
  pays for when it asks for one. Nothing is added for a package that judge has not got either (Go answers that
  want github.com/emirpasic/gods).
- The problem's own words about the judging are read with the examples and shown on the card: **any order** when the
  statement says the answer may come in any order (the answer then counts however its elements are ordered, though
  not how each element is ordered inside: Permutations says the same, and there that order is the answer), **in
  place** when it says not to return the answer but to write it into the argument, and **tolerance 1e-09** when it
  allows an error (then every number counts within it). Said or not, a failing example whose result holds the
  expected values in another order says "Some results hold the same values in another order". When no code in the
  answer defines the function the examples name, the one function the answer defines that takes as many arguments is
  run instead: the problem's own name is often only in the editor, which the part of the screen read for the examples
  leaves out.
- Known limits: the words about the judging are read off the screen, so one may be missed (on four screens over
  three rounds every one but one was read right). An answer whose elements are themselves in another order, such
  as Group Anagrams with its groups built in a different order, still fails, with the note above: counting it
  would also count an answer to Permutations that sorted each permutation. Go code written without its imports compiles: a Go compile that
  failed is tried once more with the standard packages the compiler itself named (180 of 600 corpus problems
  failed on that alone).
- When an example fails, the engine that wrote the answer gets one more try with the failing examples, shown
  under the answer as **Retry**, and its new code is checked on the same examples.
- When the problem shows no examples (12 of 17 checks in real use ran nothing), the local
  model is asked on its own for three small inputs the problem allows, with no answers, and the code is run on
  them. **Tests** then says whether it ended without an error. Nothing is judged by what it returns, since the
  only answers there would be the model's own, and a run that fails asks for no retry: the made-up input may be
  the one that breaks the problem's rules, and the card says so.
- Both follow **Check the examples** in **Solver settings**.

### Problem text

**Problem text** on the latest answered screen problem has the local model write the problem out as text
(Markdown, math in LaTeX), shown under the answer with **Copy problem text**. Only the latest
problem has it, because only its screen is kept, as for follow-up questions; switching the screen off drops it.

### Answer language

- The answers follow the panel's language. In English (the default), the models are asked to write the whole
  answer in English: the answer line, the explanation, the section headings and the comments in code. Measured with
  the 26b on the 56 screens and spoken questions of the known-answer set: all 56 answers in English (none with more
  than 5% Korean outside code), 52 right where the Korean run had 51, and all 7 code answers passing.
- In Korean every explanation is Korean, whatever language the problem is in. What the user would write down or
  say back is in the problem's own language instead: for a problem on screen in English, or a question heard in
  English, the answer line, the answer paragraph and the code come in English while the explanation under them
  stays Korean. Above the answer the card shows **Question**, one Korean line saying what the problem asks, which is
  written for a Korean problem too, so a problem read wrongly shows there. Measured on 24 problems (12 of them
  English statements of a public corpus): the answer in the right language 23, the explanation in Korean 24, the
  Korean line written 20.

## 8. When it solves again

- Together with the answer, the model reports where the problem is on the screen. From then on the server
  watches only that region.
- So typing code next to the problem, looking at another window, or a playing video does not make it solve the
  same problem again.
- A change inside the region does. It catches even one changed word, as with the next problem on the same
  template.
- The same problem seen again somewhere else (scrolled, the window moved, or come back to after another screen)
  is not solved again either: the server keeps small pictures of the last six problems it answered (for 30
  minutes) and looks for them where the new problem is, before anything is spent on it. The panel says so once,
  and **Reanalyze** solves it all the same. What the model calls the problem does not matter, and when a busy GPU
  gave no box, the words about to go to the agent are compared with those of the answers before it (the numbers have to
  be the same). **Don't solve the same problem again** turns these checks off.
- The panel's notice about a problem seen again takes you to its answer when you press it.
- When the agent says its plan's usage is used up ("weekly limit, resets ...", Codex's "try again at 12:26 PM" or
  "at Nov 4th, 2026 11:13 AM", the API's "credit balance is too low"), it is not asked again until the time it
  gives (an hour when it gives none). This PC's model answers meanwhile; the band at the top of the panel says until
  when, and the agent's card counts the time down.
- With this PC's model switched off, it answers for the agent while the agent cannot: at its plan's usage limit
  (the problem that met the limit included), with its sign-in gone, or at the hourly cost limit (**This PC's model
  stands in at a limit**, on by default). A two-minute rate limit and the pause after answers in a row that found
  nothing do not load it. The model's card says **Standing in**, and when the agent can be
  asked again, and nothing is running, the model goes off the GPU, as you left it. With the agent switched off as
  well nothing stands in.
- If the screen keeps changing, an analysis in progress gives way to a new screen at most twice, then runs to
  the end.
- A screen is asked about once it has come to rest, not while it is being typed on or scrolled. The frame
  waiting is replaced by each newer one, so what is answered is the screen you stopped on. A screen that
  never comes to rest is asked about after 8 seconds anyway; a video call in a corner does not count as the
  screen moving, so the problem beside it goes at the usual wait.
- What keeps moving while the rest stands still (a video call in a corner, an animation, a clock) is left out
  of the comparison for as long as it moves (a cell that moved in at least 2 of the last 4 frames), so it never
  makes the same problem count as a new screen or cuts an answer off. Once the screen has been still for 3
  seconds everything counts again, so a scroll that has stopped is seen.
- When answer after answer finds nothing to solve, the watching quiets down: a small change on the same
  screen is then looked at once every 8 seconds instead of every 1.5. A new window or page, a question,
  **Reanalyze** and a drawn region are never held back, and any of them puts it back to normal. The
  **Screen capture** line in **Capture** says **Watching quietly** while it holds.
- If a new problem appears outside the region while the old problem is still visible, it is not solved
  automatically. Press **Reanalyze** in that case.
- A screen whose analysis failed is not retried automatically (use **Reanalyze**). If errors repeat, automatic
  analysis rests for a while: 1 minute on a usage limit, otherwise from 5 seconds up to 1 minute.
  **Reanalyze** always solves right away.

## 9. Problems given by voice

Sound is used as input only. The tool makes no sound.

- When speech ends and 1.5 seconds of quiet follow, the whole utterance is written down and analyzed even if
  the screen did not change. The screen, if there is one, is used as context.
- A problem may be read in several sentences. Pauses shorter than 6 seconds join the sentences into one
  problem.
- With a question phrase in Korean or English (such as "find", "choose", "explain", "what", "which" or "why"), it
  solves as soon as the sentence ends.
  Speech without one (a lecture, small talk) is looked at once, after the speech has paused for 6 seconds, so a
  lecture video playing in the background does not set off an analysis per sentence.
  The phrase has to be in the sentence just spoken, or in an earlier sentence of the same unbroken run of
  speech, and one run starts at most 3 analyses. Whatever is still being read is solved whole once you stop.
- Sound shorter than 0.8 seconds is not written down at all. The speech model does not stay silent on a blip
  of noise, it writes a sentence, usually in English.
- Speech shorter than 12 characters ("yes, I see" in Korean, "okay") is not taken as a problem.
- The screen comes first. What the microphone hears is mostly whatever the PC is playing, so a problem heard
  never interrupts an analysis of the screen; it waits and runs as soon as that answer is written. A screen
  that has clearly moved on does take over from a problem heard, on the same terms as any other screen.
  Speech heard while paused or with sound off is never analyzed later.
- After a stretch of quiet, the speech in **What is heard** and the recent speech attached to analyses are cleared
  too.
- The speech languages are Korean and English. The default **Auto** picks between those two only, and
  it goes by the session rather than by the one utterance in front of it: a short Korean sentence is often
  read as English (32 of 108 measured), so one read that way while the session has been speaking Korean is
  written down again as Korean. It never goes the other way. Pinning the language is what removes the
  mistake: pin **한국어** (the choice is written in Korean in both languages) if that is all you speak to it. With
  **English** pinned, Korean speech is written down translated into English, so use **Auto** when the two are mixed.
- The model corrects small transcription errors from the context.

## 10. Long problems: joining while you scroll (`--stitch`)

A problem that only fits by scrolling is joined by itself: the capture program notices that the screen
was scrolled rather than replaced, joins what follows into one page (from the screen before the scroll,
so nothing scrolled past is lost) and goes back to single screens about four seconds after the scrolling
stops. The card then says how many screens the problem was joined from. `--stitch` keeps it on the whole
time, and `--no-auto-stitch` turns it off.

How it tells a scroll from a new screen: one number per row of the screen, per vertical band, each row
summed with fixed weights so the number says what is in the row. Two bands have to find the same shift,
which an animation or a video in one of them does not. Bands are read apart because a coding-test page
scrolls the problem while the editor beside it stays still.

1. Scroll through the problem area from top to bottom at a normal pace. Just do not jump a whole screen
   height at once.
2. At the bottom, stop for about 2 seconds. The whole collected problem is sent and solved at once. When that
   problem was answered in the last 10 minutes, it is not solved again as a new card: the engine that wrote the
   answer gets the whole joined problem and fills the answer out under the same card (the follow-up reads
   **Solution filled out from the scrolled problem**), writing the changed answer first, or one line saying
   nothing it shows changes the answer.
3. Scrolling back up does not join parts already collected a second time. Moving on to another problem starts
   a new collection.

On split pages such as coding tests, where only the problem pane scrolls, it finds that pane and joins only it,
leaving out the fixed header and the editor.
Only vertical scrolling is supported. Stretches of blank margin are joined with less margin (no text is lost).

## 11. Status and history (monitoring)

| Command | What it shows |
|---|---|
| `./sidenote status` | Server, local model, the agent and its login, capture program connection, pause, code runner |
| `./sidenote stats` | Since the server started: answers, errors, tokens, cost, response times (median and 90th percentile), the last error, log size. `--json` |
| `./sidenote events` | Recent events, one per line, with why an analysis stopped (`reason`, `after`), which answer a problem seen again was (`of`, `score`), who answered and why the agent got it (`engine`, `via`) and what went to it (`sent`). `-n 100` for the count, `--errors` for the errors and what held work back (the spend brake, the agent's limit, a stuck model server) |
| `./sidenote report` | A summary per day, then the whole period: each engine's time to its first word (the median and the slowest tenth), what the agent was paid for answers, for screens with nothing to solve and for answers with no head line, the agent's answers that found nothing by what it was given and why it got them, why analyses were stopped and how long the ones a newer screen replaced had run, how many problems seen again were not solved again (and their lowest score), how often the GPU was busy and the local model timed out, and what the example checks concluded (with the runs on made-up inputs). The default is 7 days including today (a day ends at midnight). `--days 30`, `--json` |
| `./sidenote logs` | Follow the server log (Ctrl+C to leave) |
| `./sidenote doctor` | Setup check (ends as a failure if there is any ✗) |

Results for screens with nothing to solve count toward tokens and cost but not toward the answers and response
times; `stats` and `report` show them separately.

`stats` asks the running server, while `events` and `report` read the log folder, so they work with the server
down too.
For the same data as JSON, open `http://127.0.0.1:8777/stats`.

With Docker, logs are kept in `~/.local/state/sidenote/logs/` (the app keeps them in its data folder: section 3).

| File | Contents |
|---|---|
| `server.log` | Server log |
| `events.jsonl` | Analysis starts and ends, errors, follow-up questions, switch changes, capture connections. One JSON object per line |
| `capture.log` | Output of the capture program started by `./sidenote capture` |

Their size is capped.
- Each file is replaced by a new one at 5 MB, and at most 4 replaced old files are kept: at most 25 MB per
  kind.
- `capture.log` of the windowless capture program is kept by the program itself: past 4 MB it drops the older
  half. Started with `--console`, the launcher writes it and replaces it at 5 MB like the others.
- Old files replaced more than 14 days ago are deleted (when the server starts and every 6 hours after).
- Docker's own copy of each container's output is capped too: the server's at 3 files of 5 MB, the others smaller.

## 12. Settings

The panel's **Solver settings** (in the **Settings** menu) switches every stage: the local model and when it thinks
first, web search and page reading, the cloud agent (which problems, what is sent, confirm before sending), where
the problem is cut out (the crop and the window edges), code checks, speech, capture, and when the GPU is
released. A change applies to the next analysis and is kept across restarts (`.settings.json` in the log folder).
A row that depends on a switched-off stage is grayed out with the reason.

The sheet is in sections down the left: **Solving**, **Agent** (the agent's section, whichever agent the server
uses), **Screen**, **Capture**, **Speech**, **Code** and **GPU**. The agent's section also holds what used to be
environment-only: **Agent model** (which model answers, or the one the agent picks by itself), **Thinking effort**
(how hard it is told to think) and **Hourly cost limit** (what an hour of the agent may cost before the tool stops
sending by itself).

- Models follow new releases. For Claude Code and the Anthropic API the list offers the families `opus`, `sonnet`
  and `haiku`, each the newest release of its family, so a new release is used without a change; a version chosen
  there before moves to its family. `SIDENOTE_AGENT_MODEL` pins a version (for example `claude-opus-5-5`), which the
  list then offers as well. For Codex the list holds Codex's own choice and the model `SIDENOTE_AGENT_MODEL` names.
- **Thinking effort** goes from low to max for Claude Code and from low to high for Codex.
- With nothing chosen, a CLI picks its own model and effort, and the Anthropic API agent takes `SIDENOTE_MODEL` and
  `SIDENOTE_EFFORT`. For a family it asks the API's model list for the newest model by release date, once a run.
  The agent's card shows the model and the effort the next problem is asked with.
- Changing the model or the effort starts a fresh CLI process for the next problem; the **Hourly cost limit** applies
  at once.
- The **Hourly cost limit** counts only an agent that reports a price. A Codex login reports none, so its answers do
  not count toward it; the brake on empty answers in a row holds for every agent.

**Speech language** is in the **Speech** section, not in the **Settings** menu.

`.env` sets the starting values, and the settings the panel does not have. Create a `.env` file in this folder
with one setting per line and run `./sidenote up` to apply it. For example:

```bash
SIDENOTE_FAST=1
SIDENOTE_SPEECH_LANG=ko
```

| Setting | Default | Meaning |
|---|---|---|
| `SIDENOTE_LOCAL_MODEL` | `auto` | The local model: `auto` picks the largest measured model the local server has that fits the GPU's memory (server/models.py), or names one (pulled with `./sidenote llm pull`; also chosen in the panel) |
| `SIDENOTE_LOCAL_URL` | `http://llm:11434/v1` (the `llm` container) | The local model's server: Ollama, or any OpenAI-compatible server that takes images (LM Studio, llama.cpp's server, vLLM), as an address ending in `/v1` (the server asks `/chat/completions` and `/models` under it). The app uses `http://127.0.0.1:11434/v1` |
| `SIDENOTE_LOCAL_VRAM_GB` | (read from the GPU) | The GPU memory `auto` sizes the model by, when it cannot be read |
| `SIDENOTE_LOCAL_PULL` | `0` (`1` in the app) | `1`: the local model's card offers to download a missing model through Ollama (the app; in Docker the model container has no internet, and `./sidenote llm pull` fetches it) |
| `SIDENOTE_LOCAL_THINK` | `auto` | When the local model thinks before answering: `auto` (multiple choice, math, code and whatever the first pass says needs reasoning), `always`, `never` |
| `SIDENOTE_LOCAL_BUSY_MODEL` | `auto` | The smaller model used while another program keeps the GPU busy, which also takes the slower model off the card so its memory goes back (`auto`: the main model's smaller size, pulled with it; switched off or chosen in the panel) |
| `SIDENOTE_LOCAL_BUSY_RATIO` | `0.5` | An answer generated at under this share of its model's usual rate (the median of the recent ones) counts the GPU as busy |
| `SIDENOTE_LOCAL_BUSY_HOLD_SEC` | `30` | Seconds on the smaller model after a slow answer, before the usual model is tried again; a retry that finds the GPU still busy doubles it (`SIDENOTE_LOCAL_BUSY_HOLD_MIN`, in minutes, still works) |
| `SIDENOTE_LOCAL_BUSY_HOLD_MAX_SEC` | `600` | The longest that doubling goes: through a long video call the usual model is tried again ever less often, not every half minute |
| `SIDENOTE_LOCAL_IDLE_MIN` | `10` | Minutes after the last local answer before the model leaves the GPU (`-1`: never) |
| `SIDENOTE_LOCAL_SLOTS` | `2` | Requests the local model keeps its prompt for: the fast pass and the thinking pass, so a screen with nothing to solve stays at about 0.7 s after a problem (1.0 to 1.5 s with `1`; 1.3 to 1.5 s once after a thinking pass and its code check). Each slot takes about 740 MiB of GPU memory; `3` made every request slower when it was measured (section 10 of the local-first design) |
| `SIDENOTE_SEARCH_URL` | (the SearXNG container) | Web search for the local model. Empty turns it off |
| `SIDENOTE_FAST` | `0` | `1`: the local model answers without thinking (faster, but multiple choice with a trap option and hidden calculation go wrong more often), and the CLI agent answers at low effort, Claude Code on the newest Sonnet (measured with Claude Code: first character in about 0.6 seconds and the whole answer in about 3 seconds on a standard coding problem, about half of its default). `SIDENOTE_AGENT_MODEL` and `SIDENOTE_AGENT_EFFORT` still win |
| `SIDENOTE_AGENT` | `claude-code` | The cloud agent: `claude-code` (the Claude Code CLI with this PC's login), `codex` (the Codex CLI with this PC's login), `anthropic-api` (`ANTHROPIC_API_KEY`) or `off` (no agent: the local model answers everything). Any case is read the same, and an unknown value runs as `claude-code`. `SIDENOTE_CLAUDE`, its earlier name, is read when this is not set (its `cli` and `api` mean `claude-code` and `anthropic-api`); with neither set, `SIDENOTE_ANALYZER=api` means `anthropic-api` |
| `SIDENOTE_AGENT_MODEL` | (the agent's own default) | The model the CLI agent starts with: for Claude Code a family (`opus`, `sonnet`, `haiku`: the newest release of each) or a version that pins it (`claude-opus-5-5`), for Codex a model name. **Agent model** in the panel starts from it. `SIDENOTE_CLAUDE_MODEL`, its earlier name, is read when this is not set |
| `SIDENOTE_AGENT_EFFORT` | (the agent's own default) | How hard the CLI agent is told to think: `low`, `medium`, `high`, `xhigh` or `max` for Claude Code, `low` to `high` for Codex. Lower is faster. **Thinking effort** in the panel starts from it. `SIDENOTE_CLAUDE_EFFORT`, its earlier name, is read when this is not set |
| `SIDENOTE_MODEL` | `opus` | The Anthropic API agent's model when the panel chooses none: a family (`opus`, `sonnet`, `haiku`) is the newest model of that family the API lists, by release date, and a full name (`claude-opus-5-5`) pins it |
| `SIDENOTE_EFFORT` | `medium` | The Anthropic API agent's effort when the panel chooses none, `low` to `max`; empty sends none, which leaves the model's own default |
| `ANTHROPIC_API_KEY` | (none) | The key the Anthropic API agent uses |
| `SIDENOTE_SPEECH_LANG` | `auto` | Speech language `auto`, `ko` or `en`. Also **Speech language** in the panel |
| `SIDENOTE_LANG` | (not set) | The language of the panel, the server's messages and the commands: `en` or `ko`. Not set, the panel follows the browser's first language and the server the last panel that connected, and the commands and the capture program follow the system's language. With English, the models are asked to write the whole answer in English |
| `SIDENOTE_AUDIO` | `1` | `0` makes the server ignore sound |
| `SIDENOTE_VOICE_TRIGGER` | `1` | `0` stops solving problems given by voice automatically (live speech is still shown) |
| `SIDENOTE_WHISPER_MODEL` | `small` | Transcription model. `base` is lighter but makes more than twice as many errors on Korean |
| `SIDENOTE_SPEECH_GAP` | `6` | A pause longer than this (seconds) starts a new problem |
| `SIDENOTE_UTTER_END` | `1.5` | This much quiet (seconds) ends an utterance |
| `SIDENOTE_UTTER_MIN` | `0.8` | Shorter than this and the sound was a blip, not speech: it is never transcribed (the speech model writes a sentence anyway) |
| `SIDENOTE_SPEECH_GROUP_TRIES` | `3` | Analyses one unbroken run of speech may start. What is still being read is solved whole once the speaker stops |
| `SIDENOTE_REGION_THRESHOLD` | `0.25` | This much change inside the problem region counts as a new screen |
| `SIDENOTE_SUPERSEDE_LIMIT` | `2` | How many times in a row an analysis in progress gives way to a new screen |
| `SIDENOTE_SUPERSEDE_KEEP_SEC` | `20` | An analysis that has run this long (seconds) is in its long pass: a new screen no longer stops it, and is looked at after it (section 5) |
| `SIDENOTE_MIN_INTERVAL` | `1.5` | Minimum interval between analyses (seconds) |
| `SIDENOTE_SETTLE_SEC` | `1.2` | How long the screen must have been still before it is asked about by itself. A screen being typed on or scrolled is not the one you want an answer about |
| `SIDENOTE_SETTLE_BUSY` | `3.0` | How long it must have been still when the frame before it arrived less than `SIDENOTE_BUSY_GAP` ago. Frames one after another are a screen being driven, and the pause between two of them is not you stopping to read |
| `SIDENOTE_BUSY_GAP` | `4.0` | A frame arriving more than this long after the one before it is taken as something appearing on a screen that had gone quiet, and waits only `SIDENOTE_SETTLE_SEC` |
| `SIDENOTE_SETTLE_MAX_SEC` | `8` | A screen that never comes to rest (a video in a corner) is asked about anyway after this long. 0 turns the settle off |
| `SIDENOTE_QUIET_AFTER` | `8` | Answers in a row that find nothing before the watching quiets down. 0 turns that off |
| `SIDENOTE_QUIET_SEC` | `8` | How long a small screen change then waits. A new window or page, a question, **Reanalyze** or a drawn region is not held back |
| `SIDENOTE_QUIET_JUMP_RATIO` | `1.6` | What counts as a new window or page while quiet, as a multiple of `SIDENOTE_CHANGE_THRESHOLD` |
| `SIDENOTE_LOCAL_TIMEOUT` | `180` | Time limit for one local answer, and for loading the model before it when it is not on the GPU (seconds) |
| `SIDENOTE_LOCAL_FAST_TIMEOUT` | `45` | Time limit for the first pass, which only says what kind of problem is on screen; running out of it counts as a busy GPU |
| `SIDENOTE_LOCAL_FIRST_TOKEN_SEC` | `6` | When the agent could take the screen, the first pass's first token must come within this; nothing by then counts as a busy GPU and the screen goes to the agent at once |
| `SIDENOTE_LOCAL_COLD_FIRST_TOKEN_SEC` | `45` | The same limit for a model that has not answered since it was loaded, whose prompt cache is still empty |
| `SIDENOTE_LOCAL_STUCK_SEC` | `60` | A local request with no token for this long, while nothing else is answered either, is checked with a one-token request; a model server that answers that one with nothing is taken off the GPU, and Ollama starts it again and answers the waiting request |
| `SIDENOTE_LOCAL_PROBE_SEC` | `20` | How long that one-token request may take before the model server counts as stuck |
| `SIDENOTE_LOCAL_SLOW_RATIO` | `1.5` | A problem that needs reasoning goes to the agent whatever its type when the local model takes this many times as long as the agent to start its answer (0 turns it off) |
| `SIDENOTE_CONTINUE_WINDOW_SEC` | `600` | A problem joined by scrolling within this many seconds of its answer fills that answer out under the same card instead of being solved again (0 turns it off) |
| `SIDENOTE_CLI_TIMEOUT` | `120` | How long a CLI agent's answer may go quiet before the turn is ended (seconds) |
| `SIDENOTE_RUNNER_URL` | (set automatically in the container) | Code runner address. Empty turns the **Run** feature off (the button disappears from the panel) |
| `SIDENOTE_RUNNER_TIMEOUT` | `10` | Time limit for one code run (seconds) |
| `SIDENOTE_RUNNER_TOKEN` | (empty) | The token sent with every run, for a runner reached over TCP that takes runs only with it (`RUNNER_TOKEN`). The Helm chart makes one; compose's Unix socket needs none |
| `SIDENOTE_TRUST_GATEWAY` | `1` | Whether connections from the container's default gateway are let in, as Docker's published port makes them. The Helm chart sets `0`: loopback only, where `kubectl port-forward` arrives |
| `SIDENOTE_PORT` | `8777` | Port of the panel address. `./sidenote` uses the same value |
| `SIDENOTE_LOG_MAX_MB` | `5` | Maximum size of one log file (MB, whole number) |
| `SIDENOTE_LOG_FILES` | `4` | Number of old log files kept |
| `SIDENOTE_LOG_DAYS` | `14` | Days before old log files are deleted |
| `SIDENOTE_LOG_PATH` | `~/.local/state/sidenote/logs` | Log folder. Write an absolute path when you change it |
| `SIDENOTE_ANALYZER` | `local` | `agent`: the cloud agent alone, with no local model (`cli` and `api`, its earlier names, still mean it); `mock`: fixed practice answers from both engines (for testing). Any case is read the same, and an unknown value runs as `local`, by the server and `./sidenote` alike |
| `SIDENOTE_AGENT_HOURLY_USD` | `2.0` | What an hour of the agent may cost before the tool stops sending by itself. Only an agent that reports a price counts toward it (Claude Code and the Anthropic API; a Codex login reports none). **Reanalyze** and questions still go. 0 turns the cap off. `SIDENOTE_CLAUDE_HOURLY_USD`, its earlier name, is read when this is not set |
| `SIDENOTE_AGENT_EMPTY_STREAK` | `6` | Agent answers in a row that find nothing before automatic sending pauses (0 turns the pause off). `SIDENOTE_CLAUDE_EMPTY_STREAK`, its earlier name, is read when this is not set |
| `SIDENOTE_AGENT_COOL_SEC` | `300` | How long that pause lasts. `SIDENOTE_CLAUDE_COOL_SEC`, its earlier name, is read when this is not set |
| `SIDENOTE_CLI_TURN_BUDGET` | `300` | Seconds one turn of a CLI agent may take in all, however much it is still writing |
| `SIDENOTE_CLI_SESSION_TURNS` | `8` | Problems one `claude -p` process answers before a fresh one starts (Claude Code) |
| `SIDENOTE_GATE` | `signature` | How a changed screen is noticed: `signature` (pixels), `ocr`, `hybrid`, `auto` |
| `SIDENOTE_CROP` | `off` | Trimming the screen before the models see it: `off`, `auto` (margins), `aggressive` (the dominant block) |
| `SIDENOTE_CROP_SNAP` | `ink` | Growing the model's problem box out to the piece of writing it landed in, before the crop is cut: `ink` (walk the ink out to the gutters around it), `detector` (and ask the text detector, which needs `server/requirements-ocr.txt` installed into the image), `off` |
| `SIDENOTE_MAX_IMAGE_WIDTH` | `1600` | The screen is scaled down to this width before it goes to a model |
| `SIDENOTE_TRANSCRIBER` | `auto` | `auto` uses faster-whisper when it is installed, `null` turns speech off, `faster-whisper` requires it |
| `SIDENOTE_WHISPER_COMPUTE` | `int8` | How the speech model computes (`int8`, `float32`, ...) |
| `SIDENOTE_WHISPER_THREADS` | `4` | Cores the speech model may decode on. Left to itself it takes every core the container has |
| `SIDENOTE_WHISPER_HINT` | (technical words) | Words given to the speech model so it spells them right. Empty turns the hint off |
| `SIDENOTE_LOG_SPEECH` | `short` | What the log keeps about speech: `short` (how long, how many characters), `full` (the words too), `off` |
| `SIDENOTE_TRANSCRIBE_INTERVAL` | `2.0` | Seconds between passes over the rolling audio window |
| `SIDENOTE_TRANSCRIPT_WINDOW` | `15` | Seconds of speech the panel shows live |
| `SIDENOTE_SPEECH_MIN_CHARS` | `12` | Shorter than this, what was heard is a remark, not a problem |
| `SIDENOTE_SPEECH_CONTEXT` | `120` | Seconds of utterances that belong to one spoken problem |
| `SIDENOTE_AUDIO_HISTORY` | `180` | Seconds of sound kept in memory (must hold a whole utterance) |
| `SIDENOTE_UTTER_MAX` | `90` | Seconds before a long utterance is cut and carries on in the next one |
| `SIDENOTE_STALL_WARN_SEC` | `45` | The server writes every thread's stack when its event loop stops turning for this long |
| `SIDENOTE_STALL_EXIT_SEC` | `180` | And ends the process when it stays stuck. 0 turns either off |
| `SIDENOTE_SEARCH_ROUNDS` | `3` | Searches or page reads one answer may make |
| `SIDENOTE_SEARCH_TIMEOUT` | `8` | Seconds one search or page read may take |
| `SIDENOTE_DEBUG_FRAMES` | (off) | `1` writes the screens behind a "nothing to solve" into the log folder, 8 at a time |
| `SIDENOTE_LOCAL_KEEP_ALIVE` | `30m` | How long the local model stays on the GPU between problems (ollama's own form: `30m`, `-1` for always) |
| `SIDENOTE_AGENT_BIN` | (`claude` or `codex`) | The command the server runs for a CLI agent. `SIDENOTE_CLAUDE_BIN`, its earlier name, is read when this is not set |
| `SIDENOTE_CLAUDE_VERSION` | (this PC's Claude Code, else `2.1.307`) | The Claude Code version built into the server image. `./sidenote up` sets it from this PC's `claude --version` |
| `SIDENOTE_CODEX_VERSION` | (this PC's Codex, else `0.165.0`) | The Codex CLI version built into the server image. `./sidenote up` sets it from this PC's `codex --version` |
| `SIDENOTE_HISTORY_DAYS` | `90` | Days the answers are kept (section 5) |
| `SIDENOTE_HISTORY_MB` | `200` | Size the kept answers may reach; past it the oldest go first |
| `SIDENOTE_CPUS` | `8` | Cores the server may use (fewer on a machine with fewer: `./sidenote` brings this and `SIDENOTE_LLM_CPUS` down to what is there) |
| `SIDENOTE_LLM_CPUS` | `8` | Cores the model server may use. Answers run on the GPU; this caps loading a model and any fallback to the CPU, and the model download (`./sidenote llm pull`) too |

Finer settings not in the table (the change thresholds, the local model's context size and so on) are in
`server/config.py`, with explanations.
An empty value runs that setting with its default, and a value that is not a number also falls back to the
default, with a warning in the server's startup output (`./sidenote logs`). The log caps cannot be turned off
with 0 (at least 64 KB per file and at least 1 old file).
`.env` is read with the same rules as docker compose: an `export` prefix, quotes, and a ` # comment` after the
value.

## 13. Troubleshooting

The messages are given here in English; section 18 has the Korean that the panel, the tray menu and `./sidenote`
show for each.

| Symptom | What to do |
|---|---|
| The panel says "Server disconnected" | `./sidenote up`. If that does not help, `./sidenote logs` |
| `up` says it cannot connect to Docker | Start Docker and run `./sidenote up` again |
| `up` says the server stopped while starting | The last line of the log shown with it is the cause. Check the `.env` value you just changed |
| A solution says "Stopped: connection lost" | It was cut off while the server restarted. Solve it again with **Reanalyze** |
| The panel says "Model … missing" | `./sidenote llm pull` (the default model), or `./sidenote llm pull <model>` for the one the panel names. The server notices it within 20 seconds |
| The panel says "The local model does not respond" | `./sidenote llm logs`. `./sidenote up` starts it again |
| The panel says "Nothing to solve N times in a row: automatic sending to the agent stops for N min" | The brake on asking the agent about nothing. **Reanalyze**, a question or a drawn region still go; it lifts itself after five minutes. The row and the hour are in `./sidenote events --errors` as `agent_brake` |
| The panel says "The agent's cost in the last hour, $…, reached the limit ($…)" | The hour's ceiling (**Solver settings**, **Agent**, **Hourly cost limit**). **Reanalyze** and questions still go |
| The tray says "Not connected (./sidenote up)" | The capture program is running but the server is not: `./sidenote up`. It stops grabbing the screen while there is nowhere to send it, and starts again by itself |
| The server disappeared and the panel says "Server disconnected" | It may have ended itself in a stall: `stall.txt` in the log folder holds every thread's stack from that moment, and the next start says so in its log. `./sidenote up` |
| The panel says "Agent sign-in needed" | `./sidenote login` signs in the agent the server uses (`./sidenote login codex` for Codex); analysis resumes within 20 seconds. The Anthropic API agent needs `ANTHROPIC_API_KEY` in `.env` and `./sidenote up` |
| The panel says "Agent sign-in expired", and its card says **Sign-in expired** | The CLI's login expired. `./sidenote login` (or `./sidenote login codex`), or `/login` in Claude Code |
| The panel says "Capture program off" | `./sidenote capture`. If that says the capture is already running, run `./sidenote capture-stop` and try again |
| Capture has ended but something seems to be left on Windows | `./sidenote capture-stop`. If it could not stop some, it says how many |
| The screen signal is orange | The capture program is off. `./sidenote capture` |
| The screen signal is green but no solutions appear | Check that `capture.log` in the log folder (or the terminal, with `--console`) shows `[screen] sent frame`. With several monitors, use `--monitor` |
| The sound signal is gray or orange | Check the **Sound capture** switch in **Capture**. If the device could not be opened, use `--audio-device "part of the name"` |
| The screen changed but it did not solve again | The change was outside the problem region. **Reanalyze** solves right away |
| The panel says "Usage limit" | Continue with **Reanalyze** a little later |
| `up` says another program is using port 8777 | Stop that program, or put another port in `.env`, such as `SIDENOTE_PORT=8778`, and run `./sidenote up` |
| A code box has no **Run** | It is added only to code marked as Python, Java, C, C++, JavaScript, TypeScript, Kotlin, Go or Bash. If it is still missing, look at the code runner line of `./sidenote status` |
| A run says "Cannot reach the runner" | `./sidenote up` starts the runner again |
| A run says "No result in time" | The runner is up but stuck (`./sidenote status` says the code runner is not responding). `./sidenote restart` recreates it; `up` leaves a running container as it is |
| A run says "Another code run is going" | Press it again when the previous run ends (runs go one at a time) |
| A run shows **Compile timed out** or **Timed out** | Check for an endless loop or an input that is too large. The limits are in section 5 |
| Answers are slow | Put `SIDENOTE_FAST=1` in `.env` and run `./sidenote up`. Making the images smaller does not make it faster |
| Analysis errors keep coming | `./sidenote events --errors` shows the cause |
| The browser does not open `localhost` | Open `127.0.0.1` instead. In some WSL network setups `localhost` resolves to IPv6 |

If a port opened in WSL is not visible from Windows, add the following to `%UserProfile%\.wslconfig`, run
`wsl --shutdown`, and start WSL again.

```ini
[wsl2]
networkingMode=mirrored
```

## 14. Security and privacy

The table says what leaves this PC, and the points under it give the details.

| What | Leaves the PC | When |
|---|---|---|
| Screens, crops, the problem text, speech | Not by themselves: they go to this PC's model, the speech recognizer and the code runner | Always; what the agent is sent is the last row |
| Search queries | To search engines, through SearXNG | **Web search** is on and the local model searches; never with a number shaped like personal data |
| Page reads | To that site | **Read pages** is on and the local model asks for a page; public addresses only, never with a number shaped like personal data |
| What the agent is sent | To the agent's service: Anthropic for Claude Code and the Anthropic API, OpenAI for Codex | The agent is signed in and **Problems the agent solves** is not **Off**; in the form **What is sent to the agent** chooses |

- The server listens only inside this PC (`127.0.0.1`). The panel has no login and shows screen thumbnails, so
  do not open the port to the outside.
- A website open in the browser cannot attach to the panel. The server accepts only connections from the
  panel's own address (Origin) and requests addressed to `127.0.0.1` or `localhost` (Host). A WebSocket
  connection from another site is rejected and recorded as `refused` in `./sidenote events`; a request with
  another Host is rejected without a record.
- No other container can attach to the panel either, the code runner above all: the example check runs code a
  model wrote from what is on the screen, and that code could otherwise connect the way the capture program does
  and change the switches. The server takes connections only through its published port (the browser and the
  capture program) and from inside its own container; any other is refused and recorded as `refused`.
- The panel loads nothing from the internet. The fonts and libraries (marked, DOMPurify, KaTeX, highlight.js,
  mermaid) are fetched at pinned versions when the image is built, with their checksums verified, and the
  Content Security Policy (CSP) runs only the server's own scripts.
- Screens, crops and speech go to the local model, the speech recognizer and the code runner, all in containers
  on this PC; the local model's container has no internet.
- Faces on the screen (a video call, a video, a photo, a profile picture) are painted gray as each screen arrives,
  before the change detector, this PC's model, the cloud agent, the crops or the panel's thumbnail see it
  (**Screen** > **Cover faces**, on by default). The finder runs on this PC's CPU (about 50 ms a screen at 1080p,
  120 ms at 4K). It covers most faces from about 64 px wide up and about half of the 32 px ones (an avatar), and
  leaves drawn figures alone, so a face in a black-and-white photo stays. For a screen that must not be read at all,
  switch the screen off or pause.
- The log keeps the shape of what was heard, not the words: how long an utterance was and how many characters
  it held. Everything near the microphone passes through, including other people and whatever is playing, so
  the words are written to a file that lives for days only when asked for (`SIDENOTE_LOG_SPEECH=full`). The
  panel shows the live transcript either way, from memory.
- Every container drops all Linux capabilities and cannot gain privileges. The server adds back one
  capability (CHOWN) and the code runner four (SETUID, SETGID, CHOWN and KILL, to start each run as a user of
  its own); the others keep none. The server, the code runner and the search engine run with a read-only root
  filesystem; the local model's is writable, with the models in a volume of their own. The code runner has no
  network at all. The limits in `compose.yaml`: the server 512 processes, 8 GB of memory and 8 CPUs; the code
  runner 128 processes, 1 GB and 2 CPUs; the local model 256 processes, 24 GB and `SIDENOTE_LLM_CPUS` (8)
  CPUs; the search engine 128 processes and 512 MB, with no CPU limit; the model download that
  `./sidenote llm pull` starts has the local model's CPU limit and no other. They are there so that a part
  that goes wrong cannot take the PC over: measured: a stuck server held eight cores for 95
  minutes, which is what the server's limits and the stall watchdog are for.
- `POST /capture/quit`, which `./sidenote capture-stop` uses to ask the capture program to end itself, is
  refused when it comes from a page (any Origin that is not this server's own).
- With web search on (the default), the local model's search queries go to search engines through SearXNG
  (Brave, DuckDuckGo, Google's custom search, Bing, Yahoo, Wikipedia and Wikidata: SearXNG's defaults, and Bing and
  Yahoo turned on in `docker/searxng.yml` so a search still finds pages while some engines turn this PC away), and
  with page reading on (the default too) the server opens the public pages the model asks for itself (never
  addresses on this PC or its network). Each search and page read is shown on the panel as it happens. A search
  or page address holding a number shaped like personal data (a resident registration, phone, card or bank
  account number) is not sent; the model is told so.
- With the agent signed in, the problems that need reasoning go to it by default (to Anthropic for Claude Code and
  the Anthropic API, to OpenAI for Codex), as only what **What is sent to the agent** allows: the problem part of the
  screen (the default), the problem written out as text, or the whole screen. A problem given by voice goes as the
  question part of what was heard (with the whole screen chosen, the screen goes with it). When the local model
  cannot tell where the problem is on the screen and no box is drawn, the problem part and problem text choices send
  the problem as the local model wrote it out from the whole screen (on a landscape screen 3200 px or wider, from the
  model's own box first), and nothing (the local model solves it) when it could not write it out or the text holds a
  number shaped like personal data (a resident registration, phone, card or bank account number). While the local
  model is off or not answering, the agent gets every problem, as the whole screen (or the drawn region). To keep
  everything but search queries and page reads on this PC, set **Problems the agent solves** to **Off**, or
  `SIDENOTE_AGENT=off`.
- Each answer's **Details** list the search words and pages read for it, and `events.jsonl` records every item that
  left the PC (`outbound`: where to and what: the search words, the page address, or the kind and size of what went
  to the agent, never the screen itself). Before showing a screen that must not be seen, switch the screen off or pause.
- Full screen images are not saved. With **Keep answers** on, each answer keeps a small thumbnail of its screen in
  `history.sqlite` (90 days, 200 MB at most). `events.jsonl` keeps the time, the type, the one-line answer, follow-up
  questions, the first 200 characters of the speech that set off an analysis (small talk included), the search
  words and page addresses, tokens and cost, and is deleted under the 14-day rule.
- **Clear history** in the menu deletes the kept answers (`history.sqlite`). It does not touch the log files: delete
  those in the log folder (`~/.local/state/sidenote/logs/` with Docker, the data folder's `logs` with the app).
- The Claude Code agent reads and writes this PC's `~/.claude` (token refresh), and the Codex agent uses this PC's
  `~/.codex` for its login. Everything else they write stays inside the container: Claude Code's config backups and
  process registry go to the container's scratch space, each Codex run works in a temporary folder of its own that
  is removed after it, and no session history is kept.
- The server's container runs with almost every privilege dropped: one capability (CHOWN), no privilege
  escalation, a read-only root filesystem, and a process limit (the other containers are in the bullet on
  capabilities and limits above).
- The panel sanitizes the HTML in solutions before drawing it. Script or image tags from the screen that end
  up in a solution neither run nor send requests out.
  Solutions cannot imitate the panel's buttons or alerts (they cannot use id, class or data attributes), and
  links in solutions open in a new tab.
- Code that **Run** starts runs in a separate container (`runner`) with no network at all: the server reaches it
  through a socket only the two share. It runs on a read-only filesystem and has process and memory caps. Runs go one
  at a time, each as a user of its own, with CPU, memory and file size limits and a time limit; every process a run
  leaves behind and every file it wrote are deleted when it ends. Code that runs there cannot reach the server or the
  internet, cannot read or change the files or the processes of another run or of the compile, and cannot read or
  stop the runner itself. A run's result goes only to the panel that sent the code.
- Core dumps are off in the server, the code runner, the local model and the search engine. WSL writes the
  dump of a crashing program into the Windows temp folder, and one dump can be hundreds of MB.

## 15. For developers

- Panel preview: `http://127.0.0.1:8777/?demo=1` shows the panel with sample solutions and no server data.
- Testing without the GPU or a cloud agent: put `SIDENOTE_ANALYZER=mock` in `.env`, run `./sidenote up`, then
  `docker exec sidenote python -m server.mock_capture` sends synthetic problem screens.
- One test with the real engine: `docker exec sidenote python -m server.probe` (prints the solution of one
  synthetic problem with its tokens and cost; the local model in the default setup, the cloud agent with
  `SIDENOTE_ANALYZER=agent`).
- Structure and design decisions: [`ARCHITECTURE.md`](ARCHITECTURE.md).

### How it is built and shipped

Three parts, built and updated in different ways:

| Part | What it is | Built how | Updated by |
|---|---|---|---|
| Server | A container image, `sidenote:local` | `docker/Dockerfile`, built by `./sidenote up` | `./sidenote up` after a change (it rebuilds only what changed) |
| Code runner | A second image, `sidenote-runner:local`, with no network | `runner/Dockerfile` | the same |
| Capture program | Python run by the Windows Python, from `client/capture.py` | not built: run as it is | `./sidenote setup-windows` for its packages |

What is pinned, so a rebuild gives the same thing:

- Every Python package in the server image: exact versions in `docker/constraints.txt`, which `docker/Dockerfile`
  passes to pip as constraints. `server/requirements.txt` names what is wanted, the constraints decide which.
- The panel's libraries and fonts: `docker/vendor.json` holds a URL and a SHA-256 for each, fetched at build
  time and verified; nothing is loaded from the internet at run time.
- The images below the project: `ollama/ollama` and `searxng/searxng` at the tags in `compose.yaml`
  (`SIDENOTE_OLLAMA_VERSION`, `SIDENOTE_SEARXNG_VERSION`).
- Claude Code and Codex inside the image are built at this PC's versions, so the two never differ
  (`SIDENOTE_CLAUDE_VERSION` and `SIDENOTE_CODEX_VERSION`, passed by `./sidenote up`; without one on this PC, the
  version `compose.yaml` names). Claude Code is checked against its release manifest's SHA-256 and Codex against
  the npm registry's SHA-512.
- The capture program's Windows packages are the one thing not pinned: they install into a Python this project
  does not own, and a pin there would fight whatever else uses it.

`./sidenote version` prints all of it as it actually is: the source commit, the server image, the panel build
the running server serves, Claude Code and Codex on this PC and in the container, the image tags, the models pulled and
the log folder.

`./sidenote uninstall` lists everything this project put on the PC (containers, images, volumes, the desktop
shortcut, the log folder) and removes it only with `--yes`. The models live in a volume of tens of gigabytes,
so nothing is removed by a command that was typed by accident. The logs are left behind on purpose.

### Checks

The suites CI runs are in `tests/`, in two groups: the server and the capture program in mock mode (no GPU, no
network and no cloud agent), and the panel in headless Chromium through Playwright. Each suite prints one line per
check and a tally. [tests/README.md](../tests/README.md) says what every suite covers, what each needs on this PC,
and which checks are skipped where the measurement data is missing. `./sidenote qa` runs them here.
[QA.md](QA.md) follows a finding from its check through CI to the deploy.

```bash
tests/run.sh              # every suite
tests/run.sh server       # the server and capture suites
tests/run.sh panel        # the panel suites
tests/run.sh --list       # what a run would start, without running anything
```

Some of them:

| Suite | What it covers |
|---|---|
| `integ.py` | The server end to end with mock engines: the pipeline's branches, the code check in nine languages, the spend brake, the agent's settings |
| `agent_first.py` | The agent first and this PC's model when the agent cannot: routing by speed and by the GPU, the first-token deadline, the verify mode on a 4K screen |
| `codex_agent.py` | The Codex agent against a stand-in CLI that streams, sends whole, fails, dies and signs out |
| `capture_panel.py`, `capture_loop.py` | The capture client's loop and its messages, with a fake screen grabber |
| `stall_guard.py` | The stall watchdog (including a stall that holds the GIL) and the fork guard |
| `scroll_auto.py`, `audio_path.py` | Reading a scroll, and the sound path |
| `launcher_args.sh` | What `./sidenote` hands to Windows (each capture option as typed, a value with spaces whole), how it reads `SIDENOTE_ANALYZER`, works without Claude Code and finds the capture program; every outside program is stood in for |
| `panel_*.py` | The panel in headless Chromium: the scroller and the rail, the run box, the follow-up buttons, the settings sheet, charts and diagrams, redraws while the page is read |

A few checks need a real GPU, a Windows desktop or a signed-in agent; they are not part of CI.

## 16. Running on Kubernetes

A Helm chart in `deploy/helm/sidenote` runs the same services on a cluster with the same isolation: the code
runner gets no network (a NetworkPolicy with no egress, and the server as its only client), the local model is
optional and asks for a GPU, and the agent's login comes from a Secret you create. The chart has no Ingress: the
server answers only requests addressed to `127.0.0.1` or `localhost`, so the panel is reached through a
port-forward that you keep on 127.0.0.1.

```bash
helm install sidenote deploy/helm/sidenote --namespace sidenote --create-namespace -f my-values.yaml
kubectl --namespace sidenote port-forward svc/sidenote-server 8777:8777
```

[deploy/helm/sidenote/README.md](../deploy/helm/sidenote/README.md) covers what the cluster needs (a network
plugin that enforces NetworkPolicy, the NVIDIA device plugin for the local model), building and pushing the two
images, the Secret for each agent, and what differs from compose. The capture program then runs on its own on the
Windows PC (section 17).

## 17. Running the capture program on its own

When the server is not in this PC's WSL (in a cluster, for example), the capture program runs alone on the Windows
PC whose screen and sound it reads: install its packages into Windows Python and start it with the server's
address. It sends to `ws://127.0.0.1:8777/ingest` by default, which a port-forward on that PC reaches. With the
repository in WSL on that PC, `./sidenote capture` starts it as usual. [capture-client.md](capture-client.md) has
the steps and the options.

## 18. Panel labels

The panel shows its labels and messages in English, or in Korean when the browser is set to Korean
(the menu's **Language** picks one). This guide calls each control by its English label; the table gives the Korean one.
The agent is **Agent** (에이전트) in every label, whichever agent the server uses. The messages of the tray menu and
of `./sidenote` are here too.

| Korean | English | Where |
|---|---|---|
| 서버 | Server | top bar, a signal |
| 이 PC의 모델 | Local model | top bar signal, its own card |
| 이 PC의 모델 | This PC's model | **Solving**, the local model's switch |
| 에이전트 | Agent | the agent's signal, card and settings section, whichever agent the server uses |
| 화면 | Screen | top bar, a signal |
| 소리 | Sound | top bar, a signal |
| 다시 분석 | Reanalyze | top bar |
| 일시정지 | Pause | top bar |
| 계속하기 | Continue | top bar: **Pause** while paused |
| 일시정지 중 | Paused | alert bar, **What is heard** |
| 밝기 | Theme | **Settings** menu |
| 자동 | Auto | **Settings** menu (**Theme**, **Motion**, **Language**), **Think before answering**, **Speech language** |
| 밝게 | Light | **Settings** menu |
| 어둡게 | Dark | **Settings** menu |
| 풀이 설정 | Solver settings | **Settings** menu, the settings sheet |
| 기록 지우기 | Clear history | **Settings** menu |
| 새로고침 | Reload | alert bar, when a new version of the panel is ready |
| 명령 복사 | Copy command | alert bar, error cards |
| 자세한 오류 | Error details | error cards |
| 서버 연결 끊김 | Server disconnected | alert bar |
| 캡처 프로그램 꺼짐 | Capture program off | alert bar |
| 모델 … 없음 | Model … missing | alert bar |
| 아직 이 PC의 모델 없음 | No local model yet | alert bar, in the app |
| 이 PC의 모델 응답 없음 | The local model does not respond | alert bar |
| 풀 엔진이 모두 꺼짐 | Every engine is off | alert bar |
| 풀 엔진 없음 | No engine to solve | error cards |
| 풀 수 있는 엔진이 없습니다 | No engine can answer | `./sidenote status` |
| 에이전트 로그인 필요 | Agent sign-in needed | alert bar, error cards |
| 에이전트 로그인 만료 | Agent sign-in expired | alert bar |
| 사용량 한도 | Usage limit | error cards |
| 연결 끊김으로 중단 | Stopped: connection lost | error cards, an answer cut off |
| 연달아 N번 풀 것이 없어 N분 동안 에이전트에 자동 전송 멈춤 (다시 분석, 질문은 보냄) | Nothing to solve N times in a row: automatic sending to the agent stops for N min (Reanalyze and questions still go) | notice, the agent's card |
| 최근 1시간 에이전트 비용 $…, 한도($…)에 닿아 자동 전송 멈춤 (다시 분석, 질문은 보냄) | The agent's cost in the last hour, $…, reached the limit ($…): automatic sending stops (Reanalyze and questions still go) | notice, the agent's card |
| 복사 | Copy | the answer line, code boxes, tables |
| 정답 한 줄 복사 | Copy the one-line answer | the tooltip of **Copy** beside the answer line |
| 복사됨 | Copied | a copy button after a press |
| 복사 실패 | Copy failed | a copy button that could not copy |
| 전체 복사 | Copy all | an answer's tools |
| 접기 | Fold | an answer's tools |
| 풀이 보기 | Show the solution | a folded answer |
| 문제 글 | Problem text | an answer's tools; a choice of **What is sent to the agent** |
| 문제 글 복사 | Copy problem text | under the problem text |
| 물음 | Question | above the answer |
| 검증 | Tests | under an answer: the example check |
| 통과 | Passed | **Tests** |
| 순서 무관 | any order | **Tests** |
| 제자리 수정 | in place | **Tests** |
| 오차 1e-09 | tolerance 1e-09 | **Tests** (the number is the problem's own) |
| 같은 값이 순서만 다른 결과 있음 | Some results hold the same values in another order | **Tests**, a failed example |
| 다시 풀기 | Retry | under an answer: the retry after a failed example |
| 스크롤해 이어 본 문제로 풀이 보강 | Solution filled out from the scrolled problem | a follow-up under the same card |
| 답 검토 | Review | the margin of the agent's verdict under an answer, in the **Check answers** mode (the mode's own name, on one line) |
| 세부 | Details | under an answer: the tokens, the cost, the search words and pages read |
| 멈춤 | Stopped | an answer stopped by pause or a switch |
| 풀 문제 없음 | No problem to solve | the one-line card |
| (생각이 길어 출력 한도에 닿음, 그 생각으로 다시 씀) | (The thinking reached the output limit; writing the answer again from it) | an answer being written again |
| 그림을 그리는 중… | Drawing the diagram… | a picture being written |
| 표로 보기 | View as a table | under a chart |
| 원문 보기 | View the source | under a diagram |
| 표 | Table | a table's bar |
| 작성 중 | Writing | a code box's bar while it is written |
| 실행 | Run | code boxes |
| 입력 | Input | code boxes, the hover over a function |
| 출력 | Output | the hover over a function |
| 컴파일 시간 초과 | Compile timed out | a run's result |
| 시간 초과 | Timed out | a run's result |
| 실행기 연결 실패 · 서버 터미널에서 ./sidenote up | Cannot reach the runner · ./sidenote up in the server's terminal | a run's result |
| 실행 결과 시간 초과 · 계속되면 서버 터미널에서 ./sidenote restart | No result in time · if it goes on, ./sidenote restart in the server's terminal | a run's result |
| 다른 코드 실행 중 · 끝나면 다시 실행 | Another code run is going · run again when it ends | a run's result |
| 더 묻기 | More | under the newest answer |
| 더 깊게 | Go deeper | **More** |
| 다른 풀이 | Another approach | **More**, an algorithm answer |
| 복잡도 근거 | Why this complexity | **More**, an algorithm answer |
| 반례 찾기 | Find a counterexample | **More**, an algorithm answer |
| 확인 방법 | How to confirm | **More**, a work answer |
| 다른 원인 | Other causes | **More**, a work answer |
| 새 답 | New answer | the button that jumps to the latest answer |
| 추가 질문 | Follow-up | the question box; the type of a follow-up's answer |
| 질문 | Ask | the button beside the question box |
| 보내기 | Send | **Confirm before sending** |
| 보내지 않기 | Don't send | **Confirm before sending** |
| 이 PC | This PC | the engine named under an answer |
| 선다형 | MCQ (the margin), Multiple choice (**Types the agent solves**) | a problem's type |
| 단답형 | Short (the margin), Short answer (**Types the agent solves**) | a problem's type |
| 서술형 | Essay | a problem's type |
| 코딩 | Coding | a problem's type |
| 알고리즘 | Algorithm | a problem's type |
| 실무 | Work (the margin), Practical (**Types the agent solves**) | a problem's type |
| 수학 | Math | a problem's type |
| 그림 | Diagram | a problem's type |
| 기타 | Other | a problem's type |
| 화면 캡처 | Screen capture | **Capture**, a switch |
| 소리 캡처 | Sound capture | **Capture**, a switch |
| 24시간 답, 응답 p50, 평균 TTFT, 평균 TPS | 24 h, Response p50, Avg TTFT, Avg TPS | the cards of **Local model** and **Agent** |
| TTFT, 쓰는 시간 | TTFT, Writing time | the key of the bars under them |
| TTFT N초 | TTFT N s | a bar's tooltip, the line under an answer |
| 세션, 주간, N% 사용, … 뒤 초기화 | Session, Week, N% used, Resets in … | the agent's card: the plan's usage of its five-hour session and week, read where Claude Code's own `/usage` reads it, at once when a panel opens and every 90 s while one is |
| 움직임: 켜기, 자동, 끄기 | Motion: Full, Auto (the system's setting), None | **Settings** menu; **Full** by default, though the system asks for less |
| 언어: 자동, English, 한국어 | Language: Auto (the browser's language), English, 한국어 | **Settings** menu; each language is named in its own words |
| 확인 중 | Checking | a state of a source |
| 연결됨 | Connected | a state of a source |
| 꺼 둠 | Off | a state of a source |
| 로그인 필요 | Sign-in needed | the agent's card |
| 로그인 만료 | Sign-in expired | the agent's card |
| 올라감 | On GPU | **Local model** |
| 대기 중 | Idle | **Local model** |
| GPU 비우기 | Free the GPU | **Local model**, the **GPU** section |
| GPU에 올리기 | Load onto the GPU | **Local model**, the **GPU** section |
| 조용히 보는 중 | Watching quietly | **Screen capture** |
| 소리 없이 실행 중 | Running without sound | **Sound capture** |
| 이 답의 화면 | This answer's screen | the screen card |
| 영역 그리기 | Draw a region | the screen card |
| 영역 해제 | Clear the region | the screen card |
| 들리는 말 | What is heard | a card in the right column |
| 목차 | Contents | a card in the right column |
| 풀이 엔진 | Solving | a section of **Solver settings** |
| 화면 처리 | Screen | a section of **Solver settings** |
| 캡처 | Capture | a section of **Solver settings** |
| 음성 | Speech | a section of **Solver settings** |
| 코드 | Code | a section of **Solver settings** |
| 생각하고 답하기 | Think before answering | **Solving** |
| 항상 | Always | **Think before answering** |
| 안 함 | Never | **Think before answering** |
| 안 함 | Off | **Problems the agent solves** |
| 쓸 모델 | Model | **Solving** |
| GPU가 바쁠 때 쓸 모델 | Model when the GPU is busy | **Solving** |
| 웹 검색 | Web search | **Solving**; **Details**, as "Sent to Web search: …" |
| 페이지 읽기 | Read pages; Page reading | **Solving**; **Details**, as "Sent to Page reading: …" |
| 에이전트가 푸는 문제 | Problems the agent solves | **Agent** |
| 어려운 문제 | Hard problems | **Problems the agent solves** |
| 답 검토 | Check answers | **Problems the agent solves** |
| 모두 | All | **Problems the agent solves** |
| 에이전트에 보내는 것 | What is sent to the agent | **Agent** |
| 문제 부분 화면 | Problem area | **What is sent to the agent** |
| 화면 전체 | Whole screen | **What is sent to the agent** |
| 에이전트가 푸는 유형 | Types the agent solves | **Agent** |
| 에이전트 모델 | Agent model | **Agent** |
| 생각 깊이 | Thinking effort | **Agent** |
| 한 시간 비용 한도 | Hourly cost limit | **Agent** |
| 한도일 때 이 PC의 모델이 대신 풀기 | This PC's model stands in at a limit | **Agent** |
| 에이전트가 거절하면 이 PC의 모델이 풀기 | This PC's model answers when the agent declines | **Agent** |
| 보내기 전 확인 | Confirm before sending | **Agent** |
| 대신 푸는 중 | Standing in | **Local model** card |
| 한도로 쉼 | Resting at its limit | the agent's card |
| 다시 보냄 | Sends again | the agent's card |
| 답 찾기 | Find an answer | **Contents**, the search box |
| 답 기록 남기기 | Keep answers | **Screen** |
| 기록 지우기 | Clear history | the menu |
| 내보내기 | Export | **Contents** |
| 얼굴 가리기 | Cover faces | **Screen** |
| 같은 문제 다시 풀지 않기 | Don't solve the same problem again | **Screen** |
| 문제 부분 확대 | Zoom in on the problem | **Screen** |
| 직접 그린 영역 | Drawn region | **Screen** |
| 창 경계에서 자르기 | Cut at window edges | **Screen** |
| 문제 글 옮겨 적기 | Write out the problem text | **Screen** |
| 실행 버튼 | Run button | **Code** |
| 예제 자동 검증 | Check the examples | **Code** |
| 말로 한 문제 자동 풀이 | Solve spoken problems | **Speech** |
| 기술 용어 힌트 | Technical term hints | **Speech** |
| 음성 언어 | Speech language | **Speech** |
| 한국어 | 한국어 | **Speech language** (written in Korean in both languages, as **English** is in English) |
| 스크롤 이어 붙이기 | Join scrolled screens | **Capture** |
| 모니터 | Monitor | **Capture**; **Screen capture** |
| 쉬는 동안 GPU 비우기 | Free the GPU when idle | **GPU** |
| 기본값으로 되돌리기 | Reset to defaults | the foot of **Solver settings** |
| 패널 열기 | Open the panel | the tray menu |
| 화면 보기 | Screen capture | the tray menu |
| 소리 듣기 | Sound capture | the tray menu |
| 캡처 다시 시작 | Restart capture | the tray menu |
| 끝내기 | Quit | the tray menu |
| 서버에 연결되지 않음 (./sidenote up) | Not connected (./sidenote up) | the tray menu's state line |
| Docker에 연결할 수 없습니다 | Cannot connect to Docker | `./sidenote up` |
| 서버가 시작하다 멈췄습니다 | The server stopped while starting | `./sidenote up` |
| 포트(8777)를 다른 프로그램이 쓰고 있습니다 | Another program is using port 8777 | `./sidenote up` |
| 캡처가 이미 실행 중입니다 | The capture is already running | `./sidenote capture` |
| 코드 실행기: 응답 없음 | Code runner: not responding | `./sidenote status` |
| 예제 없음 | no examples | `./sidenote report`, the example checks |
