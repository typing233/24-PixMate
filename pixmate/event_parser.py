"""Event parser: detects Claude Code session events from terminal I/O stream."""

import re
import time
from typing import Generator

from .events import Event, EventType, EventSource, Direction


ANSI_ESCAPE = re.compile(
    r"\x1b(?:\[[0-9;]*[A-Za-z]|\][^\x07]*(?:\x07|\x1b\\)|[()][AB012]|[78M]|.)"
)

SPINNER_CHARS = frozenset("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷")

TOOL_PATTERNS = {
    "Read": re.compile(r"(?:Read|Reading)\b"),
    "Edit": re.compile(r"(?:Edit|Editing)\b"),
    "Write": re.compile(r"(?:Write|Writing)\b"),
    "Bash": re.compile(r"(?:Bash|Running)\b"),
    "LSP": re.compile(r"LSP\b"),
    "WebSearch": re.compile(r"WebSearch|WebFetch"),
    "Agent": re.compile(r"Agent\b"),
    "TaskCreate": re.compile(r"TaskCreate\b"),
    "Monitor": re.compile(r"Monitor\b"),
}

BOX_CHARS = frozenset("─│┌┐└┘├┤┬┴┼╭╮╰╯")

ERROR_PATTERNS = re.compile(
    r"(?:Error|error|ERROR|FAILED|failed|panic|Traceback|Exception)", re.IGNORECASE
)

PERMISSION_PATTERN = re.compile(
    r"(?:Allow|Deny|allow|deny)\s.*\?|(?:\[Y/n\]|\[y/N\])"
)

PERMISSION_RESPONSE_PATTERN = re.compile(
    r"(?:Allowed|Denied|allowed|denied|Permission granted|approved)\b"
)

SUCCESS_PATTERNS = re.compile(r"[✓✔]|(?:^|\s)Done(?:\s|$)|Success|Completed")

RESUME_PATTERN = re.compile(r"(?:Resuming|Resume|Reconnect)")

RETRY_PATTERN = re.compile(
    r"(?:Retrying|Retry|retrying|retry|Reattempt|reattempt|trying again|attempt \d+)"
)

CONCURRENT_TASK_PATTERN = re.compile(
    r"(?:background|Background|run_in_background|parallel|concurrent|task[-_ ]?\d+)",
    re.IGNORECASE,
)


