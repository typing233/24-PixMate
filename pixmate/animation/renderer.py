"""ANSI-based pixel art renderer using half-block characters."""

import sys
from io import StringIO

from .sprites import Sprite, BUILTIN_SPRITES, ASCII_SPRITES
from ..terminal_detect import TerminalProfile, ColorDepth


class Renderer:
    def __init__(self, profile: TerminalProfile):
        self._profile = profile
        self._sprites = BUILTIN_SPRITES
        self._ascii_sprites = ASCII_SPRITES
        self._frame_indices: dict[str, int] = {}
        self._prev_buffer: list[str] = []
        self._use_ascii = not profile.unicode or profile.color_depth == ColorDepth.NONE

    def next_frame(self, animation_key: str) -> str:
        if self._use_ascii:
            return self._render_ascii(animation_key)
        return self._render_halfblock(animation_key)

    def render_static(self, animation_key: str, frame: int = 0) -> str:
        if self._use_ascii:
            return self._render_ascii_frame(animation_key, frame)
        sprite = self._sprites.get(animation_key)
        if not sprite:
            return ""
        return self._sprite_to_ansi(sprite, frame)

    def _render_halfblock(self, animation_key: str) -> str:
        sprite = self._sprites.get(animation_key)
        if not sprite:
            sprite = self._sprites["idle"]

        idx = self._frame_indices.get(animation_key, 0)
        result = self._sprite_to_ansi(sprite, idx)
        self._frame_indices[animation_key] = (idx + 1) % sprite.frame_count
        return result

    def _sprite_to_ansi(self, sprite: Sprite, frame_idx: int) -> str:
        frame = sprite.frames[frame_idx % sprite.frame_count]
        buf = StringIO()

        for char_row in range(sprite.height // 2):
            top_y = char_row * 2
            bot_y = top_y + 1

            for x in range(sprite.width):
                top_idx = frame[top_y][x]
                bot_idx = frame[bot_y][x]
                top_color = sprite.palette[top_idx] if top_idx < len(sprite.palette) else None
                bot_color = sprite.palette[bot_idx] if bot_idx < len(sprite.palette) else None

                if top_color is None and bot_color is None:
                    buf.write(" ")
                elif top_color is None:
                    buf.write(self._fg(bot_color) + "▄" + "\x1b[0m")
                elif bot_color is None:
                    buf.write(self._fg(top_color) + "▀" + "\x1b[0m")
                else:
                    buf.write(self._fg(top_color) + self._bg(bot_color) + "▀" + "\x1b[0m")

            buf.write("\n")

        return buf.getvalue()

    def _render_ascii(self, animation_key: str) -> str:
        frames = self._ascii_sprites.get(animation_key, self._ascii_sprites["idle"])
        idx = self._frame_indices.get(animation_key, 0)
        rows_per_frame = 3
        frame_idx = (idx // rows_per_frame) % (len(frames) // rows_per_frame)
        start = frame_idx * rows_per_frame
        result = "\n".join(row[0] if row else "" for row in frames[start:start + rows_per_frame])
        self._frame_indices[animation_key] = idx + 1
        return result + "\n"

    def _render_ascii_frame(self, animation_key: str, frame: int) -> str:
        frames = self._ascii_sprites.get(animation_key, self._ascii_sprites["idle"])
        rows_per_frame = 3
        frame_idx = frame % (len(frames) // rows_per_frame)
        start = frame_idx * rows_per_frame
        return "\n".join(row[0] if row else "" for row in frames[start:start + rows_per_frame]) + "\n"

    def _fg(self, rgb: tuple[int, int, int]) -> str:
        if self._profile.color_depth >= ColorDepth.TRUECOLOR:
            return f"\x1b[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"
        elif self._profile.color_depth >= ColorDepth.COLORS_256:
            return f"\x1b[38;5;{self._rgb_to_256(rgb)}m"
        else:
            return f"\x1b[{self._rgb_to_16_fg(rgb)}m"

    def _bg(self, rgb: tuple[int, int, int]) -> str:
        if self._profile.color_depth >= ColorDepth.TRUECOLOR:
            return f"\x1b[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"
        elif self._profile.color_depth >= ColorDepth.COLORS_256:
            return f"\x1b[48;5;{self._rgb_to_256(rgb)}m"
        else:
            return f"\x1b[{self._rgb_to_16_bg(rgb)}m"

    @staticmethod
    def _rgb_to_256(rgb: tuple[int, int, int]) -> int:
        r, g, b = rgb
        if r == g == b:
            if r < 8:
                return 16
            if r > 248:
                return 231
            return round((r - 8) / 247 * 24) + 232
        return 16 + (36 * round(r / 255 * 5)) + (6 * round(g / 255 * 5)) + round(b / 255 * 5)

    @staticmethod
    def _rgb_to_16_fg(rgb: tuple[int, int, int]) -> int:
        r, g, b = rgb
        brightness = (r + g + b) / 3
        if brightness > 200:
            return 97  # bright white
        if r > g and r > b:
            return 91  # bright red
        if g > r and g > b:
            return 92  # bright green
        if b > r and b > g:
            return 94  # bright blue
        if brightness > 100:
            return 37  # white
        return 90  # dark gray

    @staticmethod
    def _rgb_to_16_bg(rgb: tuple[int, int, int]) -> int:
        r, g, b = rgb
        brightness = (r + g + b) / 3
        if brightness > 200:
            return 107
        if r > g and r > b:
            return 101
        if g > r and g > b:
            return 102
        if b > r and b > g:
            return 104
        if brightness > 100:
            return 47
        return 100


class PositionedRenderer:
    """Renders frames at fixed terminal positions with differential updates."""

    def __init__(self, renderer: Renderer, row: int, col: int):
        self._renderer = renderer
        self._row = row
        self._col = col
        self._prev_lines: list[str] = []

    def draw(self, animation_key: str, stream=sys.stdout) -> None:
        frame_str = self._renderer.next_frame(animation_key)
        lines = frame_str.rstrip("\n").split("\n")
        output = StringIO()

        output.write("\x1b7")  # save cursor

        for i, line in enumerate(lines):
            if i < len(self._prev_lines) and self._prev_lines[i] == line:
                continue
            output.write(f"\x1b[{self._row + i};{self._col}H")
            output.write(line)

        output.write("\x1b8")  # restore cursor
        self._prev_lines = lines

        result = output.getvalue()
        if result != "\x1b7\x1b8":
            stream.write(result)
            stream.flush()
