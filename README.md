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
  <a href="https://github.com/kanggu12/sidenote/releases"><img alt="Release v0.1.6" src="docs/assets/badges/release.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="docs/assets/badges/license.svg"></a>
  <img alt="Runs on Windows, Linux and macOS" src="docs/assets/badges/runs-on.svg">
  <img alt="GPU: NVIDIA, AMD or none" src="docs/assets/badges/gpu.svg">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> |
  <a href="#why-sidenote">Why Sidenote</a> |
  <a href="#what-it-runs-on">What it runs on</a> |
  <a href="docs/README.md">User guide</a> |
  <a href="docs/ARCHITECTURE.md">Architecture</a> |
  <a href="CONTRIBUTING.md">Contributing</a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshot-dark.png">
    <img alt="The Sidenote panel: a practice problem's answer with its key point, the approach, the code and its complexity, beside the capture, local model and agent cards" src="docs/assets/screenshot-light.png" width="920">
  </picture>
</p>

Sidenote reads your screen and listens to your speakers. When a problem appears (a practice coding problem, a question in
your course material, an error log to debug, a question someone asks out loud), it writes a worked answer into a notebook
panel beside your work. It runs on your own PC, and the cloud agent sees only the problems that need it.

## Please use it fairly

Sidenote is made for learning, practice and your own work. Please do not use it where outside help is not allowed,
such as a graded exam, a certification test or a job interview. Thank you.

## Quick start

