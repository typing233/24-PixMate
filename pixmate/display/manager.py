"""Display manager: selects and coordinates the display strategy."""

import os
import sys
import subprocess
import asyncio
from typing import Protocol

from ..terminal_detect import TerminalProfile
from ..animation.renderer import Renderer, PositionedRenderer


class DisplayStrategy(Protocol):
    def setup(self, profile: TerminalProfile) -> None: ...
    def draw_frame(self, animation_key: str) -> None: ...
    def draw_label(self, label: str) -> None: ...
    def teardown(self) -> None: ...
    @property
    def companion_width(self) -> int: ...


class TmuxSplitDisplay:
    """Renders companion in a tmux split pane."""

    def __init__(self, width: int = 20):
        self._width = width
        self._pane_id: str | None = None
        self._renderer: Renderer | None = None
        self._pipe_path: str = ""
        self._pipe_fd: int = -1

    @property
    def companion_width(self) -> int:
        # Return requested width (used for child PTY sizing)
        # even before setup confirms the pane — the proxy needs this at fork time
        return self._width

    def setup(self, profile: TerminalProfile) -> None:
        if not os.environ.get("TMUX"):
            self._width = 0
            return

        self._renderer = Renderer(profile)
        self._pipe_path = f"/tmp/pixmate_pipe_{os.getpid()}"

        try:
            if os.path.exists(self._pipe_path):
                os.unlink(self._pipe_path)
            os.mkfifo(self._pipe_path)
        except OSError:
            self._width = 0
            return

        companion_script = (
            f"python3 -m pixmate.display.companion_pane {self._pipe_path} {self._width}"
        )
        try:
            result = subprocess.run(
                ["tmux", "split-window", "-h", "-l", str(self._width),
                 "-d", "-P", "-F", "#{pane_id}", companion_script],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                self._pane_id = result.stdout.strip()
            else:
                self._width = 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            self._width = 0

    def draw_frame(self, animation_key: str) -> None:
        if not self._pane_id or not self._pipe_path:
            return
        try:
            fd = os.open(self._pipe_path, os.O_WRONLY | os.O_NONBLOCK)
            os.write(fd, f"frame:{animation_key}\n".encode())
            os.close(fd)
        except (OSError, BrokenPipeError):
            pass

    def draw_label(self, label: str) -> None:
        if not self._pane_id or not self._pipe_path:
            return
        try:
            fd = os.open(self._pipe_path, os.O_WRONLY | os.O_NONBLOCK)
            os.write(fd, f"label:{label}\n".encode())
            os.close(fd)
        except (OSError, BrokenPipeError):
            pass

    def teardown(self) -> None:
        if self._pane_id:
            try:
                subprocess.run(["tmux", "kill-pane", "-t", self._pane_id],
                              capture_output=True, timeout=3)
            except Exception:
                pass
            self._pane_id = None
        if self._pipe_path and os.path.exists(self._pipe_path):
            try:
                os.unlink(self._pipe_path)
            except OSError:
                pass


class InlineDisplay:
    """Renders companion in a fixed region at the bottom of the terminal."""

    def __init__(self, height: int = 8):
        self._height = height
        self._renderer: Renderer | None = None
        self._positioned: PositionedRenderer | None = None
        self._profile: TerminalProfile | None = None
        self._label: str = ""

    @property
    def companion_width(self) -> int:
        return 0

    def setup(self, profile: TerminalProfile) -> None:
        self._profile = profile
        self._renderer = Renderer(profile)

        row = profile.rows - self._height + 1
        col = profile.cols - 14
        self._positioned = PositionedRenderer(self._renderer, row, col)

        sys.stdout.write(f"\x1b[1;{profile.rows - self._height}r")
        sys.stdout.flush()

    def draw_frame(self, animation_key: str) -> None:
        if self._positioned:
            self._positioned.draw(animation_key)
            if self._label and self._profile:
                row = self._profile.rows
                col = self._profile.cols - len(self._label) - 2
                sys.stdout.write(f"\x1b7\x1b[{row};{col}H\x1b[2m{self._label}\x1b[0m\x1b8")
                sys.stdout.flush()

    def draw_label(self, label: str) -> None:
        self._label = label

    def teardown(self) -> None:
        sys.stdout.write("\x1b[r")
        sys.stdout.flush()


class StandaloneDisplay:
    """Renders companion standalone (for demo mode) in center of terminal."""

    def __init__(self):
        self._renderer: Renderer | None = None
        self._profile: TerminalProfile | None = None
        self._current_label: str = ""

    @property
    def companion_width(self) -> int:
        return 0

    def setup(self, profile: TerminalProfile) -> None:
        self._profile = profile
        self._renderer = Renderer(profile)
        sys.stdout.write("\x1b[2J\x1b[H")  # clear screen
        sys.stdout.write("\x1b[?25l")  # hide cursor
        sys.stdout.flush()

    def draw_frame(self, animation_key: str) -> None:
        if not self._renderer or not self._profile:
            return

        frame_str = self._renderer.next_frame(animation_key)
        lines = frame_str.rstrip("\n").split("\n")

        start_row = max(1, (self._profile.rows - len(lines) - 2) // 2)
        start_col = max(1, (self._profile.cols - 12) // 2)

        buf = "\x1b7"  # save cursor
        for i, line in enumerate(lines):
            buf += f"\x1b[{start_row + i};{start_col}H{line}"

        label_row = start_row + len(lines) + 1
        label_col = max(1, (self._profile.cols - max(len(self._current_label), 20)) // 2)
        # Clear old label then write new one
        buf += f"\x1b[{label_row};{label_col}H" + " " * 30
        if self._current_label:
            label_col = max(1, (self._profile.cols - len(self._current_label)) // 2)
            buf += f"\x1b[{label_row};{label_col}H\x1b[1m{self._current_label}\x1b[0m"

        buf += "\x1b8"  # restore cursor
        sys.stdout.write(buf)
        sys.stdout.flush()

    def draw_label(self, label: str) -> None:
        self._current_label = label

    def teardown(self) -> None:
        sys.stdout.write("\x1b[?25h")  # show cursor
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.flush()


def choose_display(mode: str, profile: TerminalProfile, width: int = 20) -> DisplayStrategy:
    """Select display strategy based on mode and terminal capabilities.

    Args:
        mode: Display mode string (tmux-split, inline, standalone, auto)
        profile: Detected terminal capabilities
        width: Companion panel width in columns (applies to tmux-split)
    """
    if mode == "tmux-split" and profile.in_tmux:
        return TmuxSplitDisplay(width=width)
    elif mode == "tmux-split" and not profile.in_tmux:
        # Requested tmux but not in tmux — fallback to inline
        return InlineDisplay()
    elif mode == "inline":
        return InlineDisplay()
    elif mode == "standalone":
        return StandaloneDisplay()
    else:
        if profile.in_tmux:
            return TmuxSplitDisplay(width=width)
        return InlineDisplay()
