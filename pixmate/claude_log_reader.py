"""Claude Code log stream reader.

Parses Claude Code's real session JSONL transcripts to emit structured events.
Claude Code writes conversation transcripts to:
  ~/.claude/projects/<project-hash>/<session-id>.jsonl

Entry types observed in real transcripts:
  - type="user": user input or tool_result feedback
    message.content: str (user text) | list[{type: "tool_result", ...}]
  - type="assistant": model response
    message.content: list[{type: "thinking"|"text"|"tool_use", ...}]
  - type="system": system events (api_error → retry, turn_duration, informational)
    subtype, level, error fields
  - type="permission-mode": permission mode changes
  - type="file-history-snapshot": file state snapshots
  - type="ai-title": session title
  - type="last-prompt": prompt tracking
  - type="attachment": context attachments
  - type="queue-operation": task queue operations
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import AsyncGenerator

from .events import Event, EventType, EventSource


def find_claude_log_dir() -> Path | None:
    """Find the Claude Code projects base directory."""
    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        return None
    return base


def find_latest_log(log_dir: Path | None = None) -> Path | None:
    """Find the most recently modified .jsonl transcript across all projects."""
    if log_dir is None:
        log_dir = find_claude_log_dir()
    if log_dir is None or not log_dir.exists():
        return None

    best_path = None
    best_mtime = 0.0

    for project_dir in log_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for f in project_dir.glob("*.jsonl"):
            try:
                mt = f.stat().st_mtime
                if mt > best_mtime:
                    best_mtime = mt
                    best_path = f
            except OSError:
                continue

    return best_path


def parse_log_entry(entry: dict) -> list[Event]:
    """Parse a single Claude Code JSONL entry into PixMate events.

    Handles the real Claude Code transcript format:
    - type="user" with message.content as str → user input
    - type="user" with message.content as list[tool_result] → tool results
    - type="assistant" with content blocks → thinking/text/tool_use
    - type="system" with subtype="api_error" → retry/error
    """
    events = []
    entry_type = entry.get("type", "")

    if entry_type == "user":
        events.extend(_parse_user_entry(entry))
    elif entry_type == "assistant":
        events.extend(_parse_assistant_entry(entry))
    elif entry_type == "system":
        events.extend(_parse_system_entry(entry))
    elif entry_type == "permission-mode":
        events.append(Event(
            EventType.SESSION_RESUME,
            source=EventSource.CLAUDE_LOG,
            data={"mode": entry.get("permissionMode", "")},
        ))

    return events


def _parse_user_entry(entry: dict) -> list[Event]:
    """Parse a user-type entry (user input or tool results)."""
    events = []
    msg = entry.get("message", {})
    content = msg.get("content", "")

    if isinstance(content, str) and content.strip():
        # Direct user text input
        events.append(Event(
            EventType.USER_INPUT,
            source=EventSource.CLAUDE_LOG,
            data={"text": content.strip()[:100]},
        ))
    elif isinstance(content, list):
        # Tool results come back as user messages with tool_result blocks
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")

            if block_type == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                is_error = block.get("is_error", False)
                result_content = block.get("content", "")

                if isinstance(result_content, list):
                    # content can be a list of {type: "text", text: "..."}
                    texts = []
                    for rb in result_content:
                        if isinstance(rb, dict) and rb.get("type") == "text":
                            texts.append(rb.get("text", ""))
                    result_text = "\n".join(texts)
                elif isinstance(result_content, str):
                    result_text = result_content
                else:
                    result_text = str(result_content)

                if is_error:
                    events.append(Event(
                        EventType.ERROR,
                        source=EventSource.CLAUDE_LOG,
                        data={
                            "tool_use_id": tool_use_id,
                            "text": result_text[:150],
                        },
                    ))
                else:
                    events.append(Event(
                        EventType.TOOL_END,
                        source=EventSource.CLAUDE_LOG,
                        data={
                            "tool_use_id": tool_use_id,
                            "text": result_text[:80],
                        },
                    ))

    return events


def _parse_assistant_entry(entry: dict) -> list[Event]:
    """Parse an assistant-type entry (thinking, text, tool_use)."""
    events = []
    msg = entry.get("message", {})
    content = msg.get("content", [])

    if not isinstance(content, list):
        if isinstance(content, str) and content.strip():
            events.append(Event(
                EventType.STREAM_START,
                source=EventSource.CLAUDE_LOG,
                data={"text": content[:80]},
            ))
        return events

    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")

        if block_type == "thinking":
            events.append(Event(
                EventType.THINKING_START,
                source=EventSource.CLAUDE_LOG,
                data={"length": len(block.get("text", ""))},
            ))

        elif block_type == "text":
            text = block.get("text", "")
            if text.strip():
                events.append(Event(
                    EventType.STREAM_START,
                    source=EventSource.CLAUDE_LOG,
                    data={"text": text[:80]},
                ))

        elif block_type == "tool_use":
            tool_name = block.get("name", "unknown")
            tool_id = block.get("id", "")
            tool_input = block.get("input", {})

            # Extract useful context from input
            context = ""
            if isinstance(tool_input, dict):
                if "command" in tool_input:
                    context = tool_input["command"][:60]
                elif "file_path" in tool_input:
                    context = tool_input["file_path"]
                elif "query" in tool_input:
                    context = tool_input["query"][:60]

            events.append(Event(
                EventType.TOOL_START,
                source=EventSource.CLAUDE_LOG,
                data={
                    "tool": tool_name,
                    "id": tool_id,
                    "context": context,
                },
            ))

    return events


def _parse_system_entry(entry: dict) -> list[Event]:
    """Parse system entries (api_error → retry, etc.)."""
    events = []
    subtype = entry.get("subtype", "")
    level = entry.get("level", "")

    if subtype == "api_error":
        error = entry.get("error", {})
        status = error.get("status", 0) if isinstance(error, dict) else 0
        events.append(Event(
            EventType.RETRY,
            source=EventSource.CLAUDE_LOG,
            data={"subtype": subtype, "status": status},
        ))
    elif level == "error":
        events.append(Event(
            EventType.ERROR,
            source=EventSource.CLAUDE_LOG,
            data={"subtype": subtype},
        ))

    return events


class ClaudeLogWatcher:
    """Tails the active Claude Code JSONL transcript and emits parsed events."""

    def __init__(self, log_path: Path | str | None = None):
        self._log_path: Path | None = Path(log_path) if log_path else None
        self._position: int = 0
        self._running: bool = False
        self._last_check_path_time: float = 0.0

    async def start(self) -> None:
        """Initialize watcher, seek to end of current log."""
        if self._log_path is None:
            self._log_path = find_latest_log()
        if self._log_path and self._log_path.exists():
            self._position = self._log_path.stat().st_size
        self._running = True

    def stop(self) -> None:
        self._running = False

    async def poll(self) -> list[Event]:
        """Poll for new log entries. Non-blocking, returns events found."""
        if not self._running:
            return []

        # Periodically re-check for newer log files (session switch)
        now = time.monotonic()
        if now - self._last_check_path_time > 10.0:
            self._last_check_path_time = now
            newer = find_latest_log()
            if newer and newer != self._log_path:
                self._log_path = newer
                self._position = 0

        if self._log_path is None or not self._log_path.exists():
            return []

        try:
            current_size = self._log_path.stat().st_size
        except OSError:
            return []

        if current_size <= self._position:
            return []

        events = []
        try:
            with open(self._log_path, "r") as f:
                f.seek(self._position)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        events.extend(parse_log_entry(entry))
                    except json.JSONDecodeError:
                        continue
                self._position = f.tell()
        except OSError:
            pass

        return events

    @property
    def active_log(self) -> Path | None:
        return self._log_path
