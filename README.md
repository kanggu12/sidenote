<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.svg">
    <img alt="Sidenote" src="docs/assets/logo-light.svg" width="380">
  </picture>
</p>

<p align="center">
  <b>A study and work companion that reads your screen and writes the worked answer beside it.</b><br>
  A vision model on your own GPU looks at every screen first. Only the hard problems go to a cloud agent you already use.
</p>

<p align="center">
  <a href="https://github.com/kanggu12/sidenote/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/kanggu12/sidenote/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/kanggu12/sidenote/releases"><img alt="Release" src="https://img.shields.io/github/v/release/kanggu12/sidenote?include_prereleases&sort=semver"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-2a78d6.svg"></a>
  <img alt="Runs on Windows and Linux" src="https://img.shields.io/badge/runs%20on-Windows%20%7C%20Linux-555.svg">
  <img alt="GPU: NVIDIA, AMD or none" src="https://img.shields.io/badge/GPU-NVIDIA%20%7C%20AMD%20%7C%20none-555.svg">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#why-sidenote">Why Sidenote</a> ·
  <a href="#what-it-runs-on">What it runs on</a> ·
  <a href="docs/README.md">User guide</a> ·
  <a href="docs/ARCHITECTURE.md">Architecture</a> ·
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshot-dark.png">
    <img alt="The Sidenote panel: a practice problem's answer with its key point, the approach, the code and its complexity, beside the screen, sound, local model and agent cards" src="docs/assets/screenshot-light.png" width="920">
  </picture>
</p>

Sidenote reads your screen and listens to your speakers, finds the problem in front of you (a practice coding problem,
a question in your course material, an error log to debug, a question someone asks out loud), and writes a worked
answer into a notebook panel beside your work, as soon as the problem appears.

It runs on your own machine. A local vision model reads every screen and answers what it can right away. The problems
that need longer reasoning go to a cloud coding agent you are already signed in to (Claude Code or Codex), or to an
API. With Docker or Kubernetes, code answers are also run in a sandbox with no network and checked against the
problem's own examples.

## Please use it fairly

Sidenote is made for learning, practice and your own work. Please do not use it where outside help is not allowed,
such as a graded exam, a certification test or a job interview. Thank you.

## Why Sidenote

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/stats-dark.svg">
  <img alt="1,271 empty screens checked on the GPU with no API tokens; 1.2 s median to decide; 97% kept off the paid agent; 15.0k tokens per empty screen when the agent saw every screen" src="docs/assets/stats-light.svg" width="100%">
</picture>

Most screens have nothing to solve: a chat, a blog, the editor between problems. A tool that sends every screen to a
paid model pays for all of them. Sidenote asks the model on your GPU first, and it says "nothing here" in about a
second, for free. The cloud agent sees a screen only when there is a problem on it that needs reasoning.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/chart-screening-dark.svg">
  <img alt="Screens with nothing to solve by day: before local-first screening up to 158 a day went to the paid agent; after it, almost all stayed on the GPU" src="docs/assets/chart-screening-light.svg" width="100%">
</picture>

<sub>From the author's own use, Oct 26 to Nov 2, read from Sidenote's event log. Before local-first screening an empty
screen sent to the agent cost a median of 15.0k input tokens.</sub>

- **Local first, and it measures itself.** Every answer's card says which engine answered, how long it took and what it
  cost; `./sidenote report` adds them up by day.
- **Uses the agent you already have.** Claude Code and Codex run through their own CLI and your existing sign-in, so
  no API key is needed. The Anthropic API works too, or no agent at all.
- **Fits your GPU.** It reads the GPU's memory (NVIDIA or AMD, on Windows or Linux) and picks the largest measured model
  that fits. With no GPU, the cloud agent answers everything.
- **Checks code answers** (with Docker or Kubernetes). A coding answer is run on the problem's own examples in nine
  languages, in a sandbox with no network, and the card shows which examples pass.
- **Private by design.** Faces on the screen are covered before any model sees it. Each card lists exactly what left
  your PC for it. The server listens on 127.0.0.1 only.
- **Open.** MIT licensed, with a test suite CI runs on every push.

## Quick start

### Windows: the app

No Docker and no Python needed.

