from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from vmc_twin.config.schemas import (
    FixturesShopConfig,
    MachinesShopConfig,
    ScenarioConfig,
    ShiftsShopConfig,
    ToolsShopConfig,
)
from vmc_twin.domain.fixture import FixtureSpec, FixtureTransitionMatrix
from vmc_twin.domain.machine import MachineSpec
from vmc_twin.domain.operator import Operator
from vmc_twin.domain.states import SkillLevel
from vmc_twin.domain.tool import ToolSpec


class ConfigLoader:
    """Safe loader and validator for YAML configurations."""

    @staticmethod
    def _read_yaml(file_path: Path | str) -> dict[str, Any]:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Configuration file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)
        if not isinstance(content, dict):
            raise TypeError(f"YAML content in {p} must be a top-level mapping/dictionary")
        return content

    @classmethod
    def load_machines(cls, file_path: Path | str) -> list[MachineSpec]:
        data = cls._read_yaml(file_path)
        parsed = MachinesShopConfig.model_validate(data)
        return [
            MachineSpec(
                machine_id=m.machine_id,
                machine_type=m.machine_type,
                spindle_power_kw=m.spindle_power_kw,
                max_spindle_rpm=m.max_spindle_rpm,
                magazine_capacity=m.magazine_capacity,
                has_pallet_changer=m.has_pallet_changer,
                mtbf_hours=m.mtbf_hours,
                mttr_minutes=m.mttr_minutes,
                hourly_rate_usd=m.hourly_rate_usd,
                pallet_setup_factor=m.pallet_setup_factor,
            )
            for m in parsed.machines
        ]

    @classmethod
    def load_tools(cls, file_path: Path | str) -> list[ToolSpec]:
        data = cls._read_yaml(file_path)
        parsed = ToolsShopConfig.model_validate(data)
        return [
            ToolSpec(
                tool_type=t.tool_type,
                description=t.description,
                nominal_life_minutes=t.nominal_life_minutes,
                weibull_shape=t.weibull_shape,
                weibull_scale=t.weibull_scale,
                base_change_time_minutes=t.base_change_time_minutes,
                auto_change_time_minutes=t.auto_change_time_minutes,
            )
            for t in parsed.tools
        ]

    @classmethod
    def load_fixtures(cls, file_path: Path | str) -> tuple[list[FixtureSpec], FixtureTransitionMatrix]:
        data = cls._read_yaml(file_path)
        parsed = FixturesShopConfig.model_validate(data)
        specs = [
            FixtureSpec(
                fixture_id=f.fixture_id,
                fixture_type=f.fixture_type,
                description=f.description,
                total_quantity=f.total_quantity,
            )
            for f in parsed.fixtures
        ]
        matrix = FixtureTransitionMatrix(
            transitions=parsed.setup_matrix.transitions,
            default_setup_minutes=parsed.setup_matrix.default_setup_minutes,
        )
        return specs, matrix

    @classmethod
    def load_operators(cls, file_path: Path | str) -> list[Operator]:
        data = cls._read_yaml(file_path)
        parsed = ShiftsShopConfig.model_validate(data)
        return [
            Operator(
                operator_id=o.operator_id,
                name=o.name,
                skill_level=SkillLevel(o.skill_level),
                shift_ids=o.shift_ids,
                certified_fixtures=o.certified_fixtures,
            )
            for o in parsed.operators
        ]

    @classmethod
    def load_scenario(cls, file_path: Path | str) -> ScenarioConfig:
        data = cls._read_yaml(file_path)
        return ScenarioConfig.model_validate(data)
