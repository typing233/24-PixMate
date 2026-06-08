"""Companion pane process: runs in the tmux split, receives commands via FIFO."""

import os
import select
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pixmate.terminal_detect import detect_terminal
from pixmate.animation.renderer import Renderer


def run_companion(pipe_path: str, width: int = 20) -> None:
    profile = detect_terminal()
    profile.cols = width
    renderer = Renderer(profile)

    current_animation = "idle"
    current_label = "Idle"

    sys.stdout.write("\x1b[2J\x1b[H")  # clear
    sys.stdout.write("\x1b[?25l")  # hide cursor
    sys.stdout.flush()

    # Open FIFO for reading (non-blocking)
    pipe_fd = os.open(pipe_path, os.O_RDONLY | os.O_NONBLOCK)

    last_render = 0.0
    frame_interval = 0.25  # 4 fps default

    try:
        while True:
            # Poll FIFO for commands
            try:
                ready, _, _ = select.select([pipe_fd], [], [], 0.05)
                if ready:
                    raw = os.read(pipe_fd, 4096)
                    if raw:
                        for line in raw.decode(errors="replace").split("\n"):
                            line = line.strip()
                            if line.startswith("frame:"):
                                new_anim = line[6:]
                                if new_anim != current_animation:
                                    current_animation = new_anim
                            elif line.startswith("label:"):
                                current_label = line[6:]
                            elif line == "quit":
                                return
                    else:
                        # EOF on pipe — writer closed, reopen
                        os.close(pipe_fd)
                        pipe_fd = os.open(pipe_path, os.O_RDONLY | os.O_NONBLOCK)
            except (OSError, IOError):
                # Reopen pipe on error
                try:
                    os.close(pipe_fd)
                except OSError:
                    pass
                time.sleep(0.1)
                try:
                    pipe_fd = os.open(pipe_path, os.O_RDONLY | os.O_NONBLOCK)
                except OSError:
                    return

            # Render at frame interval
            now = time.monotonic()
            if now - last_render >= frame_interval:
                last_render = now
                _render_frame(renderer, current_animation, current_label, width)

    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.close(pipe_fd)
        except OSError:
            pass
        sys.stdout.write("\x1b[?25h")  # show cursor
        sys.stdout.flush()


def _render_frame(renderer: Renderer, animation: str, label: str, width: int) -> None:
    frame_str = renderer.next_frame(animation)
    lines = frame_str.rstrip("\n").split("\n")

    buf = "\x1b[H"  # home cursor

    # Center the sprite horizontally in the pane
    sprite_width = 12
    pad = max(0, (width - sprite_width) // 2)
    pad_str = " " * pad

    for i, line in enumerate(lines):
        buf += f"\x1b[{i + 2};1H\x1b[2K{pad_str}{line}"

    # Label below sprite
    label_row = len(lines) + 4
    # Truncate label to fit width
    display_label = label[:width - 2] if len(label) > width - 2 else label
    label_pad = max(0, (width - len(display_label)) // 2)
    buf += f"\x1b[{label_row};1H\x1b[2K{' ' * label_pad}\x1b[1m{display_label}\x1b[0m"

    # Border top
    buf += f"\x1b[1;1H{'─' * width}"

    sys.stdout.write(buf)
    sys.stdout.flush()


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        pipe = sys.argv[1]
        w = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        run_companion(pipe, w)
    else:
        print("Usage: python -m pixmate.display.companion_pane <pipe_path> [width]")
        sys.exit(1)
