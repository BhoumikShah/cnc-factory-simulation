from pathlib import Path

import pytest
from pydantic import ValidationError

from vmc_twin.config.loader import ConfigLoader
from vmc_twin.config.schemas import MachineConfig


def test_load_valid_shop_configs() -> None:
    shop_dir = Path("configs/shop")
    machines = ConfigLoader.load_machines(shop_dir / "machines.yaml")
    assert len(machines) == 10
    assert machines[0].machine_id == "VMC-01"

    tools = ConfigLoader.load_tools(shop_dir / "tools.yaml")
    assert len(tools) >= 5

    fixtures, matrix = ConfigLoader.load_fixtures(shop_dir / "fixtures.yaml")
    assert len(fixtures) == 4
    assert matrix.get_setup_time("VISE_6INCH_DUAL", "CHUCK_4JAW_SCROLL") == 25.0

    operators = ConfigLoader.load_operators(shop_dir / "shifts.yaml")
    assert len(operators) >= 5


def test_load_valid_scenarios() -> None:
    scen_dir = Path("configs/scenarios")
    for scen_file in scen_dir.glob("*.yaml"):
        cfg = ConfigLoader.load_scenario(scen_file)
        assert cfg.scenario_name
        assert cfg.duration_minutes > 0


def test_machine_config_validation_rejects_negative_power() -> None:
    with pytest.raises(ValidationError):
        MachineConfig(
            machine_id="VMC-ERR",
            machine_type="VMC_3AXIS_STD",
            spindle_power_kw=-10.0,  # invalid negative
            max_spindle_rpm=10000.0,
            magazine_capacity=30,
            has_pallet_changer=False,
            mtbf_hours=100.0,
            mttr_minutes=30.0,
        )
