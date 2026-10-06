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


class SlackDispatchPolicy:
    """Minimum Slack: Prioritizes jobs with minimum remaining time buffer until due date."""

    @property
    def name(self) -> str:
        return "SLACK"

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

        def slack_key(item: tuple[Job, Operation]) -> tuple[float, float, str]:
            j, _op = item
            rem_proc = sum(o.nominal_cycle_minutes for o in j.operations)
            slack = j.due_date - context.current_time - rem_proc
            return (slack, j.due_date, j.job_id)

        eligible.sort(key=slack_key)
        return eligible[0]


class ATCDispatchPolicy:
    """Apparent Tardiness Cost (ATC): Dynamic composite dispatching rule with lookahead."""

    def __init__(self, k_lookahead: float = 2.0) -> None:
        self.k_lookahead = k_lookahead

    @property
    def name(self) -> str:
        return "ATC"

    def select_next_job(self, context: DispatchContext) -> tuple[Job, Operation] | None:
        import math

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

        # Compute average processing time p_bar of eligible operations
        p_bar = sum(op.nominal_cycle_minutes for _, op in eligible) / len(eligible)
        p_bar = max(0.1, p_bar)

        def atc_index(item: tuple[Job, Operation]) -> float:
            j, op = item
            p_j = max(0.1, op.nominal_cycle_minutes)
            w_j = float(j.priority)
            slack = max(0.0, j.due_date - p_j - context.current_time)
            exp_term = math.exp(-slack / (self.k_lookahead * p_bar))
            return (w_j / p_j) * exp_term

        # Maximize ATC index (sort descending)
        eligible.sort(key=lambda item: (-atc_index(item), item[0].job_id))
        return eligible[0]


class ScheduleDispatchPolicy:
    """Pre-computed deterministic schedule dispatch adapter (e.g. from CP-SAT optimizer)."""

    def __init__(self, machine_job_sequences: Mapping[str, Sequence[str]]) -> None:
        # machine_id -> list of job_ids in execution order
        self._sequences: dict[str, list[str]] = {
            m: list(seq) for m, seq in machine_job_sequences.items()
        }

    @property
    def name(self) -> str:
        return "SCHEDULE"

    def select_next_job(self, context: DispatchContext) -> tuple[Job, Operation] | None:
        m_id = context.machine.machine_id
        target_seq = self._sequences.get(m_id, [])

        job_map = {
            j.job_id: j
            for j in context.available_jobs
            if j.job_id not in context.in_progress_job_ids
            and j.release_time <= context.current_time
            and j.operations
            and context.machine.machine_type in j.operations[0].allowed_machine_types
        }

        # Pick the first available job that matches the planned schedule sequence
        for j_id in list(target_seq):
            if j_id in job_map:
                target_seq.remove(j_id)
                target_job = job_map[j_id]
                return (target_job, target_job.operations[0])

        # Fallback to FIFO if pre-computed list empty or completed
        fallback_eligible = [
            (j, j.operations[0])
            for j in context.available_jobs
            if j.job_id not in context.in_progress_job_ids
            and j.release_time <= context.current_time
            and j.operations
            and context.machine.machine_type in j.operations[0].allowed_machine_types
        ]
        if fallback_eligible:
            fallback_eligible.sort(key=lambda item: (item[0].release_time, item[0].job_id))
            return fallback_eligible[0]

        return None
