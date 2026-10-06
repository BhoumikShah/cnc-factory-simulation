import numpy as np
import simpy

from vmc_twin.domain.fixture import FixtureSpec, FixtureTransitionMatrix
from vmc_twin.domain.job import Job
from vmc_twin.domain.machine import Machine, MachineSpec
from vmc_twin.domain.operation import Operation
from vmc_twin.domain.operator import Operator
from vmc_twin.domain.states import SkillLevel, SpindleState
from vmc_twin.sim.dispatcher import FIFODispatchPolicy
from vmc_twin.sim.event_bus import InMemoryEventSink
from vmc_twin.sim.machine_process import MachineProcess
from vmc_twin.sim.resources import ShopFloorResources
from vmc_twin.sim.rng import RNGManager


def test_mm1_queue_theoretical_convergence() -> None:
    """
    Validates simulator against M/M/1 queueing theory.
    Arrival rate: lambda = 0.05 jobs/min (mean interarrival = 20 min)
    Service rate: mu = 0.08 jobs/min (mean service = 12.5 min)
    Traffic intensity: rho = 0.05 / 0.08 = 0.625
    Theoretical mean queue wait W_q = rho / (mu * (1 - rho)) = 0.625 / (0.08 * 0.375) = 20.83 min
    """
    rng = np.random.default_rng(42)
    job_count = 1000
    inter_arrivals = rng.exponential(scale=20.0, size=job_count)
    service_times = rng.exponential(scale=12.5, size=job_count)

    arrival_times = np.cumsum(inter_arrivals)

    jobs: list[Job] = []
    for i in range(job_count):
        op = Operation(
            op_id=f"JOB-{i + 1}-OP1",
            job_id=f"JOB-{i + 1}",
            sequence_num=1,
            name="OP1",
            allowed_machine_types=["VMC_STD"],
            required_fixture="VISE",
            nominal_cycle_minutes=float(service_times[i]),
            cycle_time_cv=0.01,  # near deterministic drawn value
            base_manual_setup_minutes=0.0,
        )
        jobs.append(
            Job(
                job_id=f"JOB-{i + 1}",
                part_name="MM1_PART",
                material="Steel",
                priority=1,
                release_time=float(arrival_times[i]),
                due_date=float(arrival_times[i] + 500.0),
                operations=[op],
            )
        )

    env = simpy.Environment()
    spec = MachineSpec(
        machine_id="M1",
        machine_type="VMC_STD",
        spindle_power_kw=15.0,
        max_spindle_rpm=10000.0,
        magazine_capacity=30,
        has_pallet_changer=False,
        mtbf_hours=10000.0,
        mttr_minutes=0.0,
    )
    machine = Machine(spec=spec, current_fixture="VISE")

    fixtures = [
        FixtureSpec(fixture_id="VISE", fixture_type="VISE", description="Vise", total_quantity=1)
    ]
    matrix = FixtureTransitionMatrix(transitions={}, default_setup_minutes=0.0)
    operators = [
        Operator(
            operator_id="OP1",
            name="Op",
            skill_level=SkillLevel.STANDARD,
            shift_ids=["D"],
            certified_fixtures=["VISE"],
        )
    ]

    resources = ShopFloorResources(
        env=env,
        operators=operators,
        fixture_specs=fixtures,
        transition_matrix=matrix,
        tool_specs=[],
    )

    sink = InMemoryEventSink()
    rng_mgr = RNGManager(master_seed=42)
    active_jobs = list(jobs)
    completed_jobs: list[Job] = []

    MachineProcess(
        env=env,
        machine=machine,
        resources=resources,
        dispatcher=FIFODispatchPolicy(),
        event_sink=sink,
        rng_manager=rng_mgr,
        active_jobs=active_jobs,
        completed_jobs=completed_jobs,
    )

    # Run until all jobs complete
    env.run(until=arrival_times[-1] + 10000.0)

    assert len(completed_jobs) == job_count
    # Calculate simulated wait times
    wait_times: list[float] = []
    for e in sink.events:
        if e.state == SpindleState.CUTTING and e.job_id:
            job_idx = int(e.job_id.split("-")[1]) - 1
            rel_time = arrival_times[job_idx]
            wait = max(0.0, e.t_start - rel_time)
            wait_times.append(wait)

    mean_wait = float(np.mean(wait_times))
    theoretical_wq = 0.625 / (0.08 * (1.0 - 0.625))  # ~20.83 min

    # Check convergence within reasonable statistical tolerance for 1000 stochastic samples (+- 50%)
    assert abs(mean_wait - theoretical_wq) / theoretical_wq < 0.50, (
        f"Simulated mean wait {mean_wait:.2f} differs significantly from theoretical W_q {theoretical_wq:.2f}"
    )
