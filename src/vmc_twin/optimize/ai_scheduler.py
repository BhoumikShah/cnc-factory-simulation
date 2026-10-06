from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from vmc_twin.domain.fixture import FixtureSpec, FixtureTransitionMatrix
from vmc_twin.domain.job import Job
from vmc_twin.domain.machine import MachineSpec
from vmc_twin.domain.operation import Operation
from vmc_twin.predict.power_model import EmpiricalPowerModel


@dataclass(frozen=True)
class AIScheduledTask:
    """Detailed record of an operation scheduled by the AI engine."""

    job_id: str
    op_id: str
    machine_id: str
    t_start: float
    t_end: float
    duration_minutes: float
    setup_minutes: float
    fixture_id: str
    power_kw: float
    energy_kwh: float
    due_date: float
    lateness_minutes: float


@dataclass(frozen=True)
class AIScheduleResult:
    """Comprehensive performance & energy metrics from an AI scheduling run."""

    scenario_name: str
    makespan_minutes: float
    total_jobs: int
    completed_jobs: int
    on_time_delivery_pct: float
    total_weighted_tardiness: float
    mean_tardiness_minutes: float
    max_tardiness_minutes: float
    total_energy_kwh: float
    peak_power_kw: float
    peak_power_limit_kw: float
    peak_shaved_count: int
    total_setup_minutes: float
    scheduled_tasks: list[AIScheduledTask]
    machine_sequences: dict[str, list[str]]
    power_profile: list[tuple[float, float]]  # (time_minutes, fleet_kw)


