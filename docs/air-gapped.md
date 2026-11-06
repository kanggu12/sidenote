# Running Sidenote with no internet

Sidenote runs on a PC or a network with no way to the internet. The local model reads the screen and answers, the speech
model hears, and the code runner checks the code, all on that machine. What it needs is prepared once on a connected PC and
carried over as a bundle of files.

## What works, and what cannot

| | With no internet |
|:---|:---|
| Reading the screen and answering, with the local model | Works |
| Hearing a question and answering it | Works, with the speech model in the bundle |
| The panel, Practice, stars, history, Anki and Markdown export, Keep what is heard | Works: the panel's libraries and fonts come with Sidenote |
| Running code and checking it on a problem's examples | Works |
| **Cloud agents** (Claude Code, Codex, the Anthropic API) | Not possible: they are on the internet. The local model answers everything |
| **Web search and reading pages** | Not possible: a question about something current is answered from what the model knows |
| The new-version notice, `./sidenote llm pull`, the panel's **Download** button | Off: a new version or model comes the way the first one did |

With the agent off, the largest model answers most of what the agent would. On the project's known-answer set the `26b` got
51 of 56 right, with all of the spoken questions and all of the code; the `e4b` 34 and the `e2b` 24.

## What to bring

Sidenote runs there in one of three ways. Step 1 makes the same bundle for all of them, and each takes what it needs from it.

| | Docker | The app | Kubernetes |
|:---|:---|:---|:---|
| From the bundle | all of it | `models.tar`, `speech.tar` | all but `sidenote.tar.gz` |
| From the release | nothing more | the app's zip | the chart and the capture program's zip |
| Installed first, your own way | Docker with Compose, `python3`, the GPU's driver | Ollama, the GPU's driver | a cluster, a registry inside the network |

For an NVIDIA GPU, Docker also needs the NVIDIA Container Toolkit. With Docker the capture program needs Python: Python for
Windows when Sidenote runs in WSL, and the `python3-venv` package on a Debian or Ubuntu desktop.

## 1. On a connected PC: make the bundle

Use an x86-64 Linux or WSL 2 PC with Docker. The images are built for x86-64, so the PC with no internet must be x86-64 too.
It needs no GPU, only room for the bundle: about 5 GB of images, half a GB for speech, and the models.

Pick the models for the GPU of the PC with no internet. The second is the smaller one Sidenote answers with while another
program keeps the GPU busy; leave it out if you do not want that.

| GPU memory on the PC with no internet | Model | While the GPU is busy | Download |
|:---|:---|:---|---:|
| 24 GB or more | `sidenote-gemma4:26b` | `sidenote-gemma4:e4b` | 18 GB + 6.6 GB |
| 10 to 22 GB | `sidenote-gemma4:e4b` | `sidenote-gemma4:e2b` | 6.6 GB + 4.6 GB |
| 8 GB | `sidenote-gemma4:e2b` | none | 4.6 GB |

```bash
V=0.1.5                                     # the newest release, from the releases page
git clone --depth 1 --branch "v$V" https://github.com/kanggu12/sidenote
cd sidenote
./sidenote up                               # builds the images, pulls Ollama's and downloads the speech model
until docker logs sidenote 2>&1 | grep -q "speech model ready"; do sleep 10; done   # a few minutes, the first time
./sidenote llm pull sidenote-gemma4:e4b sidenote-gemma4:e2b                       # the two from the table above
```

Every model pulled on this PC goes into the bundle, so pull only the ones you want. The speech model `small` comes by
default. To carry `medium` as well, choose it now, in the panel at <http://127.0.0.1:8777>: **Solver settings**, **Speech**,
**Speech model**. Wait until `docker logs sidenote` shows `speech model ready (medium)`, then stop Sidenote:

```bash
./sidenote down
```

Then write the bundle. `docker save` takes the Ollama image the PC with no internet runs: `ollama/ollama:0.40.5`, or for an
AMD GPU on Linux `ollama/ollama:0.40.5-rocm`, which you `docker pull` first and name below instead.

```bash
mkdir bundle
docker save sidenote:local sidenote-runner:local ollama/ollama:0.40.5 | gzip > bundle/images.tar.gz
docker run --rm --entrypoint tar -v sidenote_llm-models:/v:ro -v "$PWD/bundle":/out sidenote:local \
  cf /out/models.tar --exclude='./id_ed25519*' -C /v .
docker run --rm --entrypoint tar -v sidenote_hf-cache:/v:ro -v "$PWD/bundle":/out sidenote:local \
  cf /out/speech.tar --dereference --exclude=blobs -C /v hub
git archive --format=tar.gz --prefix=sidenote/ -o bundle/sidenote.tar.gz HEAD
```

The speech model goes as plain files: its cache keeps them behind links, which Windows unpacks only with Developer Mode on.
`--dereference` follows the links, and `--exclude=blobs` keeps the model from going in twice.

