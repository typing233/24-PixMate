"""Replay player: drives state machine and renderer from recorded event logs."""

import asyncio

from .event_log import load_event_log
from .events import Event, EventType, EventSource
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
                # Animate during the delay
                state = self._sm.current
                frames = int(delay * state.frame_rate)
                frame_delay = delay / max(frames, 1)
                for _ in range(max(frames, 1)):
                    self._display.draw_frame(state.animation_key)
                    timeout_state = self._sm.check_timeout()
                    if timeout_state:
                        state = timeout_state
                    await asyncio.sleep(frame_delay)
            last_t = t

            event_type = entry.get("type", "")
            try:
                etype = EventType(event_type)
            except ValueError:
                continue

            source_str = entry.get("source", "pty")
            try:
                source = EventSource(source_str)
            except ValueError:
                source = EventSource.PTY

            event = Event(type=etype, data=entry.get("data", {}), source=source)
            new_state = self._sm.process_event(event)

            state = self._sm.current
            self._display.draw_frame(state.animation_key)

            label = self._format_label(event)
            if label:
                self._display.draw_label(label)

    def _format_label(self, event: Event) -> str:
        source_tag = ""
        if event.source == EventSource.CLAUDE_LOG:
            source_tag = "[log] "

        labels = {
            EventType.USER_INPUT: "Listening...",
            EventType.THINKING_START: "Thinking...",
            EventType.THINKING_END: "",
            EventType.STREAM_START: "Writing...",
            EventType.STREAM_END: "",
            EventType.TOOL_START: f"Working: {event.data.get('tool', '')}",
            EventType.TOOL_END: "",
            EventType.ERROR: "Error!",
            EventType.SUCCESS: "Done!",
            EventType.CANCEL: "Cancelled",
            EventType.IDLE: "Idle",
            EventType.RETRY: "Retrying...",
            EventType.PERMISSION_PROMPT: "Awaiting permission",
            EventType.PERMISSION_RESPONSE: "Permission granted" if event.data.get("accepted") else "Permission denied",
            EventType.CONCURRENT_TASK: "Parallel task",
            EventType.SESSION_RESUME: "Resuming...",
        }
        label = labels.get(event.type, "")
        return f"{source_tag}{label}" if label else ""
