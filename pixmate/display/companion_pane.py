"""Companion pane process: runs in the tmux split, receives commands via pipe."""

import os
import sys
import time

# Add parent package to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pixmate.terminal_detect import detect_terminal
from pixmate.animation.renderer import Renderer


def run_companion(pipe_path: str) -> None:
    profile = detect_terminal()
    renderer = Renderer(profile)

    current_animation = "idle"
    current_label = "Idle"

    sys.stdout.write("\x1b[2J\x1b[H")  # clear
    sys.stdout.write("\x1b[?25l")  # hide cursor
    sys.stdout.flush()

    try:
        while True:
            # Render current frame
            frame_str = renderer.next_frame(current_animation)
            lines = frame_str.rstrip("\n").split("\n")

            buf = "\x1b[H"  # home cursor
            for i, line in enumerate(lines):
                buf += f"\x1b[{i + 2};2H{line}"

            # Draw label
            label_row = len(lines) + 3
            buf += f"\x1b[{label_row};2H\x1b[2K\x1b[1m{current_label}\x1b[0m"

            sys.stdout.write(buf)
            sys.stdout.flush()

            # Check for commands (non-blocking)
            try:
                with open(pipe_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("frame:"):
                            current_animation = line[6:]
                        elif line.startswith("label:"):
                            current_label = line[6:]
                        elif line == "quit":
                            return
            except (OSError, IOError):
                pass

            time.sleep(0.2)

    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[?25h")  # show cursor
        sys.stdout.flush()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        run_companion(sys.argv[1])
    else:
        print("Usage: python -m pixmate.display.companion_pane <pipe_path>")
        sys.exit(1)
