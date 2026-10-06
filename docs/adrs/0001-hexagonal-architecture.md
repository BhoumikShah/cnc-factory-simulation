# ADR 0001: Hexagonal Architecture and Layer Isolation

## Status
Accepted

## Context
A digital twin shop floor simulator connects diverse subsystems: discrete-event simulation, explainable expert system rules, constraint-programming schedulers, ML prognostics, and interactive visualization. Direct coupling between these components quickly leads to circular imports, fragile testing, and tight lock-in to simulation frameworks.

## Decision
We adopt a 4-layer Hexagonal Architecture:
1. `domain/` contains pure Python 3.12 dataclasses and enums with zero external dependencies.
2. `sim/`, `rules/`, `optimize/`, `predict/`, `report/` depend solely on `domain/` and never on each other.
3. Subsystems interact exclusively via domain value objects and the immutable `Event` log.
4. Layer isolation is enforced via automated import boundary tests in `tests/architecture/test_layers.py`.

## Consequences
- **Positive**: Subsystems can be tested in complete isolation without running a SimPy environment.
- **Positive**: Swapping SimPy for another engine or extending rule libraries requires zero changes to the domain or optimization models.
- **Trade-off**: Requires explicit adapters (e.g. `ScheduleDispatchPolicy`) to bridge optimizer outputs back to simulation dispatchers.