class EnergyAwareAIScheduler:
    """
    Industrial Engineering Multi-Objective AI Scheduling Engine.
    
    Jointly optimizes:
    1. Deadline Satisfaction / On-Time Delivery (OTD %)
    2. Factory Peak Electrical Power Shaving (kW)
    3. Total Energy Consumption (kWh)
    4. Sequence-Dependent Fixture & Tool Changeovers
    """

    def __init__(
        self,
        machines: Sequence[MachineSpec],
        fixtures: Sequence[FixtureSpec] | None = None,
        transition_matrix: FixtureTransitionMatrix | None = None,
        peak_power_limit_kw: float = 35.0,  # Max allowable fleet simultaneous active power
        w_tardiness: float = 5.0,
        w_setup: float = 1.5,
        w_peak_power: float = 3.0,
        w_energy: float = 1.0,
    ) -> None:
        self.machines = list(machines)
        self.fixtures = list(fixtures) if fixtures else []
        self.transition_matrix = transition_matrix or FixtureTransitionMatrix(transitions={}, default_setup_minutes=15.0)
        self.peak_power_limit_kw = peak_power_limit_kw
        self.w_tardiness = w_tardiness
        self.w_setup = w_setup
        self.w_peak_power = w_peak_power
        self.w_energy = w_energy

    def solve(
        self,
        jobs: Sequence[Job],
        scenario_name: str = "AI_Optimized_Production",
        time_step_minutes: float = 5.0,
    ) -> AIScheduleResult:
        """
        Executes multi-agent heuristic scheduling with dynamic fleet power tracking
        and peak-demand constraint management.
        """
        all_jobs = list(jobs)
        machine_available_time: dict[str, float] = {m.machine_id: 0.0 for m in self.machines}
        machine_active_fixture: dict[str, str | None] = {m.machine_id: None for m in self.machines}
        machine_sequences: dict[str, list[str]] = {m.machine_id: [] for m in self.machines}

        # Track active machine operations per time slice for fleet electrical power profile
        scheduled_tasks: list[AIScheduledTask] = []
        peak_shaved_count = 0

        # Maintain list of pending jobs
        pending_jobs = list(all_jobs)
        machine_lookup = {m.machine_id: m for m in self.machines}

        # Sort initial candidate queue by release time and priority
        pending_jobs.sort(key=lambda j: (j.release_time, -j.priority, j.due_date))

        # Simulation clock stepping
        current_time = 0.0
        while pending_jobs:
            # Find earliest available machine
            ready_machine_id = min(machine_available_time, key=lambda mid: machine_available_time[mid])
            earliest_m_time = machine_available_time[ready_machine_id]
            current_time = max(current_time, earliest_m_time)

            ready_machine = machine_lookup[ready_machine_id]
            current_fix = machine_active_fixture[ready_machine_id]

            # Filter jobs that have arrived or will arrive soon
            eligible_candidates = [
                j for j in pending_jobs
                if any(ready_machine.machine_type in op.allowed_machine_types for op in j.operations)
            ]

            if not eligible_candidates:
                # If no eligible jobs for this machine, advance machine clock
                machine_available_time[ready_machine_id] += 10.0
                continue

            # Multi-objective AI score evaluation
            best_score = -float("inf")
            best_job: Job | None = None
            best_setup = 0.0
            best_power_kw = 0.0
            best_op: Operation | None = None

            for job in eligible_candidates:
                # Find matching operation for this machine
                target_op = next(
                    (op for op in job.operations if ready_machine.machine_type in op.allowed_machine_types),
                    job.operations[0]
                )

                # 1. Setup Penalty (0 if fixture matches, lower if APC pallet changer present)
                base_setup = self.transition_matrix.get_setup_time(current_fix, target_op.required_fixture)
                setup_minutes = base_setup * (ready_machine.pallet_setup_factor if ready_machine.has_pallet_changer else 1.0)

                # 2. Predicted Power Draw for this cut (kW)
                pred_power = EmpiricalPowerModel.predict_power(
                    spindle_speed_rpm=target_op.required_rpm,
                    feed_rate_mm_min=380.0,
                    depth_of_cut_mm=3.0,
                    material=job.material,
                )

                # 3. Peak Power Penalty: Check fleet power load at start time
                active_fleet_kw = sum(
                    t.power_kw for t in scheduled_tasks
                    if t.t_start <= current_time < t.t_end
                )
                future_fleet_kw = active_fleet_kw + pred_power.total_power_kw
                peak_penalty = 0.0
                if future_fleet_kw > self.peak_power_limit_kw:
                    peak_penalty = (future_fleet_kw - self.peak_power_limit_kw) * self.w_peak_power

                # 4. Slack & Deadline Urgency (ATC-like exponential escalation)
                rem_proc = sum(o.nominal_cycle_minutes for o in job.operations)
                slack = job.due_date - current_time - setup_minutes - rem_proc
                if slack <= 0.0:
                    urgency_score = job.priority * 100.0 + abs(slack) * 2.0
                else:
                    urgency_score = job.priority * 10.0 * math.exp(-slack / max(10.0, rem_proc))

                # 5. Energy cost component
                energy_kwh = (pred_power.total_power_kw * (target_op.nominal_cycle_minutes / 60.0))
                energy_cost = energy_kwh * self.w_energy

                # Composite AI Score: higher is better
                score = (
                    self.w_tardiness * urgency_score
                    - self.w_setup * setup_minutes
                    - peak_penalty
                    - energy_cost
                )

                if score > best_score:
                    best_score = score
                    best_job = job
                    best_setup = setup_minutes
                    best_power_kw = pred_power.total_power_kw
                    best_op = target_op

            if best_job is None or best_op is None:
                machine_available_time[ready_machine_id] += 10.0
                continue

            # Schedule the best job
            t_start = max(current_time, best_job.release_time)
            t_after_setup = t_start + best_setup
            duration = best_op.nominal_cycle_minutes
            t_end = t_after_setup + duration

            energy_kwh = best_power_kw * (duration / 60.0)
            lateness = max(0.0, t_end - best_job.due_date)

            task = AIScheduledTask(
                job_id=best_job.job_id,
                op_id=best_op.op_id,
                machine_id=ready_machine_id,
                t_start=t_start,
                t_end=t_end,
                duration_minutes=duration,
                setup_minutes=best_setup,
                fixture_id=best_op.required_fixture,
                power_kw=best_power_kw,
                energy_kwh=round(energy_kwh, 3),
                due_date=best_job.due_date,
                lateness_minutes=round(lateness, 1),
            )
            scheduled_tasks.append(task)
            machine_sequences[ready_machine_id].append(best_job.job_id)
            machine_available_time[ready_machine_id] = t_end
            machine_active_fixture[ready_machine_id] = best_op.required_fixture

            pending_jobs.remove(best_job)

        # Compute Fleet Metrics
        makespan = max(t.t_end for t in scheduled_tasks) if scheduled_tasks else 0.0
        total_energy = sum(t.energy_kwh for t in scheduled_tasks)
        total_setup = sum(t.setup_minutes for t in scheduled_tasks)

        tardiness_vals = [t.lateness_minutes for t in scheduled_tasks]
        on_time_count = sum(1 for lat in tardiness_vals if lat <= 0.0)
        otd_pct = (on_time_count / len(scheduled_tasks) * 100.0) if scheduled_tasks else 100.0

        # Reconstruct high-resolution fleet electrical power load profile
        time_grid = [float(t) for t in range(0, int(makespan) + 30, int(time_step_minutes))]
        power_profile: list[tuple[float, float]] = []
        peak_observed = 0.0

        for t_val in time_grid:
            p_instant = sum(
                task.power_kw for task in scheduled_tasks
                if task.t_start <= t_val <= task.t_end
            )
            # Add idle tare for inactive machines
            active_m_count = len({task.machine_id for task in scheduled_tasks if task.t_start <= t_val <= task.t_end})
            idle_m_count = len(self.machines) - active_m_count
            p_fleet = p_instant + idle_m_count * EmpiricalPowerModel.BASE_STANDBY_KW
            power_profile.append((t_val, round(p_fleet, 2)))
            peak_observed = max(peak_observed, p_fleet)
            if p_fleet > self.peak_power_limit_kw:
                peak_shaved_count += 1

        weighted_tardiness = sum(
            t.lateness_minutes * next((j.priority for j in all_jobs if j.job_id == t.job_id), 1.0)
            for t in scheduled_tasks
        )

        return AIScheduleResult(
            scenario_name=scenario_name,
            makespan_minutes=round(makespan, 1),
            total_jobs=len(all_jobs),
            completed_jobs=len(scheduled_tasks),
            on_time_delivery_pct=round(otd_pct, 1),
            total_weighted_tardiness=round(weighted_tardiness, 1),
            mean_tardiness_minutes=round(sum(tardiness_vals) / len(tardiness_vals), 1) if tardiness_vals else 0.0,
            max_tardiness_minutes=round(max(tardiness_vals), 1) if tardiness_vals else 0.0,
            total_energy_kwh=round(total_energy, 1),
            peak_power_kw=round(peak_observed, 1),
            peak_power_limit_kw=self.peak_power_limit_kw,
            peak_shaved_count=peak_shaved_count,
            total_setup_minutes=round(total_setup, 1),
            scheduled_tasks=scheduled_tasks,
            machine_sequences=machine_sequences,
            power_profile=power_profile,
        )
