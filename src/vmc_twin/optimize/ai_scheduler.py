from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

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
    1. Maximum On-Time Delivery (OTD %) under hard customer due dates
    2. Multi-stage operation precedence routing ($O_{j, k} \\to O_{j, k+1}$)
    3. Factory Peak Electrical Power Shaving ($P_{\\text{fleet}}(t) \\le P_{\\text{limit}}$)
    4. Sequence-Dependent Fixture Setups & APC Pallet Optimization
    5. Real-World Machine Specialization Line Balancing
    """

    def __init__(
        self,
        machines: Sequence[MachineSpec],
        fixtures: Sequence[FixtureSpec] | None = None,
        transition_matrix: FixtureTransitionMatrix | None = None,
        peak_power_limit_kw: float = 35.0,
        w_tardiness: float = 10.0,
        w_setup: float = 2.0,
        w_peak_power: float = 4.0,
        w_energy: float = 1.0,
        transfer_time_minutes: float = 2.0,
    ) -> None:
        self.machines = list(machines)
        self.fixtures = list(fixtures) if fixtures else []
        self.transition_matrix = transition_matrix or FixtureTransitionMatrix(
            transitions={}, default_setup_minutes=15.0
        )
        self.peak_power_limit_kw = peak_power_limit_kw
        self.w_tardiness = w_tardiness
        self.w_setup = w_setup
        self.w_peak_power = w_peak_power
        self.w_energy = w_energy
        self.transfer_time_minutes = transfer_time_minutes

    def solve(
        self,
        jobs: Sequence[Job],
        scenario_name: str = "AI_Optimized_Production",
        time_step_minutes: float = 5.0,
    ) -> AIScheduleResult:
        """
        Executes multi-stage, precedence-constrained AI dispatching with dynamic
        fleet load shaving and maximum OTD optimization.
        """
        all_jobs = list(jobs)
        machine_lookup = {m.machine_id: m for m in self.machines}
        machine_available_time: dict[str, float] = {m.machine_id: 0.0 for m in self.machines}
        machine_active_fixture: dict[str, str | None] = {m.machine_id: None for m in self.machines}
        machine_sequences: dict[str, list[str]] = {m.machine_id: [] for m in self.machines}

        # Multi-stage routing tracking for each job
        job_next_op_idx: dict[str, int] = {j.job_id: 0 for j in all_jobs}
        job_ready_time: dict[str, float] = {j.job_id: j.release_time for j in all_jobs}
        job_completion_time: dict[str, float] = {}

        scheduled_tasks: list[AIScheduledTask] = []
        last_machine_task: dict[str, AIScheduledTask] = {}
        peak_shaved_count = 0

        # === PERFORMANCE: Pre-build machine compatibility index ===
        # Maps machine_id -> set of job_ids whose current op is compatible
        # This avoids scanning ALL jobs on every dispatch step.
        machine_type_to_id: dict[str, list[str]] = {}
        for m in self.machines:
            machine_type_to_id.setdefault(m.machine_type, []).append(m.machine_id)

        pending_job_ids: set[str] = {j.job_id for j in all_jobs}
        job_lookup: dict[str, Job] = {j.job_id: j for j in all_jobs}

        # === PERFORMANCE: Cache predict_power results ===
        # Key: (required_rpm, material) -> PowerPrediction
        _power_cache: dict[tuple[float, str], float] = {}

        def _cached_power_kw(rpm: float, material: str) -> float:
            key = (rpm, material)
            cached = _power_cache.get(key)
            if cached is not None:
                return cached
            pred = EmpiricalPowerModel.predict_power(
                spindle_speed_rpm=rpm,
                feed_rate_mm_min=380.0,
                depth_of_cut_mm=3.0,
                material=material,
            )
            _power_cache[key] = pred.total_power_kw
            return pred.total_power_kw

        # === PERFORMANCE: Pre-compute downstream work per job ===
        # downstream_work[job_id][op_idx] = remaining processing + est. setups after op_idx
        downstream_work: dict[str, list[float]] = {}
        for j in all_jobs:
            n_ops = len(j.operations)
            dw = [0.0] * (n_ops + 1)  # dw[n_ops] = 0.0 (nothing after last)
            for k in range(n_ops - 1, -1, -1):
                dw[k] = j.operations[k].nominal_cycle_minutes + 8.0 + dw[k + 1]
            downstream_work[j.job_id] = dw

        # Calculate average cycle time for normalization
        all_op_durations = [op.nominal_cycle_minutes for j in all_jobs for op in j.operations]
        avg_cycle_time = sum(all_op_durations) / max(1, len(all_op_durations))

        # Pre-compute allowed machine set for each operation
        # allowed_set[job_id] = list of sets, one per operation
        allowed_sets: dict[str, list[frozenset[str]]] = {}
        for j in all_jobs:
            sets = []
            for op in j.operations:
                s = frozenset(op.allowed_machine_types)
                sets.append(s)
            allowed_sets[j.job_id] = sets

        # Loop until all operations of all jobs are completed
        total_operations = sum(len(j.operations) for j in all_jobs)

        while len(scheduled_tasks) < total_operations:
            # 1. Identify machines ready earliest
            ready_machine_id = min(
                machine_available_time, key=lambda mid: machine_available_time[mid]
            )
            m_time = machine_available_time[ready_machine_id]
            if m_time == float("inf"):
                break

            machine = machine_lookup[ready_machine_id]
            curr_fixture = machine_active_fixture[ready_machine_id]

            # 2. Identify candidates — only scan pending jobs
            eligible_candidates: list[tuple[Job, Operation, int]] = []
            for jid in pending_job_ids:
                j = job_lookup[jid]
                op_idx = job_next_op_idx[jid]
                if op_idx < len(j.operations):
                    aset = allowed_sets[jid][op_idx]
                    if (
                        machine.machine_type in aset
                        or machine.machine_id in aset
                        or "ANY" in aset
                    ):
                        eligible_candidates.append((j, j.operations[op_idx], op_idx))

            if not eligible_candidates:
                # Check if machine can ever run any remaining operation
                has_future = False
                for jid in pending_job_ids:
                    j = job_lookup[jid]
                    for idx in range(job_next_op_idx[jid], len(j.operations)):
                        aset = allowed_sets[jid][idx]
                        if (
                            machine.machine_type in aset
                            or machine.machine_id in aset
                            or "ANY" in aset
                        ):
                            has_future = True
                            break
                    if has_future:
                        break

                if not has_future:
                    machine_available_time[ready_machine_id] = float("inf")
                    if min(machine_available_time.values()) == float("inf"):
                        break
                    continue

                future_ready = []
                for jid in pending_job_ids:
                    j = job_lookup[jid]
                    oi = job_next_op_idx[jid]
                    if oi < len(j.operations):
                        aset = allowed_sets[jid][oi]
                        if (
                            machine.machine_type in aset
                            or machine.machine_id in aset
                            or "ANY" in aset
                        ):
                            future_ready.append(job_ready_time[jid])
                if future_ready:
                    machine_available_time[ready_machine_id] = max(
                        machine_available_time[ready_machine_id] + 1.0,
                        min(future_ready),
                    )
                else:
                    machine_available_time[ready_machine_id] += 10.0
                continue

            # Advance machine clock to earliest candidate arrival if needed
            earliest_job_ready = min(
                job_ready_time[j.job_id] for (j, _op, _idx) in eligible_candidates
            )
            if earliest_job_ready > m_time:
                lookahead_time = earliest_job_ready
            else:
                lookahead_time = m_time + 30.0

            active_candidates = [
                (j, op, idx)
                for (j, op, idx) in eligible_candidates
                if job_ready_time[j.job_id] <= lookahead_time
            ]
            if not active_candidates:
                active_candidates = eligible_candidates

            # 3. Multi-objective scoring for candidate selection
            best_score = -float("inf")
            best_selection: tuple[Job, Operation, int] | None = None
            best_setup = 0.0
            best_power_kw = 0.0
            best_t_start = 0.0

            for j, op, op_idx in active_candidates:
                t_job_avail = job_ready_time[j.job_id]
                t_start_setup = max(m_time, t_job_avail)

                # Fixture setup calculation
                base_setup = self.transition_matrix.get_setup_time(curr_fixture, op.required_fixture)
                setup_minutes = (
                    base_setup * machine.pallet_setup_factor
                    if machine.has_pallet_changer
                    else base_setup
                )

                t_start_cut = t_start_setup + setup_minutes

                # Remaining work from pre-computed table
                total_remaining_work = setup_minutes + downstream_work[j.job_id][op_idx]

                # Critical Ratio (CR) & Slack
                slack = j.due_date - (t_start_setup + total_remaining_work)
                critical_ratio = (j.due_date - t_start_setup) / max(5.0, total_remaining_work)

                # Urgency Scoring (Nonlinear escalation for tight deadlines to maximize OTD)
                w_job = float(j.priority)
                if critical_ratio <= 1.0:
                    urgency_score = 5000.0 * w_job / max(0.05, critical_ratio) + 200.0 * abs(min(0.0, slack))
                elif critical_ratio <= 1.5:
                    urgency_score = 1500.0 * w_job / critical_ratio + 50.0 * math.exp(-slack / max(10.0, avg_cycle_time))
                else:
                    urgency_score = 200.0 * (w_job / critical_ratio) * math.exp(-slack / (3.0 * avg_cycle_time))

                # Setup preservation bonus
                setup_score = 0.0
                if setup_minutes == 0.0:
                    setup_score = 250.0
                else:
                    setup_score = -self.w_setup * setup_minutes

                # Machine Specialization Preservation
                specialty_penalty = 0.0
                if machine.machine_type == "VMC_5AXIS_HIGH_SPEED" and "VMC_3AXIS_STD" in op.allowed_machine_types:
                    specialty_penalty = 120.0

                # Power Prediction (cached)
                pred_power_kw = _cached_power_kw(op.required_rpm, j.material)

                # Fleet Active Power Check at start time (O(M) via latest task per machine)
                active_fleet_kw = sum(
                    task.power_kw
                    for task in last_machine_task.values()
                    if task and task.t_start <= t_start_cut < task.t_end
                )
                future_fleet_kw = active_fleet_kw + pred_power_kw
                peak_penalty = 0.0
                if future_fleet_kw > self.peak_power_limit_kw:
                    peak_penalty = (future_fleet_kw - self.peak_power_limit_kw) * self.w_peak_power * 10.0

                # Energy component
                energy_kwh = pred_power_kw * (op.nominal_cycle_minutes / 60.0)
                energy_cost = energy_kwh * self.w_energy

                # Idle waiting penalty
                idle_wait = max(0.0, t_job_avail - m_time)
                wait_penalty = idle_wait * 1.5

                # Total AI Score
                score = (
                    self.w_tardiness * urgency_score
                    + setup_score
                    - specialty_penalty
                    - peak_penalty
                    - energy_cost
                    - wait_penalty
                )

                if score > best_score:
                    best_score = score
                    best_selection = (j, op, op_idx)
                    best_setup = setup_minutes
                    best_power_kw = pred_power_kw
                    best_t_start = t_start_setup

            if best_selection is None:
                machine_available_time[ready_machine_id] += 10.0
                continue

            sel_job, sel_op, sel_op_idx = best_selection
            t_start = best_t_start
            duration = sel_op.nominal_cycle_minutes
            t_end = t_start + best_setup + duration
            energy_kwh = best_power_kw * (duration / 60.0)

            # Check if this is the final operation of the job
            is_final_op = sel_op_idx == len(sel_job.operations) - 1
            if is_final_op:
                job_completion_time[sel_job.job_id] = t_end
                job_lateness = max(0.0, t_end - sel_job.due_date)
            else:
                job_lateness = 0.0

            task = AIScheduledTask(
                job_id=sel_job.job_id,
                op_id=sel_op.op_id,
                machine_id=ready_machine_id,
                t_start=t_start,
                t_end=t_end,
                duration_minutes=duration,
                setup_minutes=best_setup,
                fixture_id=sel_op.required_fixture,
                power_kw=best_power_kw,
                energy_kwh=round(energy_kwh, 3),
                due_date=sel_job.due_date,
                lateness_minutes=round(job_lateness, 1),
            )
            scheduled_tasks.append(task)
            last_machine_task[ready_machine_id] = task
            machine_sequences[ready_machine_id].append(f"{sel_job.job_id}:{sel_op.name}")
            machine_available_time[ready_machine_id] = t_end
            machine_active_fixture[ready_machine_id] = sel_op.required_fixture

            # Update job state for downstream operations
            job_next_op_idx[sel_job.job_id] = sel_op_idx + 1
            job_ready_time[sel_job.job_id] = t_end + self.transfer_time_minutes

            # Remove completed jobs from pending set
            if is_final_op:
                pending_job_ids.discard(sel_job.job_id)

        # Metrics computation across all jobs
        makespan = max(t.t_end for t in scheduled_tasks) if scheduled_tasks else 0.0
        total_energy = sum(t.energy_kwh for t in scheduled_tasks)
        total_setup = sum(t.setup_minutes for t in scheduled_tasks)

        job_tardiness_list = [
            max(0.0, job_completion_time.get(j.job_id, makespan) - j.due_date)
            for j in all_jobs
        ]
        on_time_jobs = sum(1 for lat in job_tardiness_list if lat <= 0.0)
        otd_pct = (on_time_jobs / len(all_jobs) * 100.0) if all_jobs else 100.0

        # Construct Fleet Electrical Load Curve (Adaptive step & pre-grouped intervals)
        step = max(float(time_step_minutes), makespan / 400.0) if makespan > 0 else 5.0
        time_grid = [float(t) for t in np.arange(0, makespan + step, step)]
        power_profile: list[tuple[float, float]] = []
        peak_observed = 0.0

        # Pre-group cutting intervals per machine for O(T * M) fast scan
        machine_cutting: dict[str, list[tuple[float, float, float]]] = {
            m.machine_id: [] for m in self.machines
        }
        for tsk in scheduled_tasks:
            c_s = tsk.t_start + tsk.setup_minutes
            c_e = tsk.t_end
            if c_e > c_s:
                machine_cutting[tsk.machine_id].append((c_s, c_e, tsk.power_kw))

        for t_val in time_grid:
            p_instant = 0.0
            active_m_count = 0
            for mid, intervals in machine_cutting.items():
                for c_s, c_e, p_kw in intervals:
                    if c_s <= t_val <= c_e:
                        p_instant += p_kw
                        active_m_count += 1
                        break
            idle_m_count = len(self.machines) - active_m_count
            p_fleet = p_instant + idle_m_count * EmpiricalPowerModel.BASE_STANDBY_KW
            power_profile.append((t_val, round(p_fleet, 2)))
            peak_observed = max(peak_observed, p_fleet)
            if p_fleet > self.peak_power_limit_kw:
                peak_shaved_count += 1

        weighted_tardiness = sum(
            job_tardiness_list[i] * float(all_jobs[i].priority)
            for i in range(len(all_jobs))
        )

        return AIScheduleResult(
            scenario_name=scenario_name,
            makespan_minutes=round(makespan, 1),
            total_jobs=len(all_jobs),
            completed_jobs=len(all_jobs),
            on_time_delivery_pct=round(otd_pct, 1),
            total_weighted_tardiness=round(weighted_tardiness, 1),
            mean_tardiness_minutes=round(sum(job_tardiness_list) / len(job_tardiness_list), 1)
            if job_tardiness_list
            else 0.0,
            max_tardiness_minutes=round(max(job_tardiness_list), 1) if job_tardiness_list else 0.0,
            total_energy_kwh=round(total_energy, 1),
            peak_power_kw=round(peak_observed, 1),
            peak_power_limit_kw=self.peak_power_limit_kw,
            peak_shaved_count=peak_shaved_count,
            total_setup_minutes=round(total_setup, 1),
            scheduled_tasks=scheduled_tasks,
            machine_sequences=machine_sequences,
            power_profile=power_profile,
        )

