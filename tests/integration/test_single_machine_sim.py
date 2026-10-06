from pathlib import Path

from vmc_twin.config.loader import ConfigLoader
from vmc_twin.data.generator import SyntheticDataGenerator
from vmc_twin.domain.states import SpindleState
from vmc_twin.sim.engine import SimulationEngine


def test_single_machine_simulation_run() -> None:
    scenario_cfg = ConfigLoader.load_scenario("configs/scenarios/baseline.yaml")
    shop_dir = Path("configs/shop")

    machines = ConfigLoader.load_machines(shop_dir / "machines.yaml")
    tools = ConfigLoader.load_tools(shop_dir / "tools.yaml")
    fixtures, matrix = ConfigLoader.load_fixtures(shop_dir / "fixtures.yaml")
    operators = ConfigLoader.load_operators(shop_dir / "shifts.yaml")

    gen = SyntheticDataGenerator(random_seed=42)
    # Generate a small workload of 25 jobs over 480 minutes (8 hrs)
    jobs = gen.generate_jobs(count=25, horizon_minutes=480.0)

    engine = SimulationEngine(
        scenario=scenario_cfg,
        machines=machines,
        tools=tools,
        fixtures=fixtures,
        transition_matrix=matrix,
        operators=operators,
        jobs=jobs,
    )

    # Run for single machine VMC-01
    result = engine.run(single_machine_id="VMC-01")

    assert result.total_events > 0
    assert len(result.machines) == 1
    m = result.machines[0]
    assert m.machine_id == "VMC-01"
    assert m.accumulated_cutting_minutes > 0.0

    # Verify event stream properties
    events = result.events
    assert len(events) > 0

    # Ensure no negative durations
    for e in events:
        assert e.t_end >= e.t_start
        assert e.machine_id == "VMC-01"

    # Check presence of cutting and setup events
    states_present = {e.state for e in events}
    assert SpindleState.CUTTING in states_present
    assert SpindleState.SETUP in states_present
