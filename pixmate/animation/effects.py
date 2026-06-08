"""Transition effects between animation states."""

import time


class TransitionEffect:
    """Base class for visual transition effects."""

    def __init__(self, duration: float = 0.3):
        self.duration = duration
        self._start_time: float | None = None

    def start(self) -> None:
        self._start_time = time.monotonic()

    @property
    def progress(self) -> float:
        if self._start_time is None:
            return 0.0
        elapsed = time.monotonic() - self._start_time
        return min(1.0, elapsed / self.duration)

    @property
    def is_complete(self) -> bool:
        return self.progress >= 1.0


class FadeEffect(TransitionEffect):
    """Fade between states by dimming brightness."""

    def apply_brightness(self, rgb: tuple[int, int, int], phase: str) -> tuple[int, int, int]:
        p = self.progress
        if phase == "out":
            factor = 1.0 - p
        else:
            factor = p
        return (
            int(rgb[0] * factor),
            int(rgb[1] * factor),
            int(rgb[2] * factor),
        )


class BounceEffect(TransitionEffect):
    """Vertical bounce during transition."""

    def get_offset(self) -> int:
        p = self.progress
        bounce = abs(int(2 * (1 - (2 * p - 1) ** 2)))
        return -bounce
