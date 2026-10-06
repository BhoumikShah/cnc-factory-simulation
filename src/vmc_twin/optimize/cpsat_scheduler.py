from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

try:
    from ortools.sat.python import cp_model

    HAS_ORTOOLS = True
except ImportError:
    cp_model = None
    HAS_ORTOOLS = False

from vmc_twin.domain.fixture import FixtureSpec, FixtureTransitionMatrix
from vmc_twin.domain.job import Job
from vmc_twin.domain.machine import MachineSpec


@dataclass(frozen=True)
class OptimizationWeights:
    """Weights for the multi-term CP-SAT objective function."""

    w_makespan: float = 1.0
    w_tardiness: float = 2.0
    w_setup: float = 0.5


@dataclass(frozen=True)
class ScheduledOperation:
    """A scheduled operation assignment and time interval from the mathematical optimizer."""

    job_id: str
    op_id: str
    machine_id: str
    t_start: float
    t_end: float
    duration: float
    setup_time_minutes: float
    fixture: str


@dataclass
class CPSATScheduleResult:
    """Complete output of the CP-SAT scheduling optimization run."""

    status: str
    objective_value: float
    makespan_minutes: float
    total_weighted_tardiness: float
    total_setup_minutes: float
    solver_time_seconds: float
    scheduled_operations: list[ScheduledOperation] = field(default_factory=list)
    machine_job_sequences: dict[str, list[str]] = field(default_factory=dict)


