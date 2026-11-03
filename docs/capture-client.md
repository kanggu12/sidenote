# Capture program

The capture program runs on the PC whose screen and sound Sidenote reads: Windows, or a Linux desktop with X11. It
sends a frame when the screen changes and settles, the speaker output for spoken problems, and the list of visible
windows (so a crop of the problem stops at its window's edge). It connects to the Sidenote server over a WebSocket
and does nothing else.

The app starts it by itself. On the PC that runs the server with Docker (in WSL, or on Linux), `./sidenote install`
sets it up and `./sidenote capture` starts it. To run it on its own (for a server in Kubernetes, or on another machine
whose port is forwarded to this PC):

1. Install Python 3.10 or newer ([python.org](https://www.python.org/downloads/); on Windows its installer adds the
   `py` command).
2. Install its packages, from the folder of the release's `sidenote-capture-<version>.zip` or the repository's
   `client` folder: `py -m pip install -r requirements.txt` on Windows, or on Linux
   `python3 -m pip install -r requirements.txt` in a virtual environment.
3. Start it there, pointing at the server:

   ```powershell
   py capture.py --server ws://127.0.0.1:8777/ingest
   ```

   On Linux, `python3 capture.py --server ws://127.0.0.1:8777/ingest` in the desktop session: it reads the X11 screen
   (in a Wayland session only what XWayland shows) and the speaker sound through PulseAudio or PipeWire's PulseAudio.

   For a server in a cluster, forward its port to this PC first and keep the forward on 127.0.0.1:
   `kubectl --namespace sidenote port-forward svc/sidenote-server 8777:8777`. The server answers only requests
   addressed to `127.0.0.1` or `localhost`, so the chart has no Ingress
   ([the Helm chart's guide](https://github.com/kanggu12/sidenote/blob/main/deploy/helm/sidenote/README.md)). A port-forward ends when the server's pod
   is replaced; start it again, and the program reconnects by itself. The panel has no login of its own, so keep
   the server off public networks.

Useful options:

| Option | What it does |
|---|---|
| `--monitor N` | capture monitor N (`--list-monitors` lists them; 0 is all of them as one image) |
| `--stitch` | join a long problem into one image while you scroll through it |
| `--no-audio` | the screen only |
| `--audio-device NAME` | a loopback device other than the default speaker |
| `--no-tray` | no icon in the notification area |
| `--fps N` | how often the screen is looked at (default 3) |

The icon in the notification area opens the panel, switches the screen and the sound on and off, restarts the program
and quits it (**Open the panel**, **Screen capture**, **Sound capture**, **Restart capture**, **Quit**, in English, or in
Korean on a Korean system: [section 18 of the user guide](https://github.com/kanggu12/sidenote/blob/main/docs/README.md#18-panel-labels) has each label). On Linux the icon
appears where the desktop shows such icons (an AppIndicator or the X11 tray). Faces on the screen are covered
by the server before anything reads the frame ([the user guide, section 14](https://github.com/kanggu12/sidenote/blob/main/docs/README.md#14-security-and-privacy)).
