# Third-party notices

Sidenote's own code is under the MIT License (LICENSE). It uses the components below. None of the panel's libraries or
fonts is kept in this repository: `docker/vendor.json` lists each file with its source and checksum, and the build
fetches them into `panel/vendor/`, served by the panel itself so that it needs no network once built.

## In the panel (fetched at build time, `docker/vendor.json`)

| Component | Version | License | Source |
|:---|:---:|:---:|:---|
| marked | 18.1.0 | MIT | https://github.com/markedjs/marked |
| marked-cjk-friendly | 0.1.2 | MIT | https://github.com/tats-u/markdown-cjk-friendly |
| DOMPurify | 3.1.6 | Apache-2.0 or MPL-2.0 | https://github.com/cure53/DOMPurify |
| highlight.js | 11.9.0 | BSD-3-Clause | https://github.com/highlightjs/highlight.js |
| KaTeX | 0.16.9 | MIT (its fonts: SIL Open Font License 1.1) | https://github.com/KaTeX/KaTeX |
| Mermaid | 11.17.2 | MIT | https://github.com/mermaid-js/mermaid |
| Pretendard | 1.3.9 | SIL Open Font License 1.1 | https://github.com/orioncactus/pretendard |
| JetBrains Mono | 5.0.20 (Fontsource) | SIL Open Font License 1.1 | https://github.com/JetBrains/JetBrainsMono |
| Bricolage Grotesque | Google Fonts v9 | SIL Open Font License 1.1 | https://github.com/ateliertriay/bricolage |
| Instrument Sans | 5.2.8 (Fontsource) | SIL Open Font License 1.1 | https://github.com/Instrument/instrument-sans |

## In this repository

| Component | License | Where |
|:---|:---:|:---|
| YuNet face detection model (2023mar) | MIT, Copyright (c) 2020 Shiqi Yu | `server/assets/face_detection_yunet_2023mar.onnx`, its license beside it |
| Hallmark themes (Ribbon, Dusk, Refract) | MIT, https://github.com/Nutlope/hallmark | their component styles, followed by `panel/new.css`, an alternative design that is not loaded |

## Run beside Sidenote, not part of it

These are separate programs that Sidenote starts or talks to. Their own licenses and terms apply, and the local model's
weights are downloaded by you from their publisher, under the publisher's terms.

| Component | License or terms | Note |
|:---|:---:|:---|
| Ollama | MIT | the local model server (its own container image) |
| Local model weights (Gemma 4 by default) | the model publisher's terms (Gemma Terms of Use) | `./sidenote llm pull` downloads them; Sidenote does not redistribute them |
| SearXNG | AGPL-3.0 | the web search, its own unmodified container image |
| Claude Code | Anthropic's terms | downloaded from Anthropic when you build the server image, or by the Helm chart when a pod starts; not in the published images |
| Codex CLI | Apache-2.0 | downloaded from npm when the server image is built, and part of the published image |
| faster-whisper and the server's Python packages | their own licenses (MIT, BSD, Apache-2.0) | installed from PyPI when you build the server image |

## In the desktop app (`desktop/build.py`)

The app for Windows, macOS and Linux is one folder (on macOS, an app bundle) with Python (PSF License 2.0) and the
Python packages the server and the capture program use, built with PyInstaller (GPL-2.0 with its bootloader exception,
which leaves the built program's license to its author). Each package's license files are in the app's `licenses/`
folder (on macOS, `Sidenote.app/Contents/Resources/licenses`), one folder per package, with a line naming its license.
Most are MIT, BSD or Apache-2.0. These are under other terms:

| Component | License | Note |
|:---|:---:|:---|
| FFmpeg libraries, inside PyAV (`av`) | LGPL-2.1 or later | the speech recognizer's audio decoding; shared libraries, as PyAV ships them. Source: https://ffmpeg.org |
| pystray | LGPL-3.0 | the tray icon. Its source is at https://github.com/moses-palmer/pystray, and the app can be rebuilt with another copy from this repository |
| python-xlib (Linux) | LGPL-2.1 | pystray's X11 backend |
| tqdm | MPL-2.0 and MIT | a dependency of the speech model download |
