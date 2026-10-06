from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from vmc_twin.domain.job import Job
from vmc_twin.domain.machine import Machine
from vmc_twin.domain.operation import Operation


@dataclass(frozen=True, slots=True)
class DispatchContext:
    """Current shop floor state presented to dispatch policies."""

    current_time: float
    machine: Machine
    available_jobs: Sequence[Job]
    active_fixtures: Mapping[str, str]
    tool_magazine: Sequence[str]
    in_progress_job_ids: frozenset[str] = frozenset()


@runtime_checkable
class DispatchPolicy(Protocol):
    """Protocol for dynamic job dispatching and sequencing rules."""

    @property
    def name(self) -> str: ...

    def select_next_job(self, context: DispatchContext) -> tuple[Job, Operation] | None:
        """Select next (Job, Operation) to process on the requesting machine."""
        ...


class FIFODispatchPolicy:
    """First-In First-Out: Prioritizes jobs with the earliest release time."""

    @property
    def name(self) -> str:
        return "FIFO"

    def select_next_job(self, context: DispatchContext) -> tuple[Job, Operation] | None:
        eligible: list[tuple[Job, Operation]] = []
        for job in context.available_jobs:
            if job.job_id in context.in_progress_job_ids:
                continue
            if job.release_time > context.current_time:
                continue
            if not job.operations:
                continue
            next_op = job.operations[0]
            if context.machine.machine_type in next_op.allowed_machine_types:
                eligible.append((job, next_op))

        if not eligible:
            return None

        # Sort by release_time, then job_id for strict determinism
        eligible.sort(key=lambda item: (item[0].release_time, item[0].job_id))
        return eligible[0]


class EDDDispatchPolicy:
    """Earliest Due Date: Prioritizes jobs with the most urgent deadline."""

    @property
    def name(self) -> str:
        return "EDD"

    def select_next_job(self, context: DispatchContext) -> tuple[Job, Operation] | None:
        eligible: list[tuple[Job, Operation]] = []
        for job in context.available_jobs:
            if job.job_id in context.in_progress_job_ids:
                continue
            if job.release_time > context.current_time:
                continue
            if not job.operations:
                continue
            next_op = job.operations[0]
            if context.machine.machine_type in next_op.allowed_machine_types:
                eligible.append((job, next_op))

        if not eligible:
            return None

        # Sort by due_date, then priority descending, then job_id
        eligible.sort(key=lambda item: (item[0].due_date, -item[0].priority, item[0].job_id))
        return eligible[0]


class SPTDispatchPolicy:
    """Shortest Processing Time: Prioritizes operations with the shortest cycle time."""

    @property
    def name(self) -> str:
        return "SPT"

    def select_next_job(self, context: DispatchContext) -> tuple[Job, Operation] | None:
        eligible: list[tuple[Job, Operation]] = []
        for job in context.available_jobs:
            if job.job_id in context.in_progress_job_ids:
                continue
            if job.release_time > context.current_time:
                continue
            if not job.operations:
                continue
            next_op = job.operations[0]
            if context.machine.machine_type in next_op.allowed_machine_types:
                eligible.append((job, next_op))

        if not eligible:
            return None

        eligible.sort(
            key=lambda item: (item[1].nominal_cycle_minutes, item[0].due_date, item[0].job_id)
        )
        return eligible[0]
