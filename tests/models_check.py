"""Which local model fits which GPU: the GPU readers (server/hardware.py) on each vendor's output, the profiles and the
choice among pulled models (server/models.py), and how the server resolves "auto" and talks to a server that is not
Ollama (server/analyzer.py).

    .venv/bin/python tests/models_check.py
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]   # the repository: this file is in tests/
sys.path.insert(0, str(ROOT))
os.environ.update(SIDENOTE_ANALYZER="mock", SIDENOTE_LOCAL_MODEL="auto", SIDENOTE_LOCAL_BUSY_MODEL="auto")
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'ok' if ok else 'FAIL'} {name}" + (f": {detail}" if detail and not ok else ""))


from server import hardware, models  # noqa: E402

print("[the GPU readers]")
nv = hardware.parse_nvidia_smi("NVIDIA GeForce RTX 4090, 24564\nNVIDIA GeForce RTX 3060, 12288\n")
check("nvidia-smi: each card's name and memory in GB", [(g.vendor, g.name, g.memory_gb) for g in nv]
      == [("nvidia", "NVIDIA GeForce RTX 4090", 25.8), ("nvidia", "NVIDIA GeForce RTX 3060", 12.9)], nv)
check("...and a line that is not a card is passed over", hardware.parse_nvidia_smi("No devices were found\n") == [])
amd_list = json.dumps([{"gpu": 0, "asic": {"market_name": "AMD Radeon RX 7900 XTX"}, "vram": {"size": {"value": 24560, "unit": "MB"}}}])
amd_obj = json.dumps({"gpu_data": [{"asic": {"market_name": "Radeon RX 7800 XT"}, "vram": {"size": "16368 MB"}}]})
check("amd-smi: a list with {value, unit}", [(g.name, g.memory_gb) for g in hardware.parse_amd_smi(amd_list)] == [("AMD Radeon RX 7900 XTX", 25.8)],
      hardware.parse_amd_smi(amd_list))
check("...or an object holding gpu_data with the unit beside the number",
      [(g.name, g.memory_gb) for g in hardware.parse_amd_smi(amd_obj)] == [("Radeon RX 7800 XT", 17.2)], hardware.parse_amd_smi(amd_obj))
rocm = json.dumps({"card0": {"VRAM Total Memory (B)": "17163091968", "VRAM Total Used Memory (B)": "1", "Card Series": "Radeon RX 7800 XT"},
                   "system": {"Driver version": "6.8"}})
check("rocm-smi: cards by key, the size in bytes", [(g.name, g.memory_gb) for g in hardware.parse_rocm_smi(rocm)] == [("Radeon RX 7800 XT", 17.2)],
      hardware.parse_rocm_smi(rocm))
with tempfile.TemporaryDirectory() as root:
    for card, vendor, size, name in (("card0", "0x1002", "17163091968", "Radeon RX 7800 XT"), ("card1", "0x8086", "0", None)):
        d = Path(root, card, "device")
        d.mkdir(parents=True)
        (d / "vendor").write_text(vendor + "\n")
        (d / "mem_info_vram_total").write_text(size + "\n")
        if name:
            (d / "product_name").write_text(name + "\n")
    got = hardware.amd_sysfs(root)
    check("the amdgpu driver's sysfs files, no ROCm tools: AMD cards only", [(g.vendor, g.name, g.memory_gb) for g in got]
          == [("amd", "Radeon RX 7800 XT", 17.2)], got)
gpus = [hardware.Gpu("intel", "Iris Xe", 2.0), hardware.Gpu("amd", "RX 7600", 8.6), hardware.Gpu("nvidia", "RTX 3060", 12.9)]
check("the GPU a model runs on is the supported one with the most memory", hardware.best(gpus).name == "RTX 3060")
check("...and an Intel GPU alone counts as none", hardware.best([hardware.Gpu("intel", "Arc", 16.0)]) is None)

print("[the GPU chart on a host, where no container writes the readings]")
use = hardware.parse_nvidia_usage("1796, 23028, 1, 35, 70.12\n500, 8192, 3, 40, [N/A]\n")
check("nvidia-smi's reading: the card with the most memory, power rounded",
      use == {"used": 1796, "total": 23028, "util": 1, "temp": 35, "power": 70}, use)
check("...and a card that reports no power gives None for it",
      hardware.parse_nvidia_usage("500, 8192, 3, 40, [N/A]\n")["power"] is None)
with tempfile.TemporaryDirectory() as root:
    d = Path(root, "card0", "device")
    (d / "hwmon" / "hwmon3").mkdir(parents=True)
    for name, value in {"vendor": "0x1002", "mem_info_vram_used": str(2 << 30), "mem_info_vram_total": str(16 << 30),
                        "gpu_busy_percent": "37"}.items():
        (d / name).write_text(value + "\n")
    (d / "hwmon/hwmon3/temp1_input").write_text("54000\n")
    (d / "hwmon/hwmon3/power1_average").write_text("121000000\n")
    use = hardware.amd_usage(root)
    check("the amdgpu driver's files: MiB, busy %, degrees and watts", use == {"used": 2048, "total": 16384, "util": 37,
                                                                            "temp": 54, "power": 121}, use)
import server.app as app_module  # noqa: E402
saved_stat, saved_usage = app_module.GPU_STAT, hardware.usage
try:
    app_module.GPU_STAT = str(Path(tempfile.gettempdir()) / "no-such-gpu-stat.csv")
    hardware.usage = lambda: {"used": 1, "total": 2, "util": 3, "temp": 4, "power": None}
    check("with no readings file the server asks the GPU's own tools", app_module.read_gpu() == hardware.usage())
finally:
    app_module.GPU_STAT, hardware.usage = saved_stat, saved_usage

print("[the profiles and the sizes]")
check("a 24 GB card is suggested the 26b", models.fits(24.1).key == "gemma4:26b")
check("16 and 12 GB the e4b", models.fits(16.0).key == "gemma4:e4b" and models.fits(12.0).key == "gemma4:e4b")
check("8 GB the e2b", models.fits(8.0).key == "gemma4:e2b")
check("4 GB or an unknown size none (a cloud agent then solves)", models.fits(4.0) is None and models.fits(None) is None)
check("only measured models or their smaller sizes are suggested", all(models.by_key(k) is not None for k in models.TIERS)
      and models.by_key(models.TIERS[0]).tested)
check("a tuned copy and a plain pull share a profile", models.profile_for("sidenote-gemma4:26b") is models.profile_for("gemma4:26b"))
check("gemma4 with no tag is the e4b, as Ollama pulls it", models.profile_for("gemma4").key == "gemma4:e4b"
      and models.profile_for("gemma4:latest").key == "gemma4:e4b")
check("an unknown model gets the generic profile, boxes on 0-1000 and thinking left alone",
      models.profile_for("qwen2.5vl:7b") is models.GENERIC and models.GENERIC.box_scale == 1000)
pulled = ["gemma4:26b", "sidenote-gemma4:26b", "sidenote-gemma4:e4b", "llava:13b"]
check("auto on 24 GB: the tuned 26b", models.choose(pulled, 24.1) == "sidenote-gemma4:26b")
check("auto on 12 GB: the 26b does not fit, the e4b does", models.choose(pulled, 12.0) == "sidenote-gemma4:e4b")
check("auto with the GPU unknown: the largest measured one", models.choose(pulled, None) == "sidenote-gemma4:26b")
check("auto with only an unknown model pulled: that one", models.choose(["llava:13b"], 8.0) == "llava:13b")
check("auto with nothing pulled: nothing", models.choose([], 24.0) is None)
check("a fitting model is preferred to a measured one that does not fit", models.choose(["sidenote-gemma4:26b", "gemma4:e2b"], 8.0) == "gemma4:e2b")
check("the busy GPU's model is the smaller one, when pulled", models.smaller_for("sidenote-gemma4:26b", pulled) == "sidenote-gemma4:e4b"
      and models.smaller_for("sidenote-gemma4:26b", ["sidenote-gemma4:26b"]) == "")
check("a pull fetches the model and its smaller one", models.wanted("sidenote-gemma4:26b") == ["sidenote-gemma4:26b", "sidenote-gemma4:e4b"]
      and models.wanted("qwen2.5vl:7b") == ["qwen2.5vl:7b"])

print("[the server: auto, and a server that is not Ollama]")
from server.analyzer import LOCAL_SEEN, LocalLlmAnalyzer, busy_model, main_model  # noqa: E402
from server.config import Config  # noqa: E402
from server.settings import SETTINGS  # noqa: E402

cfg = Config()
LOCAL_SEEN.update(pulled=pulled, vram_gb=12.0)
SETTINGS.values["local_model"] = "auto"
SETTINGS.values["local_busy_model"] = "auto"
check("auto resolves against what the local server has and the GPU's memory", main_model(cfg) == "sidenote-gemma4:e4b")
LOCAL_SEEN.update(vram_gb=24.1)
check("...and follows the GPU when it is larger", main_model(cfg) == "sidenote-gemma4:26b")
check("the busy GPU's model resolves to the smaller one pulled", busy_model(cfg, "sidenote-gemma4:26b") == "sidenote-gemma4:e4b")
LOCAL_SEEN.update(pulled=[], vram_gb=24.1)
check("with nothing pulled, auto names the model that fits, for the panel to say it is missing", main_model(cfg) == "sidenote-gemma4:26b")
SETTINGS.values["local_model"] = "llava:13b"
check("a model chosen in the panel is used as it is", main_model(cfg) == "llava:13b")
SETTINGS.values["local_model"] = "auto"
LOCAL_SEEN.update(pulled=pulled, vram_gb=24.1)
SETTINGS.values["local_busy_model"] = ""
check("the busy GPU's model can be switched off", busy_model(cfg, "sidenote-gemma4:26b") == "")
SETTINGS.values["local_busy_model"] = "auto"


async def backends():
    import httpx2
    seen = []

    def answer(request):
        seen.append(request.url.path)
        if request.url.path.startswith("/api/"):
            return httpx2.Response(404, text="not here")   # llama.cpp, vLLM and LM Studio have no Ollama API
        return httpx2.Response(200, json={})

    local = LocalLlmAnalyzer(Config())
    local._client = httpx2.AsyncClient(transport=httpx2.MockTransport(answer))
    check("a server with no /api/ps is not Ollama", await local._native() is False)
    check("...so what is on its GPU is not known", await local.loaded() == {"unknown": True})
    check("...nothing is unloaded from it", await local.unload() is False)
    body = local._body([{"role": "user", "content": "x"}], think=False, tools=None)
    check("...and it is not sent Ollama's way of turning thinking off", "reasoning_effort" not in body, body)
    check("only Ollama's own addresses were tried on it, each answered 'not here'", seen and all(p.startswith("/api/") for p in seen), seen)

    ollama = LocalLlmAnalyzer(Config())
    ollama._client = httpx2.AsyncClient(transport=httpx2.MockTransport(
        lambda r: httpx2.Response(200, json={"models": []})))
    check("Ollama answers /api/ps", await ollama._native() is True)
    body = ollama._body([{"role": "user", "content": "x"}], think=False, tools=None)
    check("...and is sent the profile's way of turning thinking off", body.get("reasoning_effort") == "none", body)
    check("...but not when the pass thinks", "reasoning_effort" not in ollama._body([], think=True, tools=None))
    check("the box grid comes from the model's profile", ollama.region_scale == 1000)
    await local._client.aclose()
    await ollama._client.aclose()

asyncio.run(backends())

print("[the panel's model download, against a stand-in Ollama]")


def stand_in_ollama(fail=False):
    """An HTTP server that answers /api/pull with Ollama's progress lines and /api/create, and writes down the bodies."""
    import http.server
    import threading
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            got.append((self.path, body))
            if self.path == "/api/pull":
                lines = [{"status": "pulling manifest"}, {"status": "pulling abc", "completed": 0, "total": 4000},
                         {"status": "pulling abc", "completed": 4000, "total": 4000}]
                lines += [{"error": "pull model manifest: file does not exist"}] if fail else [{"status": "success"}]
                out = "".join(json.dumps(x) + "\n" for x in lines).encode()
            else:
                out = json.dumps({"status": "success"}).encode()
            self.send_response(200)
            self.send_header("content-length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, got


async def downloads():
    import server.app as A
    from server.analyzer import Engines
    told = []

    async def broadcast(msg):
        told.append(msg)

    async def nothing(*a, **k):
        return {}
    saved = (A.CONFIG.local_url, A.CONFIG.local_pull, A.ENGINES, A.broadcast, A.check_local, A.broadcast_engines)
    try:
        A.broadcast, A.check_local, A.broadcast_engines = broadcast, nothing, nothing
        A.ENGINES = Engines(type("Local", (), {"native": True})(), None)
        srv, got = stand_in_ollama()
        A.CONFIG.local_url, A.CONFIG.local_pull = f"http://127.0.0.1:{srv.server_address[1]}/v1", False
        await A.pull_model("sidenote-gemma4:e4b")
        check("nothing is pulled where SIDENOTE_LOCAL_PULL is off", not got and not told, got)
        A.CONFIG.local_pull = True
        await A.pull_model("some-model:latest")
        check("...nor a model that is not one of the profiles", not got, got)
        await A.pull_model("sidenote-gemma4:e4b")
        paths = [p for p, _ in got]
        check("the tuned name pulls its base model through the local server, then makes the copy",
              paths == ["/api/pull", "/api/create"] and got[0][1]["model"] == "gemma4:e4b"
              and got[1][1] == {"model": "sidenote-gemma4:e4b", "from": "gemma4:e4b", "parameters": {"num_batch": 1152},
                                "stream": False}, got)
        steps = [m.get("status") for m in told if m.get("type") == "llm_pull"]
        check("the panels are told it starts, the copy is made, and it is done",
              steps[0] == "pulling" and "tuning" in steps and steps[-1] == "done", steps)
        check("...and nothing is left under way", A.PULL == {}, A.PULL)
        srv.shutdown()
        srv, got = stand_in_ollama(fail=True)
        A.CONFIG.local_url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
        told.clear()
        await A.pull_model("gemma4:e2b")
        last = [m for m in told if m.get("type") == "llm_pull"][-1]
        check("a pull Ollama turns down ends as failed, with its reason, and no copy is made",
              last.get("status") == "failed" and "does not exist" in last.get("error", "")
              and [p for p, _ in got] == ["/api/pull"], (last, got))
        A.ENGINES = Engines(type("Local", (), {"native": False})(), None)
        check("an OpenAI-compatible server that is not Ollama is never asked", not A.pull_allowed())
        srv.shutdown()
    finally:
        (A.CONFIG.local_url, A.CONFIG.local_pull, A.ENGINES, A.broadcast, A.check_local, A.broadcast_engines) = saved

asyncio.run(downloads())

print(f"\n==== {len(PASS)} passed, {len(FAIL)} failed ====")
sys.exit(1 if FAIL else 0)
