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
  <a href="https://github.com/kanggu12/sidenote/releases"><img alt="Release v0.13.2" src="docs/assets/badges/release.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="docs/assets/badges/license.svg"></a>
  <img alt="Runs on Windows, Linux and macOS" src="docs/assets/badges/runs-on.svg">
  <img alt="GPU: NVIDIA, AMD, Apple silicon or none" src="docs/assets/badges/gpu.svg">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> |
  <a href="#what-it-does">What it does</a> |
  <a href="#how-it-works">How it works</a> |
  <a href="#what-it-runs-on">What it runs on</a> |
  <a href="docs/README.md">User guide</a> |
  <a href="docs/API.md">API</a> |
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screens-dark.png">
    <img alt="Sidenote in use: on the left a practice coding problem, Pairs k apart, with its examples and an empty editor; on the right the Sidenote panel answering it, the approach to count the values and look for x + k in O(n), the reasoning and the Python code. Under it three more views: Heard, the sheet of what was said out loud, each line with its time; Solver settings on its Agent section, the chosen choices marked; and Capture, the tray menu and the start window of the capture program" src="docs/assets/screens-light.png" width="920">
  </picture>
</p>

Sidenote reads your screen and listens to your speakers. When a problem appears (a practice coding problem, a question in
your course material, an error log to debug, a question someone asks out loud), it writes a worked answer into a notebook
panel beside your work. It runs on your own PC, and the cloud agent sees only the problems that need it.

## Quick start

