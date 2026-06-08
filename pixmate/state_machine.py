"""State machine engine for PixMate character animation."""

from dataclasses import dataclass, field
from typing import Callable
import time

from .events import Event, EventType


@dataclass
class State:
    name: str
    animation_key: str
    frame_rate: float = 2.0
    timeout: float | None = None
    timeout_target: str | None = None


@dataclass
class Transition:
    event: EventType
    source: str  # state name or "*" for wildcard
    target: str
    priority: int = 0


DEFAULT_STATES: dict[str, State] = {
    "idle": State("idle", "idle", frame_rate=1.0, timeout=30.0, timeout_target="sleeping"),
    "listening": State("listening", "listening", frame_rate=2.0),
    "thinking": State("thinking", "thinking", frame_rate=4.0),
    "typing": State("typing", "typing", frame_rate=6.0),
    "working": State("working", "working", frame_rate=3.0),
    "confused": State("confused", "confused", frame_rate=2.0, timeout=5.0, timeout_target="idle"),
    "celebrating": State("celebrating", "celebrating", frame_rate=4.0, timeout=3.0, timeout_target="idle"),
    "sleeping": State("sleeping", "sleeping", frame_rate=0.5),
}

DEFAULT_TRANSITIONS: list[Transition] = [
    Transition(EventType.USER_INPUT, "*", "listening", priority=5),
    Transition(EventType.THINKING_START, "*", "thinking", priority=10),
    Transition(EventType.STREAM_START, "*", "typing", priority=10),
    Transition(EventType.STREAM_END, "typing", "idle", priority=5),
    Transition(EventType.TOOL_START, "*", "working", priority=10),
    Transition(EventType.TOOL_END, "working", "idle", priority=5),
    Transition(EventType.ERROR, "*", "confused", priority=15),
    Transition(EventType.SUCCESS, "*", "celebrating", priority=15),
    Transition(EventType.CANCEL, "*", "idle", priority=20),
    Transition(EventType.IDLE, "*", "idle", priority=1),
    Transition(EventType.PERMISSION_PROMPT, "*", "listening", priority=8),
    Transition(EventType.SESSION_RESUME, "*", "idle", priority=5),
]


class StateMachine:
    def __init__(
        self,
        states: dict[str, State] | None = None,
        transitions: list[Transition] | None = None,
    ):
        self._states = states or DEFAULT_STATES
        self._transitions = transitions or DEFAULT_TRANSITIONS
        self._current_name = "idle"
        self._entered_at = time.monotonic()
        self._listeners: list[Callable[[str, str, Event | None], None]] = []

    @property
    def current(self) -> State:
        return self._states[self._current_name]

    @property
    def current_name(self) -> str:
        return self._current_name

    def add_listener(self, callback: Callable[[str, str, Event | None], None]) -> None:
        self._listeners.append(callback)

    def process_event(self, event: Event) -> State | None:
        matching = []
        for t in self._transitions:
            if t.event != event.type:
                continue
            if t.source != "*" and t.source != self._current_name:
                continue
            if t.target == self._current_name and t.source != "*":
                continue
            matching.append(t)

        if not matching:
            return None

        matching.sort(key=lambda t: t.priority, reverse=True)
        best = matching[0]

        if best.target not in self._states:
            return None

        old_name = self._current_name
        self._current_name = best.target
        self._entered_at = time.monotonic()

        for listener in self._listeners:
            listener(old_name, best.target, event)

        return self._states[best.target]

    def check_timeout(self) -> State | None:
        state = self.current
        if state.timeout is None or state.timeout_target is None:
            return None

        elapsed = time.monotonic() - self._entered_at
        if elapsed >= state.timeout:
            target_name = state.timeout_target
            if target_name in self._states and target_name != self._current_name:
                old_name = self._current_name
                self._current_name = target_name
                self._entered_at = time.monotonic()
                for listener in self._listeners:
                    listener(old_name, target_name, None)
                return self._states[target_name]

        return None

    def force_state(self, state_name: str) -> State | None:
        if state_name not in self._states:
            return None
        old = self._current_name
        self._current_name = state_name
        self._entered_at = time.monotonic()
        for listener in self._listeners:
            listener(old, state_name, None)
        return self._states[state_name]
