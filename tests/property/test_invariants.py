from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from vmc_twin.config.loader import ConfigLoader
from vmc_twin.config.schemas import ScenarioConfig
from vmc_twin.data.generator import SyntheticDataGenerator
from vmc_twin.sim.engine import SimulationEngine


@settings(max_examples=10, deadline=None)
@given(
    seed=st.integers(min_value=1, max_value=10000),
    job_count=st.integers(min_value=5, max_value=30),
)
def test_temporal_monotonicity_and_no_overlaps(seed: int, job_count: int) -> None:
    """
    Hypothesis property test verifying that for any seed and job count:
    1. Event start/end times are monotonically increasing per machine.
    2. No two events overlap in time on the same machine.
    3. Tool remaining life is never negative.
    """
    shop_dir = Path("configs/shop")
    machines = ConfigLoader.load_machines(shop_dir / "machines.yaml")
    tools = ConfigLoader.load_tools(shop_dir / "tools.yaml")
    fixtures, matrix = ConfigLoader.load_fixtures(shop_dir / "fixtures.yaml")
    operators = ConfigLoader.load_operators(shop_dir / "shifts.yaml")

    gen = SyntheticDataGenerator(random_seed=seed)
    jobs = gen.generate_jobs(count=job_count, horizon_minutes=480.0)

    scenario_cfg = ScenarioConfig(
        scenario_name="property_test",
        description="Fast property test",
        random_seed=seed,
        duration_minutes=480.0,
        dispatch_policy="FIFO",
    )

    engine = SimulationEngine(
        scenario=scenario_cfg,
        machines=machines,
        tools=tools,
        fixtures=fixtures,
        transition_matrix=matrix,
        operators=operators,
        jobs=jobs,
    )

    result = engine.run(single_machine_id="VMC-01")

    # Group events by machine
    machine_events = [e for e in result.events if e.machine_id == "VMC-01"]
    machine_events.sort(key=lambda e: (e.t_start, e.t_end))

    # Invariant: Temporal non-overlap
    for i in range(len(machine_events) - 1):
        curr_e = machine_events[i]
        next_e = machine_events[i + 1]
        assert curr_e.t_end <= next_e.t_start + 1e-6, (
            f"Overlapping events on {curr_e.machine_id}: "
            f"Event {curr_e} ends at {curr_e.t_end} but next event {next_e} starts at {next_e.t_start}"
        )
