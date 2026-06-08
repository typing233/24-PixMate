"""JSONL event logging for replay and debugging."""

import json
import time
from pathlib import Path
from typing import TextIO

from .events import Event, EventType


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
            "data": {k: v for k, v in event.data.items() if isinstance(v, (str, int, float, bool))},
            "state_before": state_before,
            "state_after": state_after,
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
            if line:
                entries.append(json.loads(line))
    return entries
