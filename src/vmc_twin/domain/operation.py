from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ToolRequirement:
    """Tool specification and estimated cut minutes for an operation."""
    tool_type: str
    cut_minutes: float
    wear_factor: float = 1.0


@dataclass(frozen=True, slots=True)
class Operation:
    """Single discrete machining operation belonging to a Job routing."""
    op_id: str
    job_id: str
    sequence_num: int
    name: str
    allowed_machine_types: Sequence[str]
    required_fixture: str
    nominal_cycle_minutes: float
    cycle_time_cv: float = 0.05  # coefficient of variation for lognormal duration
    required_power_kw: float = 7.5
    required_rpm: float = 8000.0
    tool_requirements: Sequence[ToolRequirement] = field(default_factory=list)
    base_manual_setup_minutes: float = 10.0
