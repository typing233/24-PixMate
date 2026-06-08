"""PTY proxy layer: intercepts I/O between user terminal and child process."""

import asyncio
import fcntl
import os
import pty
import signal
import struct
import sys
import termios
import tty
from typing import Callable, Awaitable

from .events import Direction


class PtyProxy:
    def __init__(self, companion_width: int = 0):
        self._companion_width = companion_width
        self._master_fd: int = -1
        self._child_pid: int = -1
        self._original_termios: list | None = None
        self._running: bool = False

    async def run(
        self,
        argv: list[str],
        on_data: Callable[[bytes, Direction], Awaitable[None] | None],
    ) -> int:
        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd

        parent_size = self._get_terminal_size()
        child_cols = max(40, parent_size[1] - self._companion_width)
        self._set_pty_size(slave_fd, parent_size[0], child_cols)

        pid = os.fork()
        if pid == 0:
            self._child_process(slave_fd, argv)

        os.close(slave_fd)
        self._child_pid = pid

        if sys.stdin.isatty():
            self._original_termios = termios.tcgetattr(sys.stdin.fileno())
            tty.setraw(sys.stdin.fileno())

        self._setup_signals()
        self._running = True

        try:
            return await self._proxy_loop(master_fd, pid, on_data)
        finally:
            self._cleanup()

    def _child_process(self, slave_fd: int, argv: list[str]) -> None:
        os.close(self._master_fd)
        os.setsid()

        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

        os.dup2(slave_fd, 0)
        os.dup2(slave_fd, 1)
        os.dup2(slave_fd, 2)

        if slave_fd > 2:
            os.close(slave_fd)

        os.execvp(argv[0], argv)

    async def _proxy_loop(
        self,
        master_fd: int,
        pid: int,
        on_data: Callable[[bytes, Direction], Awaitable[None] | None],
    ) -> int:
        loop = asyncio.get_event_loop()

        stdin_fd = sys.stdin.fileno()
        stdout_fd = sys.stdout.fileno()

        fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

        child_done = asyncio.Event()
        exit_status = [0]

        def handle_sigchld(*_):
            try:
                wpid, status = os.waitpid(pid, os.WNOHANG)
                if wpid == pid:
                    exit_status[0] = os.WEXITSTATUS(status) if os.WIFEXITED(status) else 1
                    loop.call_soon_threadsafe(child_done.set)
            except ChildProcessError:
                loop.call_soon_threadsafe(child_done.set)

        signal.signal(signal.SIGCHLD, handle_sigchld)

        async def read_stdin():
            if not sys.stdin.isatty():
                return
            while self._running and not child_done.is_set():
                try:
                    data = await loop.run_in_executor(None, lambda: os.read(stdin_fd, 4096))
                except OSError:
                    break
                if not data:
                    break
                result = on_data(data, Direction.INPUT)
                if asyncio.iscoroutine(result):
                    await result
                try:
                    os.write(master_fd, data)
                except OSError:
                    break

        async def read_master():
            while self._running:
                try:
                    data = os.read(master_fd, 16384)
                except BlockingIOError:
                    if child_done.is_set():
                        break
                    await asyncio.sleep(0.005)
                    continue
                except OSError:
                    break
                if not data:
                    break
                result = on_data(data, Direction.OUTPUT)
                if asyncio.iscoroutine(result):
                    await result
                try:
                    os.write(stdout_fd, data)
                except OSError:
                    break

        stdin_task = asyncio.create_task(read_stdin())
        master_task = asyncio.create_task(read_master())

        await child_done.wait()

        # Drain remaining output from master after child exits
        await asyncio.sleep(0.05)
        while True:
            try:
                data = os.read(master_fd, 16384)
                if not data:
                    break
                result = on_data(data, Direction.OUTPUT)
                if asyncio.iscoroutine(result):
                    await result
                try:
                    os.write(stdout_fd, data)
                except OSError:
                    pass
            except (OSError, BlockingIOError):
                break

        self._running = False

        stdin_task.cancel()
        master_task.cancel()
        try:
            await asyncio.gather(stdin_task, master_task, return_exceptions=True)
        except Exception:
            pass

        return exit_status[0]

    def _setup_signals(self) -> None:
        def handle_winch(*_):
            if self._master_fd >= 0:
                size = self._get_terminal_size()
                child_cols = max(40, size[1] - self._companion_width)
                self._set_pty_size(self._master_fd, size[0], child_cols)
                if self._child_pid > 0:
                    try:
                        os.kill(self._child_pid, signal.SIGWINCH)
                    except ProcessLookupError:
                        pass

        signal.signal(signal.SIGWINCH, handle_winch)

    def _cleanup(self) -> None:
        self._running = False
        if self._original_termios and sys.stdin.isatty():
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSAFLUSH, self._original_termios)
            except Exception:
                pass
        if self._master_fd >= 0:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = -1

    @staticmethod
    def _get_terminal_size() -> tuple[int, int]:
        try:
            data = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\x00" * 8)
            rows, cols = struct.unpack("HHHH", data)[:2]
            return (rows, cols)
        except Exception:
            return (24, 80)

    @staticmethod
    def _set_pty_size(fd: int, rows: int, cols: int) -> None:
        size = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, size)
