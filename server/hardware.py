"""The GPUs of this machine and how much memory each has, read with the standard library alone.

The server uses it on a host install, `./sidenote` uses it before it pulls a model, and the setup page shows what
it found, so the largest local model that fits can be suggested (server/models.py). Each reader returns what it can
and an empty list when its tool or file is not there:

    NVIDIA   nvidia-smi                               Windows, Linux, WSL
    AMD      amd-smi, then rocm-smi                   Linux with ROCm
             the amdgpu driver's files in sysfs       Linux, no tools needed
    any      DXGI, the adapter's dedicated memory     Windows
    Apple    sysctl, the share of the Mac's memory    macOS on Apple silicon
             macOS lets the GPU keep

Run it to see what it finds:  python3 -m server.hardware   (or python3 server/hardware.py), --json for the record.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# PCI vendor ids, as DXGI and sysfs give them
VENDORS = {0x10DE: "nvidia", 0x1002: "amd", 0x1022: "amd", 0x8086: "intel"}
# The vendors a local model server (Ollama) runs on; any other GPU counts as none for the suggestion
SUPPORTED = ("nvidia", "amd", "apple")


@dataclass(frozen=True)
class Gpu:
    vendor: str        # "nvidia", "amd", "apple", "intel" or "other"
    name: str          # the product name, as the driver gives it
    memory_gb: float   # the GPU's own memory in GB (10^9 bytes), one decimal

    def to_dict(self) -> dict:
        return asdict(self)


def _gb(n_bytes: float) -> float:
    """Bytes as GB with one decimal."""
    return round(n_bytes / 1e9, 1)


def _run(cmd: list[str], timeout: float = 5.0) -> str | None:
    """A tool's output, or None when it is not installed, fails or takes too long."""
    if shutil.which(cmd[0]) is None:
        return None
    try:
        # no console window on Windows: the app is a windowed program, and nvidia-smi every 2 s would flash one
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def parse_nvidia_usage(out: str) -> dict | None:
    """`nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw
    --format=csv,noheader,nounits`, one GPU a line: the reading of the one with the most memory."""
    best = None
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        try:
            used, total, util, temp = (int(float(p)) for p in parts[:4])
        except (ValueError, IndexError):
            continue
        try:
            power = round(float(parts[4]))
        except (ValueError, IndexError):     # "[N/A]" on cards that do not report it
            power = None
        if total > 0 and (best is None or total > best["total"]):
            best = {"used": used, "total": total, "util": util, "temp": temp, "power": power}
    return best


