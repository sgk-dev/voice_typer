"""Clipboard swap for text injection on GNOME Wayland.

The transcribed text is delivered by putting it on the CLIPBOARD selection and
issuing a synthetic paste (Ctrl+V, or Ctrl+Shift+V for terminals) through the
``uinput`` virtual keyboard. ``wtype`` is unsupported by Mutter and keycode
typing is layout-dependent, so this is the only reliable path.

The user's clipboard is saved before the swap and restored after. Two rules,
learned from the previous implementation:

* ``wl-copy`` gets the text on **stdin**, never as an argv element - text that
  starts with ``-`` would otherwise be parsed as a flag.
* the clipboard is restored **only if the save actually succeeded**. A failed
  read must leave the user's clipboard untouched, not clear it.
"""

from __future__ import annotations

import asyncio

from sgk_voice_typer.input.uinput_backend import SgkUinputInjector
from sgk_voice_typer.utils.logger import sgk_get_logger

_logger = sgk_get_logger(__name__)

_CMD_TIMEOUT = 2.0


class SgkClipboard:
    """CLIPBOARD save / restore and paste for GNOME Wayland."""

    def __init__(
        self,
        uinput: SgkUinputInjector,
        clipboard_settle_ms: int = 80,
        paste_settle_ms: int = 80,
        restore_clipboard: bool = True,
    ) -> None:
        self._uinput = uinput
        self._clipboard_settle = clipboard_settle_ms / 1000.0
        self._paste_settle = paste_settle_ms / 1000.0
        self._restore_enabled = restore_clipboard
        self._saved: str | None = None
        self._save_ok = False

    def sgk_configure(
        self,
        clipboard_settle_ms: int,
        paste_settle_ms: int,
        restore_clipboard: bool,
    ) -> None:
        """Update the timing / restore settings at runtime (settings dialog)."""
        self._clipboard_settle = clipboard_settle_ms / 1000.0
        self._paste_settle = paste_settle_ms / 1000.0
        self._restore_enabled = restore_clipboard

    # ------------------------------------------------------------------
    # subprocess helper
    # ------------------------------------------------------------------

    async def _sgk_run(
        self, *argv: str, stdin: bytes | None = None
    ) -> tuple[int, bytes]:
        """Run a command with a timeout. Returns (returncode, stdout)."""
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await asyncio.wait_for(
                proc.communicate(input=stdin), timeout=_CMD_TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        return proc.returncode or 0, out or b""

    # ------------------------------------------------------------------
    # save / restore
    # ------------------------------------------------------------------

    async def sgk_save(self) -> None:
        """Snapshot the current CLIPBOARD text.

        ``_save_ok`` records whether the read completed - an empty clipboard is
        a successful read (saved = None), a crashed/timed-out read is not.
        """
        try:
            rc, out = await self._sgk_run("wl-paste", "--no-newline")
        except (OSError, asyncio.TimeoutError) as exc:
            self._saved, self._save_ok = None, False
            _logger.warning("sgk_clipboard_save_failed", extra={"error": str(exc)})
            return
        # rc != 0 => "nothing is copied"; that is an empty clipboard, still a
        # valid snapshot to restore to.
        self._saved = out.decode("utf-8", "replace") if rc == 0 and out else None
        self._save_ok = True

    async def sgk_restore(self) -> None:
        """Put the saved clipboard text back, if the save succeeded."""
        if not self._restore_enabled or not self._save_ok:
            return
        try:
            if self._saved:
                await self._sgk_run("wl-copy", stdin=self._saved.encode("utf-8"))
            else:
                await self._sgk_run("wl-copy", "--clear")
        except (OSError, asyncio.TimeoutError) as exc:
            _logger.warning("sgk_clipboard_restore_failed", extra={"error": str(exc)})
        finally:
            self._saved, self._save_ok = None, False

    # ------------------------------------------------------------------
    # inject
    # ------------------------------------------------------------------

    async def sgk_type(self, text: str, terminal: bool = False) -> bool:
        """Deliver ``text`` into the focused window via clipboard + synthetic paste.

        The caller is responsible for calling sgk_save() before and sgk_restore()
        after. Returns True if the paste was issued.
        """
        if not text:
            return False
        if not self._uinput.sgk_is_available():
            _logger.error(
                "sgk_uinput_unavailable",
                extra={"hint": "uinput virtual keyboard not usable - cannot paste"},
            )
            return False
        try:
            await self._sgk_run("wl-copy", stdin=text.encode("utf-8"))
        except (OSError, asyncio.TimeoutError) as exc:
            _logger.error("sgk_clipboard_set_failed", extra={"error": str(exc)})
            return False
        await asyncio.sleep(self._clipboard_settle)
        self._uinput.sgk_paste(shift=terminal)
        await asyncio.sleep(self._paste_settle)
        _logger.info(
            "sgk_inject",
            extra={"chars": len(text), "terminal": terminal},
        )
        return True