| Your PC | What to do | What you need |
|:---|:---|:---|
| **Windows 10 or 11** | [Download the app and run it](#windows-the-app) | Ollama, for the local model |
| **A Linux desktop** | [Download the app and run it](#linux-the-app) | Ollama |
| **Linux or WSL 2, with Docker** | [`./sidenote install`](#with-docker-linux-or-windows-with-wsl-2) | Docker and `python3` |
| **A Mac** | [`./sidenote install`](#with-docker-on-a-mac) | Docker Desktop and Ollama for Mac |
| **A Kubernetes cluster** | [`helm install`](#kubernetes) | Helm 3 |

All of them run the same server and panel. Docker and Kubernetes add web search for the local model and a sandbox that
checks code answers. Not sure? On a Windows PC, use the app.

### Windows: the app

No Docker and no Python needed.

1. Install [Ollama](https://ollama.com/download) for the local model. Without it, the cloud agent answers everything;
   turn **Local model** off in **Solver settings** (in the gear menu) so the panel stops asking for Ollama.
2. Optional, for the hard problems: install [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or
   [Codex](https://github.com/openai/codex), and sign in once in a terminal: `claude`, or `codex login`. Sidenote uses
   the one it finds when it starts, Claude Code first.
3. 3. Download
   [Sidenote-windows-x64.zip](https://github.com/kanggu12/sidenote/releases/latest/download/Sidenote-windows-x64.zip),
   right-click it, choose **Extract All**, then open the `Sidenote` folder inside and run `Sidenote.exe`. If Windows warns
   about an unknown publisher, choose **More info**, then **Run anyway**.
4. After a minute the panel opens in your browser, and an icon appears by the clock (on Windows 11 perhaps under the
   **^**). A band at the top offers the model that fits your GPU: choose **Download**.

Open a practice problem and the answer appears in the panel. To stop, right-click the icon and choose **Quit Sidenote**.
If the panel does not open, see [Troubleshooting](docs/README.md#13-troubleshooting); the logs are in
`%LOCALAPPDATA%\Sidenote\logs`.

### Linux: the app

For an X11 session with glibc 2.35 or newer: Ubuntu 22.04 or newer, Debian 12 or newer. Ubuntu usually starts a
Wayland session: pick the Xorg one from the gear on the login screen.

1. Install Ollama: `curl -fsSL https://ollama.com/install.sh | sh`.
2. Optional, for the hard problems: install Claude Code or Codex and sign in once: `claude`, or `codex login`.
3. Download [Sidenote-linux-x64.zip](https://github.com/kanggu12/sidenote/releases/latest/download/Sidenote-linux-x64.zip),
   then run `unzip Sidenote-linux-x64.zip && ./Sidenote/Sidenote`.
4. In the panel, choose **Download** for the model that fits your GPU.

It reads the X11 screen, and the speaker sound through PulseAudio or PipeWire. To stop, choose **Quit Sidenote** from the
tray icon. The logs are in `~/.local/share/sidenote/logs`.

<details>
<summary>Checking a download</summary>

The app is not code-signed yet. Each release lists the SHA-256 of its files in `SHA256SUMS`: run
`sha256sum -c --ignore-missing SHA256SUMS` in the download folder, or in PowerShell compare
`Get-FileHash Sidenote-windows-x64.zip` with its line there. GitHub also records where each file was built (from 0.1.1
on): `gh attestation verify Sidenote-windows-x64.zip --repo kanggu12/sidenote`.
</details>

### With Docker: Linux, or Windows with WSL 2

You need Docker with `docker compose` and `python3` (on Windows, both inside WSL 2), and for an NVIDIA GPU on Linux the
[NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html).
On Windows the capture program runs in Python for Windows (the `py` command, from
[python.org](https://www.python.org/downloads/windows/)).

```bash
git clone https://github.com/kanggu12/sidenote.git && cd sidenote
./sidenote install        # build the server, set up the capture program, check everything
./sidenote llm pull       # the model that fits your GPU
./sidenote capture --up   # start the server and the capture
./sidenote open           # open the panel in the browser
```

`./sidenote doctor` shows which GPU it found, `./sidenote status` what is running, and `./sidenote down` stops
everything and frees the GPU.

### With Docker on a Mac

Docker on a Mac has no GPU, so the local model runs in [Ollama for Mac](https://ollama.com/download), on Apple silicon's
GPU, and the server in Docker asks it. You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) and
`python3` (macOS offers to install it the first time you type it).

```bash
# the model, with the context and batch Sidenote sets (pick the size for your memory from "What it runs on")
ollama pull gemma4:e4b
printf 'FROM gemma4:e4b\nPARAMETER num_ctx 16384\nPARAMETER num_batch 1152\n' > Modelfile
ollama create sidenote-gemma4:e4b -f Modelfile

git clone https://github.com/kanggu12/sidenote.git && cd sidenote
printf 'SIDENOTE_LOCAL_URL=http://host.docker.internal:11434/v1\nSIDENOTE_LOCAL_MODEL=sidenote-gemma4:e4b\n' >> .env
./sidenote install
./sidenote capture --up
```

The first capture makes macOS ask for **Screen Recording** for your terminal: allow it in **System Settings**, then run
`./sidenote capture --up` again. For the sound, install [BlackHole](https://github.com/ExistentialAudio/BlackHole)
(`brew install blackhole-2ch`), and in **Audio MIDI Setup** make a **Multi-Output Device** of your speakers and
BlackHole, then choose it as the output. CI checks the control script, the capture program and the arm64 images on
macOS; the models' speed and answers have not been measured on a Mac yet.

### Kubernetes

Write `my-values.yaml` with your GPU's memory, the Secret made below and the model download:

```yaml
server:
  env:
    SIDENOTE_LOCAL_VRAM_GB: "24"      # your GPU's memory in GB: it picks the model
agent:
  auth:
    existingSecret: sidenote-agent    # the Secret made below
llm:
  pull:
    enabled: true                     # download the model during the install
```

```bash
kubectl create namespace sidenote
kubectl --namespace sidenote create secret generic sidenote-agent \
  --from-file=.credentials.json="$HOME/.claude/.credentials.json"      # the agent's login: Claude Code here
helm install sidenote oci://ghcr.io/kanggu12/charts/sidenote --namespace sidenote -f my-values.yaml --timeout 2h
kubectl --namespace sidenote port-forward svc/sidenote-server 8777:8777
```

The install downloads the model, which is what `--timeout 2h` is for. The [chart's README](deploy/helm/sidenote/README.md)
has the Secret for each agent, an AMD GPU and a full values file. The capture program then runs on your PC
([docs/capture-client.md](docs/capture-client.md)).

<details>
<summary>Everyday use: starting, stopping, updating</summary>

| To | The app | Docker |
|:---|:---|:---|
| Start | `Sidenote.exe`, or `./Sidenote/Sidenote` on Linux | `./sidenote capture --up` |
| Open the panel | click the tray icon | `./sidenote open` |
| See what runs | the panel's cards | `./sidenote status` |
| Stop | **Quit Sidenote** in the tray icon's menu | `./sidenote down` |
| Update | the newest release's zip, when the panel says one is out | `git pull && ./sidenote up` |
| Read the logs | `%LOCALAPPDATA%\Sidenote\logs`, or `~/.local/share/sidenote/logs` | `./sidenote logs` |
</details>

## Why Sidenote

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/stats-dark.svg">
  <img alt="Four figures from the author's own use: 1,271 empty screens checked on the GPU with no API tokens spent; 1.2 s median to decide that a screen has nothing to solve; 97% of empty screens kept off the paid agent (841 of 865 since Oct 28); 15.0k tokens per empty screen when the agent saw every screen" src="docs/assets/stats-light.svg" width="100%">
</picture>

Most screens have nothing to solve: a chat, a blog, the editor between problems. A tool that sends every screen to a paid
model pays for all of them. Sidenote asks the model on your GPU first, which says "nothing here" in about a second, for
free.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/chart-screening-dark.svg">
  <img alt="Bar chart of screens with nothing to solve, by day from Oct 26 to Nov 2. On Oct 27, before local-first screening, 158 of them went to the paid agent. From Oct 28 on almost all stayed on the GPU: 459 on the GPU that day, and only a sliver sent to the agent on any day after" src="docs/assets/chart-screening-light.svg" width="100%">
</picture>

<sub>From the author's own use, Oct 26 to Nov 2, read from Sidenote's event log. Before local-first screening, an
empty screen sent to the agent cost a median of 15.0k input tokens.</sub>

- **Local first, and it shows the cost.** Each answer says which engine answered, how long it took and what it cost.
- **Uses the agent you already have.** Claude Code or Codex with your own sign-in, so no API key; or the Anthropic API.
- **Fits your GPU.** It reads the GPU's memory, NVIDIA or AMD, and picks the largest measured model that fits.
- **Checks code answers.** With Docker or Kubernetes, code runs on the problem's examples in a sandbox with no network.
- **Lets you try first.** **Practice** shows the question, then one hint at a time, and the answer when you ask.
- **Keeps what you learn.** Star an answer, find it in the history, and export it as Markdown or as Anki notes.
- **Private by design.** Faces are covered before any model sees the screen, and each answer lists what left your PC.
- **Open source.** MIT licensed, with the test suite run on every push.

## What it runs on

| | No local model | `gemma4:e4b` | `gemma4:26b` (recommended) |
|:---|:---|:---|:---|
| GPU | none: the agent answers | 10 GB or more, NVIDIA or AMD | 24 GB, such as an RTX 3090 or 4090 |
| Memory | 8 GB | 16 GB | 32 GB |
| Disk, beside the app or the images | none | 6.6 GB | 18 GB |

It runs on Windows 10 or 11, Linux with X11 (Ubuntu 22.04 or newer), Docker on Linux or WSL 2, and Docker on a Mac.
Measured on the test PC (Ryzen 9 9950X, RTX 4090 24 GB): the server takes about 0.1 GB of memory, the speech model 0.6 GB,
and Ollama with the 26b 14 GB of memory beside 22 GB of the GPU's; the rest of each figure is room for the system and the
browser. The speech model runs on the CPU, about 8 s of it a sentence with `small`. The Windows app downloads as 110 MB;
with Docker, the images take about 8.5 GB, Ollama's 5.6 GB of it.

| GPU memory | Local model | Right, of 56 | Code passing, of 7 | Spoken, of 8 | Empty screen |
|:---:|:---:|---:|---:|---:|---:|
| 24 GB or more | `gemma4:26b` | 51 | 7 | 8 | 1.3 s |
| 10 to 22 GB | `gemma4:e4b` | 34 | 3 | 8 | 0.7 s |
| 8 GB | `gemma4:e2b` | 24 | 1 | 7 | 0.65 s |
| 6 GB or less, or no GPU | none: the agent answers | | | | |

Each local model alone, with the cloud agent off, on an RTX 4090: 56 real screens and spoken questions with known
answers, 7 of them coding problems whose code is run. The last column is how long it takes to decide that a screen has
nothing to solve. With the agent on, what the small models miss most (code, multi-step reasoning) goes to the agent.

Most of the screens are Korean and were answered in Korean; asked to answer in English, the 26b got 52 of the 56 right. Any
other OpenAI-compatible server that takes images (LM Studio, llama.cpp's server, vLLM) can be used too: set
`SIDENOTE_LOCAL_URL` (its `/v1` address) and `SIDENOTE_LOCAL_MODEL`. With Gemma 4 E4B, vLLM got 39 of 56 and llama.cpp's
server 35, against Ollama's 38 in that separate run ([how to start
them](docs/air-gapped.md#with-a-model-server-you-already-run)). Reports from other GPUs are welcome: [open a hardware
report](https://github.com/kanggu12/sidenote/issues/new?template=hardware_report.yml).

| | The app on Windows | The app on Linux (X11) | Docker on Linux or WSL 2 | Kubernetes |
|:---|:---:|:---:|:---:|:---:|
| NVIDIA GPU | yes | yes | yes | yes |
| AMD GPU | yes, through Ollama | yes, through Ollama | Linux, with ROCm | yes, with ROCm |
| No GPU | the agent answers | the agent answers | the agent answers | the agent answers |
| Web search for the local model | no | no | yes | yes |
| Code checks in a sandbox | no | no | yes | yes |
| [No internet](docs/air-gapped.md) | yes | yes | yes | yes |

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/diagram-pieces-dark.svg">
  <img alt="The capture program sends frames, sound and the window list to the Sidenote server. The server covers faces, finds the problem, sends every screen to the local vision model on your GPU, the hard problems to the cloud agent and code answers to the code runner, and keeps the answers. The panel in your browser shows the answers as they are written and sends your questions" src="docs/assets/diagram-pieces-light.svg" width="100%">
</picture>

Everything but the cloud agent runs on your PC, or on your own server with Docker or Kubernetes. One problem goes
like this:

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/diagram-answer-dark.svg">
  <img alt="The screen settles and the capture program sends one frame. The server covers faces and compares the problem with the last one. The local model's fast pass on the GPU says what kind of problem it is and where. Then: nothing to solve, decided on the GPU in a second with no tokens; a short question, answered at once; or a hard one, for the cloud agent when it would answer sooner, otherwise for the thinking pass on the GPU. A code answer is then run on the problem's own examples" src="docs/assets/diagram-answer-light.svg" width="100%">
</picture>

- **It finds the problem on its own.** A frame goes when the screen changes and settles, and typing next to a problem
  does not start it over. A question read out loud is picked up from the speaker sound.
- **It answers locally first.** Explanations, definitions and short questions come within a second or two, and multiple
  choice gets a moment of thought first.
- **It hands the hard ones to the agent:** code, algorithms, math, essays and work problems such as a log to debug, and
  anything the local model would be much slower to start answering. The agent gets only the problem's part of the screen by
  default. With no agent, the local model thinks them through itself.

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
|:---|:---|:---|
| `claude-code` (default) | the Claude Code CLI with this PC's login | `claude` once, or `./sidenote login` |
| `codex` | the Codex CLI with this PC's login | `codex login`, or `./sidenote login codex` |
| `anthropic-api` | the Anthropic API | `ANTHROPIC_API_KEY` |
| `off` | no cloud agent: the local model answers everything | |

With Docker, set it in `.env`; the app uses the one `SIDENOTE_AGENT` names, or the CLI it finds. The agent works as a
helper, not as your own session: none of your settings, plugins, rules or MCP servers are loaded. Claude Code gets no
tools but a web search, for a question about the present; Codex runs in a read-only sandbox. For Claude Code the model
setting offers `opus`, `sonnet` and `haiku`, each its newest release.

## Privacy

- Screens, crops and speech go to the local model and the speech recognizer on your PC.
- The problems that need reasoning go to the agent you signed in to (Anthropic for Claude Code and the API, OpenAI for
  Codex), by default as only the problem's part of the screen. **Solver settings** can send the problem's text or the
  whole screen instead, or nothing at all.
- Each answer lists what left your PC for it, and only this PC can open the panel: the server is reached on 127.0.0.1
  (on Kubernetes, through `kubectl port-forward`).
- Web searches go through SearXNG, and once a day the server asks GitHub whether a newer release is out, sending only
  Sidenote's version (`SIDENOTE_UPDATE_CHECK=0` turns that off).

The details are in [Security and privacy](docs/README.md#14-security-and-privacy).

## Documentation

- [User guide](docs/README.md): every control, setting and command, troubleshooting, security and privacy.
- [Architecture](docs/ARCHITECTURE.md): the components, the data flow and the protocol.
- [Design decisions](docs/DECISIONS.md): the reason for each part of the design, and the measurements behind it.
- [Local-first design](docs/DESIGN-local-first.md): why the local model answers first, and when the agent takes over.
- [Quality](docs/QA.md): from a test case through CI to a release.
- [Helm chart](deploy/helm/sidenote/README.md) and [the capture program on its own](docs/capture-client.md).
- - [Running with no internet](docs/air-gapped.md): the local model and speech on a closed network, and what cannot work
  there.
- [Changelog](CHANGELOG.md): what changed in each release.

The panel, the server's messages and the command line speak English, or Korean when your browser or system is set to
Korean. **Language** in the panel's gear menu picks one by hand. To add a language, see
[Contributing](CONTRIBUTING.md#add-a-language).

## Contributing

Questions and ideas are welcome in [Discussions](https://github.com/kanggu12/sidenote/discussions). Most of Sidenote
can be worked on without a GPU: the tests run the server with stand-in models and the panel in a headless browser. Start
with [CONTRIBUTING.md](CONTRIBUTING.md): how the pieces fit, the setup, the tests, and recipes for adding a model, a GPU
vendor, a language or a cloud agent.

```bash
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt -r server/requirements-audio.txt -c docker/constraints.txt websocket-client
./sidenote qa server
```

## License

MIT ([LICENSE](LICENSE)). The libraries, fonts and models Sidenote uses, and the programs it runs beside it, are
listed with their licenses in [THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md).