1. Install [Ollama](https://ollama.com/download) for the local model. (Skip it to use a cloud agent only.)
2. Download `Sidenote-windows-x64.zip` from the latest [release](https://github.com/kanggu12/sidenote/releases/latest)
   (under **Assets**), unzip it, and run `Sidenote.exe`. Windows may warn about an unknown publisher the first time:
   choose **More info**, then **Run anyway**.
3. The panel opens in your browser, and an icon appears in the notification area (by the clock). A band at the top of
   the panel offers the model that fits your GPU, with its size: choose **Download**.
4. Optional, for the hard problems: install [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or
   [Codex](https://github.com/openai/codex), open **Terminal** (or PowerShell) from the Start menu, and sign in once:
   type `claude` (or `codex login`) and press Enter. Sidenote uses the one it finds, Claude Code first.

Open a practice problem and the answer appears in the panel. To stop, right-click the icon and choose
**Quit Sidenote**. The app has no web search for the local model and no code checks: those need the Docker setup.
If the panel does not open or shows an error, the logs are in `%LOCALAPPDATA%\Sidenote\logs`
([Troubleshooting](docs/README.md#13-troubleshooting)).

### Linux: the app

1. Install Ollama: `curl -fsSL https://ollama.com/install.sh | sh`.
2. Download `Sidenote-linux-x64.zip` from the latest [release](https://github.com/kanggu12/sidenote/releases/latest),
   then run `unzip Sidenote-linux-x64.zip && ./Sidenote/Sidenote`.
3. In the panel, choose **Download** for the model that fits your GPU. For the hard problems, sign in to Claude Code or
   Codex in a terminal, as on Windows.

The capture program reads an X11 screen and the speaker sound through PulseAudio or PipeWire. To stop, choose
**Quit Sidenote** from the tray icon, or press Ctrl+C in the terminal. The logs are in `~/.local/share/sidenote/logs`.

### With Docker: Linux, or Windows with WSL 2

You need Docker with `docker compose` (on Windows, inside WSL 2), and for an NVIDIA GPU on Linux the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
On Windows the capture program runs in Python for Windows (the `py` command, from [python.org](https://www.python.org/downloads/windows/)).

```bash
git clone https://github.com/kanggu12/sidenote.git && cd sidenote
./sidenote install        # build the server, set up the capture program, check everything
./sidenote llm pull       # the model that fits your GPU
./sidenote capture --up   # start the server and the capture
```

Sidenote finds the GPU on its own (NVIDIA, AMD or none; `./sidenote doctor` shows which). This way also gives the local
model web search and runs code answers in a sandbox. `./sidenote status` shows what is running, and `./sidenote down`
stops everything and frees the GPU.

### Kubernetes

```bash
helm install sidenote oci://ghcr.io/kanggu12/charts/sidenote --namespace sidenote --create-namespace -f my-values.yaml
kubectl --namespace sidenote port-forward svc/sidenote-server 8777:8777
```

`my-values.yaml` names the Secret with the agent's login and, for an AMD GPU, `llm.gpuVendor: amd`; the
[chart's README](deploy/helm/sidenote/README.md) shows one. The chart keeps Docker's isolation: the code runner gets no
network, the local model asks for an NVIDIA or AMD GPU, and the agent's login comes from that Secret. The capture
program then runs on your PC ([docs/capture-client.md](docs/capture-client.md)).

## What it runs on

| GPU memory | Local model it picks | The local model alone, on 56 real screens with known answers |
|:---:|:---:|:---|
| 24 GB | `gemma4:26b` | 51 of 56 right, all 7 code answers pass, a screen with nothing on it in 1.3 s |
| 10 to 20 GB | `gemma4:e4b` | 34 of 56: every spoken question (8 of 8) and every problem's area on screen found, 3 of 7 code answers, an empty screen in 0.7 s |
| 8 GB | `gemma4:e2b` | 24 of 56: it finds the problems, answers 7 of 8 spoken questions and an empty screen in 0.65 s, but passes 1 of 7 code answers, so let the agent take the hard ones |
| 6 GB or less, or no GPU | none: the cloud agent answers | optional: `gemma4:e2b` on the CPU, slowly |

Measured on an RTX 4090 with the cloud agent off. With the agent on, the problems small models miss most (code,
multi-step reasoning) go to the agent. Most of the screens are Korean and were answered in Korean; asked to answer in
English, the 26b got 52 of the 56 right, every answer in English. Any other model with vision that Ollama, LM Studio,
llama.cpp or vLLM serves can be used: set `SIDENOTE_LOCAL_URL` (its `/v1` address) and `SIDENOTE_LOCAL_MODEL`. Reports
from other GPUs are welcome: [open a hardware report](https://github.com/kanggu12/sidenote/issues/new?template=hardware_report.yml).

| | The app on Windows | The app on Linux (X11) | Docker on Linux or WSL 2 | Kubernetes |
|:---|:---:|:---:|:---:|:---:|
| NVIDIA GPU | yes | yes | yes | yes |
| AMD GPU | yes, through Ollama | yes, through Ollama | Linux, with ROCm | yes, with ROCm |
| No GPU | the agent answers | the agent answers | the agent answers | the agent answers |
| Web search for the local model | no | no | yes | yes |
| Code checks in a sandbox | no | no | yes | yes |

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/diagram-pieces-dark.svg">
  <img alt="The capture program sends frames, sound and the window list to the Sidenote server. The server sends every screen to the local vision model on your GPU, the hard problems to the cloud agent, and code answers to the code runner; the panel in your browser shows the answers as they are written" src="docs/assets/diagram-pieces-light.svg" width="100%">
</picture>

Everything but the cloud agent runs on your PC, or on your own server with Docker or Kubernetes. One problem goes
like this:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/diagram-answer-dark.svg">
  <img alt="The screen settles and the capture program sends one frame. The server covers faces and compares the problem with the last one. The local model's fast pass on the GPU says what kind of problem it is and where. Then: nothing to solve, decided on the GPU with no tokens; a short question answered at once; or a hard one, for the cloud agent when it would answer sooner, otherwise the thinking pass on the GPU. A code answer is then run on the problem's own examples" src="docs/assets/diagram-answer-light.svg" width="100%">
</picture>

- **Finds the problem on its own.** The capture program sends a frame when the screen changes and settles. The server
  solves again only when the area of the last answer's problem changes, so typing next to a problem does not start it
  over. A question read out loud is picked up from the speaker sound.
- **Answers locally first.** The local model answers explanations, definitions and short questions within a second or
  two, and thinks before answering multiple choice, math and code.
- **Hands the hard ones to the agent** when the agent would start answering before the local model finishes
  thinking. Only the problem's part of the screen is sent by default.

## How it compares

| | Sidenote | Interview and meeting copilots | Screen recorders with search | Local screen agents |
|:---|:---:|:---:|:---:|:---:|
| Answers the problem on screen as it appears | yes | yes | no, they search what was seen | some |
| A model on your own GPU looks first | yes | rarely | for indexing | yes |
| Uses your Claude Code or Codex sign-in | yes | rarely | no | no |
| Picks a model for your GPU's memory | yes | no | no | no |
| Runs code answers on the problem's examples | yes | no | no | no |
| Hides itself from screen sharing and proctors | no, by design | several do | no | no |
| License | MIT | many closed, some GPL | mixed | mixed |

## Choosing the cloud agent

| `SIDENOTE_AGENT` | Uses | Sign in |
|---|---|---|
| `claude-code` (default) | the Claude Code CLI with this PC's login | `claude` once, or `./sidenote login` |
| `codex` | the Codex CLI with this PC's login | `codex login`, or `./sidenote login codex` |
| `anthropic-api` | the Anthropic API | `ANTHROPIC_API_KEY` |
| `off` | no cloud agent: the local model answers everything | |

With Docker, set it in `.env`; for the app, set it as an environment variable before starting it (the app otherwise
uses the CLI it finds). The agent is a helper here, not your session: none of your own settings, plugins, rules or MCP
servers are loaded, no tools are offered, and nothing is kept as a session. New models are picked up without a change: the model setting
offers model families (`opus`, `sonnet`, `haiku`) that always mean the newest release; `SIDENOTE_AGENT_MODEL` pins one.

## Privacy

Screens, crops and speech go to the local model and the speech recognizer on your PC. With an agent signed in, the
problems that need reasoning go to it (Anthropic for Claude Code and the API, OpenAI for Codex), as only the problem's
part of the screen by default; the panel's settings choose the problem's text, the whole screen, or nothing. Web
search queries go through SearXNG. Everything is in [Security and privacy](docs/README.md#14-security-and-privacy).

## Documentation

- [User guide](docs/README.md): every control, setting and command, troubleshooting, security and privacy.
- [Architecture](docs/ARCHITECTURE.md): components, data flow, protocol, and the design decisions with the
  measurements behind them.
- [Local-first design](docs/DESIGN-local-first.md): why the local model answers first and when the agent takes over.
- [Quality](docs/QA.md): from a test case through CI to a release.
- [Helm chart](deploy/helm/sidenote/README.md) and [the capture program on its own](docs/capture-client.md).

The panel, the server's messages and the command line speak English, and Korean when your browser or system is set to
Korean; the panel's settings menu has **Language** to pick one by hand. To add a language, see
[Contributing](CONTRIBUTING.md#add-a-language).

## Contributing

Most of Sidenote can be worked on without a GPU: the tests run the server with stand-in models and the panel in a
headless browser. Start with [CONTRIBUTING.md](CONTRIBUTING.md): how the pieces fit, the setup, the tests, and recipes
for adding a model, a GPU vendor, a language or a cloud agent.

```bash
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt -r server/requirements-audio.txt -c docker/constraints.txt websocket-client
PY=.venv/bin/python tests/run.sh server
```

## License

MIT ([LICENSE](LICENSE)). The libraries, fonts and models Sidenote uses, and the programs it runs beside it, are listed
with their licenses in [THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md).
