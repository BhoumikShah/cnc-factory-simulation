from __future__ import annotations

from vmc_twin.domain.fixture import FixtureSpec, FixtureTransitionMatrix
from vmc_twin.domain.job import Job
from vmc_twin.domain.machine import Machine, MachineSpec
from vmc_twin.domain.operation import Operation
from vmc_twin.optimize.cpsat_scheduler import (
    CPSATScheduler,
    OptimizationWeights,
)
from vmc_twin.optimize.pareto import ParetoFrontier
from vmc_twin.sim.dispatcher import (
    ATCDispatchPolicy,
    DispatchContext,
    ScheduleDispatchPolicy,
    SlackDispatchPolicy,
)


def test_pareto_2d_frontier() -> None:
    # Points: (makespan, tardiness)
    # (10, 100), (20, 50), (30, 20), (25, 60 - dominated by (20,50)), (50, 200 - dominated)
    points = [
        (10.0, 100.0),
        (20.0, 50.0),
        (30.0, 20.0),
        (25.0, 60.0),
        (50.0, 200.0),
    ]

    frontier_indices = ParetoFrontier.identify_non_dominated_2d(
        points, minimize_x=True, minimize_y=True
    )
    assert 0 in frontier_indices  # (10, 100)
    assert 1 in frontier_indices  # (20, 50)
    assert 2 in frontier_indices  # (30, 20)
    assert 3 not in frontier_indices  # (25, 60) dominated
    assert 4 not in frontier_indices  # (50, 200) dominated


def test_dispatch_policies_atc_slack_schedule() -> None:
    spec = MachineSpec(
        machine_id="VMC-01",
        machine_type="3AX_STANDARD",
        spindle_power_kw=15.0,
        max_spindle_rpm=12000.0,
        magazine_capacity=30,
        has_pallet_changer=False,
        mtbf_hours=100.0,
        mttr_minutes=60.0,
    )
    machine = Machine(spec=spec)

    op1 = Operation(
        op_id="OP1",
        job_id="J001",
        sequence_num=1,
        name="Milling 1",
        allowed_machine_types=["3AX_STANDARD"],
        required_fixture="FIX_A",
        nominal_cycle_minutes=20.0,
        cycle_time_cv=0.05,
    )
    op2 = Operation(
        op_id="OP2",
        job_id="J002",
        sequence_num=1,
        name="Milling 2",
        allowed_machine_types=["3AX_STANDARD"],
        required_fixture="FIX_A",
        nominal_cycle_minutes=50.0,
        cycle_time_cv=0.05,
    )

    job1 = Job(
        job_id="J001",
        part_name="Part1",
        material="Aluminum_6061",
        release_time=0.0,
        due_date=100.0,
        priority=3,
        operations=[op1],
    )
    job2 = Job(
        job_id="J002",
        part_name="Part2",
        material="Steel_4140",
        release_time=0.0,
        due_date=40.0,
        priority=1,
        operations=[op2],
    )

    context = DispatchContext(
        current_time=0.0,
        machine=machine,
        available_jobs=[job1, job2],
        active_fixtures={},
        tool_magazine=[],
    )

    # 1. Slack Policy: Job2 has slack 40 - 0 - 50 = -10, Job1 has slack 100 - 0 - 20 = 80
    slack_policy = SlackDispatchPolicy()
    sel_slack = slack_policy.select_next_job(context)
    assert sel_slack is not None
    assert sel_slack[0].job_id == "J002"

    # 2. ATC Policy: Lookahead calculation
    atc_policy = ATCDispatchPolicy(k_lookahead=2.0)
    sel_atc = atc_policy.select_next_job(context)
    assert sel_atc is not None

    # 3. Schedule Policy: Explicit predetermined order
    sched_policy = ScheduleDispatchPolicy({"VMC-01": ["J001", "J002"]})
    sel_sched = sched_policy.select_next_job(context)
    assert sel_sched is not None
    assert sel_sched[0].job_id == "J001"


