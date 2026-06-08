"""Replay player: drives state machine and renderer from recorded event logs."""

import asyncio
import time

from .event_log import load_event_log
from .events import Event, EventType
from .state_machine import StateMachine
from .display.manager import DisplayStrategy


class ReplayPlayer:
    def __init__(
        self,
        state_machine: StateMachine,
        display: DisplayStrategy,
    ):
        self._sm = state_machine
        self._display = display

    async def play(self, log_path: str, speed: float = 1.0) -> None:
        entries = load_event_log(log_path)
        if not entries:
            return

        last_t = 0.0

        for entry in entries:
            t = entry.get("t", 0.0)
            delay = (t - last_t) / speed
            if delay > 0:
                await asyncio.sleep(delay)
            last_t = t

            event_type = entry.get("type", "")
            try:
                etype = EventType(event_type)
            except ValueError:
                continue

            event = Event(type=etype, data=entry.get("data", {}))
            new_state = self._sm.process_event(event)

            state = self._sm.current
            self._display.draw_frame(state.animation_key)

            label = self._format_label(event)
            if label:
                self._display.draw_label(label)

    def _format_label(self, event: Event) -> str:
        labels = {
            EventType.USER_INPUT: "Listening...",
            EventType.THINKING_START: "Thinking...",
            EventType.STREAM_START: "Writing...",
            EventType.TOOL_START: f"Working: {event.data.get('tool', '')}",
            EventType.ERROR: "Error!",
            EventType.SUCCESS: "Done!",
            EventType.CANCEL: "Cancelled",
            EventType.IDLE: "Idle",
            EventType.PERMISSION_PROMPT: "Awaiting permission",
        }
        return labels.get(event.type, "")