The capture program needs a few Python packages, downloaded for the system and Python version it will run on: Windows, for a
Windows screen. On Linux:

```bash
python3 -m pip download -r client/requirements.txt -d bundle/wheels
```

On Windows, in a copy of the checkout's `client` folder, run `py -m pip download -r requirements.txt -d wheels`, then copy
the `wheels` folder into `bundle`. Bring Python's own installer too if the PC with no internet has none.

Last, write the checksums, which show a file damaged on the way:

```bash
cd bundle && find . -type f ! -name SHA256SUMS -exec sha256sum {} + > SHA256SUMS
```

## 2. On the PC with no internet

Carry the `bundle` folder over, and in it:

```bash
sha256sum -c SHA256SUMS
tar xzf sidenote.tar.gz
gunzip -c images.tar.gz | docker load
docker volume create sidenote_llm-models
docker volume create sidenote_hf-cache
docker run --rm --entrypoint tar -v sidenote_llm-models:/v -v "$PWD":/in sidenote:local xf /in/models.tar -C /v
docker run --rm --entrypoint tar -v sidenote_hf-cache:/v -v "$PWD":/in sidenote:local xf /in/speech.tar -C /v
cd sidenote
cat > .env <<SETTINGS
SIDENOTE_OFFLINE=1
SIDENOTE_AGENT=off
SIDENOTE_SEARCH_URL=
SIDENOTE_UPDATE_CHECK=0
HF_HUB_OFFLINE=1
SIDENOTE_WHEELS=$(cd .. && pwd)/wheels
SETTINGS
./sidenote up
./sidenote setup-capture                    # the capture program, from the bundle's wheels
./sidenote capture
```

Compose says the two volumes were not created by it, which does no harm. The panel is at <http://127.0.0.1:8777>, and
`./sidenote status` shows the local model.

| Line in `.env` | What it does |
|:---|:---|
| `SIDENOTE_OFFLINE=1` | `./sidenote up` builds nothing, pulls nothing and leaves the search engine out; `./sidenote llm pull` says a model comes with the bundle |
| `SIDENOTE_AGENT=off` | No cloud agent is asked, and none is shown as signed out |
| `SIDENOTE_SEARCH_URL=` | No web search: a model would otherwise call it and wait |
| `SIDENOTE_UPDATE_CHECK=0` | The server does not ask GitHub for a newer release |
| `HF_HUB_OFFLINE=1` | The speech model is taken from the volume at once, with no try at the network |
| `SIDENOTE_WHEELS=...` | `./sidenote setup-capture` installs from this folder instead of the internet |

A speech model that is not in the bundle cannot be chosen in the panel: the choice goes back to the one that is there.

## The app, with no Docker

The Windows and Linux apps hold the server and the capture program, so they need no images and no Python packages. Bring
`models.tar` and `speech.tar` from step 1, the app's zip from the [release](https://github.com/kanggu12/sidenote/releases)
(`Sidenote-windows-x64.zip` or `Sidenote-linux-x64.zip`), and Ollama's own download: on Linux its archive, as its install
script needs the internet.

Install Ollama. Its installer starts it at every sign-in, and Sidenote then uses that Ollama as it is. A model from a bundle
made with Sidenote 0.1.5 or later carries Sidenote's context with it. With an older bundle, quit Ollama from its tray icon
before you start Sidenote, which then starts it with its own settings: otherwise the model gets Ollama's 4096 tokens of
context instead of 16384. Then put the two in place, on Windows:

```bat
if not exist "%USERPROFILE%\.ollama" mkdir "%USERPROFILE%\.ollama"
tar xf models.tar -C "%USERPROFILE%\.ollama"
if not exist "%LOCALAPPDATA%\Sidenote\hf" mkdir "%LOCALAPPDATA%\Sidenote\hf"
tar xf speech.tar -C "%LOCALAPPDATA%\Sidenote\hf"
setx SIDENOTE_AGENT off
setx SIDENOTE_UPDATE_CHECK 0
setx SIDENOTE_LOCAL_PULL 0
setx HF_HUB_OFFLINE 1
```

`setx` reaches only the programs started after it. Start Sidenote from the Start menu or a new Command Prompt; if it is
already running, quit it from its tray icon first.

On Linux, with `ollama` from its archive on the `PATH`:

```bash
mkdir -p ~/.ollama ~/.local/share/sidenote/hf
tar xf models.tar -C ~/.ollama
tar xf speech.tar -C ~/.local/share/sidenote/hf
SIDENOTE_AGENT=off SIDENOTE_UPDATE_CHECK=0 SIDENOTE_LOCAL_PULL=0 HF_HUB_OFFLINE=1 ./Sidenote/Sidenote
```

An Ollama that runs as a service keeps its own settings, and its models in `/usr/share/ollama/.ollama`. Stop it with
`sudo systemctl disable --now ollama` so that Sidenote starts its own.

