"""Claude Code log stream reader.

Parses Claude Code's real session logs (JSONL) to emit structured events.
Claude Code writes conversation transcripts to:
  ~/.claude/projects/<project-hash>/logs/<session-id>.jsonl

Each line is a JSON object representing a message turn with role, content,
tool_use blocks, etc. This module tails the active log file and maps entries
to PixMate events — giving richer signal than PTY heuristics alone.
"""

import asyncio
import glob
import json
import os
import time
from pathlib import Path
from typing import AsyncGenerator

from .events import Event, EventType, EventSource


def find_claude_log_dir() -> Path | None:
    """Find the most recently active Claude Code log directory."""
    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        return None

    # Find subdirs, pick the one with the most recent log file
    best_dir = None
    best_mtime = 0.0

    for project_dir in base.iterdir():
        if not project_dir.is_dir():
            continue
        # Claude Code stores conversation in the project dir directly
        # or under a sessions/ subdirectory depending on version
        for candidate in [project_dir, project_dir / "sessions"]:
            if not candidate.exists():
                continue
            for f in candidate.glob("*.jsonl"):
                mt = f.stat().st_mtime
                if mt > best_mtime:
                    best_mtime = mt
                    best_dir = candidate

    return best_dir


def find_latest_log(log_dir: Path | None = None) -> Path | None:
    """Find the most recent .jsonl log file in the given or auto-detected dir."""
    if log_dir is None:
        log_dir = find_claude_log_dir()
    if log_dir is None or not log_dir.exists():
        return None

    candidates = sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def parse_log_entry(entry: dict) -> list[Event]:
    """Parse a single Claude Code log entry into PixMate events."""
    events = []

    msg_type = entry.get("type", "")
    role = entry.get("role", "")
    content = entry.get("content", "")

    # Handle different log entry formats
    if msg_type == "human" or role == "human" or role == "user":
        events.append(Event(
            EventType.USER_INPUT,
            source=EventSource.CLAUDE_LOG,
            data={"text": _extract_text(content)[:80]},
        ))

    elif msg_type == "assistant" or role == "assistant":
        # Check for tool use in content blocks
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type == "tool_use":
                        tool_name = block.get("name", "unknown")
                        events.append(Event(
                            EventType.TOOL_START,
                            source=EventSource.CLAUDE_LOG,
                            data={"tool": tool_name},
                        ))
                    elif block_type == "thinking":
                        events.append(Event(
                            EventType.THINKING_START,
                            source=EventSource.CLAUDE_LOG,
                        ))
                    elif block_type == "text":
                        text = block.get("text", "")
                        if text and not events:
                            events.append(Event(
                                EventType.STREAM_START,
                                source=EventSource.CLAUDE_LOG,
                                data={"text": text[:60]},
                            ))
        elif isinstance(content, str) and content:
            events.append(Event(
                EventType.STREAM_START,
                source=EventSource.CLAUDE_LOG,
                data={"text": content[:60]},
            ))

    elif msg_type == "tool_result" or role == "tool":
        is_error = entry.get("is_error", False)
        if is_error:
            events.append(Event(
                EventType.ERROR,
                source=EventSource.CLAUDE_LOG,
                data={"text": _extract_text(content)[:100]},
            ))
        else:
            events.append(Event(
                EventType.TOOL_END,
                source=EventSource.CLAUDE_LOG,
                data={"tool": entry.get("name", "")},
            ))

    elif msg_type == "permission_request":
        events.append(Event(
            EventType.PERMISSION_PROMPT,
            source=EventSource.CLAUDE_LOG,
            data={"tool": entry.get("tool", "")},
        ))

    elif msg_type == "permission_response":
        accepted = entry.get("accepted", entry.get("allowed", False))
        events.append(Event(
            EventType.PERMISSION_RESPONSE,
            source=EventSource.CLAUDE_LOG,
            data={"accepted": accepted},
        ))

    elif msg_type == "retry" or "retry" in str(entry.get("error", "")):
        events.append(Event(
            EventType.RETRY,
            source=EventSource.CLAUDE_LOG,
            data={"reason": entry.get("error", "")},
        ))

    elif msg_type == "resume" or msg_type == "session_start":
        events.append(Event(
            EventType.SESSION_RESUME,
            source=EventSource.CLAUDE_LOG,
        ))

    return events


def _extract_text(content) -> str:
    """Extract plain text from various content formats."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return str(content)


class ClaudeLogWatcher:
    """Tails the active Claude Code log file and emits parsed events."""

    def __init__(self, log_path: Path | None = None):
        self._log_path = log_path
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
