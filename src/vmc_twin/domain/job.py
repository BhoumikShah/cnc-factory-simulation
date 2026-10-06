from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vmc_twin.domain.operation import Operation


@dataclass(frozen=True, slots=True)
class Job:
    """Production work order consisting of sequential machining operations."""

    job_id: str
    part_name: str
    material: str
    priority: int  # 1 (low) to 5 (urgent)
    release_time: float  # arrival time in shop (minutes)
    due_date: float  # delivery deadline (minutes)
    operations: Sequence[Operation]
    quantity: int = 1
    weight_tardiness_penalty: float = 1.0

    def total_nominal_processing_time(self) -> float:
        """Sum of nominal operation cycle times."""
        return sum(op.nominal_cycle_minutes for op in self.operations)
