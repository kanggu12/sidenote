# Running Sidenote with no internet

Sidenote runs on a PC or a network with no way to the internet. The local model reads the screen and answers, the speech
model hears, and the code runner checks the code, all on that machine. What it needs is prepared once on a connected PC and
carried over as a bundle of files.

## What works, and what cannot

| | With no internet |
|:---|:---|
| Reading the screen and answering, with the local model | Works |
| Hearing a question and answering it | Works, with the speech model in the bundle |
| The panel, Practice, stars, history, Anki and Markdown export, Keep what is heard | Works: the panel's libraries and fonts are in the image |
| Running code and checking it on a problem's examples | Works |
| **Cloud agents** (Claude Code, Codex, the Anthropic API) | Not possible: they are on the internet. The local model answers everything |
| **Web search and reading pages** | Not possible: a question about something current is answered from what the model knows |
| The new-version notice, `./sidenote llm pull`, the panel's **Download** key | Off: a new version or model comes the way the first one did |

With the agent off, the largest model answers most of what the agent would. On the project's known-answer set the `26b` got
51 of 56 right, with all of the spoken questions and all of the code; the `e4b` 34 and the `e2b` 24.

The bundle does not hold what the PC itself needs first, which you bring your own way: Docker with Compose, `python3`, and for
the GPU its driver, with the NVIDIA Container Toolkit on NVIDIA.

## 1. On a connected PC: make the bundle

Any Linux or WSL 2 PC with Docker, x86-64 as the other one is. It needs no GPU, and room for the bundle: about 5 GB of images,
half a GB for speech, and the model. Take the newest [release](https://github.com/kanggu12/sidenote/releases) by its tag:

```bash
git clone --depth 1 --branch <tag> https://github.com/kanggu12/sidenote
cd sidenote
./sidenote up                                     # builds the images, pulls Ollama's, downloads the speech model
docker logs sidenote 2>&1 | grep "speech model ready"   # ask again until this prints a line: minutes, the first time
./sidenote llm pull sidenote-gemma4:e4b           # the model for the other PC's GPU, from the table below
./sidenote down
```

| GPU memory on the PC with no internet | Model | Download |
|:---|:---|---:|
| 24 GB | `sidenote-gemma4:26b` | 18 GB |
| 12 to 16 GB | `sidenote-gemma4:e4b` | 6.6 GB |
| 8 GB | `sidenote-gemma4:e2b` | 4.6 GB |

Every model pulled on this PC goes into the bundle, so pull only the ones you want. A speech model comes along the same way:
`small` by default, and to carry `medium` as well, choose it in the panel here first. Then write the bundle. For an AMD GPU,
`docker pull ollama/ollama:0.40.5-rocm` and save that in place of `ollama/ollama:0.40.5`.

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
`--dereference` follows the links, and `--exclude=blobs` keeps the model from going twice.

The capture program takes a few Python packages. Download them on a connected PC with the same system and the same Python
version as the one it will run on (Windows, for a Windows screen). On Windows, with a copy of the checkout's `client` folder:

```bat
py -3 -m pip download -r client\requirements.txt -d bundle\wheels
```

On Linux, `python3 -m pip download -r client/requirements.txt -d bundle/wheels`. Bring Python's own installer too if that PC
has none. Last, the checksums, to tell a file damaged on the way:

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
```

Compose then says the two volumes were not created by it, which does no harm. The panel is at <http://127.0.0.1:8777>, and
`./sidenote status` shows the local model.

| Line in `.env` | What it does |
|:---|:---|
| `SIDENOTE_OFFLINE=1` | `./sidenote up` builds nothing, pulls nothing and leaves the search engine out, and `./sidenote llm pull` says where a model comes from |
| `SIDENOTE_AGENT=off` | No cloud agent is asked, and none is shown as signed out |
| `SIDENOTE_SEARCH_URL=` | No web search: a model would otherwise call it and wait |
| `SIDENOTE_UPDATE_CHECK=0` | The server does not ask GitHub for a newer release |
| `HF_HUB_OFFLINE=1` | The speech model is taken from the volume at once, with no try at the network |
| `SIDENOTE_WHEELS=...` | `./sidenote setup-capture` installs from this folder instead of the internet |

Then the capture program, on the PC whose screen it reads:

```bash
./sidenote setup-capture
./sidenote capture
```

A speech model that is not in the bundle cannot be chosen in the panel: the choice stays on the one there is.

## The app, with no Docker

The Windows and Linux apps hold the server and the capture program, so there are no packages to carry. Bring the zip from the
[release](https://github.com/kanggu12/sidenote/releases), Ollama's own download (on Linux its archive, as its install script
needs the internet), and `models.tar` and `speech.tar` from step 1. Install Ollama, then put the two in place. The paths below
are for Windows. On Linux they are `~/.local/share/sidenote/hf` and `~/.ollama`, or `/usr/share/ollama/.ollama`, owned by its
`ollama` user, for an Ollama that runs as a service.

```bat
mkdir "%USERPROFILE%\.ollama"
tar xf models.tar -C "%USERPROFILE%\.ollama"
mkdir "%LOCALAPPDATA%\Sidenote\hf"
tar xf speech.tar -C "%LOCALAPPDATA%\Sidenote\hf"
setx SIDENOTE_AGENT off
setx SIDENOTE_UPDATE_CHECK 0
setx SIDENOTE_LOCAL_PULL 0
setx HF_HUB_OFFLINE 1
```

Start the app from a new window, so that it sees them. On Linux, set the same in the environment it starts from.

## Kubernetes

Copy the images to a registry inside the network, and bring the chart, `sidenote-<version>.tgz`, from the release:

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
helm install sidenote sidenote-<version>.tgz --namespace sidenote --create-namespace -f my-values.yaml --wait
kubectl -n sidenote exec -i deploy/sidenote-llm -- tar xf - -C /root/.ollama < models.tar
kubectl -n sidenote exec -i deploy/sidenote-server -- tar xf - -C /data/hf < speech.tar
kubectl -n sidenote rollout restart deploy/sidenote-server
```

## A new version

Make a new bundle with only what changed, `images.tar.gz` and `sidenote.tar.gz`, and load them as above, keeping your `.env`.
The volumes stay, and with them the models and your history.

## How this is checked

`tests/offline_check.sh` brings the server and the code runner up from `compose.yaml` on a network with no way out, with the
settings above. It fails if the start waits on the internet, or if the page loads anything from outside. It also writes and
unpacks the speech bundle with the command above, from a cache laid out as the real one is, and fails if a link is left in it
or the model is not found. CI runs it on every commit.
