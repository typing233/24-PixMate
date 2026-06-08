"""JSONL event logging for replay and debugging.

Captures events from both PTY stream and Claude Code log reader,
recording the source so replay can distinguish heuristic PTY events
from structured log events.
"""

import json
import time
from pathlib import Path
from typing import TextIO

from .events import Event, EventType, EventSource


class EventLog:
    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO = open(self._path, "a")
        self._start = time.monotonic()

    def record(self, event: Event, state_before: str = "", state_after: str = "") -> None:
        entry = {
            "t": round(time.monotonic() - self._start, 4),
            "type": event.type.value,
            "source": event.source.value,
            "data": {k: v for k, v in event.data.items()
                     if isinstance(v, (str, int, float, bool))},
            "state_before": state_before,
            "state_after": state_after,
        }
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()

    def record_raw(self, data: bytes, direction: str) -> None:
        """Record raw PTY data for full-fidelity replay."""
        entry = {
            "t": round(time.monotonic() - self._start, 4),
            "type": "_raw",
            "direction": direction,
            "size": len(data),
            "hex": data[:256].hex(),
        }
        self._file.write(json.dumps(entry) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def load_event_log(path: Path | str) -> list[dict]:
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                # Skip raw PTY dumps in normal replay (they're for debugging)
                if entry.get("type") != "_raw":
                    entries.append(entry)
            except json.JSONDecodeError:
                continue
    return entries


def load_raw_log(path: Path | str) -> list[dict]:
    """Load all entries including raw PTY data (for full debug replay)."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries
