"""Dependency-free terminal polish for the product CLI.

The display layer is deliberately separate from protocol code. It can be
replaced by a richer renderer later while keeping stdout/json behavior stable.
"""

from __future__ import annotations

import os
import sys
import threading
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import IO, Mapping, Sequence
from urllib.parse import urlparse


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
MAGENTA = "\033[35m"
RED = "\033[31m"
YELLOW = "\033[33m"
CLEAR_LINE = "\033[2K"
CLI_UI_TODO_MARKER = "CLI_UI_TODO"


def terminal_supports_ansi(stream: IO[str]) -> bool:
    """Return true when ANSI color/status updates are likely to render cleanly."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    is_tty = getattr(stream, "isatty", lambda: False)
    if not is_tty():
        return False
    if os.name == "nt":
        return _enable_windows_virtual_terminal(stream)
    return True


def should_show_interactive_display(stream: IO[str], *, plain: bool = False) -> bool:
    return not plain and terminal_supports_ansi(stream)


def _enable_windows_virtual_terminal(stream: IO[str]) -> bool:
    """Best-effort enablement for Windows 10+ ANSI handling."""
    try:
        import ctypes
        from ctypes import wintypes

        handle_name = "STD_ERROR_HANDLE" if stream is sys.stderr else "STD_OUTPUT_HANDLE"
        handle_id = -12 if handle_name == "STD_ERROR_HANDLE" else -11
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(handle_id)
        if handle in (0, -1):
            return False
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        return bool(
            kernel32.SetConsoleMode(
                handle,
                mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING,
            )
        )
    except Exception:
        return False


@dataclass(frozen=True)
class AskNetworkDisplay:
    matcher_host: str
    value_x_prefix: str
    relay_id: str
    relay_endpoint: str
    relay_count: int
    route_mode: str

    @classmethod
    def from_join_pack(
        cls,
        matcher: Mapping[str, object],
        reachability_relay: Mapping[str, object],
        *,
        relay_count: int,
        route_mode: str,
    ) -> "AskNetworkDisplay":
        url = str(matcher.get("url", ""))
        parsed = urlparse(url)
        value_x = _first_string(matcher.get("approved_value_x"))
        relay_id = str(reachability_relay.get("relay_id", "reachability-relay"))
        relay_host = str(reachability_relay.get("host", "unknown"))
        relay_port = str(reachability_relay.get("port", ""))
        return cls(
            matcher_host=parsed.netloc or url.rstrip("/") or "attested matcher",
            value_x_prefix=value_x[:12] if value_x else "unpinned",
            relay_id=relay_id,
            relay_endpoint=f"{relay_host}:{relay_port}" if relay_port else relay_host,
            relay_count=relay_count,
            route_mode=route_mode,
        )


class AskDisplay:
    """TTY-only product display for ``por ask``."""

    def __init__(
        self,
        network: AskNetworkDisplay,
        *,
        stream: IO[str] = sys.stderr,
        enabled: bool = True,
    ) -> None:
        self.network = network
        self.stream = stream
        self.enabled = enabled

    def start(self) -> "StatusRail":
        if not self.enabled:
            return StatusRail.disabled()

        self._line(f"{BOLD}{CYAN}P-OR live network{RESET}")
        self._line(
            f"{DIM}trust{RESET}  attested matcher {self.network.matcher_host}  "
            f"value_x={self.network.value_x_prefix}..."
        )
        self._line(
            f"{DIM}route{RESET}  you -> matcher -> {self.network.relay_id} "
            f"({self.network.relay_endpoint}) -> expert"
        )
        self._line(
            f"{DIM}peers{RESET}  {self.network.relay_count} trusted relay(s), "
            f"mode={self.network.route_mode}"
        )
        self._line("")
        rail = StatusRail(
            "attesting enclave, matching expertise, and opening return path",
            stream=self.stream,
        )
        rail.start()
        return rail

    def finish(self, result: Mapping[str, object]) -> None:
        if not self.enabled:
            return
        ok = bool(result.get("ok"))
        selected = str(result.get("selected_peer_id") or "none")
        via_mailbox = bool(result.get("via_mailbox"))
        degraded = bool(result.get("degraded_anonymity"))
        color = GREEN if ok else RED
        state = "ready" if ok else "failed"
        warn = f" {YELLOW}degraded_pool{RESET}" if degraded else ""
        self._line(
            f"{color}{state}{RESET}  selected={selected} "
            f"via_mailbox={str(via_mailbox).lower()}{warn}"
        )
        self._line("")

    def _line(self, text: str) -> None:
        print(text, file=self.stream, flush=True)


@dataclass(frozen=True)
class PayoutRow:
    peer_id: str
    amount: str
    status: str


class PayoutsDisplay:
    """Future payments view placeholder.

    CLI_UI_TODO: replace this with real ledger/API-backed payout data once the
    protocol exposes a settled payment contract. This class must stay inert
    until then; do not render synthetic balances from routing state.
    """

    def render(self, rows: Sequence[PayoutRow]) -> str:
        raise NotImplementedError(
            "CLI_UI_TODO: payouts display needs a real ledger/API contract"
        )


class ExperimentalSceneRenderer:
    """Future richer terminal graphics placeholder.

    CLI_UI_TODO: evaluate terminal-safe 3D/scene rendering after the architecture
    reorg settles. The current CLI uses ASCII + ANSI only for predictable
    macOS/Linux/Windows behavior.
    """

    def render_network_scene(self, network: AskNetworkDisplay) -> str:
        raise NotImplementedError(
            "CLI_UI_TODO: 3D network scene renderer is not implemented"
        )


class StatusRail(AbstractContextManager["StatusRail"]):
    """Single-line status rail that behaves well in tmux/screen/logging."""

    _frames = ("-", "\\", "|", "/")

    def __init__(
        self,
        label: str,
        *,
        stream: IO[str] = sys.stderr,
        interval: float = 0.12,
        enabled: bool = True,
    ) -> None:
        self.label = label
        self.stream = stream
        self.interval = interval
        self.enabled = enabled
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    @classmethod
    def disabled(cls) -> "StatusRail":
        return cls("", enabled=False)

    def start(self) -> None:
        if not self.enabled or self._started:
            return
        self._started = True
        self._thread = threading.Thread(target=self._run, name="por-status-rail", daemon=True)
        self._thread.start()

    def stop(self, final_label: str = "network exchange complete") -> None:
        if not self.enabled or not self._started:
            return
        self._done.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.stream.write(f"\r{CLEAR_LINE}{GREEN}ok{RESET}  {final_label}\n")
        self.stream.flush()

    def fail(self, final_label: str = "network exchange failed") -> None:
        if not self.enabled or not self._started:
            return
        self._done.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.stream.write(f"\r{CLEAR_LINE}{RED}error{RESET}  {final_label}\n")
        self.stream.flush()

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            self.stop()
        else:
            self.fail()
        return False

    def _run(self) -> None:
        index = 0
        while not self._done.is_set():
            frame = self._frames[index % len(self._frames)]
            self.stream.write(f"\r{CLEAR_LINE}{MAGENTA}{frame}{RESET}  {self.label}")
            self.stream.flush()
            index += 1
            self._done.wait(self.interval)


def _first_string(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)) and value:
        return str(value[0])
    return ""
