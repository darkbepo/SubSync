"""Everything lives next to SubSync.exe; nothing is written anywhere else."""
from __future__ import annotations

import os
import sys

ROOT = os.environ.get("SUBSYNC_ROOT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNTIME = os.path.join(ROOT, "runtime")
CUDA_DIR = os.path.join(RUNTIME, "cuda")
MODELS = os.path.join(ROOT, "models")
WHISPER_DIR = os.path.join(MODELS, "whisper-large-v3-turbo")
MINILM_DIR = os.path.join(MODELS, "minilm")
CACHE = os.path.join(ROOT, "cache")
LOGS = os.path.join(ROOT, "logs")
SETTINGS = os.path.join(ROOT, "settings.json")


_CUDA_ORDER = ["cublasLt64_12.dll", "cublas64_12.dll", "nvrtc64_120_0.dll", "nvrtc-builtins64_129.dll",
               "cudnn_graph64_9.dll", "cudnn_engines_runtime_compiled64_9.dll",
               "cudnn_engines_precompiled64_9.dll", "cudnn_heuristic64_9.dll", "cudnn_ops64_9.dll",
               "cudnn_cnn64_9.dll", "cudnn_adv64_9.dll", "cudnn64_9.dll"]


def preload_cuda() -> list[str]:
    """Load the CUDA/cuDNN DLLs by full path (dependency order) so that
    ctranslate2 and cuDNN find them by name.  Returns load failures."""
    if sys.platform != "win32" or not os.path.isdir(CUDA_DIR):
        return ["no CUDA libraries installed"]
    import ctypes

    present = set(os.listdir(CUDA_DIR))
    order = [n for n in _CUDA_ORDER if n in present] + sorted(
        n for n in present if n.lower().endswith(".dll") and n not in _CUDA_ORDER)
    errors = []
    for name in order:
        try:
            ctypes.WinDLL(os.path.join(CUDA_DIR, name))
        except OSError as e:
            errors.append(f"{name}: {e}")
    return errors


_VC_RUNTIME = ["vcruntime140.dll", "vcruntime140_1.dll", "vcruntime140_threads.dll", "msvcp140.dll",
               "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll",
               "concrt140.dll", "vcomp140.dll"]


def preload_vc_runtime() -> list[str]:
    """Load the one consistent Microsoft C++ runtime set that sits next to
    python.exe *before* Qt, numpy etc. can each pull in their own (older,
    different) copies.  Mixed runtime versions crash natively, silently."""
    if sys.platform != "win32":
        return []
    import ctypes

    base = os.path.dirname(sys.executable)
    loaded = []
    for name in _VC_RUNTIME:
        p = os.path.join(base, name)
        if os.path.exists(p):
            try:
                ctypes.WinDLL(p)
                loaded.append(name)
            except OSError as e:
                loaded.append(f"{name} FAILED: {e}")
    return loaded


def setup_environment() -> None:
    for d in (CACHE, LOGS):
        os.makedirs(d, exist_ok=True)
    # keep every library's caches inside the tool folder
    os.environ.setdefault("HF_HOME", os.path.join(CACHE, "hf"))
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ.setdefault("CUDA_CACHE_PATH", os.path.join(CACHE, "cuda"))
    os.environ.setdefault("TMP", os.path.join(CACHE, "tmp"))
    os.environ.setdefault("TEMP", os.environ["TMP"])
    os.makedirs(os.environ["TMP"], exist_ok=True)
    if sys.platform == "win32" and os.path.isdir(CUDA_DIR):
        os.environ["PATH"] = CUDA_DIR + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(CUDA_DIR)
        except OSError:
            pass
