"""Unit tests for SgkClipboard: save / restore rules and the paste path.

``_sgk_run`` (the subprocess helper) is replaced with a recorder so nothing
touches the real clipboard.
"""

from __future__ import annotations

import pytest

from sgk_voice_typer.input.clipboard import SgkClipboard


class _FakeUinput:
    def __init__(self, available: bool = True) -> None:
        self._available = available
        self.pastes: list[bool] = []

    def sgk_is_available(self) -> bool:
        return self._available

    def sgk_paste(self, shift: bool = False) -> None:
        self.pastes.append(shift)


class _RunRecorder:
    """Stands in for SgkClipboard._sgk_run."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], bytes | None]] = []
        self.paste_result: tuple[int, bytes] = (0, b"")
        self.raise_exc: Exception | None = None

    async def __call__(self, *argv: str, stdin: bytes | None = None):
        self.calls.append((argv, stdin))
        if self.raise_exc is not None:
            raise self.raise_exc
        if argv[:1] == ("wl-paste",):
            return self.paste_result
        return (0, b"")


@pytest.fixture
def uinput() -> _FakeUinput:
    return _FakeUinput()


@pytest.fixture
def clip(uinput: _FakeUinput) -> SgkClipboard:
    c = SgkClipboard(uinput, clipboard_settle_ms=0, paste_settle_ms=0)
    c._sgk_run = _RunRecorder()  # type: ignore[method-assign]
    return c


def _rec(clip: SgkClipboard) -> _RunRecorder:
    return clip._sgk_run  # type: ignore[return-value]


class TestSave:
    async def test_save_success(self, clip: SgkClipboard) -> None:
        _rec(clip).paste_result = (0, b"hello")
        await clip.sgk_save()
        assert clip._saved == "hello"
        assert clip._save_ok is True

    async def test_save_empty_clipboard_is_a_valid_snapshot(self, clip: SgkClipboard) -> None:
        _rec(clip).paste_result = (1, b"")  # wl-paste: "nothing is copied"
        await clip.sgk_save()
        assert clip._saved is None
        assert clip._save_ok is True

    async def test_save_failure_marks_not_ok(self, clip: SgkClipboard) -> None:
        _rec(clip).raise_exc = OSError("boom")
        await clip.sgk_save()
        assert clip._save_ok is False


class TestRestore:
    async def test_restore_writes_saved_text_via_stdin(self, clip: SgkClipboard) -> None:
        _rec(clip).paste_result = (0, b"important")
        await clip.sgk_save()
        _rec(clip).calls.clear()
        await clip.sgk_restore()
        assert _rec(clip).calls == [(("wl-copy",), b"important")]

    async def test_restore_after_failed_save_is_a_noop(self, clip: SgkClipboard) -> None:
        _rec(clip).raise_exc = OSError("boom")
        await clip.sgk_save()
        _rec(clip).raise_exc = None
        _rec(clip).calls.clear()
        await clip.sgk_restore()
        assert _rec(clip).calls == []  # user's clipboard must be left untouched

    async def test_restore_empty_snapshot_clears(self, clip: SgkClipboard) -> None:
        _rec(clip).paste_result = (1, b"")
        await clip.sgk_save()
        _rec(clip).calls.clear()
        await clip.sgk_restore()
        assert _rec(clip).calls == [(("wl-copy", "--clear"), None)]

    async def test_restore_disabled(self, uinput: _FakeUinput) -> None:
        c = SgkClipboard(uinput, restore_clipboard=False)
        c._sgk_run = _RunRecorder()  # type: ignore[method-assign]
        c._sgk_run.paste_result = (0, b"x")
        await c.sgk_save()
        c._sgk_run.calls.clear()
        await c.sgk_restore()
        assert c._sgk_run.calls == []


class TestType:
    async def test_leading_dash_text_goes_through_stdin(self, clip: SgkClipboard, uinput: _FakeUinput) -> None:
        ok = await clip.sgk_type("--not-a-flag", terminal=False)
        assert ok is True
        assert _rec(clip).calls == [(("wl-copy",), b"--not-a-flag")]
        assert uinput.pastes == [False]

    async def test_terminal_paste_uses_shift(self, clip: SgkClipboard, uinput: _FakeUinput) -> None:
        await clip.sgk_type("text", terminal=True)
        assert uinput.pastes == [True]

    async def test_empty_text_is_noop(self, clip: SgkClipboard, uinput: _FakeUinput) -> None:
        assert await clip.sgk_type("", terminal=False) is False
        assert uinput.pastes == []

    async def test_unavailable_uinput_returns_false(self) -> None:
        c = SgkClipboard(_FakeUinput(available=False))
        c._sgk_run = _RunRecorder()  # type: ignore[method-assign]
        assert await c.sgk_type("hi") is False
        assert c._sgk_run.calls == []