def _read(path: Path) -> str:
    """A sysfs file's text, stripped; "" when it cannot be read."""
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def amd_usage(root: str = "/sys/class/drm") -> dict | None:
    """The same reading from the amdgpu driver's sysfs files: memory in bytes, busy %, millidegrees, microwatts."""
    best = None
    for dev in sorted(Path(root).glob("card[0-9]*/device")):
        if _read(dev / "vendor") not in ("0x1002", "0x1022"):
            continue
        try:
            used, total = int(_read(dev / "mem_info_vram_used")), int(_read(dev / "mem_info_vram_total"))
            util = int(_read(dev / "gpu_busy_percent") or 0)
        except ValueError:
            continue
        hwmon = next(iter(sorted(dev.glob("hwmon/hwmon*"))), None)
        temp = power = None
        if hwmon is not None:
            t, p = _read(hwmon / "temp1_input"), _read(hwmon / "power1_average") or _read(hwmon / "power1_input")
            temp = int(t) // 1000 if t.isdigit() else None
            power = round(int(p) / 1e6) if p.isdigit() else None
        if total > 0 and (best is None or total // 1048576 > best["total"]):
            best = {"used": used // 1048576, "total": total // 1048576, "util": util, "temp": temp or 0, "power": power}
    return best


def usage() -> dict | None:
    """What the GPU is doing now, for the panel's chart where no container writes it down (a host install):
    {"used", "total" (MiB), "util" (%), "temp" (C), "power" (W, or None)}. NVIDIA through nvidia-smi on Linux and
    Windows, AMD through sysfs on Linux; None when neither answers."""
    out = _run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits"], timeout=3)
    reading = parse_nvidia_usage(out) if out else None
    if reading is None and sys.platform.startswith("linux"):
        reading = amd_usage()
    return reading


def parse_nvidia_smi(out: str) -> list[Gpu]:
    """`nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits`: one GPU a line, memory in MiB."""
    gpus = []
    for line in out.splitlines():
        name, _, mib = line.rpartition(",")
        try:
            gpus.append(Gpu("nvidia", name.strip(), _gb(float(mib) * 1024 * 1024)))
        except ValueError:
            continue   # a line that is not "name, number" (a driver message)
    return gpus


def nvidia() -> list[Gpu]:
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    return parse_nvidia_smi(out) if out else []


def parse_amd_smi(out: str) -> list[Gpu]:
    """`amd-smi static --asic --vram --json`. Its shape changed between releases: a list of GPUs, or an object
    holding one under "gpu_data"; the size is a number with its unit beside it, or a {"value", "unit"} pair."""
    try:
        data = json.loads(out)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = data.get("gpu_data") or [data]
    gpus = []
    for item in data if isinstance(data, list) else []:
        vram = (item.get("vram") or {}).get("size")
        unit = "MB"
        if isinstance(vram, dict):
            vram, unit = vram.get("value"), str(vram.get("unit") or "MB")
        try:
            size = float(str(vram).split()[0])
        except (TypeError, ValueError, IndexError):
            continue
        scale = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}.get(unit.upper(), 1024 ** 2)
        name = (item.get("asic") or {}).get("market_name") or "AMD GPU"
        gpus.append(Gpu("amd", str(name), _gb(size * scale)))
    return gpus


def parse_rocm_smi(out: str) -> list[Gpu]:
    """`rocm-smi --showmeminfo vram --showproductname --json`: {"card0": {"VRAM Total Memory (B)": "...", ...}}."""
    try:
        data = json.loads(out)
    except ValueError:
        return []
    gpus = []
    for key, card in (data.items() if isinstance(data, dict) else ()):
        if not key.startswith("card") or not isinstance(card, dict):
            continue
        total = next((v for k, v in card.items() if k.startswith("VRAM Total Memory")), None)
        try:
            size = float(total)
        except (TypeError, ValueError):
            continue
        name = card.get("Card Series") or card.get("Card series") or card.get("Card SKU") or "AMD GPU"
        gpus.append(Gpu("amd", str(name), _gb(size)))
    return gpus


def amd_tools() -> list[Gpu]:
    out = _run(["amd-smi", "static", "--asic", "--vram", "--json"])
    gpus = parse_amd_smi(out) if out else []
    if not gpus:
        out = _run(["rocm-smi", "--showmeminfo", "vram", "--showproductname", "--json"])
        gpus = parse_rocm_smi(out) if out else []
    return gpus


def amd_sysfs(root: str = "/sys/class/drm") -> list[Gpu]:
    """The amdgpu driver writes each card's memory in bytes to mem_info_vram_total; no ROCm needed."""
    gpus = []
    for card in sorted(Path(root).glob("card[0-9]*")):
        device = card / "device"
        try:
            if int((device / "vendor").read_text().strip(), 16) not in (0x1002, 0x1022):
                continue
            size = float((device / "mem_info_vram_total").read_text().strip())
        except (OSError, ValueError):
            continue
        try:
            name = (device / "product_name").read_text().strip() or "AMD GPU"
        except OSError:
            name = "AMD GPU"
        gpus.append(Gpu("amd", name, _gb(size)))
    return gpus


def dxgi() -> list[Gpu]:
    """Every hardware adapter Windows knows, with its dedicated memory: DXGI, the one source that is right for any
    vendor (WMI's AdapterRAM is a 32-bit number and stops at 4 GB)."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class Guid(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class Luid(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class AdapterDesc1(ctypes.Structure):   # DXGI_ADAPTER_DESC1
        _fields_ = [("Description", wintypes.WCHAR * 128), ("VendorId", wintypes.UINT), ("DeviceId", wintypes.UINT),
                    ("SubSysId", wintypes.UINT), ("Revision", wintypes.UINT), ("DedicatedVideoMemory", ctypes.c_size_t),
                    ("DedicatedSystemMemory", ctypes.c_size_t), ("SharedSystemMemory", ctypes.c_size_t),
                    ("AdapterLuid", Luid), ("Flags", wintypes.UINT)]

    # IID_IDXGIFactory1 {770aae78-f26f-4dba-a829-253c83d1b387}
    iid = Guid(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
    factory = ctypes.c_void_p()
    try:
        if ctypes.windll.dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0:
            return []
    except OSError:
        return []

    def method(obj, index, *argtypes):
        """The COM method at `index` of the object's table, callable with the object first."""
        table = ctypes.cast(ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(table[index])

    gpus = []
    try:
        for i in range(16):
            adapter = ctypes.c_void_p()
            # IDXGIFactory1::EnumAdapters1, the 13th entry (IUnknown 3, IDXGIObject 4, IDXGIFactory 5)
            if method(factory, 12, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(factory, i, ctypes.byref(adapter)) != 0:
                break   # DXGI_ERROR_NOT_FOUND: no more adapters
            desc = AdapterDesc1()
            # IDXGIAdapter1::GetDesc1, the 11th entry (IUnknown 3, IDXGIObject 4, IDXGIAdapter 3)
            got = method(adapter, 10, ctypes.POINTER(AdapterDesc1))(adapter, ctypes.byref(desc))
            method(adapter, 2)(adapter)   # Release
            if got != 0 or desc.Flags & 2:   # DXGI_ADAPTER_FLAG_SOFTWARE: the Basic Render Driver
                continue
            gpus.append(Gpu(VENDORS.get(desc.VendorId, "other"), desc.Description.strip(), _gb(desc.DedicatedVideoMemory)))
    finally:
        method(factory, 2)(factory)   # Release
    return gpus


def apple() -> list[Gpu]:
    """Apple silicon's GPU, which shares the Mac's memory: as much of it as macOS lets the GPU keep, which is what Ollama
    loads a model into. That is iogpu.wired_limit_mb when it has been raised, else Metal's own default: two thirds of
    the memory up to 36 GB, three quarters above. An Intel Mac gives nothing: Ollama runs on its CPU."""
    if platform.machine() != "arm64" and (_run(["sysctl", "-n", "hw.optional.arm64"]) or "").strip() != "1":
        return []
    try:
        total = int((_run(["sysctl", "-n", "hw.memsize"]) or "").strip())
    except ValueError:
        return []
    try:
        raised = int((_run(["sysctl", "-n", "iogpu.wired_limit_mb"]) or "0").strip()) * 1048576
    except ValueError:
        raised = 0
    keep = raised if 0 < raised <= total else total * (0.75 if total > 36 * 2**30 else 2 / 3)
    name = (_run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "").strip() or "Apple silicon"
    return [Gpu("apple", name, _gb(keep))]


def detect() -> list[Gpu]:
    """Every GPU found, one entry each: the vendor's own tool where there is one, DXGI or sysfs for the rest."""
    found = nvidia()
    if sys.platform.startswith("linux"):
        found += amd_tools() or amd_sysfs()
    elif sys.platform == "win32":
        # DXGI lists the NVIDIA cards nvidia-smi already gave; those are left out, every other adapter is kept
        have_nvidia = bool(found)
        found += [g for g in dxgi() if not (have_nvidia and g.vendor == "nvidia")]
    elif sys.platform == "darwin":
        found += apple()
    return found


def best(gpus: list[Gpu]) -> Gpu | None:
    """The GPU a local model would run on: the supported one with the most memory."""
    usable = [g for g in gpus if g.vendor in SUPPORTED]
    return max(usable, key=lambda g: g.memory_gb) if usable else None


def _models():
    """server/models.py, whether this file runs inside the package or as a plain script."""
    try:
        from . import models
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import models
    return models


def report() -> dict:
    """What was found and what fits, as `./sidenote` and the setup page read it."""
    models = _models()
    gpus = detect()
    gpu = best(gpus)
    fit = models.fits(gpu.memory_gb) if gpu else None
    return {"gpus": [g.to_dict() for g in gpus], "best": gpu.to_dict() if gpu else None,
            "suggest": fit.to_dict() if fit else None, "platform": sys.platform}


def main(argv: list[str]) -> int:
    rep = report()
    if "--json" in argv:
        print(json.dumps(rep, ensure_ascii=False))
        return 0
    if not rep["gpus"]:
        print("No GPU found.")
    for g in rep["gpus"]:
        print(f"{g['vendor']:7} {g['memory_gb']:6.1f} GB  {g['name']}")
    s = rep["suggest"]
    print(f"Suggested local model: {s['pull']} (needs {s['vram_gb']} GB)" if s else
          "Suggested: no local model (not enough GPU memory, or no NVIDIA, AMD or Apple silicon GPU); use a cloud agent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
