from vmc_twin.domain.job import Job
from vmc_twin.domain.machine import Machine, MachineSpec
from vmc_twin.domain.operation import Operation
from vmc_twin.sim.dispatcher import (
    DispatchContext,
    EDDDispatchPolicy,
    FIFODispatchPolicy,
    SPTDispatchPolicy,
)


def _make_sample_job(job_id: str, release_time: float, due_date: float, cycle_mins: float) -> Job:
    op = Operation(
        op_id=f"{job_id}-OP1",
        job_id=job_id,
        sequence_num=1,
        name="OP1",
        allowed_machine_types=["VMC_3AXIS_STD"],
        required_fixture="VISE_STD",
        nominal_cycle_minutes=cycle_mins,
    )
    return Job(
        job_id=job_id,
        part_name="TEST_PART",
        material="Steel",
        priority=3,
        release_time=release_time,
        due_date=due_date,
        operations=[op],
    )


def test_fifo_dispatcher_selection() -> None:
    spec = MachineSpec(
        machine_id="M1",
        machine_type="VMC_3AXIS_STD",
        spindle_power_kw=15.0,
        max_spindle_rpm=12000.0,
        magazine_capacity=30,
        has_pallet_changer=False,
        mtbf_hours=100.0,
        mttr_minutes=30.0,
    )
    m = Machine(spec=spec)

    j1 = _make_sample_job("JOB-01", release_time=10.0, due_date=100.0, cycle_mins=30.0)
    j2 = _make_sample_job("JOB-02", release_time=5.0, due_date=200.0, cycle_mins=10.0)

    ctx = DispatchContext(
        current_time=15.0,
        machine=m,
        available_jobs=[j1, j2],
        active_fixtures={},
        tool_magazine=[],
    )

    fifo = FIFODispatchPolicy()
    sel = fifo.select_next_job(ctx)
    assert sel is not None
    assert sel[0].job_id == "JOB-02"  # Earlier release time (5.0 vs 10.0)


def test_edd_dispatcher_selection() -> None:
    spec = MachineSpec(
        machine_id="M1",
        machine_type="VMC_3AXIS_STD",
        spindle_power_kw=15.0,
        max_spindle_rpm=12000.0,
        magazine_capacity=30,
        has_pallet_changer=False,
        mtbf_hours=100.0,
        mttr_minutes=30.0,
    )
    m = Machine(spec=spec)

    j1 = _make_sample_job("JOB-01", release_time=5.0, due_date=100.0, cycle_mins=30.0)
    j2 = _make_sample_job("JOB-02", release_time=5.0, due_date=50.0, cycle_mins=40.0)

    ctx = DispatchContext(
        current_time=15.0,
        machine=m,
        available_jobs=[j1, j2],
        active_fixtures={},
        tool_magazine=[],
    )

    edd = EDDDispatchPolicy()
    sel = edd.select_next_job(ctx)
    assert sel is not None
    assert sel[0].job_id == "JOB-02"  # More urgent due date (50.0 vs 100.0)


def test_spt_dispatcher_selection() -> None:
    spec = MachineSpec(
        machine_id="M1",
        machine_type="VMC_3AXIS_STD",
        spindle_power_kw=15.0,
        max_spindle_rpm=12000.0,
        magazine_capacity=30,
        has_pallet_changer=False,
        mtbf_hours=100.0,
        mttr_minutes=30.0,
    )
    m = Machine(spec=spec)

    j1 = _make_sample_job("JOB-01", release_time=5.0, due_date=100.0, cycle_mins=30.0)
    j2 = _make_sample_job("JOB-02", release_time=5.0, due_date=200.0, cycle_mins=10.0)

    ctx = DispatchContext(
        current_time=15.0,
        machine=m,
        available_jobs=[j1, j2],
        active_fixtures={},
        tool_magazine=[],
    )

    spt = SPTDispatchPolicy()
    sel = spt.select_next_job(ctx)
    assert sel is not None
    assert sel[0].job_id == "JOB-02"  # Shortest cycle time (10.0 vs 30.0)
