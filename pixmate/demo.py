"""Demo mode: simulates a Claude Code session to showcase all animation states."""

import asyncio

from .events import Event, EventType
from .state_machine import StateMachine
from .display.manager import DisplayStrategy


DEMO_SCENARIO: list[tuple[float, EventType, dict, str]] = [
    (2.0,  EventType.IDLE,             {},                         "Idle..."),
    (0.5,  EventType.USER_INPUT,       {"raw": "Fix auth bug"},    "Listening..."),
    (1.5,  EventType.THINKING_START,   {},                         "Thinking..."),
    (3.0,  EventType.STREAM_START,     {},                         "Writing response..."),
    (4.0,  EventType.STREAM_END,       {},                         ""),
    (0.3,  EventType.TOOL_START,       {"tool": "Read"},           "Reading file..."),
    (2.0,  EventType.TOOL_END,         {"tool": "Read"},           ""),
    (0.3,  EventType.TOOL_START,       {"tool": "Bash"},           "Running tests..."),
    (3.0,  EventType.ERROR,            {"text": "3 tests failed"}, "Error! Tests failed"),
    (2.5,  EventType.THINKING_START,   {},                         "Thinking harder..."),
    (2.0,  EventType.TOOL_START,       {"tool": "Edit"},           "Editing code..."),
    (2.5,  EventType.TOOL_END,         {"tool": "Edit"},           ""),
    (0.3,  EventType.TOOL_START,       {"tool": "Bash"},           "Re-running tests..."),
    (2.0,  EventType.SUCCESS,          {},                         "All tests pass!"),
    (3.0,  EventType.IDLE,             {},                         "Idle..."),
    (1.0,  EventType.PERMISSION_PROMPT,{},                         "Awaiting permission..."),
    (2.0,  EventType.USER_INPUT,       {"raw": "y"},               "Permission granted"),
    (1.0,  EventType.TOOL_START,       {"tool": "Bash"},           "Deploying..."),
    (2.5,  EventType.SUCCESS,          {},                         "Complete!"),
    (5.0,  EventType.IDLE,             {},                         "Going to sleep..."),
]


class DemoRunner:
    def __init__(self, state_machine: StateMachine, display: DisplayStrategy):
        self._sm = state_machine
        self._display = display

    async def run(self, loops: int = 1) -> None:
        for loop_idx in range(loops):
            for delay, event_type, data, label in DEMO_SCENARIO:
                # Animate during the delay
                state = self._sm.current
                frames = int(delay * state.frame_rate)
                frame_delay = delay / max(frames, 1)

                for _ in range(max(frames, 1)):
                    self._display.draw_frame(state.animation_key)
                    # Also check timeouts
                    timeout_state = self._sm.check_timeout()
                    if timeout_state:
                        state = timeout_state
                        self._display.draw_label("Sleeping...")
                    await asyncio.sleep(frame_delay)

                # Fire the event
                event = Event(type=event_type, data=data)
                new_state = self._sm.process_event(event)
                if new_state:
                    state = new_state

                if label:
                    self._display.draw_label(label)

        # Final idle animation for a few seconds
        for _ in range(10):
            self._display.draw_frame(self._sm.current.animation_key)
            self._sm.check_timeout()
            await asyncio.sleep(0.5)
