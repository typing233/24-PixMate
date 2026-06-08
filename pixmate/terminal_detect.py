"""Terminal capability detection for graceful degradation."""

import os
import shutil
from dataclasses import dataclass
from enum import IntEnum


class ColorDepth(IntEnum):
    NONE = 0
    COLORS_16 = 16
    COLORS_256 = 256
    TRUECOLOR = 16777216


@dataclass
class TerminalProfile:
    color_depth: ColorDepth = ColorDepth.COLORS_256
    unicode: bool = True
    in_tmux: bool = False
    in_screen: bool = False
    in_ssh: bool = False
    cols: int = 80
    rows: int = 24


def detect_terminal() -> TerminalProfile:
    profile = TerminalProfile()

    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        profile.color_depth = ColorDepth.TRUECOLOR
    else:
        term = os.environ.get("TERM", "")
        if "256color" in term:
            profile.color_depth = ColorDepth.COLORS_256
        elif term:
            profile.color_depth = ColorDepth.COLORS_16
        else:
            profile.color_depth = ColorDepth.NONE

    lang = os.environ.get("LANG", "") + os.environ.get("LC_ALL", "")
    profile.unicode = "utf" in lang.lower()

    profile.in_tmux = bool(os.environ.get("TMUX"))
    term = os.environ.get("TERM", "")
    profile.in_screen = "screen" in term
    profile.in_ssh = bool(os.environ.get("SSH_CONNECTION"))

    cols, rows = shutil.get_terminal_size((80, 24))
    profile.cols = cols
    profile.rows = rows

    return profile


def rendering_tier(profile: TerminalProfile) -> str:
    if not profile.unicode:
        return "ascii"
    if profile.color_depth >= ColorDepth.TRUECOLOR:
        return "truecolor"
    if profile.color_depth >= ColorDepth.COLORS_256:
        return "color256"
    return "basic"