Install Sidenote, then add what solves: the [local model](#the-local-model-optional) on your GPU, a
[cloud agent](#the-cloud-agent-optional) you already use, or both. The panel opens in the browser with a setup guide
for the rest.

**Windows 10 or 11** (PowerShell)

```powershell
curl.exe -fL -o "$env:TEMP\Sidenote.zip" https://github.com/kanggu12/sidenote/releases/download/v0.13.2/sidenote-server-0.13.2-windows-x64.zip
mkdir -Force "$env:LOCALAPPDATA\Programs" | Out-Null; tar -xf "$env:TEMP\Sidenote.zip" -C "$env:LOCALAPPDATA\Programs"
& "$env:LOCALAPPDATA\Programs\Sidenote\Sidenote.exe"
```

**macOS 14 or newer** (Apple silicon). When macOS asks for **Screen Recording**, choose **Open System Settings**, turn
Sidenote on, then quit it from its menu bar icon and open it again.

```bash
curl -fL -o /tmp/Sidenote.zip https://github.com/kanggu12/sidenote/releases/download/v0.13.2/sidenote-server-0.13.2-macos-arm64.zip
ditto -x -k /tmp/Sidenote.zip /Applications && open /Applications/Sidenote.app
```

**Linux** (x64, an X11 session)

```bash
curl -fLO https://github.com/kanggu12/sidenote/releases/download/v0.13.2/sidenote-server-0.13.2-linux-x64.zip
unzip -oq sidenote-server-0.13.2-linux-x64.zip && ./Sidenote/Sidenote
```

**Docker** on Linux, WSL 2 or a Mac, with `git` and `python3`. It adds web search and a sandbox that runs code answers
on the problem's examples.

```bash
git clone https://github.com/kanggu12/sidenote.git && cd sidenote
./sidenote install
./sidenote capture --up
./sidenote open
```

On Kubernetes, use the [Helm chart](docs/README.md#16-running-on-kubernetes). The user guide has [what each way
needs](docs/README.md#2-requirements), [starting, stopping and updating](docs/README.md#4-everyday-use), and [the
capture program on its own](docs/capture-client.md) for another PC.

### The local model (optional)

It reads every screen first on your GPU (NVIDIA, AMD or Apple silicon), with no account. Install Ollama, start Sidenote
again, and choose **Download** on the panel's **Local model** card. With Docker, `./sidenote llm pull` instead
([on a Mac](docs/README.md#with-docker), Ollama for Mac).

```
# Windows (PowerShell)
winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
# macOS, with Homebrew
brew install ollama
# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

### The cloud agent (optional)

It takes the problems that need reasoning: [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or
[Codex](https://github.com/openai/codex) signed in once in a terminal (`claude`, or `codex login`), or the Anthropic API.
A CLI installed while Sidenote runs is found when it starts again; with Docker, `./sidenote login` checks the login.

## What it does

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/stats-dark.svg">
  <img alt="Four figures from the author's own use: 1,271 empty screens checked on the GPU with no API tokens spent; 1.2 s median to decide that a screen has nothing to solve; 97% of empty screens kept off the paid agent (841 of 865 since Oct 28); 15.0k tokens per empty screen when the agent saw every screen" src="docs/assets/stats-light.svg" width="100%">
</picture>

Most screens have nothing to solve: a chat, a blog, the editor between problems. A tool that sends every screen to a paid
model pays for all of them. Sidenote asks the model on your GPU first, which says "nothing here" in about a second, for
free.

- **Local first, and it shows the cost.** Each answer says which engine answered, how long it took and what it cost.
- **Uses the agent you already have.** Claude Code or Codex with your own sign-in, so no API key; or the Anthropic API.
- **Fits your GPU.** It reads the GPU's memory and picks the largest measured model that fits.
- **Checks code answers.** With Docker or Kubernetes, code runs on the problem's examples in a sandbox with no network.
- **Lets you try first, and keeps what you learn.** **Practice** shows the question, then one hint at a time. Star an
  answer, find it in the history, and export it as Markdown or as Anki notes.
- **Private by design.** Faces are covered before any model sees the screen, the windows you name stop the capture, and
  each answer lists what left your PC ([Security and privacy](docs/README.md#14-security-and-privacy)).

## How it works

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/diagram-pieces-dark.svg">
  <img alt="The capture program sends frames, sound and the window list to the Sidenote server. The server covers faces, finds the problem, sends every screen to the local vision model on your GPU, the hard problems to the cloud agent and code answers to the code runner, and keeps the answers. The panel in your browser shows the answers as they are written and sends your questions" src="docs/assets/diagram-pieces-light.svg" width="100%">
</picture>

Everything but the cloud agent runs on your PC, or on your own server with Docker or Kubernetes.

- **It finds the problem on its own.** A frame goes when the screen changes and settles, and a question read out loud is
  picked up from the speaker sound.
- **It answers locally first.** Explanations, definitions and short questions come within a second or two.
- **It hands the hard ones to the agent:** code, algorithms, math, essays and work problems such as a log to debug, with
  only the problem's part of the screen by default. With no agent, the local model thinks them through itself.

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

## What it runs on

| Local model | GPU | Mac | Memory | Disk | Right of 56 |
|:---|:---|:---|:---|:---|---:|
| none: the agent answers | none | any | 8 GB | | |
| `gemma4:e4b` | 10 GB or more | 16 to 24 GB | 16 GB | 6.6 GB | 34 |
| `gemma4:26b` (recommended) | 24 GB, such as an RTX 4090 | 32 GB or more | 32 GB | 18 GB | 51 |

The GPU is NVIDIA or AMD, or a Mac's Apple silicon, which works in the Mac's own memory. Sidenote runs on Windows 10 or
11, macOS 14 or newer, Linux with X11 (Ubuntu 22.04 or newer), Docker on Linux, WSL 2 or a Mac, and Kubernetes. *Right
of 56* counts real screens and spoken questions with known answers, each model alone on an RTX 4090. The rest of the
measurements and what each setup supports are in [What was measured](docs/README.md#what-was-measured); reports from
other GPUs are welcome as a [hardware report](https://github.com/kanggu12/sidenote/issues/new?template=hardware_report.yml).

## Documentation

- **Using it**: [User guide](docs/README.md) · [Running with no internet](docs/air-gapped.md) · [Changelog](CHANGELOG.md)
- **Running it elsewhere**: [Helm chart](deploy/helm/sidenote/README.md) · [The capture program on its own](docs/capture-client.md)
- **Building on it**: [API](docs/API.md) · [Architecture](docs/ARCHITECTURE.md) · [Design decisions](docs/DECISIONS.md) ·
  [Local-first design](docs/DESIGN-local-first.md) · [Quality](docs/QA.md)

The panel and the commands speak English, or Korean when your browser or terminal is set to Korean; **Language** in the
panel's gear menu picks one by hand. To add a language, see [Add a language](CONTRIBUTING.md#add-a-language).

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) has the setup, the tests (no GPU needed) and how a change goes in. Questions go to
[Discussions](https://github.com/kanggu12/sidenote/discussions), bugs to [Issues](https://github.com/kanggu12/sidenote/issues/new/choose).

## License

MIT ([LICENSE](LICENSE)). The libraries, fonts and models Sidenote uses, and the programs it runs beside it, are
listed with their licenses in [THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md).