def test_cpsat_scheduler_solve_small_instance() -> None:
    spec = MachineSpec(
        machine_id="VMC-01",
        machine_type="3AX_STANDARD",
        spindle_power_kw=15.0,
        max_spindle_rpm=12000.0,
        magazine_capacity=30,
        has_pallet_changer=False,
        mtbf_hours=100.0,
        mttr_minutes=60.0,
    )
    fix_spec = FixtureSpec(
        fixture_id="FIX_A",
        fixture_type="VISE",
        description="Standard Vise",
        total_quantity=2,
    )
    matrix = FixtureTransitionMatrix(default_setup_minutes=10.0, transitions={})

    op1 = Operation(
        op_id="OP1",
        job_id="J001",
        sequence_num=1,
        name="Milling 1",
        allowed_machine_types=["3AX_STANDARD"],
        required_fixture="FIX_A",
        nominal_cycle_minutes=15.0,
        cycle_time_cv=0.0,
    )
    op2 = Operation(
        op_id="OP2",
        job_id="J002",
        sequence_num=1,
        name="Milling 2",
        allowed_machine_types=["3AX_STANDARD"],
        required_fixture="FIX_A",
        nominal_cycle_minutes=25.0,
        cycle_time_cv=0.0,
    )

    job1 = Job(
        job_id="J001",
        part_name="Part1",
        material="Aluminum_6061",
        release_time=0.0,
        due_date=50.0,
        priority=2,
        operations=[op1],
    )
    job2 = Job(
        job_id="J002",
        part_name="Part2",
        material="Steel_4140",
        release_time=0.0,
        due_date=30.0,
        priority=1,
        operations=[op2],
    )

    weights = OptimizationWeights(w_makespan=1.0, w_tardiness=2.0, w_setup=0.5)
    scheduler = CPSATScheduler(
        machines=[spec],
        fixtures=[fix_spec],
        transition_matrix=matrix,
        weights=weights,
    )

    res = scheduler.solve([job1, job2], time_limit_seconds=5.0)
    assert res.status in ("OPTIMAL", "FEASIBLE", "HEURISTIC_FEASIBLE")
    assert res.makespan_minutes >= 40.0  # 15 + 25 = 40 min min makespan
    assert len(res.scheduled_operations) == 2
    assert "VMC-01" in res.machine_job_sequences


def test_pareto_calculate_frontier_from_benchmarks() -> None:
    from vmc_twin.optimize.pareto import PolicyBenchmarkResult

    benchmarks = [
        PolicyBenchmarkResult("FIFO", 42, 100.0, 80.0, 10.0, 50.0, 95.0, 10, 0.1),
        PolicyBenchmarkResult("EDD", 42, 120.0, 75.0, 8.0, 10.0, 99.0, 10, 0.1),
        PolicyBenchmarkResult("SPT", 42, 90.0, 85.0, 12.0, 80.0, 90.0, 10, 0.1),
        PolicyBenchmarkResult("POOR", 42, 150.0, 60.0, 20.0, 100.0, 80.0, 10, 0.1),
    ]

    frontier = ParetoFrontier.calculate_frontier_from_benchmarks(
        benchmarks, x_metric="makespan_minutes", y_metric="total_weighted_tardiness"
    )
    frontier_policies = {p.policy_name for p in frontier}
    assert "FIFO" in frontier_policies
    assert "EDD" in frontier_policies
    assert "SPT" in frontier_policies
    assert "POOR" not in frontier_policies


def test_tournament_runner_execution() -> None:
    from pathlib import Path

    from vmc_twin.optimize.pareto import TournamentRunner

    scenario_file = Path("configs/scenarios/baseline.yaml")
    results = TournamentRunner.run_bakeoff(
        scenario_path=scenario_file,
        policies=("FIFO", "EDD"),
        seeds=[42],
        optimizer_time_limit=1.0,
    )
    assert len(results) == 2
    for r in results:
        assert r.completed_jobs > 0
        assert r.makespan_minutes > 0.0


def test_dispatcher_schedule_fallback() -> None:
    spec = MachineSpec(
        machine_id="VMC-01",
        machine_type="3AX_STANDARD",
        spindle_power_kw=15.0,
        max_spindle_rpm=12000.0,
        magazine_capacity=30,
        has_pallet_changer=False,
        mtbf_hours=100.0,
        mttr_minutes=60.0,
    )
    machine = Machine(spec=spec)
    op = Operation(
        op_id="OP1",
        job_id="J999",
        sequence_num=1,
        name="Milling",
        allowed_machine_types=["3AX_STANDARD"],
        required_fixture="FIX_A",
        nominal_cycle_minutes=10.0,
    )
    job = Job(
        job_id="J999",
        part_name="Part999",
        material="Steel_4140",
        release_time=0.0,
        due_date=100.0,
        priority=1,
        operations=[op],
    )
    # Schedule policy with no jobs for VMC-01
    policy = ScheduleDispatchPolicy({"VMC-02": ["J001"]})
    ctx = DispatchContext(0.0, machine, [job], {}, [])
    # Should fallback to FIFO
    sel = policy.select_next_job(ctx)
    assert sel is not None
    assert sel[0].job_id == "J999"

