from __future__ import annotations

from pathlib import Path

from vmc_twin.config.loader import ConfigLoader
from vmc_twin.data.generator import SyntheticDataGenerator
from vmc_twin.optimize.ai_scheduler import EnergyAwareAIScheduler
from vmc_twin.predict.power_model import EmpiricalPowerModel
from vmc_twin.report.ie_dashboard import IEDashboardGenerator


def test_empirical_power_model_calibration() -> None:
    # 1. Zero spindle speed should return standby
    pred_0 = EmpiricalPowerModel.predict_power(
        spindle_speed_rpm=0.0, feed_rate_mm_min=0.0, depth_of_cut_mm=0.0
    )
    assert pred_0.standby_power_kw == 0.95
    assert pred_0.cutting_power_kw == 0.0

    # 2. Steel cutting at S=2030, F=406, ap=3.0mm (From dataset tests)
    pred_steel = EmpiricalPowerModel.predict_power(
        spindle_speed_rpm=2030.0,
        feed_rate_mm_min=406.0,
        depth_of_cut_mm=3.0,
        material="Steel_4140",
    )
    assert pred_steel.air_cut_power_kw > 0.4
    assert pred_steel.cutting_power_kw > 0.5
    assert pred_steel.total_power_kw > 2.0

    # 3. Titanium should draw more cutting power than Aluminum for same geometry
    pred_ti = EmpiricalPowerModel.predict_power(
        spindle_speed_rpm=2030.0,
        feed_rate_mm_min=406.0,
        depth_of_cut_mm=3.0,
        material="Titanium_Gr5",
    )
    pred_al = EmpiricalPowerModel.predict_power(
        spindle_speed_rpm=2030.0,
        feed_rate_mm_min=406.0,
        depth_of_cut_mm=3.0,
        material="Aluminum_6061",
    )
    assert pred_ti.cutting_power_kw > pred_al.cutting_power_kw


def test_energy_aware_ai_scheduler_and_dashboard(tmp_path: Path) -> None:
    scenario = ConfigLoader.load_scenario("configs/scenarios/baseline.yaml")
    shop_dir = Path(scenario.shop_config_dir)

    machines = ConfigLoader.load_machines(shop_dir / "machines.yaml")
    fixtures, matrix = ConfigLoader.load_fixtures(shop_dir / "fixtures.yaml")

    gen = SyntheticDataGenerator(random_seed=42)
    jobs = gen.generate_jobs(count=20, horizon_minutes=2000.0)

    scheduler = EnergyAwareAIScheduler(
        machines=machines,
        fixtures=fixtures,
        transition_matrix=matrix,
        peak_power_limit_kw=25.0,
    )

    result = scheduler.solve(jobs=jobs, scenario_name="Test_IE_Run")

    assert result.completed_jobs == 20
    assert result.makespan_minutes > 0.0
    assert result.total_energy_kwh > 0.0
    assert result.peak_power_kw > 0.0
    assert len(result.scheduled_tasks) == 20
    assert len(result.power_profile) > 0

    # Test IE Dashboard generation
    dash_out = tmp_path / "ie_test_dash.html"
    dash_path = IEDashboardGenerator.generate_dashboard(result=result, output_path=dash_out)
    assert dash_path.exists()
    content = dash_path.read_text(encoding="utf-8")
    assert "Industrial Engineering AI Scheduler" in content
    assert "Peak Demand Limit" in content
    assert "Order Fulfillment" in content