## Kubernetes

Push the bundle's images to a registry inside the network, under the names the chart asks for and the release's number as
their tag:

```bash
V=0.1.5                                     # the release the bundle was made from
gunzip -c images.tar.gz | docker load
for name in sidenote sidenote-runner; do
  docker tag "$name:local" "registry.internal/$name:$V" && docker push "registry.internal/$name:$V"
done
docker tag ollama/ollama:0.40.5 registry.internal/ollama/ollama:0.40.5 && docker push registry.internal/ollama/ollama:0.40.5
```

For an AMD GPU, push `ollama/ollama:0.40.5-rocm` the same way and add `gpuVendor: amd` under `llm` below. Bring the chart,
`sidenote-<version>.tgz`, from the release, and write a values file that names the registry and turns off what needs the
internet:

```yaml
# my-values.yaml
server:
  image:
    repository: registry.internal/sidenote
  env:
    SIDENOTE_UPDATE_CHECK: "0"
    HF_HUB_OFFLINE: "1"
runner:
  image:
    repository: registry.internal/sidenote-runner
llm:
  image:
    repository: registry.internal/ollama/ollama
agent:
  provider: "off"
search:
  enabled: false
```

```bash
helm install sidenote sidenote-$V.tgz --namespace sidenote --create-namespace -f my-values.yaml --wait
kubectl -n sidenote exec -i deploy/sidenote-llm -- tar xf - --no-same-owner -C /root/.ollama < models.tar
kubectl -n sidenote exec -i deploy/sidenote-server -- tar xf - --no-same-owner -C /data/hf < speech.tar
kubectl -n sidenote rollout restart deploy/sidenote-server
kubectl -n sidenote port-forward svc/sidenote-server 8777:8777    # the panel, at http://127.0.0.1:8777
```

`--no-same-owner` makes the unpacked files the pod's own: the pods run as root with most of its powers dropped, and that root
cannot read files that kept the owner they had on the other PC. Helm's notes after the install offer a model download, which
needs the internet; the two `tar` lines put the bundle's models in place instead.

The capture program runs on the PC with the screen, from the release's `sidenote-capture-<version>.zip`, as
[the capture program on its own](capture-client.md) says. Install its packages from the bundle's wheels, copied next to it:
`py -m pip install --no-index --find-links wheels -r requirements.txt` on Windows.

## With a model server you already run

Sidenote can use any OpenAI-compatible server that takes images, such as vLLM, llama.cpp's `llama-server` or LM Studio, in
place of Ollama. Leave `models.tar` out of the bundle and name the server and the model as that server calls it: in `.env`,
with `setx` for the app, or under `server.env` in the chart, with `llm.enabled: false`.

```bash
SIDENOTE_LOCAL_URL=http://model-server.internal:8000/v1
SIDENOTE_LOCAL_MODEL=gemma-4-26b
```

With Docker, `./sidenote up` then leaves its Ollama container out, so the bundle needs no Ollama image: save only
`sidenote:local` and `sidenote-runner:local`. The panel cannot download a model, switch to a smaller one while the GPU is
busy, or take a stuck model off the GPU with such a server: those go through Ollama's own API.

Start vLLM with the model's reasoning and tool parsers, for Gemma 4
`--reasoning-parser gemma4 --enable-auto-tool-choice --tool-call-parser gemma4`. Without the reasoning parser a pass that
thinks comes back empty, and without tool calling Sidenote leaves the web search out. With Gemma 4 E4B on the project's
known-answer set, llama.cpp's server got 35 of 56 and vLLM 30, against Ollama's 38 in the same run
([note 108](DECISIONS.md#note-108)).

## A new version

On the connected PC, clone the new release as in step 1, run `./sidenote up` and `./sidenote down`, and write
`images.tar.gz`, `sidenote.tar.gz` and `SHA256SUMS` again. On the PC with no internet, put them in the `bundle` folder, and
in it:

```bash
sha256sum -c SHA256SUMS
tar xzf sidenote.tar.gz
gunzip -c images.tar.gz | docker load
cd sidenote && ./sidenote up
```

`.env` stays, as the archive holds none. The volumes keep the models, and the history stays in
`~/.local/state/sidenote/logs`. For the app, bring the new zip. On Kubernetes, push the new images and run `helm upgrade`
with the new chart.

## How this is checked

`tests/offline_check.sh` brings the server and the code runner up from `compose.yaml` on a network with no way out, with the
settings above. It fails if the start waits on the internet, or if the page loads anything from outside. It also writes and
unpacks the speech bundle with the command above, from a cache laid out as the real one is, and fails if a link is left in it
or the model is not found. `tests/k3d_check.sh` unpacks one in the server's pod with the Kubernetes command above and finds
the model there. CI runs the first on every commit, and the second whenever the chart or the images change.
