# ADR 0002: Immutable Event Log as Primary System Contract

## Status
Accepted

## Context
Downstream analytical systems (KPI engines, Plotly Gantt charts, fact generators, explainable rule engines) require a complete, reproducible history of simulation executions. Modifying in-memory state or writing unstructured log messages prevents reliable verification.

## Decision
All simulation transitions emit an immutable `Event` object:
```python
@dataclass(frozen=True, slots=True)
class Event:
    t_start: float
    t_end: float
    machine_id: str
    job_id: str | None
    op_id: str | None
    state: SpindleState
    cause_code: CauseCode = CauseCode.NONE
    metadata: Mapping[str, Any] = field(default_factory=dict)
```
Events are dispatched to `EventSink` implementations (in-memory list, DuckDB streaming logger, Parquet writer).

## Consequences
- **Positive**: Complete auditability. Every KPI, Gantt bar, and rule fact can be reconstructed purely from the ordered Event stream.
- **Positive**: Temporal invariants (monotonicity, zero state overlaps) can be tested deterministically with property-based testing.
- **Trade-off**: Requires memory-efficient representation (`slots=True`, frozen) to handle millions of events efficiently.