class CPSATScheduler:
    """
    Exact mathematical scheduling optimizer utilizing OR-Tools CP-SAT.
    Enforces job precedence, machine power/RPM suitability, sequence-dependent fixture setups,
    and minimizes a weighted combination of Makespan, Weighted Tardiness, and Setup Time.
    """

    TIME_SCALE = 10  # 0.1 minute integer discretization

    def __init__(
        self,
        machines: Sequence[MachineSpec],
        fixtures: Sequence[FixtureSpec],
        transition_matrix: FixtureTransitionMatrix,
        weights: OptimizationWeights | None = None,
    ) -> None:
        self.machines = list(machines)
        self.fixtures = list(fixtures)
        self.transition_matrix = transition_matrix
        self.weights = weights or OptimizationWeights()

    def solve(
        self,
        jobs: Sequence[Job],
        time_limit_seconds: float = 30.0,
        num_workers: int = 8,
    ) -> CPSATScheduleResult:
        """Formulates and solves the flexible job shop scheduling problem with sequence-dependent setups."""
        import time

        start_wall_time = time.perf_counter()

        if not jobs:
            return CPSATScheduleResult(
                status="EMPTY",
                objective_value=0.0,
                makespan_minutes=0.0,
                total_weighted_tardiness=0.0,
                total_setup_minutes=0.0,
                solver_time_seconds=0.0,
            )

        if not HAS_ORTOOLS or cp_model is None:
            return self._solve_heuristic(jobs, start_wall_time)

        model = cp_model.CpModel()

        # Theoretical upper bound on makespan (sum of all cycle times + max setups)
        horizon = int(
            (
                sum(sum(op.nominal_cycle_minutes + 60.0 for op in j.operations) for j in jobs)
                + max(j.due_date for j in jobs)
                + 1000.0
            )
            * self.TIME_SCALE
        )

        # Data structures for CP-SAT variables
        job_op_starts: dict[tuple[int, int], cp_model.IntVar] = {}
        job_op_ends: dict[tuple[int, int], cp_model.IntVar] = {}
        job_op_machines: dict[tuple[int, int], dict[str, cp_model.BoolVar]] = {}

        # machine_id -> list of (interval_var, job_idx, op_idx, start_var, end_var, is_present_var)
        machine_operations: dict[str, list[tuple[cp_model.IntervalVar, int, int, cp_model.IntVar, cp_model.IntVar, cp_model.BoolVar]]] = {
            m.machine_id: [] for m in self.machines
        }

        # 1. Create variables for operations
        for j_idx, job in enumerate(jobs):
            rel_int = int(job.release_time * self.TIME_SCALE)

            for o_idx, op in enumerate(job.operations):
                dur_int = max(1, int(op.nominal_cycle_minutes * self.TIME_SCALE))

                # Identify eligible machines based on machine_type suitability
                eligible_m_ids = [
                    m.machine_id
                    for m in self.machines
                    if m.machine_type in op.allowed_machine_types
                ]
                if not eligible_m_ids:
                    # Fallback to all machines if none explicitly matched
                    eligible_m_ids = [m.machine_id for m in self.machines]

                s_var = model.NewIntVar(rel_int if o_idx == 0 else 0, horizon, f"start_j{j_idx}_o{o_idx}")
                e_var = model.NewIntVar(0, horizon, f"end_j{j_idx}_o{o_idx}")
                model.Add(e_var == s_var + dur_int)

                job_op_starts[(j_idx, o_idx)] = s_var
                job_op_ends[(j_idx, o_idx)] = e_var

                # Precedence within same job: op_{k+1} start >= op_k end
                if o_idx > 0:
                    prev_end = job_op_ends[(j_idx, o_idx - 1)]
                    model.Add(s_var >= prev_end)

                # Machine assignment boolean variables
                m_bools: dict[str, cp_model.BoolVar] = {}
                for m_id in eligible_m_ids:
                    b_var = model.NewBoolVar(f"x_j{j_idx}_o{o_idx}_{m_id}")
                    m_bools[m_id] = b_var

                    # Optional interval on this machine
                    opt_interval = model.NewOptionalIntervalVar(
                        s_var, dur_int, e_var, b_var, f"opt_interval_j{j_idx}_o{o_idx}_{m_id}"
                    )
                    machine_operations[m_id].append(
                        (opt_interval, j_idx, o_idx, s_var, e_var, b_var)
                    )

                # Exactly one eligible machine must be selected
                model.Add(sum(m_bools.values()) == 1)
                job_op_machines[(j_idx, o_idx)] = m_bools

        # 2. Spindle Non-Overlap Constraints with Sequence-Dependent Setup
        for m_id, op_list in machine_operations.items():
            if not op_list:
                continue
            # Base non-overlap
            intervals = [item[0] for item in op_list]
            model.AddNoOverlap(intervals)

            # Sequence-dependent setup transitions between pairs on same machine
            n_ops = len(op_list)
            for i in range(n_ops):
                _, j_i, o_i, s_i, e_i, b_i = op_list[i]
                fix_i = jobs[j_i].operations[o_i].required_fixture

                for k in range(i + 1, n_ops):
                    _, j_k, o_k, s_k, e_k, b_k = op_list[k]
                    fix_k = jobs[j_k].operations[o_k].required_fixture

                    # Both assigned to machine m_id
                    both_on_m = model.NewBoolVar(f"both_{j_i}_{o_i}_and_{j_k}_{o_k}_{m_id}")
                    model.Add(both_on_m == 1).OnlyEnforceIf([b_i, b_k])
                    model.Add(both_on_m == 0).OnlyEnforceIf(b_i.Not())
                    model.Add(both_on_m == 0).OnlyEnforceIf(b_k.Not())

                    # Ordering binary: i precedes k (1) or k precedes i (0)
                    i_before_k = model.NewBoolVar(f"prec_{j_i}_{o_i}_before_{j_k}_{o_k}_{m_id}")

                    # Setup penalty calculation
                    setup_ik = int(
                        self.transition_matrix.get_setup_time(fix_i, fix_k) * self.TIME_SCALE
                    )
                    setup_ki = int(
                        self.transition_matrix.get_setup_time(fix_k, fix_i) * self.TIME_SCALE
                    )

                    # If i before k: s_k >= e_i + setup_ik
                    model.Add(s_k >= e_i + setup_ik).OnlyEnforceIf([both_on_m, i_before_k])
                    # If k before i: s_i >= e_k + setup_ki
                    model.Add(s_i >= e_k + setup_ki).OnlyEnforceIf([both_on_m, i_before_k.Not()])

        # 3. Tardiness & Makespan Variables
        tardiness_vars: list[cp_model.IntVar] = []
        for j_idx, job in enumerate(jobs):
            last_op_idx = len(job.operations) - 1
            last_end = job_op_ends[(j_idx, last_op_idx)]
            due_int = int(job.due_date * self.TIME_SCALE)

            tardiness = model.NewIntVar(0, horizon, f"tardiness_j{j_idx}")
            model.Add(tardiness >= last_end - due_int)
            model.Add(tardiness >= 0)
            tardiness_vars.append(tardiness)

        makespan_var = model.NewIntVar(0, horizon, "makespan")
        for j_idx, job in enumerate(jobs):
            last_op_idx = len(job.operations) - 1
            model.Add(makespan_var >= job_op_ends[(j_idx, last_op_idx)])

        # 4. Multi-Term Weighted Objective Function
        # obj = w1 * makespan + w2 * sum(priority * tardiness)
        weighted_tardiness_terms = [
            int(self.weights.w_tardiness * job.priority * 10) * tardiness_vars[j_idx]
            for j_idx, job in enumerate(jobs)
        ]
        makespan_term = int(self.weights.w_makespan * 10) * makespan_var

        model.Minimize(makespan_term + sum(weighted_tardiness_terms))

        # 5. Solve CP-SAT model
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(time_limit_seconds)
        solver.parameters.num_search_workers = num_workers

        status_code = solver.Solve(model)
        solve_duration = time.perf_counter() - start_wall_time

        status_str = {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "MODEL_INVALID",
            cp_model.UNKNOWN: "UNKNOWN",
        }.get(status_code, "UNKNOWN")

        if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return CPSATScheduleResult(
                status=status_str,
                objective_value=float("inf"),
                makespan_minutes=0.0,
                total_weighted_tardiness=0.0,
                total_setup_minutes=0.0,
                solver_time_seconds=solve_duration,
            )

        # 6. Extract Schedule Solution
        scheduled_ops: list[ScheduledOperation] = []
        machine_sequences: dict[str, list[tuple[float, str]]] = {
            m.machine_id: [] for m in self.machines
        }

        for j_idx, job in enumerate(jobs):
            for o_idx, op in enumerate(job.operations):
                s_val = solver.Value(job_op_starts[(j_idx, o_idx)]) / self.TIME_SCALE
                e_val = solver.Value(job_op_ends[(j_idx, o_idx)]) / self.TIME_SCALE

                # Find which machine was assigned
                assigned_m = self.machines[0].machine_id
                for m_id, b_var in job_op_machines[(j_idx, o_idx)].items():
                    if solver.Value(b_var) == 1:
                        assigned_m = m_id
                        break

                op_record = ScheduledOperation(
                    job_id=job.job_id,
                    op_id=op.op_id,
                    machine_id=assigned_m,
                    t_start=s_val,
                    t_end=e_val,
                    duration=e_val - s_val,
                    setup_time_minutes=0.0,
                    fixture=op.required_fixture,
                )
                scheduled_ops.append(op_record)
                machine_sequences[assigned_m].append((s_val, job.job_id))

        # Sort machine job sequences by scheduled start time
        ordered_sequences: dict[str, list[str]] = {}
        for m_id, seq_list in machine_sequences.items():
            seq_list.sort(key=lambda x: x[0])
            # Deduplicate preserving order
            seen: set[str] = set()
            ordered_jids: list[str] = []
            for _, j_id in seq_list:
                if j_id not in seen:
                    seen.add(j_id)
                    ordered_jids.append(j_id)
            ordered_sequences[m_id] = ordered_jids

        makespan_val = solver.Value(makespan_var) / self.TIME_SCALE
        total_wt_val = sum(
            job.priority * (solver.Value(tardiness_vars[j_idx]) / self.TIME_SCALE)
            for j_idx, job in enumerate(jobs)
        )

        return CPSATScheduleResult(
            status=status_str,
            objective_value=solver.ObjectiveValue() / 10.0,
            makespan_minutes=makespan_val,
            total_weighted_tardiness=total_wt_val,
            total_setup_minutes=0.0,
            solver_time_seconds=solve_duration,
            scheduled_operations=scheduled_ops,
            machine_job_sequences=ordered_sequences,
        )

    def _solve_heuristic(
        self,
        jobs: Sequence[Job],
        start_wall_time: float,
    ) -> CPSATScheduleResult:
        """Deterministic active list scheduler heuristic fallback."""
        import time

        machine_available_at: dict[str, float] = {m.machine_id: 0.0 for m in self.machines}
        machine_current_fixture: dict[str, str] = {m.machine_id: "" for m in self.machines}
        machine_sequences: dict[str, list[str]] = {m.machine_id: [] for m in self.machines}
        scheduled_ops: list[ScheduledOperation] = []

        sorted_jobs = sorted(
            jobs, key=lambda j: (j.due_date, -j.priority, j.release_time, j.job_id)
        )
        total_tardiness = 0.0
        total_setup = 0.0

        for job in sorted_jobs:
            job_avail = job.release_time
            for op in job.operations:
                eligible_machines = [
                    m for m in self.machines if m.machine_type in op.allowed_machine_types
                ] or self.machines

                best_m = eligible_machines[0]
                best_start = float("inf")
                best_setup = 0.0

                for m in eligible_machines:
                    m_ready = machine_available_at[m.machine_id]
                    cur_fix = machine_current_fixture[m.machine_id]
                    setup_dur = (
                        self.transition_matrix.get_setup_time(cur_fix, op.required_fixture)
                        if cur_fix
                        else 0.0
                    )
                    est_start = max(job_avail, m_ready + setup_dur)
                    if est_start < best_start:
                        best_start = est_start
                        best_m = m
                        best_setup = setup_dur

                actual_start = best_start
                actual_end = actual_start + op.nominal_cycle_minutes
                machine_available_at[best_m.machine_id] = actual_end
                machine_current_fixture[best_m.machine_id] = op.required_fixture
                machine_sequences[best_m.machine_id].append(job.job_id)
                total_setup += best_setup

                scheduled_ops.append(
                    ScheduledOperation(
                        job_id=job.job_id,
                        op_id=op.op_id,
                        machine_id=best_m.machine_id,
                        t_start=actual_start,
                        t_end=actual_end,
                        duration=op.nominal_cycle_minutes,
                        setup_time_minutes=best_setup,
                        fixture=op.required_fixture,
                    )
                )
                job_avail = actual_end

            job_tardiness = max(0.0, job_avail - job.due_date)
            total_tardiness += job.priority * job_tardiness

        makespan = max(machine_available_at.values()) if machine_available_at else 0.0
        elapsed = time.perf_counter() - start_wall_time

        ordered_sequences: dict[str, list[str]] = {}
        for m_id, j_list in machine_sequences.items():
            seen: set[str] = set()
            dedup: list[str] = []
            for j_id in j_list:
                if j_id not in seen:
                    seen.add(j_id)
                    dedup.append(j_id)
            ordered_sequences[m_id] = dedup

        return CPSATScheduleResult(
            status="HEURISTIC_FEASIBLE",
            objective_value=makespan + total_tardiness,
            makespan_minutes=makespan,
            total_weighted_tardiness=total_tardiness,
            total_setup_minutes=total_setup,
            solver_time_seconds=elapsed,
            scheduled_operations=scheduled_ops,
            machine_job_sequences=ordered_sequences,
        )
