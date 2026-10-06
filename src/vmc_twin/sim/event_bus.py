from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from vmc_twin.data.store import EventStore
from vmc_twin.domain.events import Event


@runtime_checkable
class EventSink(Protocol):
    """Protocol for discrete simulation event consumers."""

    def on_event(self, event: Event) -> None:
        """Process an immutable simulation event."""
        ...

    def flush(self) -> None:
        """Flush any pending buffered events."""
        ...


class InMemoryEventSink:
    """Stores all emitted events in an in-memory list."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def on_event(self, event: Event) -> None:
        self.events.append(event)

    def flush(self) -> None:
        pass


class StoreEventSink:
    """Persists emitted events to an EventStore (SQLite/DuckDB)."""

    def __init__(self, store: EventStore, batch_size: int = 500) -> None:
        self.store = store
        self.batch_size = batch_size
        self._buffer: list[Event] = []

    def on_event(self, event: Event) -> None:
        self._buffer.append(event)
        if len(self._buffer) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if self._buffer:
            self.store.insert_events(self._buffer)
            self._buffer.clear()


class BroadcastEventSink:
    """Dispatches events to multiple registered sinks."""

    def __init__(self, sinks: Sequence[EventSink]) -> None:
        self.sinks = list(sinks)

    def on_event(self, event: Event) -> None:
        for sink in self.sinks:
            sink.on_event(event)

    def flush(self) -> None:
        for sink in self.sinks:
            sink.flush()
