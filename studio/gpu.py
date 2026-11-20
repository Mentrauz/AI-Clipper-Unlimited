"""Using the graphics card instead of the processor, when there is one that can do it.

Two jobs can move to an NVIDIA card:
  * making the clips (the video is encoded by the card's own encoder, NVENC), and
  * writing the transcript (the speech model runs on CUDA).
Both are off until the owner turns them on in Settings, Speed. Each one is checked first, and when it cannot work the
page says what is missing and how to set it up, instead of failing in the middle of a video. The choice is kept in
hardware.json in the data folder.

This file reads only the standard library, so config.py can use it before anything else is loaded."""
import importlib.metadata
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FP16_MODEL = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-fp16"      # the speech model a graphics card wants (about 1.1 GB)
CUDA_WHEELS = "https://k2-fsa.github.io/sherpa/onnx/cuda.html"

_file: Path | None = None
_cache: dict = {}
_failed = {"why": ""}       # set when the speech model was tried on the card and did not work, until the next start


def init(data_dir) -> None:
    global _file
    _file = Path(data_dir) / "hardware.json"


def prefs() -> dict:
    try:
        d = json.loads(_file.read_text(encoding="utf-8")) if _file and _file.is_file() else {}
    except (OSError, ValueError):
        d = {}
    return {"encode": bool(d.get("encode")), "speech": bool(d.get("speech"))}


def save(encode: bool, speech: bool) -> dict:
    if _file is None:
        raise RuntimeError("The data folder is not ready.")
    tmp = _file.with_suffix(".tmp")
    tmp.write_text(json.dumps({"encode": bool(encode), "speech": bool(speech)}), encoding="utf-8")
    tmp.replace(_file)
    return prefs()


def _run(cmd, timeout=25):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=NO_WINDOW, timeout=timeout)


def card() -> dict:
    """The NVIDIA card in this computer: {'name', 'memory_gb', 'driver'}, or {} when there is none."""
    if "card" not in _cache:
        info = {}
        exe = shutil.which("nvidia-smi")
        if exe:
            try:
                p = _run([exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"], 10)
                if p.returncode == 0 and p.stdout.strip():
                    name, mem, drv = [x.strip() for x in p.stdout.strip().splitlines()[0].split(",")[:3]]
                    info = {"name": name, "memory_gb": round(float(mem) / 1024, 1), "driver": drv}
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        _cache["card"] = info
    return _cache["card"]


def nvenc() -> dict:
    """Can ffmpeg encode video on the card? Tried once with a tiny test clip: {'ok', 'problem', 'fix'}."""
    if "nvenc" in _cache:
        return _cache["nvenc"]
    out = {"ok": False, "problem": "", "fix": []}
    if not card():
        out.update(problem="No NVIDIA graphics card was found in this computer.",
                   fix=["AI Clipper can use NVIDIA cards (GeForce, RTX, Quadro). Other cards, and Intel or AMD graphics, are not supported for this yet.",
                        "If you do have an NVIDIA card, install its driver from nvidia.com/drivers, restart the computer, then press Check again."])
    elif not shutil.which("ffmpeg"):
        out.update(problem="ffmpeg is not installed.", fix=["Install it with: winget install Gyan.FFmpeg"])
    else:
        try:
            enc = _run(["ffmpeg", "-hide_banner", "-encoders"], 15).stdout
        except (OSError, subprocess.SubprocessError):
            enc = ""
        if "h264_nvenc" not in enc:
            out.update(problem="This copy of ffmpeg was built without NVIDIA support.",
                       fix=["Install the full build: winget install Gyan.FFmpeg (the 'full' build includes NVENC), or download 'full' from gyan.dev/ffmpeg/builds.",
                            "Restart AI Clipper afterwards so it finds the new ffmpeg."])
        else:
            try:
                p = _run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2:r=30",
                          "-c:v", "h264_nvenc", "-f", "null", "-"], 30)
                if p.returncode == 0:
                    out["ok"] = True
                else:
                    out.update(problem="The card's encoder would not start: " + (p.stderr.strip().splitlines() or ["unknown error"])[-1][:200],
                               fix=["Update the NVIDIA driver from nvidia.com/drivers (NVENC needs a recent one), restart the computer, then press Check again."])
            except (OSError, subprocess.SubprocessError) as e:
                out.update(problem="Could not test the encoder: " + str(e)[:150], fix=[])
    _cache["nvenc"] = out
    return out


def _sherpa_version() -> str:
    try:
        return importlib.metadata.version("sherpa-onnx")
    except importlib.metadata.PackageNotFoundError:
        return ""


