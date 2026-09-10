"""Make the pip-installed CUDA libraries visible to ctranslate2 / faster-whisper.

``faster-whisper`` on CUDA needs ``libcublas`` and ``libcudnn`` from the
``nvidia-*-cu12`` wheels, but those live under ``site-packages/nvidia/*/lib``
which is not on the dynamic linker's search path. ``LD_LIBRARY_PATH`` has to be
set *before* the process starts, so if it is missing we prepend it and re-exec
the interpreter once.

The re-exec is guarded by the ``SGK_VT_CUDA_REEXEC`` env var rather than by
inspecting ``LD_LIBRARY_PATH`` - the latter gives a false positive when the
path was set by something else (a systemd unit, the user's shell) yet still
lacks the wheel directories.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_SENTINEL = "SGK_VT_CUDA_REEXEC"
_NVIDIA_PKGS = ("nvidia.cublas", "nvidia.cudnn")


def _sgk_nvidia_lib_dirs() -> list[str]:
    """Directories holding the CUDA .so files from the nvidia-*-cu12 wheels."""
    dirs: list[str] = []
    for pkg in _NVIDIA_PKGS:
        try:
            spec = importlib.util.find_spec(pkg)
        except (ImportError, ValueError, ModuleNotFoundError):
            spec = None
        locations = list(spec.submodule_search_locations or []) if spec else []
        for loc in locations:
            lib = Path(loc) / "lib"
            if lib.is_dir():
                dirs.append(str(lib))
    return dirs


def sgk_ensure_cuda_libs(device: str = "cuda") -> None:
    """Prepend the wheel CUDA dirs to LD_LIBRARY_PATH and re-exec once.

    A no-op when ``device`` is not ``cuda``, when the guard var is already set,
    or when the wheel directories cannot be found (system CUDA may still work).
    """
    if device != "cuda":
        return
    if os.environ.get(_SENTINEL) == "1":
        return

    dirs = _sgk_nvidia_lib_dirs()
    if not dirs:
        _logger.warning(
            "sgk_cuda_libs_not_found",
            extra={"hint": "pip install nvidia-cublas-cu12 nvidia-cudnn-cu12"},
        )
        os.environ[_SENTINEL] = "1"
        return

    current = os.environ.get("LD_LIBRARY_PATH", "")
    parts = current.split(os.pathsep) if current else []
    missing = [d for d in dirs if d not in parts]

    os.environ[_SENTINEL] = "1"
    if not missing:
        return  # already reachable, nothing to do

    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join(missing + parts)
    _logger.info("sgk_cuda_reexec", extra={"added": missing})
    os.execv(sys.executable, [sys.executable, "-m", "sgk_voice_typer", *sys.argv[1:]])
