from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, Iterable, List, Optional


@dataclass
class Observation:
    timestamp: datetime
    text: str
    metadata: Dict[str, str]

    def serialize(self) -> str:
        meta = ", ".join(f"{k}={v}" for k, v in self.metadata.items() if v)
        return f"[{self.timestamp.strftime('%H:%M:%S')}] {meta} | {self.text}".strip()


class ContextWindow:
    def __init__(self, max_items: int = 10) -> None:
        self.max_items = max_items
        self._buffer: Deque[Observation] = deque(maxlen=max_items)

    def add(self, text: str, **metadata: Optional[str]) -> None:
        meta = {k: v for k, v in metadata.items() if v}
        self._buffer.append(
            Observation(timestamp=datetime.utcnow(), text=text.strip(), metadata=meta)
        )

    def as_prompt(self) -> str:
        if not self._buffer:
            return ""
        serialized = [obs.serialize() for obs in self._buffer]
        return "\n".join(serialized)

    def tail(self, n: int = 3) -> Iterable[Observation]:
        return list(self._buffer)[-n:]

    def clear(self) -> None:
        self._buffer.clear()