def nvidia_dirs() -> list:
    """The folders holding NVIDIA's CUDA files when they were installed with pip (nvidia-cudnn-cu12 and friends)
    instead of NVIDIA's own installer. Windows does not look in them by itself, so the speech library is pointed
    at them before it loads. Empty when those packages are not installed."""
    if "nvidia_dirs" not in _cache:
        found = []
        try:
            import importlib.util
            spec = importlib.util.find_spec("nvidia")
            for root in (spec.submodule_search_locations or []) if spec else []:
                found += sorted(p for p in Path(root).glob("*/bin") if p.is_dir())
        except (ImportError, ValueError, OSError):
            pass
        _cache["nvidia_dirs"] = found
    return _cache["nvidia_dirs"]


def _has_dll(*names) -> bool:
    paths = [Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    cuda = os.environ.get("CUDA_PATH")
    if cuda:
        paths += [Path(cuda) / "bin", Path(cuda) / "bin" / "x64"]
    paths += nvidia_dirs()
    return any((p / n).is_file() for p in paths for n in names)


def speech() -> dict:
    """Can the speech model run on the card? Looks for what it needs, without loading anything big."""
    if "speech" in _cache:
        return _cache["speech"]
    out = {"ok": False, "problem": "", "fix": []}
    ver = _sherpa_version()
    missing = []
    if not card():
        out.update(problem="No NVIDIA graphics card was found in this computer.",
                   fix=["The speech model can only use NVIDIA cards. Install the card's driver from nvidia.com/drivers, restart, then press Check again."])
    else:
        if "cuda" not in ver.lower():
            missing.append(f"The speech library installed ({ver or 'none'}) is the processor-only one. Replace it with the CUDA build: "
                           f"pip uninstall -y sherpa-onnx sherpa-onnx-core, then pip install the matching +cuda build listed at {CUDA_WHEELS}")
        if not _has_dll("cudart64_12.dll", "cudart64_13.dll"):
            missing.append("The CUDA runtime was not found. Install the CUDA Toolkit 12 from developer.nvidia.com/cuda-downloads (or add its bin folder to PATH).")
        if not _has_dll("cudnn64_9.dll"):
            missing.append("cuDNN 9 was not found. Download it from developer.nvidia.com/cudnn and copy its bin folder's files next to the CUDA ones (or add the folder to PATH).")
        if not (_has_dll("cudart64_12.dll", "cudart64_13.dll") and _has_dll("cudnn64_9.dll")):
            missing.append("Or, without NVIDIA's installers: pip install nvidia-cuda-runtime-cu12 nvidia-cublas-cu12 \"nvidia-cudnn-cu12>=9,<10\" "
                           "nvidia-cufft-cu12 nvidia-curand-cu12 nvidia-cuda-nvrtc-cu12 nvidia-nvjitlink-cu12 into the same Python that runs AI Clipper. AI Clipper finds those files by itself.")
        if missing:
            out.update(problem="The speech model needs a few things installed first.", fix=missing + ["Restart AI Clipper afterwards, then press Check again."])
        elif _failed["why"]:
            out.update(problem="Everything is installed, but the speech model did not work on the card, so the processor is writing transcripts instead.",
                       fix=[f"What happened: {_failed['why']}.",
                            f"This usually means the speech library and the card's software do not get along. Try a different +cuda build from {CUDA_WHEELS}, or update the NVIDIA driver.",
                            "Restart AI Clipper afterwards: it tests the card again on the first video."])
        else:
            out["ok"] = True
    _cache["speech"] = out
    return out


def speech_failed(why: str) -> None:
    """The speech model was tried on the card and did not work: say so in Settings, Speed and stop using the card."""
    _failed["why"] = why
    _cache.pop("speech", None)


def recheck() -> None:
    for k in ("card", "nvenc", "speech", "nvidia_dirs"):
        _cache.pop(k, None)


def use_nvenc() -> bool:
    """Should clips be encoded on the card? Only when it was asked for and it is known to work."""
    return prefs()["encode"] and nvenc()["ok"]


def speech_on_card() -> bool:
    """Should the speech model run on the card? Only when asked for and everything it needs is there."""
    return prefs()["speech"] and speech()["ok"]


def status() -> dict:
    p = prefs()
    return {"card": card(), "encode": {**nvenc(), "on": p["encode"], "active": p["encode"] and nvenc()["ok"]},
            "speech": {**speech(), "on": p["speech"], "active": p["speech"] and speech()["ok"],
                       "model": FP16_MODEL, "restart": True}}
