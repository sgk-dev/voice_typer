"""Unit tests for the CUDA library re-exec guard."""

from __future__ import annotations

import pytest

from sgk_voice_typer.asr import cuda_env


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SGK_VT_CUDA_REEXEC", raising=False)
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)


def test_cpu_device_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(cuda_env.os, "execv", lambda *a: called.append(a))
    cuda_env.sgk_ensure_cuda_libs("cpu")
    assert called == []
    assert "SGK_VT_CUDA_REEXEC" not in cuda_env.os.environ


def test_sentinel_already_set_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SGK_VT_CUDA_REEXEC", "1")
    called = []
    monkeypatch.setattr(cuda_env.os, "execv", lambda *a: called.append(a))
    cuda_env.sgk_ensure_cuda_libs("cuda")
    assert called == []


def test_reexecs_when_libs_missing_from_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cuda_env, "_sgk_nvidia_lib_dirs", lambda: ["/x/cublas/lib", "/x/cudnn/lib"])
    captured = {}

    def _fake_execv(exe, argv):
        captured["exe"] = exe
        captured["argv"] = argv
        raise SystemExit  # execv would replace the process

    monkeypatch.setattr(cuda_env.os, "execv", _fake_execv)
    with pytest.raises(SystemExit):
        cuda_env.sgk_ensure_cuda_libs("cuda")

    assert cuda_env.os.environ["SGK_VT_CUDA_REEXEC"] == "1"
    assert "/x/cublas/lib" in cuda_env.os.environ["LD_LIBRARY_PATH"]
    assert captured["argv"][1:3] == ["-m", "sgk_voice_typer"]


def test_no_reexec_when_libs_already_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LD_LIBRARY_PATH", "/x/cublas/lib:/x/cudnn/lib")
    monkeypatch.setattr(cuda_env, "_sgk_nvidia_lib_dirs", lambda: ["/x/cublas/lib", "/x/cudnn/lib"])
    called = []
    monkeypatch.setattr(cuda_env.os, "execv", lambda *a: called.append(a))
    cuda_env.sgk_ensure_cuda_libs("cuda")
    assert called == []
    assert cuda_env.os.environ["SGK_VT_CUDA_REEXEC"] == "1"


def test_missing_wheels_sets_sentinel_and_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cuda_env, "_sgk_nvidia_lib_dirs", lambda: [])
    called = []
    monkeypatch.setattr(cuda_env.os, "execv", lambda *a: called.append(a))
    cuda_env.sgk_ensure_cuda_libs("cuda")
    assert called == []
    assert cuda_env.os.environ["SGK_VT_CUDA_REEXEC"] == "1"


def test_lib_dirs_probe_returns_list() -> None:
    assert isinstance(cuda_env._sgk_nvidia_lib_dirs(), list)
