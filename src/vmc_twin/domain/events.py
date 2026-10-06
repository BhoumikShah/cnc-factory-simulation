from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from vmc_twin.domain.states import CauseCode, SpindleState


@dataclass(frozen=True, slots=True)
class Event:
    """
    Immutable discrete event contract emitted by the simulation engine.
    Every KPI, Gantt timeline, and expert rule fact can be reconstructed from this record.
    """
    t_start: float
    t_end: float
    machine_id: str
    job_id: str | None
    op_id: str | None
    state: SpindleState
    cause_code: CauseCode = CauseCode.NONE
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def duration(self) -> float:
        """Returns the duration of the state event in minutes."""
        return self.t_end - self.t_start

    def is_cutting(self) -> bool:
        return self.state == SpindleState.CUTTING

    def is_setup(self) -> bool:
        return self.state == SpindleState.SETUP

    def is_idle(self) -> bool:
        return self.state in {
            SpindleState.IDLE_STARVED,
            SpindleState.IDLE_WAIT_SETUP,
            SpindleState.IDLE_WAIT_TOOL,
            SpindleState.IDLE_WAIT_OPERATOR,
            SpindleState.IDLE_WAIT_FIXTURE,
        }

    def is_down(self) -> bool:
        return self.state in {SpindleState.BREAKDOWN, SpindleState.PLANNED_MAINT}
