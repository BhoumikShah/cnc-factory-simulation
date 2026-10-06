from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field


class MachineConfig(BaseModel):
    """Pydantic model for machine specification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    machine_id: str
    machine_type: str
    spindle_power_kw: float = Field(gt=0)
    max_spindle_rpm: float = Field(gt=0)
    magazine_capacity: int = Field(gt=0)
    has_pallet_changer: bool = False
    mtbf_hours: float = Field(gt=0)
    mttr_minutes: float = Field(gt=0)
    hourly_rate_usd: float = Field(default=85.0, gt=0)
    pallet_setup_factor: float = Field(default=0.3, ge=0.0, le=1.0)


class MachinesShopConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    machines: Sequence[MachineConfig]


class ToolConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_type: str
    description: str
    nominal_life_minutes: float = Field(gt=0)
    weibull_shape: float = Field(gt=0)
    weibull_scale: float = Field(gt=0)
    base_change_time_minutes: float = Field(default=3.0, ge=0)
    auto_change_time_minutes: float = Field(default=0.1, ge=0)
    initial_crib_stock: int = Field(default=5, ge=0)
    replenishment_lead_time_minutes: float = Field(default=120.0, ge=0)


class ToolsShopConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tools: Sequence[ToolConfig]


class FixtureConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fixture_id: str
    fixture_type: str
    description: str
    total_quantity: int = Field(default=2, ge=1)


class FixtureMatrixConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    default_setup_minutes: float = Field(default=15.0, ge=0)
    transitions: Mapping[str, Mapping[str, float]] = Field(default_factory=dict)


class FixturesShopConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fixtures: Sequence[FixtureConfig]
    setup_matrix: FixtureMatrixConfig


class BreakConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    start_minute: float = Field(ge=0)
    duration_minutes: float = Field(gt=0)


class ShiftConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    shift_id: str
    name: str
    start_hour: float = Field(ge=0, lt=24)
    duration_hours: float = Field(gt=0, le=24)
    days_of_week: Sequence[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon-Fri
    breaks: Sequence[BreakConfig] = Field(default_factory=list)


class OperatorConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operator_id: str
    name: str
    skill_level: int = Field(default=2, ge=1, le=3)
    shift_ids: Sequence[str]
    certified_fixtures: Sequence[str] = Field(default_factory=list)


class ShiftsShopConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    shifts: Sequence[ShiftConfig]
    operators: Sequence[OperatorConfig]


class ScenarioConfig(BaseModel):
    """Configuration for an end-to-end simulation or optimization run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario_name: str
    description: str
    random_seed: int = 42
    warmup_minutes: float = Field(default=0.0, ge=0)
    duration_minutes: float = Field(default=43200.0, gt=0)  # default 30 days
    num_replications: int = Field(default=1, ge=1)
    dispatch_policy: str = "FIFO"
    shop_config_dir: str = "configs/shop"
    synthetic_job_count: int = Field(default=500, ge=1)
    workpiece_mix: Mapping[str, float] = Field(
        default_factory=lambda: {"Aluminum_6061": 0.5, "Steel_4140": 0.3, "Titanium_Gr5": 0.2}
    )
    enable_breakdowns: bool = False
    injected_faults: Mapping[str, bool] = Field(default_factory=dict)
    optimizer_time_limit_seconds: float = Field(default=30.0, gt=0)
