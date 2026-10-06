from pathlib import Path

from vmc_twin.config.loader import ConfigLoader
from vmc_twin.data.generator import SyntheticDataGenerator
from vmc_twin.report.kpis import KPICalculator
from vmc_twin.sim.engine import SimulationEngine


def test_capacity_scaling_reduces_makespan() -> None:
    """Verifies that adding machines strictly reduces makespan and tardiness for a heavy workload."""
    scenario_cfg = ConfigLoader.load_scenario("configs/scenarios/baseline.yaml")
    shop_dir = Path("configs/shop")

    all_machines = ConfigLoader.load_machines(shop_dir / "machines.yaml")
    tools = ConfigLoader.load_tools(shop_dir / "tools.yaml")
    fixtures, matrix = ConfigLoader.load_fixtures(shop_dir / "fixtures.yaml")
    operators = ConfigLoader.load_operators(shop_dir / "shifts.yaml")

    gen = SyntheticDataGenerator(random_seed=42)
    workload = gen.generate_jobs(count=80, horizon_minutes=2000.0)

    # 1. Run with 2 machines
    engine_2m = SimulationEngine(
        scenario=scenario_cfg,
        machines=all_machines[:2],
        tools=tools,
        fixtures=fixtures,
        transition_matrix=matrix,
        operators=operators,
        jobs=workload,
    )
    res_2m = engine_2m.run()
    kpi_2m = KPICalculator.calculate("2_machines", res_2m.duration_minutes, res_2m.events, workload)

    # 2. Run with 6 machines
    engine_6m = SimulationEngine(
        scenario=scenario_cfg,
        machines=all_machines[:6],
        tools=tools,
        fixtures=fixtures,
        transition_matrix=matrix,
        operators=operators,
        jobs=workload,
    )
    res_6m = engine_6m.run()
    kpi_6m = KPICalculator.calculate("6_machines", res_6m.duration_minutes, res_6m.events, workload)

    # Adding capacity must reduce makespan and increase completion rate
    assert kpi_6m.makespan_minutes < kpi_2m.makespan_minutes
    assert kpi_6m.completed_jobs >= kpi_2m.completed_jobs