class EventParser:
    def __init__(
        self,
        streaming_threshold: float = 50.0,
        idle_timeout: float = 5.0,
    ):
        self._streaming_threshold = streaming_threshold
        self._idle_timeout = idle_timeout

        self._last_output_time: float = 0.0
        self._output_rate: float = 0.0
        self._rate_alpha: float = 0.3
        self._is_streaming: bool = False
        self._is_thinking: bool = False
        self._in_tool_block: bool = False
        self._current_tool: str | None = None
        self._last_event_time: float = time.monotonic()
        self._last_data_time: float = time.monotonic()
        self._awaiting_permission: bool = False

    def strip_ansi(self, text: str) -> str:
        return ANSI_ESCAPE.sub("", text)

    def feed(self, data: bytes, direction: Direction) -> list[Event]:
        events = []
        now = time.monotonic()
        self._last_data_time = now

        if direction == Direction.INPUT:
            events.extend(self._parse_input(data, now))
        else:
            events.extend(self._parse_output(data, now))

        if events:
            self._last_event_time = now
        return events

    def check_idle(self) -> list[Event]:
        """Check for idle/stream-end based on time elapsed since last data.
        Returns a list of events (may be empty)."""
        now = time.monotonic()
        elapsed_since_data = now - self._last_data_time
        elapsed_since_event = now - self._last_event_time
        events = []

        # If streaming and no data for a while, end the stream
        if self._is_streaming and elapsed_since_data >= 1.0:
            self._is_streaming = False
            events.append(Event(EventType.STREAM_END, source=EventSource.INTERNAL))
            self._last_event_time = now

        # If thinking and no data for a while, end thinking (stall detection)
        elif self._is_thinking and elapsed_since_data >= 2.0:
            pass  # Keep thinking — normal for Claude to pause

        # General idle detection
        elif elapsed_since_event >= self._idle_timeout and not self._is_streaming:
            self._last_event_time = now
            events.append(Event(EventType.IDLE, source=EventSource.INTERNAL))

        return events

    def _parse_input(self, data: bytes, now: float) -> list[Event]:
        events = []
        if b"\x03" in data:
            events.append(Event(EventType.CANCEL))
            self._is_streaming = False
            self._is_thinking = False
            self._in_tool_block = False
            self._awaiting_permission = False
        elif self._awaiting_permission and data.strip():
            # User responded to a permission prompt
            self._awaiting_permission = False
            response = data.strip()[:20]
            accepted = response in (b"y", b"Y", b"yes", b"Yes", b"\r", b"\n")
            events.append(Event(
                EventType.PERMISSION_RESPONSE,
                data={"accepted": accepted, "raw": response.decode(errors="replace")},
            ))
        elif data.strip():
            events.append(Event(EventType.USER_INPUT, data={"raw": data[:50]}))
        return events

    def _parse_output(self, data: bytes, now: float) -> list[Event]:
        events = []

        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return events

        stripped = self.strip_ansi(text)

        # Update output rate
        dt = now - self._last_output_time if self._last_output_time else 0.1
        if dt > 0:
            instant_rate = len(stripped) / dt
            self._output_rate = (
                self._rate_alpha * instant_rate + (1 - self._rate_alpha) * self._output_rate
            )
        self._last_output_time = now

        # Spinner detection (thinking) — only when entire chunk is a spinner
        if self._detect_spinner(stripped):
            if not self._is_thinking:
                self._is_thinking = True
                self._is_streaming = False
                events.append(Event(EventType.THINKING_START))
            return events

        if self._is_thinking and len(stripped) > 3:
            self._is_thinking = False
            events.append(Event(EventType.THINKING_END))

        # Process line-by-line so events in the same chunk are all detected
        lines = stripped.split("\n")
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            line_events = self._parse_single_line(line_stripped)
            events.extend(line_events)

        # If no line-level events matched, check for streaming
        if not events or (len(events) == 1 and events[0].type == EventType.THINKING_END):
            if self._output_rate > self._streaming_threshold and len(stripped) > 5:
                if not self._is_streaming:
                    self._is_streaming = True
                    events.append(Event(EventType.STREAM_START))
            elif self._is_streaming and self._output_rate < self._streaming_threshold * 0.3:
                self._is_streaming = False
                events.append(Event(EventType.STREAM_END))

        return events

    def _parse_single_line(self, line: str) -> list[Event]:
        """Parse a single stripped line for events. Returns list (may be empty)."""
        events = []

        # Retry detection
        if RETRY_PATTERN.search(line):
            self._is_streaming = False
            if self._in_tool_block:
                self._in_tool_block = False
                events.append(Event(EventType.TOOL_END, data={"tool": self._current_tool}))
            events.append(Event(EventType.RETRY, data={"text": line[:80]}))
            return events

        # Concurrent task detection (box chars + concurrent keyword)
        if CONCURRENT_TASK_PATTERN.search(line) and BOX_CHARS & set(line):
            events.append(Event(EventType.CONCURRENT_TASK, data={"text": line[:80]}))
            return events

        # Tool block detection
        tool = self._detect_tool(line)
        if tool:
            if self._in_tool_block and self._current_tool != tool:
                events.append(Event(EventType.TOOL_END, data={"tool": self._current_tool}))
            self._in_tool_block = True
            self._current_tool = tool
            self._is_streaming = False
            events.append(Event(EventType.TOOL_START, data={"tool": tool}))
            # Don't return — also check permission on the same line (rare but possible)
            if not PERMISSION_PATTERN.search(line):
                return events

        # Permission prompt (can co-occur with tool box in same chunk)
        if PERMISSION_PATTERN.search(line):
            self._awaiting_permission = True
            events.append(Event(EventType.PERMISSION_PROMPT))
            return events

        # Permission response in output (system-side confirmation)
        if PERMISSION_RESPONSE_PATTERN.search(line):
            if self._awaiting_permission:
                self._awaiting_permission = False
            events.append(Event(EventType.PERMISSION_RESPONSE, data={"accepted": True}))
            return events

        # Error detection
        if ERROR_PATTERNS.search(line):
            if self._in_tool_block:
                self._in_tool_block = False
                events.append(Event(EventType.TOOL_END, data={"tool": self._current_tool}))
            events.append(Event(EventType.ERROR, data={"text": line[:100]}))
            self._is_streaming = False
            return events

        # Success detection
        if SUCCESS_PATTERNS.search(line):
            if self._in_tool_block:
                self._in_tool_block = False
                events.append(Event(EventType.TOOL_END, data={"tool": self._current_tool}))
            events.append(Event(EventType.SUCCESS))
            self._is_streaming = False
            return events

        # Session resume
        if RESUME_PATTERN.search(line):
            events.append(Event(EventType.SESSION_RESUME))
            return events

        return events

    def _detect_spinner(self, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        if len(stripped) <= 3 and any(c in SPINNER_CHARS for c in stripped):
            return True
        if "Thinking" in text or "thinking" in text:
            return True
        return False

    def _detect_tool(self, text: str) -> str | None:
        has_box = any(c in text for c in BOX_CHARS)
        if not has_box:
            return None
        for tool_name, pattern in TOOL_PATTERNS.items():
            if pattern.search(text):
                return tool_name
        return None
