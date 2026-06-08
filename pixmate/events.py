"""Event type definitions for PixMate."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import time


class Direction(Enum):
    INPUT = "input"
    OUTPUT = "output"


class EventType(Enum):
    USER_INPUT = "user_input"
    THINKING_START = "thinking_start"
    THINKING_END = "thinking_end"
    STREAM_START = "stream_start"
    STREAM_END = "stream_end"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    ERROR = "error"
    SUCCESS = "success"
    CANCEL = "cancel"
    PERMISSION_PROMPT = "permission_prompt"
    PERMISSION_RESPONSE = "permission_response"
    IDLE = "idle"
    SESSION_RESUME = "session_resume"
    CONCURRENT_TASK = "concurrent_task"


@dataclass
class Event:
    type: EventType
    timestamp: float = field(default_factory=time.monotonic)
    data: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"Event({self.type.value}, data={self.data})"
